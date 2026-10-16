import math
import os

import numpy as np
import pytest

from backend.skills.uav_spectrum_sim.receiver import compact_spectrum, synthesize_receiver_capture


def _observation(second=False):
    anchors = [{
        "id": "tx-01", "tx_power_dbm": 0.0,
        "cir_taps": [{"delay_s": 0.0, "real": 0.01, "imag": 0.0}],
    }]
    if second:
        anchors.append({
            "id": "tx-02", "tx_power_dbm": 0.0,
            "cir_taps": [{"delay_s": 0.0, "real": 0.01, "imag": 0.0}],
        })
    return {"frequency_hz": 2.44e9, "position_m": [0, 0, 20], "timestamp": 100.0, "anchors": anchors}


def test_1024_iq_power_and_fft_are_consistent():
    capture = synthesize_receiver_capture(_observation())
    assert len(capture["iq"]) == len(capture["spectrum"]["bin_power_dbm"]) == 1024
    assert capture["receiver"]["sample_rate_hz"] == 16_000_000
    assert capture["receiver"]["channel_bandwidth_hz"] == 10_000_000
    assert capture["metrics"]["target_power_dbm"] == pytest.approx(-40, abs=0.001)
    assert capture["metrics"]["rssi_dbm"] == pytest.approx(-40, abs=0.01)
    assert capture["metrics"]["noise_power_dbm"] == pytest.approx(-97.99, abs=0.1)
    assert math.isfinite(capture["metrics"]["sinr_db"])


def test_cochannel_source_degrades_sinr_without_changing_target_power():
    alone = synthesize_receiver_capture(_observation())
    together = synthesize_receiver_capture(_observation(second=True))
    assert together["metrics"]["target_power_dbm"] == alone["metrics"]["target_power_dbm"]
    assert together["metrics"]["sinr_db"] == pytest.approx(0, abs=0.01)
    # RSSI is measured from a finite IQ frame, so source cross terms vary.
    assert together["metrics"]["rssi_dbm"] == pytest.approx(-36.99, abs=0.5)


def test_capture_requires_real_cir_and_valid_bandwidth():
    observation = _observation()
    del observation["anchors"][0]["cir_taps"]
    with pytest.raises(ValueError, match="复数 CIR"):
        synthesize_receiver_capture(observation)
    with pytest.raises(ValueError, match="信道带宽"):
        synthesize_receiver_capture(_observation(), sample_rate_hz=16_000_000, channel_bandwidth_hz=20_000_000)


def test_api_capture_uses_latest_observation_and_reports_staleness(monkeypatch):
    from backend.api import uav_spectrum_sim as api

    class Coordinator:
        def snapshot(self, _status):
            return {"available": True, "current": False, "captured_at": 100.0,
                    "age_s": 42.0, "observation": _observation()}

    monkeypatch.setattr(api, "get_runtime_status", lambda: {})
    monkeypatch.setattr(api, "get_sionna_spectrum_situation", lambda **_kwargs: {"available": False})
    monkeypatch.setattr(api, "get_realtime_sionna_coordinator", lambda: Coordinator())

    result = api.capture_receiver(api.ReceiverCaptureRequest())

    assert result["current"] is False
    assert result["age_s"] == 42.0
    assert result["pipeline"]["payload_bytes"] == 8192
    assert result["pipeline"]["processing_location"] == "ground_station"


def test_api_remeasures_old_power_only_cache_before_capture(monkeypatch):
    from backend.api import uav_spectrum_sim as api

    old_observation = {"frequency_hz": 2.4e9, "anchors": [{"id": "tx-01", "received_power_dbm": -45}]}
    refreshed = []

    class Coordinator:
        def snapshot(self, _status):
            return {"available": True, "current": False, "captured_at": 100.0,
                    "observation": old_observation}

    def refresh():
        refreshed.append(True)
        return {"available": True, "current": True, "captured_at": 101.0,
                "observation": _observation()}

    monkeypatch.setattr(api, "get_runtime_status", lambda: {"runtime": {"state": "running"}})
    monkeypatch.setattr(api, "get_sionna_spectrum_situation", lambda **_kwargs: {"available": False})
    monkeypatch.setattr(api, "get_realtime_sionna_coordinator", lambda: Coordinator())
    monkeypatch.setattr(api, "refresh_spectrum_current", refresh)

    result = api.capture_receiver(api.ReceiverCaptureRequest())

    assert refreshed == [True]
    assert result["current"] is True
    assert len(result["iq"]) == 1024


def _recorded_scene():
    observation = _observation()
    observation["frequency_hz"] = 2.412e9
    observation["anchors"] = [{
        "id": f"tx-0{index}", "tx_power_dbm": 0.0,
        "cir_taps": [{"delay_s": 0.0, "real": 0.01, "imag": 0.0}],
    } for index in range(1, 4)]
    rng = np.random.default_rng(4)
    emitters = [{
        "id": f"tx-0{index}", "sample_rate_hz": 62_500_000,
        "recorded_center_frequency_hz": 2.412e9 - (index - 1) * 2e6,
        "samples": (rng.standard_normal(4096) + 1j * rng.standard_normal(4096)).astype(np.complex64),
    } for index in range(1, 4)]
    return observation, emitters


def test_recorded_replay_only_returns_bounded_spectrum_when_requested():
    observation, emitters = _recorded_scene()
    frame = synthesize_receiver_capture(
        observation, sample_rate_hz=62_500_000,
        channel_bandwidth_hz=40_000_000,
        recorded_emitters=emitters, include_iq=False,
    )
    compact = compact_spectrum(frame["spectrum"])
    assert "iq" not in frame
    assert frame["receiver"]["waveform"] == "recorded_protocol_iq_replay"
    assert len(compact["bin_power_dbm"]) == 256
    assert compact["source_fft_bins"] == 1024
    assert math.isfinite(frame["metrics"]["sinr_db"])


def test_live_frame_api_exposes_protocol_prior_without_raw_iq(monkeypatch):
    from backend.api import uav_spectrum_sim as api

    observation, emitters = _recorded_scene()
    monkeypatch.setattr(api, "_receiver_situation", lambda **_kwargs: {
        "observation": observation, "current": True,
    })
    monkeypatch.setattr(api, "load_recorded_emitters", lambda: emitters)
    monkeypatch.setattr(api, "recorded_emitter_summary", lambda: [{"id": "tx-01", "protocol_prior": "Wi-Fi"}])

    frame = api.receiver_frame(api.ReceiverFrameRequest())

    assert "iq" not in frame
    assert frame["emitters"][0]["protocol_prior"] == "Wi-Fi"
    assert frame["spectrum"]["source_fft_bins"] == 1024
    assert frame["current"] is True
    assert frame["spatial_update"]["rssi_dbm"] == pytest.approx(frame["metrics"]["rssi_dbm"], abs=0.001)


def test_receiver_spatial_layer_averages_linear_power_and_rejects_stale_frames():
    from backend.skills.uav_spectrum_sim.receiver_spatial import ReceiverSpatialGrid

    grid = ReceiverSpatialGrid()
    first = {"current": True, "position_m": [0.0, 0.0, 21.0], "generated_at": 100.0,
             "metrics": {"rssi_dbm": -40.0}}
    second = {**first, "generated_at": 101.0, "metrics": {"rssi_dbm": -30.0}}

    assert grid.record(first)["layer_index"] == 4
    assert grid.record(second)["rssi_dbm"] == pytest.approx(-32.596, abs=0.002)
    assert grid.record({**second, "current": False}) is None
    layer = grid.snapshot(4)
    assert layer["observed_cells"] == 1
    assert layer["samples"][0]["frame_count"] == 2
    assert grid.snapshot(3)["observed_cells"] == 0


def test_sionna_artifact_pruning_preserves_scene_and_latest(tmp_path):
    from backend.skills.uav_spectrum_sim.sionna_measurement import prune_sionna_observation_artifacts

    root = tmp_path / "uav-sionna"
    scene = root / "scene"
    scene.mkdir(parents=True)
    (scene / "urban_block.xml").write_text("scene")
    for index in range(3):
        path = root / f"sionna_live_{index}"
        path.mkdir()
        observation = path / "observation.json"
        observation.write_text("{}")
        os.utime(observation, (1000 + index * 10, 1000 + index * 10))

    removed = prune_sionna_observation_artifacts(root, now=1000 + 25 * 3600)

    assert removed == 2
    assert (root / "sionna_live_2" / "observation.json").exists()
    assert (scene / "urban_block.xml").exists()


def test_rem_persistence_excludes_large_receiver_evidence():
    from backend.skills.uav_spectrum_sim.sionna_measurement import _compact_grid_observation

    observation = _observation()
    observation.update(kind="spectrum_observation", source="sionna_rt", profile_id="sionna_urban_2_4ghz")
    observation["anchors"][0]["received_power_dbm"] = -40.0
    observation["anchors"][0]["ray_paths"] = [{"points_m": [[0, 0, 0], [1, 1, 1]]}]
    compact = _compact_grid_observation(observation)

    assert compact["anchors"][0]["received_power_dbm"] == -40.0
    assert "cir_taps" not in compact["anchors"][0]
    assert compact["anchors"][0]["ray_paths"] == []
