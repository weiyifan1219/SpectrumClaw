"""Fixed-route UAV survey that reconstructs one complete RF height layer."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .contracts import MissionPlan
from .mission import UavMissionService
from .route_planner import plan_obstacle_aware_route
from .runtime import get_runtime_status, scene_definition
from .sionna_measurement import (
    MEASUREMENT_PROFILE_ID,
    SionnaMeasurementRunner,
    get_realtime_sionna_coordinator,
)


SURVEY_LAYER_INDEX = 4
SURVEY_HEIGHT_RANGE_M = [20.0, 25.0]
SURVEY_ALTITUDE_M = 21.0
SURVEY_COVERAGE_TARGETS = (
    (0.0, -30.0, SURVEY_ALTITUDE_M),
    (-30.0, -30.0, SURVEY_ALTITUDE_M),
    (30.0, -30.0, SURVEY_ALTITUDE_M),
    (30.0, 34.0, SURVEY_ALTITUDE_M),
    (-30.0, 34.0, SURVEY_ALTITUDE_M),
    (-30.0, -30.0, SURVEY_ALTITUDE_M),
    (0.0, 0.0, SURVEY_ALTITUDE_M),
)


class _CampaignMeasurementRunner:
    def __init__(self, delegate: Any, coordinator: Any, on_sample: Callable[[dict[str, Any]], None]) -> None:
        self._delegate = delegate
        self._coordinator = coordinator
        self._on_sample = on_sample

    def measure(self, *, run_id: str, position_m: list[float], timestamp: float) -> dict[str, Any]:
        observation = self._delegate.measure(run_id=run_id, position_m=position_m, timestamp=timestamp)
        self._coordinator.ingest_observation(observation)
        self._on_sample(observation)
        return observation


class SpectrumSurveyService:
    """Run one bounded perimeter mission and expose reconstruction progress."""

    def __init__(
        self,
        *,
        coordinator: Any | None = None,
        measurement_runner: Any | None = None,
        mission_service_factory: Callable[[Any], Any] | None = None,
        survey_route: tuple[tuple[float, float, float], ...] | None = None,
        status_reader: Callable[[], dict[str, Any]] = get_runtime_status,
        executor: Any | None = None,
        time_fn: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._measurement_runner = measurement_runner
        if survey_route is None:
            self._survey_route = plan_obstacle_aware_route(
                start=(0.0, 0.0, SURVEY_ALTITUDE_M),
                targets=SURVEY_COVERAGE_TARGETS,
                objects=scene_definition()["objects"],
                bounds_m=(-35.0, 35.0),
                resolution_m=2.0,
                clearance_m=2.5,
            )
        else:
            self._survey_route = tuple(tuple(float(value) for value in point) for point in survey_route)
        self._mission_service_factory = mission_service_factory
        self._status_reader = status_reader
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="spectrum-survey")
        self._time_fn = time_fn
        self._id_factory = id_factory or (lambda: f"rf-survey-{uuid.uuid4().hex[:12]}")
        self._lock = threading.Lock()
        self._future: Any | None = None
        self._status = self._idle_status()

    def _idle_status(self) -> dict[str, Any]:
        return {
            "state": "idle",
            "campaign_id": None,
            "layer_index": SURVEY_LAYER_INDEX,
            "height_range_m": list(SURVEY_HEIGHT_RANGE_M),
            "planned_waypoints": len(self._survey_route),
            "route_strategy": "astar_inflated_grid",
            "route_waypoints_m": [list(point) for point in self._survey_route],
            "obstacle_clearance_m": 2.5,
            "samples_collected": 0,
            "last_sample_position_m": None,
            "reconstruction_ready": False,
            "reconstruction_method": "blind_path_loss_idw",
            "started_at": None,
            "completed_at": None,
            "message": "等待启动高度层采样",
            "error": "",
        }

    def _get_coordinator(self):
        if self._coordinator is None:
            self._coordinator = get_realtime_sionna_coordinator()
        return self._coordinator

    def _on_sample(self, observation: dict[str, Any]) -> None:
        with self._lock:
            self._status["samples_collected"] += 1
            self._status["last_sample_position_m"] = list(observation.get("position_m") or [])
            self._status["message"] = (
                f"已采集 {self._status['samples_collected']} 个频谱样本，继续沿安全航线飞行"
            )

    def _run(self, campaign_id: str) -> None:
        coordinator = self._get_coordinator()
        delegate = self._measurement_runner or SionnaMeasurementRunner()
        runner = _CampaignMeasurementRunner(delegate, coordinator, self._on_sample)
        mission_service = (
            self._mission_service_factory(runner)
            if self._mission_service_factory is not None
            else UavMissionService(
                measurement_runner=runner,
                safe_perimeter_route=self._survey_route,
                position_observer=lambda position: coordinator.observe_pose(position),
            )
        )
        try:
            result = mission_service.execute_plan(MissionPlan(
                mission_id=campaign_id,
                template="inspect_safe_perimeter",
                measurement_profile_id=MEASUREMENT_PROFILE_ID,
                return_home=False,
                expires_at=float(self._time_fn()) + 600.0,
            ))
            if not result.get("ok"):
                raise RuntimeError(str(result.get("message") or "高度层采样任务失败"))
            wait_for_measurements = getattr(coordinator, "wait_for_measurements", None)
            if callable(wait_for_measurements):
                with self._lock:
                    self._status.update({
                        "state": "draining",
                        "message": "飞行完成，正在补齐航迹经过的实测网格",
                    })
                if not wait_for_measurements(timeout_s=120.0, layer_index=SURVEY_LAYER_INDEX):
                    raise RuntimeError("航迹网格的 Sionna RT 实测队列未在限定时间内完成")
            grid = coordinator.grid_snapshot(layer_index=SURVEY_LAYER_INDEX, transmitter_id="all")
            reconstruction = grid.get("reconstruction", {})
            with self._lock:
                self._status.update({
                    "state": "completed",
                    "completed_at": float(self._time_fn()),
                    "reconstruction_ready": bool(reconstruction.get("ready")),
                    "reconstruction_method": str(reconstruction.get("method") or "blind_path_loss_idw"),
                    "message": "A* 避障航线采样完成，已生成盲源定位与残差插值态势",
                    "error": "",
                })
        except Exception as exc:
            with self._lock:
                self._status.update({
                    "state": "failed",
                    "completed_at": float(self._time_fn()),
                    "message": "高度层采样未完成",
                    "error": str(exc),
                })

    def start(self) -> dict[str, Any]:
        runtime_status = self._status_reader()
        runtime = runtime_status.get("runtime", {}) if isinstance(runtime_status, dict) else {}
        if runtime.get("state") != "running":
            raise RuntimeError("PX4/Gazebo 仿真未运行，无法启动高度层采样")
        if runtime.get("manual", {}).get("enabled"):
            raise RuntimeError("手动飞控正在接管无人机，请先释放后再启动高度层采样")
        with self._lock:
            if self._status.get("state") in {"running", "draining"}:
                raise RuntimeError("高度层采样任务正在运行")
            campaign_id = self._id_factory()
            self._status = {
                **self._idle_status(),
                "state": "running",
                "campaign_id": campaign_id,
                "started_at": float(self._time_fn()),
                "message": f"无人机将飞往 Z4 高度层，并沿 {len(self._survey_route)} 个 A* 避障航点采样",
            }
        self._get_coordinator().clear_grid_layer(SURVEY_LAYER_INDEX)
        self._future = self._executor.submit(self._run, campaign_id)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)


_SURVEY_SERVICE: SpectrumSurveyService | None = None
_SURVEY_SERVICE_LOCK = threading.Lock()


def get_spectrum_survey_service() -> SpectrumSurveyService:
    global _SURVEY_SERVICE
    with _SURVEY_SERVICE_LOCK:
        if _SURVEY_SERVICE is None:
            _SURVEY_SERVICE = SpectrumSurveyService()
        return _SURVEY_SERVICE
