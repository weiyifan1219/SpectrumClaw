"""Best-effort hooks for recording skill runs from API handlers.

These helpers wrap skill execution with timing + success/failure capture and
persist a SkillRun record. All persistence is best-effort: failures here never
propagate and never block the main response flow.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def track_skill_run(
    skill_name: str,
    thread_id: str = "",
    input_data: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Time a skill invocation and record a SkillRun on exit.

    Yields a mutable dict the caller can populate with ``output_summary``.
    On exception the run is recorded as failed (and the exception re-raised);
    otherwise as success. Memory persistence failures are swallowed.

    Usage::

        with track_skill_run("spectrum_construction", input_data=req.model_dump()) as run:
            result = do_work(...)
            run["output_summary"] = "variant=..., resolutions=..."
            return result
    """
    t0 = time.monotonic()
    box: dict[str, Any] = {"output_summary": "", "status": "success", "error": ""}
    try:
        yield box
    except Exception as exc:
        box["status"] = "failed"
        box["error"] = str(exc)[:200]
        raise
    finally:
        try:
            from ..config import get_settings

            settings = get_settings()
            if settings.memory_enabled:
                from .service import MemoryService

                MemoryService(db_path=settings.memory_db_path).record_skill_run(
                    skill_name=skill_name,
                    thread_id=thread_id,
                    input_data=input_data or {},
                    output_summary=str(box.get("output_summary", ""))[:200],
                    status=box.get("status", "success"),
                    error=str(box.get("error", ""))[:200],
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )
        except Exception:
            pass
