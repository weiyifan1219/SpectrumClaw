"""Synthetic spectrum scenario generator — realistic channel models.

Uses free-space path loss (FSPL) + COST231-Hata for NLOS,
3GPP 38.214 CQI table for SNR→CQI mapping, configurable environments.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Literal

Environment = Literal["urban", "suburban", "rural"]


# ── 3GPP TS 38.214 Table 5.2.2.1-2: 4-bit CQI → spectral efficiency ──
CQI_TABLE = [
    (1, 2), (3, 4), (5, 6), (7, 7),
    (8, 9), (10, 11), (12, 13), (14, 15),
]
# SNR thresholds (dB) for each CQI value in AWGN (simplified from 3GPP 36.213)
CQI_SNR_THRESHOLDS = [
    -7.0, -5.0, -3.0, -1.0, 1.0, 3.0, 5.0, 7.0,
    9.0, 11.0, 13.0, 15.0, 18.0, 21.0, 24.0,
]


def snr_to_cqi(snr_db: float) -> int:
    """Map SNR (dB) to CQI 1-15 using 3GPP thresholds."""
    for i, thresh in enumerate(CQI_SNR_THRESHOLDS):
        if snr_db < thresh:
            return max(1, i)
    return 15


def cqi_to_spectral_efficiency(cqi: int) -> float:
    """Approximate spectral efficiency (bps/Hz) from 4-bit CQI."""
    if cqi <= 0: return 0.15
    if cqi <= 6: return 0.15 + (cqi - 1) * 0.19
    if cqi <= 9: return 1.17 + (cqi - 7) * 0.32
    if cqi <= 12: return 2.41 + (cqi - 10) * 0.45
    if cqi <= 14: return 3.90 + (cqi - 13) * 0.55
    return 5.55


# ── path loss models ──

@dataclass
class EnvironmentProfile:
    name: str
    los_ratio: float          # fraction of users with LOS
    building_loss_db: float    # additional NLOS loss
    clutter_height_m: float    # avg building height
    noise_figure_db: float     # receiver noise figure
    shadowing_std_db: float    # log-normal shadowing std


URBAN = EnvironmentProfile("urban", los_ratio=0.3, building_loss_db=20.0,
                           clutter_height_m=25.0, noise_figure_db=7.0, shadowing_std_db=8.0)
SUBURBAN = EnvironmentProfile("suburban", los_ratio=0.6, building_loss_db=10.0,
                              clutter_height_m=10.0, noise_figure_db=5.0, shadowing_std_db=6.0)
RURAL = EnvironmentProfile("rural", los_ratio=0.85, building_loss_db=5.0,
                           clutter_height_m=5.0, noise_figure_db=3.0, shadowing_std_db=4.0)

ENVIRONMENTS = {"urban": URBAN, "suburban": SUBURBAN, "rural": RURAL}


def free_space_path_loss(distance_m: float, frequency_mhz: float) -> float:
    """FSPL in dB: 20*log10(d) + 20*log10(f) + 32.45."""
    return 20 * math.log10(max(distance_m, 1.0)) + 20 * math.log10(frequency_mhz) - 147.55


def cost231_hata_path_loss(
    distance_km: float, frequency_mhz: float,
    tx_height_m: float, rx_height_m: float,
    environment: str = "urban",
) -> float:
    """COST231-Hata model for 1.5-2 GHz, returns dB.

    For suburban/rural, applies correction factors.
    """
    d = max(distance_km, 0.02)
    f = frequency_mhz
    # Base urban loss
    a_hr = (1.1 * math.log10(f) - 0.7) * rx_height_m - (1.56 * math.log10(f) - 0.8)
    L = (46.3 + 33.9 * math.log10(f) - 13.82 * math.log10(tx_height_m)
         - a_hr + (44.9 - 6.55 * math.log10(tx_height_m)) * math.log10(d))

    if environment == "suburban":
        L -= 2 * (math.log10(f / 28.0)) ** 2 - 5.4
    elif environment == "rural":
        L -= 4.78 * (math.log10(f)) ** 2 + 18.33 * math.log10(f) - 40.94

    return L


def calculate_snr(
    distance_m: float, frequency_mhz: float,
    tx_power_dbm: float, tx_height_m: float, rx_height_m: float,
    env: EnvironmentProfile, rng: random.Random,
) -> float:
    """Calculate received SNR in dB for a single link."""
    distance_km = distance_m / 1000.0
    is_los = rng.random() < env.los_ratio

    if is_los:
        pl = free_space_path_loss(distance_m, frequency_mhz)
    else:
        pl = cost231_hata_path_loss(distance_km, frequency_mhz, tx_height_m, rx_height_m, env.name)
        pl += env.building_loss_db

    # Add shadowing
    pl += rng.gauss(0, env.shadowing_std_db)

    # Thermal noise
    bw_hz = 10e6  # 10 MHz per PRB
    noise_figure_linear = 10 ** (env.noise_figure_db / 10)
    noise_power_dbm = -174 + 10 * math.log10(bw_hz) + env.noise_figure_db

    rx_power_dbm = tx_power_dbm - pl
    snr_db = rx_power_dbm - noise_power_dbm

    return max(-10, min(35, snr_db))


# ── user scenario generator ──

def generate_users(
    num_users: int = 10,
    seed: int = 42,
    frequency_mhz: float = 3500.0,
    tx_power_dbm: float = 43.0,
    tx_height_m: float = 30.0,
    rx_height_m: float = 1.5,
    environment: Environment = "urban",
    service_mix: dict[str, float] | None = None,
    max_distance_m: float = 1000.0,
) -> list[dict]:
    """Generate users with realistic CQI values from channel models.

    Each user gets a random distance (50m..max_distance_m), LOS/NLOS is determined
    by the environment profile, and SNR is calculated via FSPL or COST231-Hata.
    CQI is then mapped from SNR using 3GPP thresholds.

    Returns list of {"user_id", "cqi", "service", "snr_db", "distance_m", "los", "spectral_efficiency"}.
    """
    rng = random.Random(seed)
    if service_mix is None:
        service_mix = {"eMBB": 0.6, "URLLC": 0.3, "mMTC": 0.1}

    services = list(service_mix.keys())
    weights = list(service_mix.values())
    total_w = sum(weights)
    weights = [w / total_w for w in weights]

    env = ENVIRONMENTS.get(environment, URBAN)

    users = []
    for i in range(num_users):
        svc = rng.choices(services, weights=weights, k=1)[0]
        # Distance: uniform between 50m and max_distance_m
        d = rng.uniform(50.0, max_distance_m)
        snr = calculate_snr(d, frequency_mhz, tx_power_dbm, tx_height_m, rx_height_m, env, rng)
        cqi = snr_to_cqi(snr)
        is_los = rng.random() < env.los_ratio
        se = cqi_to_spectral_efficiency(cqi)

        users.append({
            "user_id": f"UE_{i + 1:03d}",
            "cqi": cqi,
            "service": svc,
            "snr_db": round(snr, 1),
            "distance_m": round(d, 0),
            "los": is_los,
            "spectral_efficiency": round(se, 3),
        })

    return users


def generate_scenario(
    num_users: int = 12,
    total_bandwidth_mhz: float = 100.0,
    seed: int = 42,
    environment: Environment = "urban",
    frequency_mhz: float = 3500.0,
    service_mix: dict[str, float] | None = None,
    max_distance_m: float = 1000.0,
) -> dict:
    """Generate a complete allocation scenario with realistic channel data."""
    from .resource_allocator import allocate_multi_service

    users = generate_users(
        num_users=num_users, seed=seed,
        frequency_mhz=frequency_mhz, environment=environment,
        service_mix=service_mix, max_distance_m=max_distance_m,
    )
    result = allocate_multi_service(users, total_bandwidth_mhz)

    return {
        "scenario_id": f"sc_{environment}_{seed}_{num_users}u",
        "num_users": num_users,
        "total_bandwidth_mhz": total_bandwidth_mhz,
        "frequency_mhz": frequency_mhz,
        "environment": environment,
        "users": users,
        "allocation": result,
    }
