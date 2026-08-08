"""Contracts for the read-only Sionna spectrum situation API."""

from __future__ import annotations

import asyncio
import json
import time

import httpx


def _runtime(position_m: list[float]) -> dict:
    return {
        "runtime": {
            "state": "running",
            "camera": {"vehicle": {"position_m": position_m}},
        },
    }


def test_latest_sionna_situation_reports_pose_freshness_and_anchor_measurements(tmp_path):
    from backend.skills.uav_spectrum_sim.sionna_measurement import get_sionna_spectrum_situation

    artifact = tmp_path / "artifacts" / "uav-sionna" / "uav_rf_001"
    artifact.mkdir(parents=True)
    artifact.joinpath("observation.json").write_text(json.dumps({
        "kind": "spectrum_observation",
        "source": "sionna_rt",
        "profile_id": "sionna_urban_2_4ghz",
        "timestamp": 100.0,
        "position_m": [2.0, -1.0, 20.0],
        "frequency_hz": 2.4e9,
        "anchors": [
            {"id": "tx-01", "received_power_dbm": -44.2, "path_count": 2},
            {"id": "tx-02", "received_power_dbm": -48.8, "path_count": 1},
        ],
    }), encoding="utf-8")

    situation = get_sionna_spectrum_situation(
        runtime_root=tmp_path,
        runtime_status=_runtime([2.5, -1.2, 20.1]),
        now=110.0,
    )

    assert situation["available"] is True
    assert situation["current"] is True
    assert situation["age_s"] == 10.0
    assert situation["pose_offset_m"] < 1.0
    assert situation["observation"]["anchors"][0]["received_power_dbm"] == -44.2
    assert situation["history"] == [{
        "run_id": "uav_rf_001",
        "captured_at": 100.0,
        "position_m": [2.0, -1.0, 20.0],
        "anchors": situation["observation"]["anchors"],
    }]


def test_spectrum_situation_api_returns_the_current_read_only_payload(monkeypatch):
    from backend.api import uav_spectrum_sim
    from backend.app import create_app

    expected = {"available": True, "current": True, "observation": {"source": "sionna_rt"}}
    monkeypatch.setattr(uav_spectrum_sim, "get_sionna_spectrum_situation", lambda **_kwargs: expected)
    app = create_app()

    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/uav-spectrum-sim/spectrum/current")

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json() == expected


def test_spectrum_refresh_api_collects_at_the_current_pose_without_a_flight_command(monkeypatch):
    from backend.api import uav_spectrum_sim
    from backend.app import create_app

    status = _runtime([4.0, 3.0, 20.0])
    observed = {
        "kind": "spectrum_observation",
        "source": "sionna_rt",
        "profile_id": "sionna_urban_2_4ghz",
        "timestamp": 200.0,
        "position_m": [4.0, 3.0, 20.0],
        "frequency_hz": 2.4e9,
        "anchors": [{"id": "tx-01", "received_power_dbm": -42.0, "path_count": 2}],
    }
    monkeypatch.setattr(uav_spectrum_sim, "get_runtime_status", lambda: status)
    monkeypatch.setattr(uav_spectrum_sim, "collect_current_sionna_observation", lambda **kwargs: observed)
    monkeypatch.setattr(uav_spectrum_sim, "get_sionna_spectrum_situation", lambda **_kwargs: {
        "available": True,
        "current": True,
        "observation": observed,
        "history": [{"run_id": "sionna_live_test", "captured_at": 200.0, "position_m": [4.0, 3.0, 20.0], "anchors": observed["anchors"]}],
    })
    app = create_app()

    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/uav-spectrum-sim/spectrum/refresh")

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json()["current"] is True
    assert response.json()["observation"] == observed
    assert response.json()["history"][0]["position_m"] == [4.0, 3.0, 20.0]


def test_live_payload_triggers_realtime_rt_and_embeds_the_latest_grid_update(monkeypatch):
    from backend.api import uav_spectrum_sim

    status = _runtime([4.0, 3.0, 20.0])

    class Coordinator:
        def __init__(self):
            self.requests = []

        def request_update(self, runtime_status):
            self.requests.append(runtime_status)
            return True

        def snapshot(self, runtime_status):
            return {
                "available": True,
                "sequence": 7,
                "current_position_m": runtime_status["runtime"]["camera"]["vehicle"]["position_m"],
                "grid_update": {"layer_index": 4, "row": 10, "column": 12, "values_dbm": {"all": -48.0}},
            }

    coordinator = Coordinator()
    monkeypatch.setattr(uav_spectrum_sim, "get_runtime_status", lambda: status)
    monkeypatch.setattr(uav_spectrum_sim, "get_live_snapshot", lambda runtime_status=None: {"type": "uav_live_v1", "vehicle": runtime_status["runtime"]["camera"]["vehicle"]})
    monkeypatch.setattr(uav_spectrum_sim, "get_realtime_sionna_coordinator", lambda: coordinator)

    payload = uav_spectrum_sim.build_live_simulation_payload(include_spectrum=True)

    assert coordinator.requests == [status]
    assert payload["vehicle"]["position_m"] == [4.0, 3.0, 20.0]
    assert payload["spectrum"]["sequence"] == 7
    assert payload["spectrum"]["grid_update"]["values_dbm"]["all"] == -48.0


def test_realtime_spectrum_grid_api_exposes_the_selected_height_and_transmitter(monkeypatch):
    from backend.api import uav_spectrum_sim
    from backend.app import create_app

    class Coordinator:
        def grid_snapshot(self, *, layer_index, transmitter_id):
            return {
                "layer_index": layer_index,
                "transmitter_id": transmitter_id,
                "shape": [30, 30],
                "values_dbm": [[-50.0]],
                "observed_cells": 1,
            }

    monkeypatch.setattr(uav_spectrum_sim, "get_realtime_sionna_coordinator", lambda: Coordinator())
    app = create_app()

    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/uav-spectrum-sim/spectrum/grid?layer_index=4&transmitter_id=tx-01")

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json()["layer_index"] == 4
    assert response.json()["transmitter_id"] == "tx-01"
