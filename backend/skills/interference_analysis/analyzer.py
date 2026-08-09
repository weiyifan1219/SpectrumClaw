"""Deterministic first-pass interference and channel-availability analysis.

The calculations in this module are deliberately transparent and bounded. They
are suitable for planning triage, not a replacement for a site survey,
coordination study, certified receiver masks, or a full-wave propagation tool.
"""

from __future__ import annotations

import math
from typing import Any

from ...rag.keyword.frequency_matcher import FrequencyRange


_ENVIRONMENT_CLUTTER_DB = {
    "open": 0.0,
    "sea": 0.0,
    "rural": 2.0,
    "suburban": 6.0,
    "urban": 12.0,
    "dense_urban": 18.0,
    "indoor": 15.0,
}

_DEFAULT_REQUIRED_SINR_DB = {
    "iot": 3.0,
    "sensor": 3.0,
    "handheld": 7.0,
    "telemetry": 7.0,
    "base_station": 10.0,
    "wifi_ap": 10.0,
    "broadcast": 12.0,
    "radar": 13.0,
    "satellite_earth_station": 10.0,
}


def analyze_interference(request: dict[str, Any]) -> dict[str, Any]:
    """Analyze availability at the requested coverage edge.

    All powers use dBm, frequencies/bandwidths use MHz, and distances use metres.
    The result includes the numerical basis and assumptions so downstream LLMs
    can explain the calculation without inventing engineering facts.
    """
    frequency_band = str(request.get("frequency_band") or "").strip()
    parsed_band = FrequencyRange.parse(frequency_band)
    if parsed_band is None:
        return _insufficient_result(frequency_band, "无法解析目标频段，请使用如 2300-2400 MHz 的格式。")

    bandwidth_mhz = _positive(request.get("bandwidth_mhz"), 20.0)
    coverage_radius_m = _positive(request.get("coverage_radius_m"), 1000.0)
    tx_power_dbm = _number(request.get("tx_power_dbm"), 30.0)
    antenna_gain_dbi = _number(request.get("antenna_gain_dbi"), 0.0)
    receiver_gain_dbi = _number(request.get("receiver_gain_dbi"), 0.0)
    feeder_loss_db = max(0.0, _number(request.get("feeder_loss_db"), 0.0))
    noise_figure_db = max(0.0, _number(request.get("noise_figure_db"), 7.0))
    environment = str(request.get("environment") or "urban").strip().lower()
    center_mhz = parsed_band.center_mhz
    required_sinr_db = _number(
        request.get("minimum_sinr_db"),
        _DEFAULT_REQUIRED_SINR_DB.get(str(request.get("emitter_type") or "").lower(), 10.0),
    )

    desired_path_loss_db = _path_loss_db(center_mhz, coverage_radius_m, environment)
    desired_rx_dbm = tx_power_dbm + antenna_gain_dbi + receiver_gain_dbi - feeder_loss_db - desired_path_loss_db
    noise_floor_dbm = -174.0 + 10.0 * math.log10(max(bandwidth_mhz, 0.001) * 1_000_000.0) + noise_figure_db
    snr_db = desired_rx_dbm - noise_floor_dbm

    target_low, target_high = _occupied_range(center_mhz, bandwidth_mhz)
    findings: list[dict[str, Any]] = []
    interference_powers_dbm: list[float] = []
    interferers = [item for item in (request.get("interferers") or []) if isinstance(item, dict)]
    for index, item in enumerate(interferers):
        finding = _analyze_interferer(
            item,
            target_low=target_low,
            target_high=target_high,
            target_bandwidth_mhz=bandwidth_mhz,
            environment=environment,
            index=index,
        )
        findings.append(finding)
        if finding["coupled_power_dbm"] is not None:
            interference_powers_dbm.append(float(finding["coupled_power_dbm"]))

    findings.extend(_detect_third_order_products(interferers, target_low, target_high))
    aggregate_interference_dbm = _sum_dbm(interference_powers_dbm)
    sinr_db = _sinr_db(desired_rx_dbm, noise_floor_dbm, aggregate_interference_dbm)
    margin_db = sinr_db - required_sinr_db

    recommended_channels = _rank_channels(
        parsed_band=parsed_band,
        requested_bandwidth_mhz=bandwidth_mhz,
        desired_rx_dbm=desired_rx_dbm,
        noise_floor_dbm=noise_floor_dbm,
        required_sinr_db=required_sinr_db,
        interferers=interferers,
        environment=environment,
        guard_band_mhz=request.get("guard_band_mhz"),
    )
    avoid_ranges = _avoid_ranges(interferers, parsed_band)

    if margin_db >= 6.0:
        availability, risk_level = "available", "low"
    elif margin_db >= 0.0:
        availability, risk_level = "conditional", "medium"
    else:
        availability, risk_level = "unavailable", "high"

    recommendations = _recommendations(
        availability=availability,
        findings=findings,
        recommended_channels=recommended_channels,
        margin_db=margin_db,
    )
    return {
        "frequency_band": frequency_band,
        "availability": availability,
        "risk_level": risk_level,
        "interference_findings": findings,
        "link_budget": {
            "center_frequency_mhz": _round(center_mhz),
            "coverage_edge_m": _round(coverage_radius_m),
            "path_loss_db": _round(desired_path_loss_db),
            "desired_rx_dbm": _round(desired_rx_dbm),
            "noise_floor_dbm": _round(noise_floor_dbm),
            "aggregate_interference_dbm": _round(aggregate_interference_dbm) if aggregate_interference_dbm is not None else None,
            "snr_db": _round(snr_db),
            "sinr_db": _round(sinr_db),
            "required_sinr_db": _round(required_sinr_db),
            "sinr_margin_db": _round(margin_db),
        },
        "recommended_channels": recommended_channels[:5],
        "avoid_ranges": avoid_ranges,
        "recommendations": recommendations,
        "basis": {
            "propagation_model": "log-distance + FSPL reference",
            "noise_model": "thermal noise density -174 dBm/Hz + receiver noise figure",
            "interference_aggregation": "linear power sum after simplified frequency-dependent coupling loss",
            "decision_rule": "SINR margin >= 6 dB available; 0-6 dB conditional; < 0 dB unavailable",
            "environment_clutter_db": _ENVIRONMENT_CLUTTER_DB.get(environment, _ENVIRONMENT_CLUTTER_DB["urban"]),
        },
        "assumptions": [
            "在覆盖半径边缘评估期望链路，未提供接收机增益时按 0 dBi 处理。",
            "传播损耗采用自由空间参考损耗叠加场景杂波余量，未使用地形、建筑物和气象射线追踪。",
            "邻频耦合使用通用工程筛查值；实际规划应替换为设备 ACLR、ACS、ACIR 和发射掩模。",
            "干扰源按给定活动因子同时工作；未提供时按 100% 占空比处理。",
        ],
        "limitations": [
            "结果用于方案初筛，不等同于主管部门频率指配、台站协调结论或现场测试。",
            "未建模极化、天线方向图、绕射、多径快衰落、互调器件非线性和接收机阻塞曲线。",
        ],
    }


def _analyze_interferer(
    item: dict[str, Any],
    *,
    target_low: float,
    target_high: float,
    target_bandwidth_mhz: float,
    environment: str,
    index: int,
) -> dict[str, Any]:
    frequency_mhz = _positive(item.get("frequency_mhz"), (target_low + target_high) / 2.0)
    bandwidth_mhz = _positive(item.get("bandwidth_mhz"), target_bandwidth_mhz)
    int_low, int_high = _occupied_range(frequency_mhz, bandwidth_mhz)
    kind, separation_mhz, coupling_loss_db = _coupling(target_low, target_high, int_low, int_high, target_bandwidth_mhz)
    power_dbm = _number(item.get("power_dbm"), 20.0)
    gain_dbi = _number(item.get("antenna_gain_dbi"), 0.0)
    distance_m = _positive(item.get("distance_m"), 100.0)
    activity_factor = min(1.0, max(0.001, _number(item.get("activity_factor"), 1.0)))
    path_loss_db = _path_loss_db(frequency_mhz, distance_m, environment)
    raw_rx_dbm = power_dbm + gain_dbi - path_loss_db + 10.0 * math.log10(activity_factor)
    coupled_power_dbm = raw_rx_dbm - coupling_loss_db
    severity = "high" if coupled_power_dbm >= -75.0 else "medium" if coupled_power_dbm >= -95.0 else "low"
    return {
        "name": str(item.get("name") or f"干扰源 {index + 1}"),
        "emitter_type": str(item.get("emitter_type") or "unknown"),
        "type": kind,
        "severity": severity,
        "frequency_mhz": _round(frequency_mhz),
        "bandwidth_mhz": _round(bandwidth_mhz),
        "separation_mhz": _round(separation_mhz),
        "path_loss_db": _round(path_loss_db),
        "raw_received_power_dbm": _round(raw_rx_dbm),
        "coupling_loss_db": _round(coupling_loss_db),
        "coupled_power_dbm": _round(coupled_power_dbm),
        "basis": _finding_basis(kind),
    }


def _coupling(
    target_low: float,
    target_high: float,
    interferer_low: float,
    interferer_high: float,
    target_bandwidth_mhz: float,
) -> tuple[str, float, float]:
    overlap = max(0.0, min(target_high, interferer_high) - max(target_low, interferer_low))
    if overlap > 0.0:
        ratio = overlap / max(0.001, target_high - target_low)
        return ("co_channel" if ratio >= 0.5 else "partial_overlap", 0.0, 0.0 if ratio >= 0.5 else 10.0)
    separation = min(abs(target_low - interferer_high), abs(interferer_low - target_high))
    if separation <= max(0.1, target_bandwidth_mhz * 0.1):
        return "adjacent_channel", separation, 20.0
    if separation < target_bandwidth_mhz:
        return "adjacent_channel", separation, 30.0
    extra = min(20.0, 20.0 * math.log10(max(1.0, separation / target_bandwidth_mhz)))
    return "out_of_band", separation, 45.0 + extra


def _rank_channels(
    *,
    parsed_band: FrequencyRange,
    requested_bandwidth_mhz: float,
    desired_rx_dbm: float,
    noise_floor_dbm: float,
    required_sinr_db: float,
    interferers: list[dict[str, Any]],
    environment: str,
    guard_band_mhz: Any,
) -> list[dict[str, Any]]:
    band_low, band_high = parsed_band.min_mhz, parsed_band.max_mhz
    if band_high <= band_low:
        band_low = parsed_band.center_mhz - requested_bandwidth_mhz / 2.0
        band_high = parsed_band.center_mhz + requested_bandwidth_mhz / 2.0
    span = band_high - band_low
    if span + 1e-9 < requested_bandwidth_mhz:
        return []
    guard = _positive(guard_band_mhz, max(0.1, requested_bandwidth_mhz * 0.1))
    guard = min(guard, max(0.0, (span - requested_bandwidth_mhz) / 2.0))
    first_center = band_low + guard + requested_bandwidth_mhz / 2.0
    last_center = band_high - guard - requested_bandwidth_mhz / 2.0
    centers: list[float] = []
    center = first_center
    while center <= last_center + 1e-9 and len(centers) < 64:
        centers.append(center)
        center += requested_bandwidth_mhz
    if centers and last_center - centers[-1] >= requested_bandwidth_mhz * 0.25:
        centers.append(last_center)
    if not centers:
        centers = [parsed_band.center_mhz]

    candidates: list[dict[str, Any]] = []
    for channel_center in centers:
        low, high = _occupied_range(channel_center, requested_bandwidth_mhz)
        powers: list[float] = []
        nearest = None
        for item in interferers:
            int_freq = _positive(item.get("frequency_mhz"), parsed_band.center_mhz)
            int_bw = _positive(item.get("bandwidth_mhz"), requested_bandwidth_mhz)
            int_low, int_high = _occupied_range(int_freq, int_bw)
            _, separation, coupling_loss = _coupling(low, high, int_low, int_high, requested_bandwidth_mhz)
            nearest = separation if nearest is None else min(nearest, separation)
            activity = min(1.0, max(0.001, _number(item.get("activity_factor"), 1.0)))
            rx_dbm = (
                _number(item.get("power_dbm"), 20.0)
                + _number(item.get("antenna_gain_dbi"), 0.0)
                - _path_loss_db(int_freq, _positive(item.get("distance_m"), 100.0), environment)
                + 10.0 * math.log10(activity)
                - coupling_loss
            )
            powers.append(rx_dbm)
        aggregate = _sum_dbm(powers)
        sinr = _sinr_db(desired_rx_dbm, noise_floor_dbm, aggregate)
        margin = sinr - required_sinr_db
        score = max(0.0, min(100.0, 50.0 + margin * 3.0 + min(20.0, (nearest or span) / max(requested_bandwidth_mhz, 0.1) * 5.0)))
        candidates.append({
            "center_mhz": _round(channel_center),
            "range_mhz": f"{_format_freq(low)}-{_format_freq(high)} MHz",
            "estimated_sinr_db": _round(sinr),
            "sinr_margin_db": _round(margin),
            "score": _round(score),
            "status": "preferred" if margin >= 6.0 else "conditional" if margin >= 0 else "avoid",
        })
    candidates.sort(key=lambda item: (item["score"], item["sinr_margin_db"]), reverse=True)
    return candidates


def _detect_third_order_products(
    interferers: list[dict[str, Any]], target_low: float, target_high: float
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for i, first in enumerate(interferers):
        f1 = _number(first.get("frequency_mhz"), 0.0)
        if f1 <= 0:
            continue
        for second in interferers[i + 1:]:
            f2 = _number(second.get("frequency_mhz"), 0.0)
            if f2 <= 0:
                continue
            for product in (2 * f1 - f2, 2 * f2 - f1):
                if target_low <= product <= target_high:
                    findings.append({
                        "name": f"{first.get('name', '干扰源1')} / {second.get('name', '干扰源2')}",
                        "emitter_type": "multiple",
                        "type": "third_order_intermodulation_candidate",
                        "severity": "medium",
                        "frequency_mhz": _round(product),
                        "bandwidth_mhz": None,
                        "separation_mhz": 0.0,
                        "path_loss_db": None,
                        "raw_received_power_dbm": None,
                        "coupling_loss_db": None,
                        "coupled_power_dbm": None,
                        "basis": "三阶组合频率 2f1-f2 或 2f2-f1 落入目标信道；幅度需结合器件非线性实测。",
                    })
    return findings


def _avoid_ranges(interferers: list[dict[str, Any]], band: FrequencyRange) -> list[dict[str, Any]]:
    ranges = []
    for item in interferers:
        freq = _number(item.get("frequency_mhz"), 0.0)
        if freq <= 0:
            continue
        bw = _positive(item.get("bandwidth_mhz"), 1.0)
        low, high = _occupied_range(freq, bw)
        clipped_low, clipped_high = max(low, band.min_mhz), min(high, band.max_mhz)
        if clipped_low <= clipped_high:
            ranges.append({
                "range_mhz": f"{_format_freq(clipped_low)}-{_format_freq(clipped_high)} MHz",
                "reason": f"与 {item.get('name') or '已知干扰源'} 占用范围重叠",
            })
    return ranges


def _recommendations(
    *, availability: str, findings: list[dict[str, Any]], recommended_channels: list[dict[str, Any]], margin_db: float
) -> list[str]:
    recommendations: list[str] = []
    if recommended_channels:
        best = recommended_channels[0]
        recommendations.append(
            f"优先复核 {best['range_mhz']}，工程筛查得分 {best['score']:.1f}/100，估算 SINR 裕量 {best['sinr_margin_db']:.1f} dB。"
        )
    if any(item.get("type") in {"co_channel", "partial_overlap"} for item in findings):
        recommendations.append("存在同频或频谱重叠干扰，优先采用错频、时分、空间隔离或降低等效全向辐射功率。")
    if any(item.get("type") == "adjacent_channel" for item in findings):
        recommendations.append("补充设备 ACLR/ACS/ACIR、发射掩模和接收机阻塞指标，再确定保护带宽。")
    if availability != "available":
        recommendations.append("在最终指配前开展现场频谱扫描与最坏工况兼容性测试。")
    if margin_db < 3.0:
        recommendations.append("当前 SINR 余量较小，应增加链路余量或缩小覆盖边界。")
    return recommendations


def _finding_basis(kind: str) -> str:
    return {
        "co_channel": "干扰信号与目标信道重叠超过 50%，按同频耦合进行工程筛查。",
        "partial_overlap": "干扰信号与目标信道部分重叠，按 10 dB 简化耦合损耗筛查。",
        "adjacent_channel": "干扰位于相邻频段，按频率间隔采用 20-30 dB 简化耦合损耗。",
        "out_of_band": "干扰位于带外，按至少 45 dB 简化耦合损耗；需用设备实测掩模复核。",
    }.get(kind, "通用干扰筛查。")


def _path_loss_db(frequency_mhz: float, distance_m: float, environment: str) -> float:
    distance_km = max(distance_m, 1.0) / 1000.0
    fspl_db = 32.44 + 20.0 * math.log10(max(frequency_mhz, 0.001)) + 20.0 * math.log10(distance_km)
    return fspl_db + _ENVIRONMENT_CLUTTER_DB.get(environment, _ENVIRONMENT_CLUTTER_DB["urban"])


def _sinr_db(desired_dbm: float, noise_dbm: float, interference_dbm: float | None) -> float:
    denominator_mw = 10 ** (noise_dbm / 10.0)
    if interference_dbm is not None:
        denominator_mw += 10 ** (interference_dbm / 10.0)
    return desired_dbm - 10.0 * math.log10(max(denominator_mw, 1e-30))


def _sum_dbm(values: list[float]) -> float | None:
    if not values:
        return None
    return 10.0 * math.log10(sum(10 ** (value / 10.0) for value in values))


def _occupied_range(center_mhz: float, bandwidth_mhz: float) -> tuple[float, float]:
    half = bandwidth_mhz / 2.0
    return center_mhz - half, center_mhz + half


def _positive(value: Any, default: float) -> float:
    number = _number(value, default)
    return number if number > 0 else default


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _format_freq(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _insufficient_result(frequency_band: str, reason: str) -> dict[str, Any]:
    return {
        "frequency_band": frequency_band,
        "availability": "insufficient",
        "risk_level": "unknown",
        "interference_findings": [],
        "link_budget": {},
        "recommended_channels": [],
        "avoid_ranges": [],
        "recommendations": [reason],
        "basis": {"propagation_model": "not-run"},
        "assumptions": [],
        "limitations": ["缺少可计算的目标频段，未执行链路预算与干扰聚合。"],
    }
