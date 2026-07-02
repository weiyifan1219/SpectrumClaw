from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class JobRecord:
    job_id: str
    kind: str
    title: str
    status: str
    started_at: float
    updated_at: float
    finished_at: float | None = None
    thread_id: str = ""
    provider: str = ""
    model: str = ""
    prompt_preview: str = ""
    last_error: str = ""
    last_event: str = ""
    stages: dict[str, str] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    next_seq: int = 1


class JobStore:
    def __init__(self, max_jobs: int = 100, max_events_per_job: int = 300):
        self._lock = threading.RLock()
        self._max_jobs = max_jobs
        self._max_events_per_job = max_events_per_job
        self._jobs: dict[str, JobRecord] = {}
        self._order: list[str] = []

    def reset(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._order.clear()

    def start_job(
        self,
        *,
        kind: str,
        title: str,
        thread_id: str = "",
        provider: str = "",
        model: str = "",
        prompt_preview: str = "",
    ) -> str:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = time.time()
        record = JobRecord(
            job_id=job_id,
            kind=kind,
            title=title or kind,
            status="running",
            started_at=now,
            updated_at=now,
            thread_id=thread_id,
            provider=provider,
            model=model,
            prompt_preview=prompt_preview,
        )
        with self._lock:
            self._jobs[job_id] = record
            self._order.insert(0, job_id)
            self._trim_jobs()
        return job_id

    def record_event(self, job_id: str, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            record = self._jobs[job_id]
            annotated = dict(event)
            annotated["job_id"] = job_id
            annotated["trace_seq"] = record.next_seq
            record.next_seq += 1
            record.updated_at = float(annotated.get("ts") or time.time())
            record.last_event = str(annotated.get("type") or annotated.get("event") or "")
            record.events.append(annotated)
            if len(record.events) > self._max_events_per_job:
                record.events = record.events[-self._max_events_per_job :]
            self._apply_event(record, annotated)
            return dict(annotated)

    def list_jobs(self, *, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            job_ids = list(self._order)
            jobs = []
            for job_id in job_ids:
                record = self._jobs.get(job_id)
                if record is None:
                    continue
                if status and record.status != status:
                    continue
                jobs.append(self._summary(record))
                if len(jobs) >= limit:
                    break
            return jobs

    def get_job(self, job_id: str, *, event_limit: int | None = None) -> dict[str, Any] | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            payload = self._summary(record)
            events = list(record.events if event_limit is None else record.events[-event_limit:])
            payload["events"] = [dict(event) for event in events]
            return payload

    def _apply_event(self, record: JobRecord, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or event.get("event") or "")
        if event_type in {"stage", "stage_done"}:
            stage = str(event.get("stage") or "")
            if stage:
                status = "done" if event.get("status") == "done" or event_type == "stage_done" else "active"
                record.stages[stage] = status
        if event_type == "done":
            record.status = "completed"
            record.finished_at = float(event.get("ts") or time.time())
        elif event_type == "error":
            record.status = "error"
            record.finished_at = float(event.get("ts") or time.time())
            record.last_error = str(event.get("data") or "")

        data = event.get("data")
        if isinstance(data, dict):
            if data.get("thread_id"):
                record.thread_id = str(data["thread_id"])
            if data.get("runtime") and not record.title.endswith(f"· {data['runtime']}"):
                record.title = f"{record.title} · {data['runtime']}"

    def _trim_jobs(self) -> None:
        while len(self._order) > self._max_jobs:
            job_id = self._order.pop()
            self._jobs.pop(job_id, None)

    @staticmethod
    def _summary(record: JobRecord) -> dict[str, Any]:
        return {
            "job_id": record.job_id,
            "kind": record.kind,
            "title": record.title,
            "status": record.status,
            "started_at": record.started_at,
            "updated_at": record.updated_at,
            "finished_at": record.finished_at,
            "thread_id": record.thread_id,
            "provider": record.provider,
            "model": record.model,
            "prompt_preview": record.prompt_preview,
            "last_error": record.last_error,
            "last_event": record.last_event,
            "stages": dict(record.stages),
            "event_count": len(record.events),
        }


_job_store = JobStore()


def get_job_store() -> JobStore:
    return _job_store
