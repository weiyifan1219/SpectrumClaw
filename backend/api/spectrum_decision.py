"""Spectrum Decision API — resource allocation with optional LLM agent assistance."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..memory.hooks import track_skill_run

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
                    num_users=req.num_users if req.num_users != 10 else None,
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
                "environment": req.environment,
                "frequency_mhz": req.frequency_mhz,
                "seed": rs,
                "agent_explanation": "",
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
