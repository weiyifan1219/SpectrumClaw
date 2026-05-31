"""Synthetic dataset generator for spectrum resource allocation scenarios."""

from __future__ import annotations

import math
import random


def generate_users(
    num_users: int = 10,
    seed: int = 42,
    cqi_range: tuple[int, int] = (3, 14),
    service_mix: dict[str, float] | None = None,
) -> list[dict]:
    """Generate synthetic user data with CQI and service type assignment.

    Args:
        num_users: Number of users to generate.
        seed: Random seed for reproducibility.
        cqi_range: (min_cqi, max_cqi) inclusive.
        service_mix: {"eMBB": 0.6, "URLLC": 0.3, "mMTC": 0.1} — fraction per service.

    Returns:
        List of {"user_id": str, "cqi": int, "service": str} dicts.
    """
    rng = random.Random(seed)
    if service_mix is None:
        service_mix = {"eMBB": 0.6, "URLLC": 0.3, "mMTC": 0.1}

    services = list(service_mix.keys())
    weights = [service_mix[s] for s in services]
    # Normalize weights
    total_w = sum(weights)
    weights = [w / total_w for w in weights]

    users = []
    for i in range(num_users):
        svc = rng.choices(services, weights=weights, k=1)[0]
        # CQI distribution: eMBB tends higher, URLLC reliable, mMTC lower
        if svc == "eMBB":
            cqi = rng.randint(max(7, cqi_range[0]), cqi_range[1])
        elif svc == "URLLC":
            cqi = rng.randint(max(4, cqi_range[0]), min(10, cqi_range[1]))
        else:  # mMTC
            cqi = rng.randint(cqi_range[0], min(8, cqi_range[1]))

        users.append({
            "user_id": f"UE_{i + 1:03d}",
            "cqi": cqi,
            "service": svc,
        })

    return users


def generate_scenario(
    num_users: int = 12,
    total_bandwidth_mhz: float = 100.0,
    seed: int = 42,
    service_mix: dict[str, float] | None = None,
) -> dict:
    """Generate a complete resource allocation scenario.

    Returns a dict with users, total bandwidth, and ground-truth optimal allocation.
    """
    from .resource_allocator import allocate_multi_service

    users = generate_users(num_users, seed=seed, service_mix=service_mix)
    result = allocate_multi_service(users, total_bandwidth_mhz)

    return {
        "scenario_id": f"sc_{seed}_{num_users}u",
        "num_users": num_users,
        "total_bandwidth_mhz": total_bandwidth_mhz,
        "users": users,
        "allocation": result,
    }
