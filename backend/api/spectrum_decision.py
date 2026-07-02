"""Spectrum Decision API — resource allocation with optional LLM agent assistance."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..memory.hooks import track_skill_run
from ..runtime.jobs import get_job_store

router = APIRouter(prefix="/api/spectrum-decision")


class AllocationRequest(BaseModel):
    # Manual mode
    num_users: int = Field(default=10, ge=1, le=50)
    total_bandwidth_mhz: float = Field(default=100.0, ge=10.0, le=1000.0)
    environment: str = Field(default="urban")
    frequency_mhz: float = Field(default=3500.0, ge=400.0, le=100000.0)
    seed: int = Field(default=0, ge=0)
    service_mix: dict[str, float] | None = None
    # Agent mode
    use_agent: bool = Field(default=False)
    user_request: str = Field(default="")


@router.post("/allocate")
async def handle_allocate(req: AllocationRequest):
    """Run resource allocation. If use_agent=True, the LLM agent parses
    natural language intent and explains the results."""
    agent_mode = bool(req.use_agent and req.user_request.strip())
    skill_name = "spectrum_decision_agent" if agent_mode else "spectrum_decision"
    try:
        with track_skill_run(skill_name, input_data=req.model_dump()) as run:
            if agent_mode:
                from ..skills.spectrum_decision.agent import run_agent_allocation

                result = await run_agent_allocation(
                    user_request=req.user_request,
                    num_users=req.num_users,
                    total_bandwidth_mhz=req.total_bandwidth_mhz,
                    environment=req.environment or "urban",
                    frequency_mhz=req.frequency_mhz,
                    seed=req.seed,
                    service_mix=req.service_mix,
                )
                run["output_summary"] = (
                    f"agent: users={result.get('num_users', '?')}, "
                    f"throughput={result.get('total_throughput_mbps', 0):.1f}Mbps"
                )[:200]
                return result

            # Manual mode — direct optimizer
            from ..skills.spectrum_decision.dataset import generate_users
            from ..skills.spectrum_decision.resource_allocator import allocate_multi_service

            rs = req.seed if req.seed > 0 else __import__("random").randint(1, 9999)
            users = generate_users(
                num_users=req.num_users, seed=rs,
                environment=req.environment, frequency_mhz=req.frequency_mhz,
                service_mix=req.service_mix,
            )
            alloc_result = allocate_multi_service(users, req.total_bandwidth_mhz)

            for a, u in zip(alloc_result["allocations"], users):
                a.update({
                    "snr_db": u.get("snr_db", 0),
                    "distance_m": u.get("distance_m", 0),
                    "los": u.get("los", False),
                    "spectral_efficiency": u.get("spectral_efficiency", 0),
                })

            run["output_summary"] = (
                f"manual: users={req.num_users}, bw={req.total_bandwidth_mhz}MHz, "
                f"throughput={alloc_result['total_throughput_mbps']:.1f}Mbps, "
                f"fairness={alloc_result['fairness']:.2f}"
            )[:200]
            return {
                "users": users,
                "allocations": alloc_result["allocations"],
                "total_bandwidth_mhz": alloc_result["total_bandwidth_mhz"],
                "total_throughput_mbps": alloc_result["total_throughput_mbps"],
                "fairness": alloc_result["fairness"],
                "method": alloc_result["method"],
                "feasible": alloc_result["feasible"],
                "per_service": alloc_result["per_service"],
                "baseline": alloc_result["baseline"],
                "gain": alloc_result["gain"],
                "environment": req.environment,
                "frequency_mhz": req.frequency_mhz,
                "seed": rs,
                "agent_explanation": "",
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/allocate/stream")
async def handle_allocate_stream(req: AllocationRequest):
    """Agent-mode allocation with SSE streaming — intent → optimize → explanation.

    Emits stage events plus a token-streamed explanation, mirroring the
    frequency-plan stream. Requires use_agent + a user_request.
    """
    from ..agent.run_events import error as run_error
    from ..agent.run_events import standardize_event
    from ..skills.spectrum_decision.agent import run_agent_allocation_stream
    job_id = get_job_store().start_job(
        kind="spectrum_decision",
        title=f"Spectrum Decision · {req.user_request[:48] or 'stream'}",
        prompt_preview=req.user_request[:160],
    )

    async def generate():
        try:
            with track_skill_run("spectrum_decision_agent", input_data=req.model_dump()) as run:
                last = {}
                async for event in run_agent_allocation_stream(
                    user_request=req.user_request,
                    num_users=req.num_users,
                    total_bandwidth_mhz=req.total_bandwidth_mhz,
                    environment=req.environment or "urban",
                    frequency_mhz=req.frequency_mhz,
                    seed=req.seed,
                    service_mix=req.service_mix,
                ):
                    if event.get("type") == "done":
                        last = event.get("data", {})
                    event = standardize_event(event, source="spectrum_decision")
                    event = get_job_store().record_event(job_id, event)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                run["output_summary"] = (
                    f"agent-stream: users={last.get('num_users', '?')}, "
                    f"throughput={last.get('total_throughput_mbps', 0)}Mbps"
                )[:200]
        except Exception as exc:
            event = get_job_store().record_event(job_id, run_error(str(exc), source="spectrum_decision"))
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
