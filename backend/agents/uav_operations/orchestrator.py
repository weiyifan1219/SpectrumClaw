"""Draft, approval and audited execution coordinator for UAV operations."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ...skills.uav_spectrum_sim.audit import AuditEvent
from ...skills.uav_spectrum_sim.mission import UavMissionService, get_uav_mission_service
from ...skills.uav_spectrum_sim.policy import MissionPolicy
from .deepseek_planner import DeepSeekMissionPlanner
from .mission_author import MissionAuthor
from .sandbox import MissionSandbox


DEFAULT_SANDBOX_ROOT = Path("data/uav-agent-runs")


class UavOperationsOrchestrator:
    """Keep draft approval separate from task execution and manual control."""

    def __init__(
        self,
        *,
        service: UavMissionService | Any | None = None,
        sandbox_root: str | Path = DEFAULT_SANDBOX_ROOT,
        policy: MissionPolicy | None = None,
    ) -> None:
        self._service = service or get_uav_mission_service()
        self._sandbox = MissionSandbox(sandbox_root)
        self._author = DeepSeekMissionPlanner(MissionAuthor(self._sandbox), self._sandbox)
        self._policy = policy or MissionPolicy()
        self._lock = threading.RLock()
        self._runs: dict[str, dict[str, Any]] = {}
        self._restore_runs()

    @staticmethod
    def _digest(plan: dict[str, Any]) -> str:
        payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _event(
        event_type: str,
        summary: str,
        *,
        run_id: str | None = None,
        trace_id: str | None = None,
        **data: Any,
    ) -> dict[str, Any]:
        """Create a public event with stable task correlation identifiers."""
        if run_id:
            data.setdefault("run_id", run_id)
        if trace_id:
            data.setdefault("trace_id", trace_id)
        event = AuditEvent(event_type=event_type, summary=summary, data=data).to_public_dict()
        # Keep correlation available to generic SSE/log consumers without
        # requiring each consumer to unpack the event payload.
        if run_id:
            event["run_id"] = run_id
        if trace_id:
            event["trace_id"] = trace_id
        return event

    @classmethod
    def _correlate_events(cls, run: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Attach task identity to adapter events originating below the agent layer."""
        return [
            cls._event(
                str(event.get("event_type", "observation")),
                str(event.get("summary", "无人机适配层事件。")),
                run_id=str(run["run_id"]),
                trace_id=str(run["trace_id"]),
                **dict(event.get("data") or {}),
            )
            for event in events
        ]

    @staticmethod
    def _copy(run: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(run))

    def _status(self) -> dict[str, Any]:
        return self._service._status_reader()

    def _persist(self, run: dict[str, Any]) -> None:
        self._sandbox.write_json(str(run["run_id"]), "run_state.json", self._copy(run))

    def _restore_runs(self) -> None:
        """Restore terminal history and safely close work orphaned by a restart."""
        if not self._sandbox.root.is_dir():
            return
        for path in self._sandbox.root.glob("*/run_state.json"):
            run_id = path.parent.name
            run = self._sandbox.read_json(run_id, "run_state.json")
            if not run or run.get("run_id") != run_id:
                continue
            # Records created before correlation identifiers were introduced
            # remain readable and gain a deterministic trace identifier.
            run.setdefault("trace_id", f"uav-trace-{run_id}")
            if run.get("status") == "running":
                ended_at = time.time()
                run.update(
                    status="interrupted",
                    summary="任务编排服务已重启；原任务被安全终止，请复核后重新创建任务。",
                    updated_at=ended_at,
                    ended_at=ended_at,
                    lifecycle={"phase": "interrupted", "terminal": True, "reason": "orchestrator_restarted"},
                )
                run.setdefault("events", []).append(
                    self._event(
                        "interruption",
                        run["summary"],
                        run_id=run_id,
                        trace_id=run.get("trace_id"),
                        reason="orchestrator_restarted",
                    )
                )
                self._persist(run)
            self._runs[run_id] = run

    def create_draft(self, intent: str) -> dict[str, Any]:
        with self._lock:
            run_id = f"uav_{uuid.uuid4().hex[:16]}"
            trace_id = f"uav-trace-{uuid.uuid4().hex[:16]}"
            plan, planner = self._author.author(run_id, intent)
            decision = self._policy.validate(plan, self._status())
            run = {
                "run_id": run_id,
                "trace_id": trace_id,
                "intent": intent,
                "status": "awaiting_approval" if decision.allowed else "rejected",
                "plan": plan.model_dump(),
                "plan_digest": self._digest(plan.model_dump()),
                "created_at": time.time(),
                "started_at": None,
                "ended_at": None,
                "updated_at": time.time(),
                "summary": decision.summary,
                "planner": planner,
                "events": [
                    self._event("intent", "已生成受限任务草案。", run_id=run_id, trace_id=trace_id, template=plan.template, planner=planner["provider"]),
                    self._event("policy_decision", decision.summary, run_id=run_id, trace_id=trace_id, allowed=decision.allowed, code=decision.code),
                ],
                "lifecycle": {"phase": "draft", "terminal": False, "reason": None},
            }
            if not decision.allowed:
                run["error_code"] = decision.code
                run["lifecycle"] = {"phase": "rejected", "terminal": True, "reason": decision.code}
            self._runs[run_id] = run
            self._persist(run)
            return self._copy(run)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            return self._copy(run) if run else None

    def _prepare_approval(self, run_id: str, plan_digest: str):
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return None, {"run_id": run_id, "status": "missing", "error_code": "run_not_found"}
            if run["status"] != "awaiting_approval":
                return None, self._copy(run)
            if plan_digest != run["plan_digest"]:
                return None, {**self._copy(run), "error_code": "plan_digest_mismatch"}
            from ...skills.uav_spectrum_sim.contracts import MissionPlan

            plan = MissionPlan.model_validate(run["plan"])
            decision = self._policy.validate(plan, self._status())
            run["events"].append(
                self._event(
                    "policy_decision",
                    decision.summary,
                    run_id=run_id,
                    trace_id=run["trace_id"],
                    allowed=decision.allowed,
                    code=decision.code,
                )
            )
            if not decision.allowed:
                rejected_at = time.time()
                run.update(
                    status="rejected",
                    error_code=decision.code,
                    summary=decision.summary,
                    updated_at=rejected_at,
                    ended_at=rejected_at,
                    lifecycle={"phase": "rejected", "terminal": True, "reason": decision.code},
                )
                self._persist(run)
                return None, self._copy(run)
            started_at = time.time()
            run.update(
                status="running",
                summary="任务已开始，正在通过受限飞控适配层执行。",
                updated_at=started_at,
                started_at=started_at,
                lifecycle={"phase": "started", "terminal": False, "reason": None},
            )
            run["events"].append(
                self._event(
                    "run_started",
                    "任务已开始执行，飞控适配层已接管受限计划。",
                    run_id=run_id,
                    trace_id=run["trace_id"],
                    template=plan.template,
                )
            )
            self._persist(run)
            return plan, None

    def _execute_approved_plan(self, run_id: str, plan) -> dict[str, Any]:
        try:
            result = self._service.execute_plan(plan)
        except Exception as exc:  # preserve a terminal lifecycle for unexpected bridge faults
            result = {"ok": False, "error_code": "execution_interrupted", "message": f"任务执行意外中断：{exc}", "events": []}
        with self._lock:
            run = self._runs[run_id]
            run["events"].extend(self._correlate_events(run, result.get("events", [])))
            if run.get("status") == "cancelled":
                run["events"].append(
                    self._event("completion", "任务已在执行期间取消。", run_id=run_id, trace_id=run["trace_id"], ok=False)
                )
                self._persist(run)
                return self._copy(run)
            completed_at = time.time()
            terminal_status = "completed" if result.get("ok") else "failed"
            run.update(
                status=terminal_status,
                summary=str(result.get("message", "任务已成功完成，已在安全终点悬停。")) if result.get("ok") else str(result.get("message", "任务执行失败。")),
                updated_at=completed_at,
                ended_at=completed_at,
                result=result,
                lifecycle={
                    "phase": "completed" if result.get("ok") else "failed",
                    "terminal": True,
                    "reason": result.get("error_code"),
                    "terminal_action": result.get("terminal_action"),
                },
            )
            if not result.get("ok"):
                run["error_code"] = result.get("error_code", "mission_failed")
            self._sandbox.write_text(run_id, "report.md", f"# UAV 任务报告\n\n{run['summary']}\n")
            self._persist(run)
            return self._copy(run)

    def approve(self, run_id: str, plan_digest: str) -> dict[str, Any]:
        """Synchronous approval for direct callers and unit tests."""
        plan, result = self._prepare_approval(run_id, plan_digest)
        return result if result is not None else self._execute_approved_plan(run_id, plan)

    def start_approval(self, run_id: str, plan_digest: str) -> dict[str, Any]:
        """Start the bounded task in a daemon worker so HTTP can stream events."""
        plan, result = self._prepare_approval(run_id, plan_digest)
        if result is not None:
            return result
        worker = threading.Thread(
            target=self._execute_approved_plan,
            args=(run_id, plan),
            name=f"uav-agent-{run_id}",
            daemon=True,
        )
        worker.start()
        return self.get_run(run_id) or {"run_id": run_id, "status": "missing"}

    def cancel(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return {"run_id": run_id, "status": "missing", "error_code": "run_not_found"}
            result = self._service.cancel()
            ended_at = time.time()
            run.update(
                status="cancelled",
                summary="任务已取消，已请求 PX4 悬停。",
                updated_at=ended_at,
                ended_at=ended_at,
                lifecycle={"phase": "cancelled", "terminal": True, "reason": "user_cancelled", "terminal_action": "hover"},
            )
            run["events"].append(
                self._event(
                    "completion",
                    run["summary"],
                    run_id=run_id,
                    trace_id=run["trace_id"],
                    ok=bool(result.get("ok")),
                )
            )
            self._persist(run)
            return self._copy(run)


_orchestrator: UavOperationsOrchestrator | None = None


def get_uav_operations_orchestrator() -> UavOperationsOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = UavOperationsOrchestrator()
    return _orchestrator
