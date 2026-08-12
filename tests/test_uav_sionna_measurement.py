from __future__ import annotations

import json
import io
import math
import threading

import time
from concurrent.futures import Future, ThreadPoolExecutor

import pytest
from pydantic import ValidationError


class _ImmediateExecutor:
    def submit(self, function, *args, **kwargs):
        future = Future()
        try:
            future.set_result(function(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - exercised by coordinator error tests
            future.set_exception(exc)
        return future


def _live_runtime(position_m):
    return {
        "runtime": {
            "state": "running",
            "camera": {"vehicle": {"position_m": list(position_m)}},
        },
    }


def test_realtime_sionna_recomputes_after_pose_change_and_publishes_new_ray_endpoint():
    from backend.skills.uav_spectrum_sim.sionna_measurement import RealtimeSionnaCoordinator

    measured_positions = []

    class Runner:
        def measure(self, *, run_id, position_m, timestamp):
            measured_positions.append(list(position_m))
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": "sionna_urban_2_4ghz",
                "timestamp": timestamp,
                "position_m": list(position_m),
                "frequency_hz": 2.4e9,
                "anchors": [{
                    "id": "tx-01",
                    "received_power_dbm": -42.0,
                    "path_count": 1,
                    "ray_paths": [{
                        "id": "path-1",
                        "points_m": [[42.0, 6.0, 24.0], list(position_m)],
                        "interaction_count": 0,
                    }],
                }],
            }

    clock = iter([100.0, 100.0, 101.0, 102.0, 102.0, 103.0])
    coordinator = RealtimeSionnaCoordinator(
        runner=Runner(),
        executor=_ImmediateExecutor(),
        movement_threshold_m=0.5,
        min_interval_s=0.1,
        time_fn=lambda: next(clock),
    )

    assert coordinator.request_update(_live_runtime([0.0, 0.0, 3.0])) is True
    first = coordinator.snapshot(_live_runtime([0.0, 0.0, 3.0]))
    assert first["sequence"] == 1
    assert first["observation"]["anchors"][0]["ray_paths"][0]["points_m"][-1] == [0.0, 0.0, 3.0]

    assert coordinator.request_update(_live_runtime([0.1, 0.0, 3.0])) is False
    assert coordinator.request_update(_live_runtime([4.1, 0.0, 3.0])) is True
    second = coordinator.snapshot(_live_runtime([4.1, 0.0, 3.0]))

    assert second["sequence"] == 2
    assert second["current"] is True
    assert second["pose_offset_m"] == 0.0
    assert second["observation"]["anchors"][0]["ray_paths"][0]["points_m"][-1] == [4.1, 0.0, 3.0]
    assert measured_positions == [[0.0, 0.0, 3.0], [4.1, 0.0, 3.0]]


def test_grid_trace_positions_covers_every_cell_crossed_by_the_uav_segment():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid

    grid = RealtimeSpectrumGrid(area_size_m=20.0, cell_size_m=2.0, layer_step_m=5.0)

    traced = grid.trace_positions([-9.0, 1.0, 20.0], [9.0, 1.0, 20.0])

    assert [(item["row"], item["column"]) for item in traced] == [(4, column) for column in range(10)]
    assert traced[0]["position_m"] == [-9.0, 1.0, 20.0]
    assert traced[-1]["position_m"] == [9.0, 1.0, 20.0]


def test_grid_trace_positions_is_supercover_for_an_uneven_diagonal_segment():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid

    grid = RealtimeSpectrumGrid(area_size_m=20.0, cell_size_m=2.0, layer_step_m=5.0)

    traced = grid.trace_positions([-9.0, -9.0, 21.0], [9.0, -5.0, 21.0])
    cells = [(item["row"], item["column"]) for item in traced]

    assert len(cells) == 12
    assert len(set(cells)) == 12
    assert all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 1 for a, b in zip(cells, cells[1:]))


def test_realtime_coordinator_keeps_every_crossed_grid_cell_queued_while_rt_is_busy():
    from concurrent.futures import Future

    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid
    from backend.skills.uav_spectrum_sim.sionna_measurement import RealtimeSionnaCoordinator

    class DeferredExecutor:
        def __init__(self):
            self.future = Future()

        def submit(self, _function, *_args, **_kwargs):
            return self.future

    coordinator = RealtimeSionnaCoordinator(
        runner=object(),
        executor=DeferredExecutor(),
        spectrum_grid=RealtimeSpectrumGrid(area_size_m=20.0, cell_size_m=2.0, layer_step_m=5.0),
        min_interval_s=0.05,
        time_fn=iter([100.0, 101.0, 102.0]).__next__,
    )

    assert coordinator.request_update(_live_runtime([-9.0, 1.0, 20.0])) is True
    assert coordinator.request_update(_live_runtime([9.0, 1.0, 20.0])) is True
    live = coordinator.snapshot(_live_runtime([9.0, 1.0, 20.0]))

    assert live["measurement_queue"]["strategy"] == "grid_crossing_fifo"
    assert live["measurement_queue"]["tracked_cells"] == 10
    assert live["measurement_queue"]["pending"] == 10
    assert live["measurement_track"] == []


def test_grid_queued_measurements_publish_an_authoritative_cell_track():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid
    from backend.skills.uav_spectrum_sim.sionna_measurement import RealtimeSionnaCoordinator

    class Runner:
        def measure(self, *, run_id, position_m, timestamp):
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": "sionna_urban_2_4ghz",
                "timestamp": timestamp,
                "position_m": list(position_m),
                "frequency_hz": 2.4e9,
                "anchors": [{"id": "tx-01", "received_power_dbm": -40.0 - position_m[0], "path_count": 1, "ray_paths": []}],
            }

    clock = iter([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
    grid = RealtimeSpectrumGrid(area_size_m=12.0, cell_size_m=4.0, layer_step_m=5.0)
    coordinator = RealtimeSionnaCoordinator(
        runner=Runner(),
        executor=_ImmediateExecutor(),
        spectrum_grid=grid,
        min_interval_s=0.05,
        time_fn=lambda: next(clock),
    )

    coordinator.request_update(_live_runtime([-5.0, 0.0, 20.0]))
    coordinator.request_update(_live_runtime([5.0, 0.0, 20.0]))
    live = coordinator.snapshot(_live_runtime([5.0, 0.0, 20.0]))
    layer = coordinator.grid_snapshot(layer_index=4, transmitter_id="tx-01")

    assert layer["observed_cells"] == 3
    assert [item["grid_update"]["column"] for item in live["measurement_track"]] == [0, 1, 2]
    assert all(item["source"] == "sionna_rt" for item in live["measurement_track"])
    assert live["measurement_queue"]["pending"] == 0


def test_clearing_a_layer_rejects_an_inflight_result_from_the_previous_campaign():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid
    from backend.skills.uav_spectrum_sim.sionna_measurement import RealtimeSionnaCoordinator

    started = threading.Event()
    release = threading.Event()

    class BlockingRunner:
        def measure(self, *, run_id, position_m, timestamp):
            started.set()
            assert release.wait(timeout=1.0)
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": "sionna_urban_2_4ghz",
                "timestamp": timestamp,
                "position_m": list(position_m),
                "frequency_hz": 2.4e9,
                "anchors": [{"id": "tx-01", "received_power_dbm": -45.0, "path_count": 1, "ray_paths": []}],
            }

    grid = RealtimeSpectrumGrid(area_size_m=12.0, cell_size_m=4.0, layer_step_m=5.0)
    executor = ThreadPoolExecutor(max_workers=1)
    coordinator = RealtimeSionnaCoordinator(
        runner=BlockingRunner(),
        executor=executor,
        spectrum_grid=grid,
        time_fn=lambda: 100.0,
    )
    try:
        coordinator.observe_pose([0.0, 0.0, 21.0])
        assert started.wait(timeout=1.0)

        coordinator.clear_grid_layer(4)
        release.set()

        assert coordinator.wait_for_measurements(timeout_s=1.0, layer_index=4) is True
        assert coordinator.grid_snapshot(layer_index=4)["observed_cells"] == 0
        live = coordinator.snapshot(_live_runtime([0.0, 0.0, 21.0]))
        assert live["measurement_track"] == []
    finally:
        release.set()
        executor.shutdown(wait=True)


def test_direct_refresh_rejects_a_result_captured_before_the_layer_generation_changed():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid
    from backend.skills.uav_spectrum_sim.sionna_measurement import RealtimeSionnaCoordinator

    coordinator = RealtimeSionnaCoordinator(
        runner=object(),
        executor=_ImmediateExecutor(),
        spectrum_grid=RealtimeSpectrumGrid(area_size_m=12.0, cell_size_m=4.0, layer_step_m=5.0),
    )
    status = _live_runtime([0.0, 0.0, 21.0])
    token = coordinator.capture_generation(status)
    observation = {
        "kind": "spectrum_observation",
        "source": "sionna_rt",
        "profile_id": "sionna_urban_2_4ghz",
        "timestamp": 100.0,
        "position_m": [0.0, 0.0, 21.0],
        "frequency_hz": 2.4e9,
        "anchors": [{"id": "tx-01", "received_power_dbm": -45.0, "path_count": 1, "ray_paths": []}],
    }

    coordinator.clear_grid_layer(4)

    with pytest.raises(ValueError, match="过期"):
        coordinator.ingest_observation(observation, generation_token=token)
    assert coordinator.grid_snapshot(layer_index=4)["observed_cells"] == 0


def test_transient_rt_failure_is_retried_before_a_grid_cell_is_marked_measured():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid
    from backend.skills.uav_spectrum_sim.sionna_measurement import RealtimeSionnaCoordinator

    attempts = []

    class FlakyRunner:
        def measure(self, *, run_id, position_m, timestamp):
            attempts.append(run_id)
            if len(attempts) == 1:
                raise RuntimeError("temporary RT failure")
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": "sionna_urban_2_4ghz",
                "timestamp": timestamp,
                "position_m": list(position_m),
                "frequency_hz": 2.4e9,
                "anchors": [{"id": "tx-01", "received_power_dbm": -45.0, "path_count": 1, "ray_paths": []}],
            }

    coordinator = RealtimeSionnaCoordinator(
        runner=FlakyRunner(),
        executor=_ImmediateExecutor(),
        spectrum_grid=RealtimeSpectrumGrid(area_size_m=12.0, cell_size_m=4.0, layer_step_m=5.0),
        time_fn=lambda: 100.0,
    )

    coordinator.observe_pose([0.0, 0.0, 21.0])
    live = coordinator.snapshot(_live_runtime([0.0, 0.0, 21.0]))

    assert len(attempts) == 2
    assert live["measurement_queue"]["measured_cells"] == 1
    assert live["measurement_queue"]["failed_cells"] == 0
    assert coordinator.wait_for_measurements(timeout_s=0.1, layer_index=4) is True


def test_permanent_rt_failure_is_reported_instead_of_masquerading_as_a_complete_track():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid
    from backend.skills.uav_spectrum_sim.sionna_measurement import RealtimeSionnaCoordinator

    attempts = []

    class FailingRunner:
        def measure(self, *, run_id, position_m, timestamp):
            attempts.append(run_id)
            raise RuntimeError("persistent RT failure")

    coordinator = RealtimeSionnaCoordinator(
        runner=FailingRunner(),
        executor=_ImmediateExecutor(),
        spectrum_grid=RealtimeSpectrumGrid(area_size_m=12.0, cell_size_m=4.0, layer_step_m=5.0),
        max_measurement_attempts=3,
        time_fn=lambda: 100.0,
    )

    coordinator.observe_pose([0.0, 0.0, 21.0])
    live = coordinator.snapshot(_live_runtime([0.0, 0.0, 21.0]))

    assert len(attempts) == 3
    assert coordinator.wait_for_measurements(timeout_s=0.1, layer_index=4) is False
    assert live["measurement_queue"]["pending"] == 0
    assert live["measurement_queue"]["measured_cells"] == 0
    assert live["measurement_queue"]["failed_cells"] == 1
    assert live["measurement_queue"]["failed"][0]["attempts"] == 3


def test_grid_record_validation_failure_uses_the_same_retry_and_failed_cell_path():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid
    from backend.skills.uav_spectrum_sim.sionna_measurement import RealtimeSionnaCoordinator

    attempts = []

    class EmptyPowerRunner:
        def measure(self, *, run_id, position_m, timestamp):
            attempts.append(run_id)
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": "sionna_urban_2_4ghz",
                "timestamp": timestamp,
                "position_m": list(position_m),
                "frequency_hz": 2.4e9,
                "anchors": [],
            }

    coordinator = RealtimeSionnaCoordinator(
        runner=EmptyPowerRunner(),
        executor=_ImmediateExecutor(),
        spectrum_grid=RealtimeSpectrumGrid(area_size_m=12.0, cell_size_m=4.0, layer_step_m=5.0),
        max_measurement_attempts=2,
        time_fn=lambda: 100.0,
    )

    coordinator.observe_pose([0.0, 0.0, 21.0])
    live = coordinator.snapshot(_live_runtime([0.0, 0.0, 21.0]))

    assert len(attempts) == 2
    assert coordinator.wait_for_measurements(timeout_s=0.1, layer_index=4) is False
    assert live["measurement_queue"]["pending"] == 0
    assert live["measurement_queue"]["measured_cells"] == 0
    assert live["measurement_queue"]["failed_cells"] == 1
    assert live["measurement_queue"]["tracked_cells"] == 1


def test_navigation_poll_observes_live_pose_without_waiting_for_an_rt_measurement():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    observed_positions = []
    status = {
        "runtime": {
            "state": "running",
            "manual": {"enabled": False},
            "camera": {"vehicle": {"position_m": [4.0, 2.0, 21.0]}},
        },
    }
    service = UavMissionService(
        status_reader=lambda: status,
        position_observer=lambda position: observed_positions.append(position),
        poll_interval_s=0.01,
        arrival_timeout_s=0.1,
    )

    assert service._wait_for_position((4.0, 2.0, 21.0)) == "arrived"
    assert observed_positions == [[4.0, 2.0, 21.0]]


def test_sionna_measurement_runner_preserves_pose_and_reports_only_rf_observation(tmp_path):
    from backend.skills.uav_spectrum_sim.sionna_measurement import SionnaMeasurementRunner

    def execute(command):
        request_path = next(path for path in command if str(path).endswith("request.json"))
        output_path = next(path for path in command if str(path).endswith("observation.json"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        output_path.write_text(json.dumps({
            "kind": "spectrum_observation",
            "source": "sionna_rt",
            "profile_id": request["profile_id"],
            "timestamp": request["timestamp"],
            "position_m": request["position_m"],
            "frequency_hz": 2.4e9,
            "anchors": [{"id": "tx-01", "received_power_dbm": -72.5, "path_count": 2}],
        }), encoding="utf-8")

    runner = SionnaMeasurementRunner(runtime_root=tmp_path, command_executor=execute)
    observation = runner.measure(
        run_id="uav_sionna_001",
        position_m=[12.0, -3.0, 20.0],
        timestamp=100.5,
    )

    assert observation["kind"] == "spectrum_observation"
    assert observation["source"] == "sionna_rt"
    assert observation["profile_id"] == "sionna_urban_2_4ghz"
    assert observation["position_m"] == [12.0, -3.0, 20.0]
    assert observation["anchors"][0]["received_power_dbm"] == -72.5


def test_sionna_measurement_runner_reuses_a_persistent_worker_and_persists_each_observation(tmp_path):
    from backend.skills.uav_spectrum_sim.sionna_measurement import SionnaMeasurementRunner

    class Worker:
        def __init__(self):
            self.requests = []

        def measure(self, request):
            self.requests.append(request)
            position = request["position_m"]
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": request["profile_id"],
                "timestamp": request["timestamp"],
                "position_m": position,
                "frequency_hz": 2.4e9,
                "anchors": [{
                    "id": "tx-01",
                    "received_power_dbm": -50.0,
                    "path_count": 1,
                    "ray_paths": [{"id": "path-1", "points_m": [[42.0, 6.0, 24.0], position]}],
                }],
            }

    worker = Worker()
    runner = SionnaMeasurementRunner(runtime_root=tmp_path, worker_client=worker)

    first = runner.measure(run_id="sionna_realtime_001", position_m=[0.0, 0.0, 3.0], timestamp=100.0)
    second = runner.measure(run_id="sionna_realtime_002", position_m=[2.0, 0.0, 3.0], timestamp=101.0)

    assert len(worker.requests) == 2
    assert first["position_m"] == [0.0, 0.0, 3.0]
    assert second["anchors"][0]["ray_paths"][0]["points_m"][-1] == [2.0, 0.0, 3.0]
    assert (tmp_path / "artifacts" / "uav-sionna" / "sionna_realtime_001" / "observation.json").is_file()
    assert (tmp_path / "artifacts" / "uav-sionna" / "sionna_realtime_002" / "observation.json").is_file()


def test_default_sionna_runner_uses_the_shared_realtime_worker(monkeypatch, tmp_path):
    from backend.skills.uav_spectrum_sim import sionna_measurement

    calls = []

    class Worker:
        def measure(self, request):
            calls.append(request["position_m"])
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": request["profile_id"],
                "timestamp": request["timestamp"],
                "position_m": request["position_m"],
                "frequency_hz": 2.4e9,
                "anchors": [],
            }

    shared_worker = Worker()
    monkeypatch.setattr(sionna_measurement, "_get_worker_client", lambda _sidecar: shared_worker)
    runner = sionna_measurement.SionnaMeasurementRunner(runtime_root=tmp_path)

    result = runner.measure(run_id="sionna_realtime_default", position_m=[1.0, 2.0, 3.0], timestamp=100.0)

    assert result["position_m"] == [1.0, 2.0, 3.0]
    assert calls == [[1.0, 2.0, 3.0]]


def test_realtime_spectrum_grid_records_total_rf_power_in_the_correct_height_layer():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid

    grid = RealtimeSpectrumGrid(area_size_m=120.0, cell_size_m=4.0, layer_step_m=5.0)
    observation = {
        "kind": "spectrum_observation",
        "source": "sionna_rt",
        "profile_id": "sionna_urban_2_4ghz",
        "timestamp": 100.0,
        "position_m": [1.0, -1.0, 20.2],
        "frequency_hz": 2.4e9,
        "anchors": [
            {"id": "tx-01", "received_power_dbm": -50.0, "path_count": 1},
            {"id": "tx-02", "received_power_dbm": -60.0, "path_count": 1},
        ],
    }

    update = grid.record(observation)
    total = grid.snapshot(layer_index=4, transmitter_id="all")
    tx_one = grid.snapshot(layer_index=4, transmitter_id="tx-01")
    other_layer = grid.snapshot(layer_index=2, transmitter_id="all")

    assert update["layer_index"] == 4
    assert update["row"] == 15
    assert update["column"] == 15
    assert total["shape"] == [30, 30]
    assert total["height_range_m"] == [20.0, 25.0]
    assert total["values_dbm"][15][15] == pytest.approx(-49.586, abs=0.001)
    assert tx_one["values_dbm"][15][15] == -50.0
    assert total["observed_mask"][15][15] == 1
    assert total["sample_count"] == 1
    assert total["observed_cells"] == 1
    assert total["coverage_ratio"] == pytest.approx(1 / 900)
    assert other_layer["observed_cells"] == 0
    assert other_layer["values_dbm"][15][15] is None


def test_realtime_sionna_coordinator_updates_the_sparse_grid_with_each_completed_sample():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid
    from backend.skills.uav_spectrum_sim.sionna_measurement import RealtimeSionnaCoordinator

    class Runner:
        def measure(self, *, run_id, position_m, timestamp):
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": "sionna_urban_2_4ghz",
                "timestamp": timestamp,
                "position_m": list(position_m),
                "frequency_hz": 2.4e9,
                "anchors": [{"id": "tx-01", "received_power_dbm": -45.0, "path_count": 1, "ray_paths": []}],
            }

    grid = RealtimeSpectrumGrid(area_size_m=120.0, cell_size_m=4.0, layer_step_m=5.0)
    coordinator = RealtimeSionnaCoordinator(
        runner=Runner(),
        executor=_ImmediateExecutor(),
        spectrum_grid=grid,
        time_fn=lambda: 100.0,
    )

    coordinator.request_update(_live_runtime([4.0, 4.0, 3.0]))
    live = coordinator.snapshot(_live_runtime([4.0, 4.0, 3.0]))
    layer = coordinator.grid_snapshot(layer_index=0, transmitter_id="all")

    assert live["grid_update"]["layer_index"] == 0
    assert live["grid_update"]["position_m"] == [4.0, 4.0, 3.0]
    assert layer["sample_count"] == 1
    assert layer["observed_cells"] == 1
    assert layer["max_dbm"] == -45.0


def test_sionna_ray_path_extraction_keeps_only_real_vertices():
    from simulation.rf_engine.sionna_measurement_sidecar import extract_ray_paths

    result = extract_ray_paths(
        vertices=[[[[[4.0, 2.0, 6.0], [0.0, 0.0, 0.0]]]]],
        objects=[[[[7, (1 << 32) - 1]]]],
        valid=[[[True, True]]],
        anchor_positions=((10.0, 0.0, 20.0),),
        receiver_position=[0.0, 0.0, 3.0],
    )

    assert result[0][0]["points_m"] == [[10.0, 0.0, 20.0], [4.0, 2.0, 6.0], [0.0, 0.0, 3.0]]
    assert result[0][0]["interaction_count"] == 1
    assert result[0][1]["points_m"] == [[10.0, 0.0, 20.0], [0.0, 0.0, 3.0]]


def test_sionna_sidecar_stream_processes_multiple_poses_without_restarting(tmp_path):
    from simulation.rf_engine.sionna_measurement_sidecar import RESULT_PREFIX, serve_json_lines

    requests = [
        {"request_id": "sample-1", "profile_id": "sionna_urban_2_4ghz", "timestamp": 100.0, "position_m": [0.0, 0.0, 3.0]},
        {"request_id": "sample-2", "profile_id": "sionna_urban_2_4ghz", "timestamp": 101.0, "position_m": [2.0, 0.0, 3.0]},
    ]
    source = io.StringIO("".join(json.dumps(item) + "\n" for item in requests))
    sink = io.StringIO()
    measured = []

    def fake_measure(request, _asset_dir):
        measured.append(request["position_m"])
        return {
            "kind": "spectrum_observation",
            "source": "sionna_rt",
            "profile_id": request["profile_id"],
            "timestamp": request["timestamp"],
            "position_m": request["position_m"],
            "frequency_hz": 2.4e9,
            "anchors": [],
        }

    serve_json_lines(source, sink, asset_dir=tmp_path, measure_fn=fake_measure)

    responses = [json.loads(line.removeprefix(RESULT_PREFIX)) for line in sink.getvalue().splitlines()]
    assert [item["request_id"] for item in responses] == ["sample-1", "sample-2"]
    assert all(item["ok"] is True for item in responses)
    assert responses[1]["observation"]["position_m"] == [2.0, 0.0, 3.0]
    assert measured == [[0.0, 0.0, 3.0], [2.0, 0.0, 3.0]]


def test_sionna_profile_declares_three_distinct_measurement_anchors():
    from simulation.rf_engine.sionna_measurement_sidecar import ANCHORS

    assert len(ANCHORS) == 3
    assert len({anchor_id for anchor_id, _position, _power in ANCHORS}) == 3
    assert all(len(position) == 3 for _anchor_id, position, _power in ANCHORS)
    assert all(power_dbm == 20.0 for _anchor_id, _position, power_dbm in ANCHORS)


def test_sparse_grid_reconstructs_a_complete_layer_with_idw_after_three_cells():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid

    grid = RealtimeSpectrumGrid(area_size_m=12.0, cell_size_m=4.0, layer_step_m=5.0)
    samples = [
        ([-4.0, -4.0, 20.0], -70.0),
        ([4.0, -4.0, 20.0], -50.0),
        ([0.0, 4.0, 20.0], -60.0),
    ]
    for index, (position, power_dbm) in enumerate(samples, start=1):
        grid.record({
            "timestamp": float(index),
            "position_m": position,
            "anchors": [{"id": "tx-01", "received_power_dbm": power_dbm}],
        })

    layer = grid.snapshot(layer_index=4, transmitter_id="tx-01")

    reconstruction = layer["reconstruction"]
    assert reconstruction["method"] == "blind_path_loss_idw"
    assert reconstruction["ready"] is True
    assert reconstruction["minimum_observed_cells"] == 3
    assert reconstruction["source_cells"] == 3
    assert reconstruction["estimated_cells"] == 6
    assert reconstruction["coverage_ratio"] == 1.0
    assert reconstruction["power"] == 2.0
    assert reconstruction["max_neighbors"] == 8
    assert reconstruction["prior"] == "rss_inferred_source"
    assert set(reconstruction["estimated_sources"]) == {"tx-01"}
    assert all(value is not None for row in layer["reconstructed_values_dbm"] for value in row)
    assert layer["reconstructed_values_dbm"][2][0] == -70.0
    assert layer["reconstructed_values_dbm"][2][2] == -50.0
    assert layer["reconstructed_values_dbm"][0][1] == -60.0


def test_path_loss_constrained_reconstruction_is_stronger_near_the_transmitter():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid

    grid = RealtimeSpectrumGrid(
        area_size_m=20.0,
        cell_size_m=2.0,
        layer_step_m=5.0,
    )
    for index, (position, power_dbm) in enumerate((
        ([-6.0, -6.0, 20.0], -43.0),
        ([-2.0, 6.0, 20.0], -51.0),
        ([6.0, -6.0, 20.0], -61.0),
        ([6.0, 6.0, 20.0], -63.0),
    ), start=1):
        grid.record({
            "timestamp": float(index),
            "position_m": position,
            "anchors": [{"id": "tx-01", "received_power_dbm": power_dbm}],
        })

    layer = grid.snapshot(layer_index=4, transmitter_id="tx-01")
    reconstructed = layer["reconstructed_values_dbm"]

    near_source = reconstructed[4][1]
    far_from_source = reconstructed[4][9]
    assert near_source > far_from_source + 6.0
    inferred = layer["reconstruction"]["estimated_sources"]["tx-01"]
    assert math.dist(inferred["position_m"][:2], [-8.0, 0.0]) <= 5.0


def test_blind_reconstruction_estimates_source_location_from_rss_without_scene_coordinates():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid

    grid = RealtimeSpectrumGrid(area_size_m=24.0, cell_size_m=2.0, layer_step_m=5.0)
    hidden_source = (6.0, -2.0)
    positions = [
        (-10.0, -10.0), (-6.0, -8.0), (0.0, -10.0), (8.0, -10.0),
        (-10.0, 0.0), (-4.0, 2.0), (2.0, 2.0), (10.0, 0.0),
        (-8.0, 10.0), (0.0, 8.0), (6.0, 8.0), (10.0, 10.0),
    ]
    for index, (east, north) in enumerate(positions, start=1):
        distance = max(1.0, math.hypot(east - hidden_source[0], north - hidden_source[1]))
        power_dbm = -28.0 - 22.0 * math.log10(distance)
        grid.record({
            "timestamp": float(index),
            "position_m": [east, north, 21.0],
            "anchors": [{"id": "unknown-source", "received_power_dbm": power_dbm}],
        })

    layer = grid.snapshot(layer_index=4, transmitter_id="unknown-source")
    estimate = layer["reconstruction"]["estimated_sources"]["unknown-source"]

    assert math.dist(estimate["position_m"][:2], hidden_source) <= 3.0
    assert len(estimate["position_m"]) == 2
    assert estimate["altitude_m"] is None
    assert estimate["height_basis"] == "selected_layer_only"
    assert 1.0 <= estimate["path_loss_exponent"] <= 6.0
    assert estimate["rmse_db"] < 1.5


def test_sparse_grid_waits_for_three_cells_before_reconstructing():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid

    grid = RealtimeSpectrumGrid(area_size_m=12.0, cell_size_m=4.0, layer_step_m=5.0)
    for index, position in enumerate(([-4.0, -4.0, 20.0], [4.0, -4.0, 20.0]), start=1):
        grid.record({
            "timestamp": float(index),
            "position_m": position,
            "anchors": [{"id": "tx-01", "received_power_dbm": -60.0 + index}],
        })

    layer = grid.snapshot(layer_index=4, transmitter_id="tx-01")

    assert layer["reconstruction"]["ready"] is False
    assert layer["reconstruction"]["source_cells"] == 2
    assert layer["reconstructed_values_dbm"] is None


def test_sparse_grid_can_clear_one_campaign_layer_without_touching_other_layers():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid

    grid = RealtimeSpectrumGrid(area_size_m=12.0, cell_size_m=4.0, layer_step_m=5.0)
    for height in (15.0, 20.0):
        grid.record({
            "timestamp": height,
            "position_m": [0.0, 0.0, height],
            "anchors": [{"id": "tx-01", "received_power_dbm": -55.0}],
        })

    grid.clear_layer(4)

    assert grid.snapshot(layer_index=4)["observed_cells"] == 0
    assert grid.snapshot(layer_index=3)["observed_cells"] == 1


def test_urban_block_scene_asset_uses_the_shared_enu_building_layout(tmp_path):
    from simulation.rf_engine.sionna_measurement_sidecar import write_urban_block_scene_assets

    xml_path = write_urban_block_scene_assets(tmp_path)

    assert xml_path.name == "urban_block.xml"
    assert xml_path.is_file()
    assert (tmp_path / "urban_block.ply").is_file()
    xml = xml_path.read_text(encoding="utf-8")
    assert 'type="itu-radio-material"' in xml
    assert 'filename" value="urban_block.ply"' in xml
    ply = (tmp_path / "urban_block.ply").read_text(encoding="utf-8")
    assert "element vertex 56" in ply  # ground cuboid plus six building cuboids
    assert "element face 84" in ply


def test_mission_plan_allows_only_the_declared_sionna_measurement_profile():
    from backend.skills.uav_spectrum_sim.contracts import MissionPlan

    plan = MissionPlan(
        mission_id="uav_sionna_profile",
        template="hover",
        measurement_profile_id="sionna_urban_2_4ghz",
        expires_at=time.time() + 60,
    )

    assert plan.measurement_profile_id == "sionna_urban_2_4ghz"
    with pytest.raises(ValidationError):
        MissionPlan.model_validate({
            **plan.model_dump(),
            "measurement_profile_id": "sionna_custom_5ghz",
        })


def test_completed_mission_records_a_sionna_observation_without_expanding_flight_control():
    from backend.skills.uav_spectrum_sim.contracts import MissionPlan
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    status = {
        "runtime": {
            "state": "running",
            "manual": {"enabled": False},
            "agent_navigation": {"ready": True},
            "camera": {"vehicle": {"position_m": [3.0, -4.0, 12.0]}},
        },
    }
    flight_actions: list[str] = []

    class FakeMeasurementRunner:
        def measure(self, *, run_id, position_m, timestamp):
            assert run_id == "uav_sionna_execute"
            assert position_m == [3.0, -4.0, 12.0]
            assert timestamp > 0
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": "sionna_urban_2_4ghz",
                "position_m": position_m,
                "frequency_hz": 2.4e9,
                "anchors": [{"id": "tx-01", "received_power_dbm": -65.0, "path_count": 2}],
            }

    service = UavMissionService(
        status_reader=lambda: status,
        command_executor=lambda action, altitude_m=None: flight_actions.append(action) or {"ok": True},
        navigation_clearer=lambda: {"ok": True},
        measurement_runner=FakeMeasurementRunner(),
    )
    result = service.execute_plan(MissionPlan(
        mission_id="uav_sionna_execute",
        template="hover",
        measurement_profile_id="sionna_urban_2_4ghz",
        expires_at=time.time() + 60,
    ))

    assert result["ok"] is True
    assert flight_actions == ["hover"]
    assert result["spectrum_observation"]["source"] == "sionna_rt"
    assert result["spectrum_observation"]["position_m"] == [3.0, -4.0, 12.0]
    assert result["events"][-1]["event_type"] == "observation"


def test_navigation_plan_samples_each_confirmed_waypoint_with_the_live_pose():
    from backend.skills.uav_spectrum_sim.contracts import MissionPlan
    from backend.skills.uav_spectrum_sim.mission import SAFE_PERIMETER_ROUTE, UavMissionService

    status = {
        "runtime": {
            "state": "running",
            "manual": {"enabled": False},
            "agent_navigation": {"ready": True},
            "camera": {"vehicle": {"position_m": [0.0, 0.0, 20.0]}},
        },
    }
    samples: list[tuple[str, list[float]]] = []

    class FakeMeasurementRunner:
        def measure(self, *, run_id, position_m, timestamp):
            samples.append((run_id, position_m))
            return {
                "kind": "spectrum_observation",
                "source": "sionna_rt",
                "profile_id": "sionna_urban_2_4ghz",
                "timestamp": timestamp,
                "position_m": position_m,
                "frequency_hz": 2.4e9,
                "anchors": [],
            }

    service = UavMissionService(
        status_reader=lambda: status,
        command_executor=lambda *_args: {"ok": True},
        navigation_writer=lambda *_args: {"ok": True},
        navigation_clearer=lambda: {"ok": True},
        measurement_runner=FakeMeasurementRunner(),
    )
    service._takeoff_to_cruise = lambda _mission: None
    def arrive_with_two_progress_samples(_target, on_progress=None):
        if on_progress is not None:
            on_progress()
            on_progress()
        return "arrived"

    service._wait_for_position = arrive_with_two_progress_samples

    result = service.execute_plan(MissionPlan(
        mission_id="uav_live_rf_route",
        template="inspect_safe_perimeter",
        measurement_profile_id="sionna_urban_2_4ghz",
        expires_at=time.time() + 60,
    ))

    assert result["ok"] is True
    assert len(samples) == len(SAFE_PERIMETER_ROUTE) * 3
    assert [run_id for run_id, _position in samples] == [
        f"uav_live_rf_route_rf_{index:02d}" for index in range(1, len(SAFE_PERIMETER_ROUTE) * 3 + 1)
    ]
    assert sum(event["event_type"] == "observation" for event in result["events"]) == len(SAFE_PERIMETER_ROUTE) * 3
