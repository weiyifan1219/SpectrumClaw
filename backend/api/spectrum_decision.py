"""Spectrum Decision API — resource allocation endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/spectrum-decision")


class AllocationRequest(BaseModel):
    num_users: int = Field(default=10, ge=1, le=50)
    total_bandwidth_mhz: float = Field(default=100.0, ge=10.0, le=1000.0)
    seed: int = Field(default=42, ge=0)
    service_mix: dict[str, float] | None = None
    manual_cqi: list[int] | None = None
    manual_services: list[str] | None = None


@router.post("/allocate")
async def handle_allocate(req: AllocationRequest):
    """Run resource allocation for a given user scenario."""
    from ..skills.spectrum_decision.dataset import generate_users
    from ..skills.spectrum_decision.resource_allocator import allocate_multi_service

    try:
        if req.manual_cqi and len(req.manual_cqi) > 0:
            cqis = req.manual_cqi
            services = req.manual_services or ["eMBB"] * len(cqis)
            users = [
                {"user_id": f"UE_{i + 1:03d}", "cqi": c, "service": s}
                for i, (c, s) in enumerate(zip(cqis, services))
            ]
        else:
            users = generate_users(
                num_users=req.num_users,
                seed=req.seed,
                service_mix=req.service_mix,
            )

        result = allocate_multi_service(users, req.total_bandwidth_mhz)

        # Add CQI and service to allocations
        for a, u in zip(result["allocations"], users):
            a["cqi"] = u["cqi"]
            a["service"] = u["service"]

        return {
            "users": users,
            "allocations": result["allocations"],
            "total_bandwidth_mhz": result["total_bandwidth_mhz"],
            "total_throughput_mbps": result["total_throughput_mbps"],
            "fairness": result["fairness"],
            "method": result["method"],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
