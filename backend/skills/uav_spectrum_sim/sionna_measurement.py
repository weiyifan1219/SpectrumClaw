"""Bounded bridge from a UAV pose to one Sionna RT observation."""

from __future__ import annotations

import atexit
import json
import math
import os
import re
import selectors
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any


MEASUREMENT_PROFILE_ID = "sionna_urban_2_4ghz"
DEFAULT_RUNTIME_ROOT = Path("/workspace/YiFan/spectrumclaw_runtime")
DEFAULT_SIDECAR = Path("simulation/rf_engine/sionna_measurement_sidecar.py")
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{3,96}$")
_RESULT_PREFIX = "SPECTRUMCLAW_RESULT "
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _valid_observation(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("kind") == "spectrum_observation"
        and payload.get("source") == "sionna_rt"
        and payload.get("profile_id") == MEASUREMENT_PROFILE_ID
        and isinstance(payload.get("position_m"), list)
        and len(payload["position_m"]) == 3
        and isinstance(payload.get("anchors"), list)
    )


def _runtime_position(runtime_status: dict[str, Any] | None) -> list[float] | None:
    runtime = runtime_status.get("runtime", {}) if isinstance(runtime_status, dict) else {}
    camera = runtime.get("camera", {}) if isinstance(runtime, dict) else {}
    vehicle = camera.get("vehicle", {}) if isinstance(camera, dict) else {}
    position = vehicle.get("position_m") if isinstance(vehicle, dict) else None
    if not isinstance(position, list) or len(position) != 3:
        return None
    try:
        parsed = [float(value) for value in position]
    except (TypeError, ValueError):
        return None
    return parsed if all(math.isfinite(value) for value in parsed) else None


def get_sionna_spectrum_situation(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
    runtime_status: dict[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Return the newest validated Sionna observation without running Sionna.

    This is intentionally a read-only view for the operations UI.  A displayed
    observation always carries its age and ENU offset from the current vehicle
    pose, so a cached measurement cannot masquerade as a live RF update.
    """
    root = Path(runtime_root) / "artifacts" / "uav-sionna"
    current_position = _runtime_position(runtime_status)
    candidates = sorted(root.glob("*/observation.json"), key=lambda path: path.stat().st_mtime, reverse=True) if root.is_dir() else []
    history: list[dict[str, Any]] = []
    latest: dict[str, Any] | None = None
    for path in candidates:
        try:
            observation = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not _valid_observation(observation):
            continue
        captured_at = float(observation.get("timestamp") or path.stat().st_mtime)
        age_s = max(0.0, float(time.time() if now is None else now) - captured_at)
        observed_position = [float(value) for value in observation["position_m"]]
        pose_offset_m = (
            math.dist(current_position, observed_position)
            if current_position is not None else None
        )
        snapshot = {
            "run_id": path.parent.name,
            "captured_at": captured_at,
            "position_m": observed_position,
            "anchors": observation["anchors"],
        }
        history.append(snapshot)
        if latest is not None:
            continue
        latest = {
            "available": True,
            "current": bool(pose_offset_m is not None and pose_offset_m <= 2.0 and age_s <= 300.0),
            "profile_id": MEASUREMENT_PROFILE_ID,
            "run_id": path.parent.name,
            "captured_at": captured_at,
            "age_s": round(age_s, 1),
            "current_position_m": current_position,
            "pose_offset_m": round(pose_offset_m, 2) if pose_offset_m is not None else None,
            "observation": observation,
        }
    if latest is not None:
        latest["history"] = history[:16]
        return latest
    return {
        "available": False,
        "current": False,
        "profile_id": MEASUREMENT_PROFILE_ID,
        "current_position_m": current_position,
        "reason": "尚未采集 Sionna RT 频谱观测",
        "history": [],
    }


def collect_current_sionna_observation(
    *,
    runtime_status: dict[str, Any],
    runner: "SionnaMeasurementRunner | None" = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Measure only the current simulator pose; never issue a flight command."""
    runtime = runtime_status.get("runtime", {}) if isinstance(runtime_status, dict) else {}
    if runtime.get("state") != "running":
        raise ValueError("PX4/Gazebo 仿真未运行，无法采集频谱观测")
    position_m = _runtime_position(runtime_status)
    if position_m is None:
        raise ValueError("当前仿真未提供有效无人机 ENU 位姿")
    timestamp = float(time.time() if now is None else now)
    measurement_runner = runner or SionnaMeasurementRunner()
    return measurement_runner.measure(
        run_id=f"sionna_live_{int(timestamp * 1000)}",
        position_m=position_m,
        timestamp=timestamp,
    )


class SionnaWorkerClient:
    """Serialized JSONL client for one warm GPU-side Sionna process."""

    def __init__(self, sidecar: str | Path) -> None:
        path = Path(sidecar)
        self._sidecar = path if path.is_absolute() else (_PROJECT_ROOT / path).resolve()
        self._python = Path(os.environ.get(
            "SPECTRUMCLAW_SIONNA_PYTHON",
            "/root/miniconda3/envs/spectrumclaw-rt/bin/python",
        ))
        self._asset_dir = Path(os.environ.get(
            "SPECTRUMCLAW_SIONNA_ASSET_DIR",
            str(DEFAULT_RUNTIME_ROOT / "artifacts" / "uav-sionna" / "scene"),
        ))
        self._timeout_s = max(2.0, float(os.environ.get("SPECTRUMCLAW_SIONNA_WORKER_TIMEOUT_S", "30")))
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._recent_output: list[str] = []

    def _start(self) -> subprocess.Popen:
        if self._process is not None and self._process.poll() is None:
            return self._process
        if not self._python.is_file():
            raise RuntimeError(f"未找到 Sionna RT Python: {self._python}")
        if not self._sidecar.is_file():
            raise RuntimeError(f"未找到 Sionna RT 实时侧车: {self._sidecar}")
        self._asset_dir.mkdir(parents=True, exist_ok=True)
        self._process = subprocess.Popen(
            [str(self._python), "-u", str(self._sidecar), "--serve", "--assets", str(self._asset_dir)],
            cwd=str(_PROJECT_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        return self._process

    def _stop(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _measure_once(self, request: dict[str, Any]) -> dict[str, Any]:
        process = self._start()
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Sionna RT 实时侧车管道不可用")
        request_id = uuid.uuid4().hex
        payload = {**request, "request_id": request_id}
        process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + self._timeout_s
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Sionna RT 实时计算超时")
                if process.poll() is not None:
                    detail = self._recent_output[-1] if self._recent_output else "worker exited"
                    raise RuntimeError(f"Sionna RT 实时侧车退出: {detail}")
                if not selector.select(remaining):
                    raise RuntimeError("Sionna RT 实时计算超时")
                line = process.stdout.readline()
                if not line:
                    continue
                stripped = line.strip()
                if not stripped.startswith(_RESULT_PREFIX):
                    self._recent_output = [*self._recent_output[-19:], stripped]
                    continue
                response = json.loads(stripped.removeprefix(_RESULT_PREFIX))
                if response.get("request_id") != request_id:
                    continue
                if not response.get("ok"):
                    raise RuntimeError(str(response.get("error") or "Sionna RT 实时计算失败"))
                observation = response.get("observation")
                if not isinstance(observation, dict):
                    raise RuntimeError("Sionna RT 实时侧车没有返回观测")
                return observation
        finally:
            selector.close()

    def measure(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            last_error: Exception | None = None
            for _attempt in range(2):
                try:
                    return self._measure_once(request)
                except (BrokenPipeError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                    last_error = exc
                    self._stop()
            raise RuntimeError(str(last_error or "Sionna RT 实时侧车不可用"))

    def close(self) -> None:
        with self._lock:
            self._stop()


_WORKER_CLIENTS: dict[str, SionnaWorkerClient] = {}
_WORKER_CLIENTS_LOCK = threading.Lock()


def _get_worker_client(sidecar: str | Path) -> SionnaWorkerClient:
    path = Path(sidecar)
    key = str(path if path.is_absolute() else (_PROJECT_ROOT / path).resolve())
    with _WORKER_CLIENTS_LOCK:
        client = _WORKER_CLIENTS.get(key)
        if client is None:
            client = SionnaWorkerClient(key)
            _WORKER_CLIENTS[key] = client
        return client


def _close_worker_clients() -> None:
    with _WORKER_CLIENTS_LOCK:
        clients = list(_WORKER_CLIENTS.values())
        _WORKER_CLIENTS.clear()
    for client in clients:
        client.close()


atexit.register(_close_worker_clients)


class RealtimeSionnaCoordinator:
    """Queue one real RT solve for every grid cell crossed by the UAV.

    Pose observation stays non-blocking. A single background worker drains the
    ordered, de-duplicated cell queue, preserving the complete measurement
    footprint without coupling flight control to Sionna latency.
    """

    def __init__(
        self,
        *,
        runner: "SionnaMeasurementRunner | None" = None,
        executor: Any | None = None,
        spectrum_grid: Any | None = None,
        movement_threshold_m: float = 0.5,
        min_interval_s: float = 0.4,
        max_measurement_attempts: int = 3,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self._runner = runner or SionnaMeasurementRunner()
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="sionna-realtime")
        self._owns_executor = executor is None
        if spectrum_grid is None:
            from .realtime_grid import RealtimeSpectrumGrid
            spectrum_grid = RealtimeSpectrumGrid()
        self._spectrum_grid = spectrum_grid
        self._movement_threshold_m = max(0.05, float(movement_threshold_m))
        self._min_interval_s = max(0.05, float(min_interval_s))
        self._max_measurement_attempts = max(1, int(max_measurement_attempts))
        self._time_fn = time_fn
        self._lock = threading.Lock()
        self._future: Future | None = None
        self._draining = False
        self._measurement_queue: deque[dict[str, Any]] = deque()
        self._scheduled_cells: set[tuple[int, int, int]] = set()
        self._measured_cells: set[tuple[int, int, int]] = set()
        self._failed_cells: dict[tuple[int, int, int], dict[str, Any]] = {}
        self._layer_generations: dict[int, int] = {}
        self._last_telemetry_position: list[float] | None = None
        self._measurement_track: list[dict[str, Any]] = []
        self._measurement_index = 0
        self._target_position: list[float] | None = None
        self._target_cell_key: tuple[int, int, int] | None = None
        self._last_requested_at = float("-inf")
        self._latest: dict[str, Any] | None = None
        self._sequence = 0
        self._error = ""
        self._last_grid_update: dict[str, Any] | None = None

    def _accept_observation_locked(self, observation: dict[str, Any]) -> None:
        try:
            grid_update = self._spectrum_grid.record(observation)
        except ValueError as exc:
            self._last_grid_update = None
            self._error = str(exc)
            raise
        self._latest = observation
        self._sequence += 1
        self._last_grid_update = grid_update
        cell_key = (
            int(self._last_grid_update["layer_index"]),
            int(self._last_grid_update["row"]),
            int(self._last_grid_update["column"]),
        )
        self._measured_cells.add(cell_key)
        self._scheduled_cells.discard(cell_key)
        self._failed_cells.pop(cell_key, None)
        self._measurement_track.append({
            "sequence": self._sequence,
            "source": "sionna_rt",
            "captured_at": float(observation.get("timestamp") or 0.0),
            "position_m": list(observation.get("position_m") or []),
            "grid_update": dict(self._last_grid_update),
        })
        self._measurement_track.sort(key=lambda item: (float(item["captured_at"]), int(item["sequence"])))
        self._measurement_track = self._measurement_track[-512:]
        self._error = ""

    def _handle_measurement_failure_locked(self, item: dict[str, Any], exc: Exception) -> None:
        current_generation = self._layer_generations.get(item["cell_key"][0], 0)
        if item["generation"] != current_generation:
            return
        if int(item["attempts"]) < self._max_measurement_attempts:
            self._measurement_queue.append(item)
            self._error = (
                f"{exc}；网格 {item['cell_key']} 将进行 "
                f"{int(item['attempts']) + 1}/{self._max_measurement_attempts} 次尝试"
            )
            return
        self._scheduled_cells.discard(item["cell_key"])
        self._failed_cells[item["cell_key"]] = {
            "layer_index": int(item["cell_key"][0]),
            "row": int(item["cell_key"][1]),
            "column": int(item["cell_key"][2]),
            "position_m": list(item["position_m"]),
            "attempts": int(item["attempts"]),
            "error": str(exc),
        }
        self._error = str(exc)

    def capture_generation(self, runtime_status: dict[str, Any]) -> dict[str, int]:
        """Bind a synchronous direct measurement to the current layer epoch."""
        position = _runtime_position(runtime_status)
        cell_key = self._spectrum_grid.cell_key(position) if position is not None else None
        if cell_key is None:
            raise ValueError("当前无人机位姿不在实时频谱网格范围内")
        layer_index = int(cell_key[0])
        with self._lock:
            return {
                "layer_index": layer_index,
                "generation": self._layer_generations.get(layer_index, 0),
            }

    def ingest_observation(
        self,
        observation: dict[str, Any],
        *,
        generation_token: dict[str, int] | None = None,
    ) -> None:
        if not _valid_observation(observation):
            raise ValueError("Sionna RT 实时计算返回了无效观测")
        observed_cell = self._spectrum_grid.cell_key(list(observation["position_m"]))
        if observed_cell is None:
            raise ValueError("Sionna RT 观测位姿不在实时频谱网格范围内")
        with self._lock:
            if generation_token is not None:
                token_layer = int(generation_token.get("layer_index", -1))
                token_generation = int(generation_token.get("generation", -1))
                current_generation = self._layer_generations.get(int(observed_cell[0]), 0)
                if token_layer != int(observed_cell[0]) or token_generation != current_generation:
                    raise ValueError("Sionna RT 观测已过期：所属高度层已开始新的采样任务")
            self._accept_observation_locked(observation)

    def _enqueue_trace_locked(self, position: list[float], timestamp: float) -> int:
        start = self._last_telemetry_position or list(position)
        traced = self._spectrum_grid.trace_positions(start, position)
        self._last_telemetry_position = list(position)
        added = 0
        for item in traced:
            cell_key = (int(item["layer_index"]), int(item["row"]), int(item["column"]))
            if (
                cell_key in self._measured_cells
                or cell_key in self._scheduled_cells
                or cell_key in self._failed_cells
            ):
                continue
            generation = self._layer_generations.get(cell_key[0], 0)
            self._scheduled_cells.add(cell_key)
            self._measurement_queue.append({
                **item,
                "cell_key": cell_key,
                "timestamp": float(timestamp),
                "generation": generation,
                "attempts": 0,
            })
            added += 1
        return added

    def _drain_measurement_queue(self) -> None:
        while True:
            with self._lock:
                if not self._measurement_queue:
                    self._draining = False
                    self._target_position = None
                    self._target_cell_key = None
                    return
                item = self._measurement_queue.popleft()
                if item["cell_key"] in self._measured_cells:
                    self._scheduled_cells.discard(item["cell_key"])
                    continue
                if item["generation"] != self._layer_generations.get(item["cell_key"][0], 0):
                    continue
                self._target_position = list(item["position_m"])
                self._target_cell_key = item["cell_key"]
                item["attempts"] = int(item.get("attempts", 0)) + 1
                self._measurement_index += 1
                measurement_index = self._measurement_index
            try:
                observation = self._runner.measure(
                    run_id=f"sionna_grid_{int(item['timestamp'] * 1000)}_{measurement_index:06d}",
                    position_m=list(item["position_m"]),
                    timestamp=float(item["timestamp"]),
                )
                if not _valid_observation(observation):
                    raise RuntimeError("Sionna RT 实时计算返回了无效观测")
                with self._lock:
                    current_generation = self._layer_generations.get(item["cell_key"][0], 0)
                    if item["generation"] != current_generation:
                        continue
                    self._accept_observation_locked(observation)
            except Exception as exc:
                with self._lock:
                    self._handle_measurement_failure_locked(item, exc)
                continue

    def _start_drain_if_needed(self) -> bool:
        with self._lock:
            if self._draining or not self._measurement_queue:
                return False
            self._draining = True
        future = self._executor.submit(self._drain_measurement_queue)
        with self._lock:
            self._future = future
        return True

    def observe_pose(self, position_m: list[float], *, timestamp: float | None = None) -> bool:
        """Queue crossed cells immediately and return without waiting for RT."""
        if len(position_m) != 3 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in position_m):
            return False
        captured_at = float(self._time_fn() if timestamp is None else timestamp)
        with self._lock:
            added = self._enqueue_trace_locked([float(value) for value in position_m], captured_at)
        self._start_drain_if_needed()
        return added > 0

    def request_update(self, runtime_status: dict[str, Any]) -> bool:
        runtime = runtime_status.get("runtime", {}) if isinstance(runtime_status, dict) else {}
        if runtime.get("state") != "running":
            return False
        position = _runtime_position(runtime_status)
        if position is None:
            return False
        now = float(self._time_fn())
        with self._lock:
            if now - self._last_requested_at < self._min_interval_s:
                return False
            self._last_requested_at = now
        return self.observe_pose(position, timestamp=now)

    def snapshot(self, runtime_status: dict[str, Any]) -> dict[str, Any]:
        current_position = _runtime_position(runtime_status)
        now = float(self._time_fn())
        with self._lock:
            observation = self._latest
            computing = self._draining
            target_position = list(self._target_position) if self._target_position is not None else None
            sequence = self._sequence
            error = self._error
            grid_update = dict(self._last_grid_update) if self._last_grid_update is not None else None
            measurement_track = [dict(item) for item in self._measurement_track]
            failed = [dict(item) for item in self._failed_cells.values()]
            queue_status = {
                "strategy": "grid_crossing_fifo",
                "pending": len(self._scheduled_cells),
                "tracked_cells": len(self._scheduled_cells | self._measured_cells | set(self._failed_cells)),
                "measured_cells": len(self._measured_cells),
                "failed_cells": len(self._failed_cells),
                "failed": failed,
            }
        observed_position = observation.get("position_m") if observation else None
        pose_offset = (
            math.dist(current_position, observed_position)
            if current_position is not None and isinstance(observed_position, list) else None
        )
        captured_at = float(observation.get("timestamp", 0)) if observation else None
        observed_cell = self._spectrum_grid.cell_key(list(observed_position)) if isinstance(observed_position, list) else None
        current_cell = self._spectrum_grid.cell_key(current_position) if current_position is not None else None
        return {
            "available": observation is not None,
            "current": bool(observed_cell is not None and observed_cell == current_cell),
            "profile_id": MEASUREMENT_PROFILE_ID,
            "sequence": sequence,
            "computing": computing,
            "target_position_m": target_position,
            "current_position_m": current_position,
            "pose_offset_m": round(pose_offset, 3) if pose_offset is not None else None,
            "captured_at": captured_at,
            "age_s": round(max(0.0, now - captured_at), 3) if captured_at is not None else None,
            "observation": observation,
            "grid_update": grid_update,
            "measurement_track": measurement_track,
            "measurement_queue": queue_status,
            "error": error,
        }

    def grid_snapshot(self, *, layer_index: int, transmitter_id: str = "all") -> dict[str, Any]:
        return self._spectrum_grid.snapshot(layer_index=layer_index, transmitter_id=transmitter_id)

    def wait_for_measurements(self, *, timeout_s: float = 120.0, layer_index: int | None = None) -> bool:
        """Wait only in the survey worker; pose observation and flight stay free."""
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        selected_layer = max(0, int(layer_index)) if layer_index is not None else None
        while time.monotonic() <= deadline:
            with self._lock:
                if selected_layer is None:
                    pending = bool(self._scheduled_cells)
                    failed = bool(self._failed_cells)
                else:
                    pending = any(key[0] == selected_layer for key in self._scheduled_cells)
                    failed = any(key[0] == selected_layer for key in self._failed_cells)
            if not pending:
                return not failed
            time.sleep(0.05)
        return False

    def clear_grid_layer(self, layer_index: int) -> None:
        selected_layer = max(0, int(layer_index))
        with self._lock:
            self._layer_generations[selected_layer] = self._layer_generations.get(selected_layer, 0) + 1
            self._spectrum_grid.clear_layer(selected_layer)
            self._measurement_queue = deque(
                item for item in self._measurement_queue if int(item["layer_index"]) != selected_layer
            )
            self._scheduled_cells = {key for key in self._scheduled_cells if key[0] != selected_layer}
            self._measured_cells = {key for key in self._measured_cells if key[0] != selected_layer}
            self._failed_cells = {
                key: value for key, value in self._failed_cells.items() if key[0] != selected_layer
            }
            self._measurement_track = [
                item for item in self._measurement_track
                if int(item.get("grid_update", {}).get("layer_index", -1)) != selected_layer
            ]
            if self._last_telemetry_position is not None:
                traced = self._spectrum_grid.trace_positions(self._last_telemetry_position, self._last_telemetry_position)
                if traced and int(traced[0]["layer_index"]) == selected_layer:
                    self._last_telemetry_position = None

    def close(self) -> None:
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)


_REALTIME_COORDINATOR: RealtimeSionnaCoordinator | None = None
_REALTIME_COORDINATOR_LOCK = threading.Lock()


def get_realtime_sionna_coordinator() -> RealtimeSionnaCoordinator:
    global _REALTIME_COORDINATOR
    with _REALTIME_COORDINATOR_LOCK:
        if _REALTIME_COORDINATOR is None:
            _REALTIME_COORDINATOR = RealtimeSionnaCoordinator()
        return _REALTIME_COORDINATOR


class SionnaMeasurementRunner:
    """Run the isolated Sionna environment without exposing it to flight control."""

    def __init__(
        self,
        *,
        runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
        sidecar: str | Path = DEFAULT_SIDECAR,
        conda_bin: str = "/root/miniconda3/bin/conda",
        command_executor: Callable[[list[Any]], Any] | None = None,
        worker_client: Any | None = None,
    ) -> None:
        self._runtime_root = Path(runtime_root)
        self._sidecar = Path(sidecar)
        self._conda_bin = conda_bin
        self._command_executor = command_executor or self._run
        self._worker_client = worker_client if worker_client is not None else (
            _get_worker_client(self._sidecar) if command_executor is None else None
        )

    @staticmethod
    def _run(command: list[Any]) -> None:
        completed = subprocess.run([str(part) for part in command], capture_output=True, text=True, timeout=30, check=False)
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "Sionna RT 测量侧车执行失败")

    def measure(self, *, run_id: str, position_m: list[float], timestamp: float) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("无效的 UAV 任务标识")
        if len(position_m) != 3 or not all(isinstance(value, (int, float)) for value in position_m):
            raise ValueError("Sionna 测量需要三维 ENU 位姿")

        work_dir = self._runtime_root / "artifacts" / "uav-sionna" / run_id
        work_dir.mkdir(parents=True, exist_ok=True)
        request_path = work_dir / "request.json"
        output_path = work_dir / "observation.json"
        request = {
            "profile_id": MEASUREMENT_PROFILE_ID,
            "timestamp": float(timestamp),
            "position_m": [float(value) for value in position_m],
        }
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        if self._worker_client is not None:
            observation = self._worker_client.measure(request)
            temporary = output_path.with_name(f".{output_path.name}.{threading.get_ident()}.tmp")
            temporary.write_text(json.dumps(observation, ensure_ascii=False), encoding="utf-8")
            temporary.replace(output_path)
        else:
            self._command_executor([
                self._conda_bin, "run", "--no-capture-output", "-n", "spectrumclaw-rt", "python", self._sidecar,
                "--request", request_path, "--output", output_path,
            ])
        try:
            observation = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Sionna RT 测量侧车未返回有效观测") from exc
        if not _valid_observation(observation):
            raise RuntimeError("Sionna RT 测量侧车返回了未知观测类型")
        if observation.get("profile_id") != MEASUREMENT_PROFILE_ID or observation.get("position_m") != request["position_m"]:
            raise RuntimeError("Sionna RT 测量侧车返回的位姿或配置不一致")
        return observation
