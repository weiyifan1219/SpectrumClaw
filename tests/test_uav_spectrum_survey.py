from __future__ import annotations

from concurrent.futures import Future

import pytest


class ImmediateExecutor:
    def submit(self, function, *args, **kwargs):
        future = Future()
        try:
            future.set_result(function(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - surfaced through service state
            future.set_exception(exc)
        return future


def running_status(*, manual: bool = False):
    return {
        "runtime": {
            "state": "running",
            "manual": {"enabled": manual},
            "agent_navigation": {"ready": True},
            "camera": {"vehicle": {"position_m": [0.0, 0.0, 0.0]}},
        },
    }


def test_survey_flies_the_fixed_layer_route_and_feeds_idw_reconstruction():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid
    from backend.skills.uav_spectrum_sim.spectrum_survey import SpectrumSurveyService

    grid = RealtimeSpectrumGrid(area_size_m=12.0, cell_size_m=4.0, layer_step_m=5.0)

    drain_calls = []

    class Coordinator:
        def clear_grid_layer(self, layer_index):
            grid.clear_layer(layer_index)

        def ingest_observation(self, observation):
            grid.record(observation)

        def grid_snapshot(self, *, layer_index, transmitter_id="all"):
            return grid.snapshot(layer_index=layer_index, transmitter_id=transmitter_id)

        def wait_for_measurements(self, *, timeout_s, layer_index=None):
            drain_calls.append((timeout_s, layer_index))
            return True

    class DelegateRunner:
        positions = iter(([-4.0, -4.0, 20.0], [4.0, -4.0, 20.0], [0.0, 4.0, 20.0]))

        def measure(self, *, run_id, position_m, timestamp):
            sampled_position = next(self.positions)
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": "sionna_urban_2_4ghz",
                "timestamp": timestamp,
                "position_m": sampled_position,
                "anchors": [{"id": "tx-01", "received_power_dbm": -60.0}],
            }

    class MissionService:
        def __init__(self, measurement_runner):
            self.measurement_runner = measurement_runner

        def execute_plan(self, plan):
            assert plan.template == "inspect_safe_perimeter"
            assert plan.measurement_profile_id == "sionna_urban_2_4ghz"
            for index in range(3):
                self.measurement_runner.measure(
                    run_id=f"survey_{index}",
                    position_m=[0.0, 0.0, 20.0],
                    timestamp=100.0 + index,
                )
            return {"ok": True, "message": "done"}

    service = SpectrumSurveyService(
        coordinator=Coordinator(),
        measurement_runner=DelegateRunner(),
        mission_service_factory=lambda runner: MissionService(runner),
        status_reader=running_status,
        executor=ImmediateExecutor(),
        time_fn=lambda: 100.0,
        id_factory=lambda: "campaign-001",
        survey_route=tuple((float(index), -30.0, 20.0) for index in range(7)),
    )

    status = service.start()

    assert status["state"] == "completed"
    assert status["campaign_id"] == "campaign-001"
    assert status["layer_index"] == 4
    assert status["height_range_m"] == [20.0, 25.0]
    assert status["samples_collected"] == 3
    assert status["planned_waypoints"] == 7
    assert status["reconstruction_ready"] is True
    assert status["reconstruction_method"] == "blind_path_loss_idw"
    assert drain_calls == [(120.0, 4)]


def test_survey_rejects_start_while_browser_manual_control_is_active():
    from backend.skills.uav_spectrum_sim.spectrum_survey import SpectrumSurveyService

    service = SpectrumSurveyService(
        status_reader=lambda: running_status(manual=True),
        executor=ImmediateExecutor(),
    )

    with pytest.raises(RuntimeError, match="手动飞控"):
        service.start()


def test_survey_rejects_restart_while_measurement_queue_is_draining():
    from backend.skills.uav_spectrum_sim.spectrum_survey import SpectrumSurveyService

    service = SpectrumSurveyService(status_reader=running_status, executor=ImmediateExecutor())
    service._status["state"] = "draining"

    with pytest.raises(RuntimeError, match="正在运行"):
        service.start()


def test_default_survey_route_flies_inside_z4_instead_of_on_the_layer_boundary():
    from backend.skills.uav_spectrum_sim.spectrum_survey import SpectrumSurveyService

    service = SpectrumSurveyService(status_reader=running_status, executor=ImmediateExecutor())
    route = service.snapshot()["route_waypoints_m"]

    assert route
    assert {point[2] for point in route} == {21.0}
    assert all(20.0 <= point[2] < 25.0 for point in route)


def test_source_agnostic_survey_closes_all_four_sides_of_the_perimeter():
    from backend.skills.uav_spectrum_sim.spectrum_survey import SpectrumSurveyService

    route = SpectrumSurveyService(status_reader=running_status, executor=ImmediateExecutor()).snapshot()["route_waypoints_m"]

    west_side = [point for point in route if point[0] <= -29.0]
    assert any(point[1] <= -25.0 for point in west_side)
    assert any(abs(point[1]) <= 15.0 for point in west_side)
    assert any(point[1] >= 25.0 for point in west_side)
