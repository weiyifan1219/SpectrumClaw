"""Spectrum resource allocation — proportional fairness optimization adapted from WirelessAgent R1.

Core algorithm: SLSQP-optimized proportional fairness (max sum(log(rate_i))),
with per-service-type bandwidth/rate constraints and CQI-based Shannon rate mapping.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class ServiceProfile:
    name: str
    bandwidth_min_mhz: float
    bandwidth_max_mhz: float
    rate_min_mbps: float
    rate_max_mbps: float
    alpha: float = 10.0  # rate scaling factor


# Default profiles — adapted for demo feasibility with typical bandwidth budgets
EMBB = ServiceProfile("eMBB", bandwidth_min_mhz=5.0, bandwidth_max_mhz=25.0,
                      rate_min_mbps=10.0, rate_max_mbps=500.0)
URLLC = ServiceProfile("URLLC", bandwidth_min_mhz=1.0, bandwidth_max_mhz=8.0,
                       rate_min_mbps=1.0, rate_max_mbps=100.0)
MMTC = ServiceProfile("mMTC", bandwidth_min_mhz=0.5, bandwidth_max_mhz=3.0,
                      rate_min_mbps=0.1, rate_max_mbps=10.0, alpha=5.0)

SERVICE_PROFILES = {"eMBB": EMBB, "URLLC": URLLC, "mMTC": MMTC}


def shannon_rate(bandwidth_mhz: float, cqi: int, alpha: float = 10.0) -> float:
    """Throughput in Mbps: rate = alpha * B * log10(1 + 10^(CQI/10))."""
    return alpha * bandwidth_mhz * math.log10(1 + 10 ** (cqi / 10))


def spectral_efficiency(cqi: int) -> float:
    """bits/s/Hz from CQI."""
    return math.log10(1 + 10 ** (cqi / 10))


def jains_fairness(rates: list[float]) -> float:
    """Jain's fairness index: (sum r)^2 / (n * sum r^2). Range [1/n, 1]."""
    n = len(rates)
    if n == 0:
        return 1.0
    s = sum(rates)
    if s == 0:
        return 0.0
    return (s * s) / (n * sum(r * r for r in rates))


@dataclass
class AllocationResult:
    bandwidths: list[float]  # MHz per user
    rates: list[float]       # Mbps per user
    total_bandwidth: float
    total_throughput: float
    fairness: float
    feasible: bool
    method: str  # "slsqp" | "fallback"


def allocate_resources(
    cqi_list: list[int],
    total_bandwidth_mhz: float,
    service: str = "eMBB",
    service_profile: ServiceProfile | None = None,
) -> AllocationResult:
    """Allocate bandwidth to users via proportional fairness optimization.

    Args:
        cqi_list: CQI values (1-15) for each user.
        total_bandwidth_mhz: Total available spectrum bandwidth.
        service: Service type key (eMBB/URLLC/mMTC).
        service_profile: Override default profile.

    Returns:
        AllocationResult with per-user bandwidth, rate, and metrics.
    """
    profile = service_profile or SERVICE_PROFILES.get(service, EMBB)
    M = len(cqi_list)
    if M == 0:
        return AllocationResult([], [], total_bandwidth_mhz, 0.0, 1.0, True, "slsqp")

    Q = np.array(cqi_list, dtype=float)
    B_min = profile.bandwidth_min_mhz
    B_max = profile.bandwidth_max_mhz
    R_min = profile.rate_min_mbps
    R_max = profile.rate_max_mbps
    alpha = profile.alpha

    # Feasibility check
    feasible = _check_feasibility(total_bandwidth_mhz, M, Q, B_min, B_max, R_min, alpha)
    if not feasible:
        # Try fallback
        alloc, rates = _fallback_allocation(total_bandwidth_mhz, M, Q, B_min, B_max, R_min, R_max, alpha)
        fair = jains_fairness(rates)
        return AllocationResult(alloc, rates, total_bandwidth_mhz, sum(rates), fair, False, "fallback")

    # SLSQP proportional fairness
    try:
        alloc, rates = _slsqp_optimize(total_bandwidth_mhz, M, Q, B_min, B_max, R_min, R_max, alpha)
        fair = jains_fairness(rates)
        return AllocationResult(alloc, rates, total_bandwidth_mhz, sum(rates), fair, True, "slsqp")
    except Exception:
        alloc, rates = _fallback_allocation(total_bandwidth_mhz, M, Q, B_min, B_max, R_min, R_max, alpha)
        fair = jains_fairness(rates)
        return AllocationResult(alloc, rates, total_bandwidth_mhz, sum(rates), fair, True, "fallback")


def allocate_multi_service(
    users: list[dict[str, Any]],
    total_bandwidth_mhz: float,
) -> dict[str, Any]:
    """Allocate bandwidth across mixed service types.

    Users: [{"cqi": int, "service": "eMBB"|"URLLC"|"mMTC"}, ...]
    Returns full allocation details per user.
    """
    # Group by service, allocate proportional bandwidth per group
    groups: dict[str, list[int]] = {}
    groups_indices: dict[str, list[int]] = {}
    for i, u in enumerate(users):
        svc = u.get("service", "eMBB")
        groups.setdefault(svc, []).append(int(u.get("cqi", 7)))
        groups_indices.setdefault(svc, []).append(i)

    # Proportional bandwidth split by user count
    total_users = len(users)
    results: list[dict[str, Any]] = [{} for _ in range(total_users)]
    all_rates: list[float] = []

    for svc, cqis in groups.items():
        indices = groups_indices[svc]
        n = len(cqis)
        bw_share = total_bandwidth_mhz * (n / total_users)
        alloc = allocate_resources(cqis, bw_share, service=svc)
        for j, idx in enumerate(indices):
            results[idx] = {
                "user_index": idx,
                "service": svc,
                "cqi": cqis[j],
                "bandwidth_mhz": round(alloc.bandwidths[j], 3) if j < len(alloc.bandwidths) else 0,
                "rate_mbps": round(alloc.rates[j], 1) if j < len(alloc.rates) else 0,
            }
            if j < len(alloc.rates):
                all_rates.append(alloc.rates[j])

    return {
        "allocations": results,
        "total_bandwidth_mhz": total_bandwidth_mhz,
        "total_throughput_mbps": round(sum(all_rates), 1),
        "fairness": round(jains_fairness(all_rates), 4),
        "method": "multi_service_slsqp",
    }


# ── internal helpers ──

def _check_feasibility(B, M, Q, B_min, B_max, R_min, alpha):
    for i in range(M):
        if shannon_rate(B_max, int(Q[i]), alpha) < R_min:
            return False
    if B < B_min * M:
        return False
    total_min = sum(
        max(R_min / (alpha * spectral_efficiency(int(Q[i]))), B_min)
        for i in range(M)
    )
    return total_min <= B


def _fallback_allocation(B, M, Q, B_min, B_max, R_min, R_max, alpha):
    """Greedy CQI-prioritized allocation when SLSQP fails."""
    alloc = np.ones(M) * B_min
    remaining = B - np.sum(alloc)

    # priority by CQI
    order = sorted(range(M), key=lambda i: Q[i], reverse=True)
    for i in order:
        if remaining <= 0:
            break
        se = spectral_efficiency(int(Q[i]))
        extra_for_rmin = max(0, R_min / (alpha * se) - B_min)
        target = min(B_max, B_min + extra_for_rmin + remaining * 0.5)
        additional = min(target - B_min, remaining)
        alloc[i] += additional
        remaining -= additional

    rates = [shannon_rate(alloc[i], int(Q[i]), alpha) for i in range(M)]
    return alloc.tolist(), rates


def _slsqp_optimize(B, M, Q, B_min, B_max, R_min, R_max, alpha):
    """SLSQP proportional fairness: minimize -sum(log(rate_i))."""
    from scipy.optimize import minimize, Bounds, NonlinearConstraint

    # Initial guess: equal share, clamped
    x0 = np.clip(np.ones(M) * (B / M), B_min, B_max)

    def objective(x):
        rates = np.array([shannon_rate(x[i], int(Q[i]), alpha) for i in range(M)])
        rates = np.maximum(rates, 1e-6)
        return -np.sum(np.log(rates))

    bounds = Bounds([B_min] * M, [B_max] * M)

    def total_bandwidth_constraint(x):
        return B - np.sum(x)

    def min_rate_constraint(x):
        rates = np.array([shannon_rate(x[i], int(Q[i]), alpha) for i in range(M)])
        return rates - R_min

    constraints = [
        {"type": "eq", "fun": total_bandwidth_constraint},
        {"type": "ineq", "fun": min_rate_constraint},
    ]

    result = minimize(
        objective, x0, method="SLSQP",
        bounds=bounds, constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-8},
    )

    if not result.success:
        raise RuntimeError(f"SLSQP failed: {result.message}")

    x_opt = np.clip(result.x, B_min, B_max)
    rates = [shannon_rate(x_opt[i], int(Q[i]), alpha) for i in range(M)]
    return x_opt.tolist(), rates
