"""Calibrated-equivalent IQ capture from a Sionna narrowband CIR.

The transmitter samples are declared stochastic test waveforms. The CIR is
ray-traced; the receiver, waveform and noise are explicit simulation models.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


BOLTZMANN = 1.380649e-23
REFERENCE_TEMPERATURE_K = 290.0
REFERENCE_FREQUENCY_HZ = 2.412e9


def _ofdm_qpsk_frame(rng: np.random.Generator, sample_count: int, sample_rate_hz: int, bandwidth_hz: int) -> np.ndarray:
    """Generic 64-tone QPSK OFDM with 1/4 cyclic prefix and guard carriers."""
    fft_size = 64
    cyclic_prefix = 16
    active_count = min(50, 2 * int((bandwidth_hz / sample_rate_hz * fft_size) // 2))
    if active_count < 2:
        raise ValueError("当前采样率与信道带宽无法容纳 OFDM 子载波")
    half = active_count // 2
    carriers = np.r_[np.arange(-half, 0), np.arange(1, half + 1)]
    symbols = []
    for _ in range(math.ceil(sample_count / (fft_size + cyclic_prefix)) + 1):
        bins = np.zeros(fft_size, dtype=np.complex128)
        bits = rng.integers(0, 2, size=(active_count, 2))
        bins[carriers % fft_size] = ((2 * bits[:, 0] - 1) + 1j * (2 * bits[:, 1] - 1)) / math.sqrt(2)
        symbol = np.fft.ifft(bins)
        symbols.append(np.r_[symbol[-cyclic_prefix:], symbol])
    frame = np.concatenate(symbols)[:sample_count]
    return frame / math.sqrt(float(np.mean(np.abs(frame) ** 2)))


def _dbm(power_mw: float) -> float:
    return round(10.0 * math.log10(max(power_mw, 1e-30)), 3)


def _ground_station_process(iq: np.ndarray, sample_rate_hz: int, center_frequency_hz: float) -> tuple[float, dict[str, list[float]]]:
    """Consume the transferred complex64 frame without access to a transmitter."""
    sample_count = len(iq)
    measured_total_power = float(np.mean(np.abs(iq) ** 2))
    window = np.hanning(sample_count + 1)[:-1]
    windowed = np.fft.fftshift(np.fft.fft(iq * window))
    bin_power = np.abs(windowed) ** 2 / (sample_count * np.sum(window ** 2))
    bin_frequencies = np.fft.fftshift(np.fft.fftfreq(sample_count, d=1 / sample_rate_hz)) + center_frequency_hz
    return _dbm(measured_total_power), {
        "frequency_hz": [float(value) for value in bin_frequencies],
        "bin_power_dbm": [_dbm(float(value)) for value in bin_power],
    }


def synthesize_receiver_capture(
    observation: dict[str, Any], *, target_id: str = "tx-01",
    sample_rate_hz: int = 16_000_000, sample_count: int = 1024,
    channel_bandwidth_hz: int = 10_000_000, noise_figure_db: float = 6.0,
    seed: int = 7, include_iq: bool = True,
    recorded_emitters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one complex baseband capture and powers at the antenna connector.

    IQ units are sqrt(mW) in a calibrated-equivalent 1-ohm normalization.
    Absolute dBm therefore comes from Sionna transmit powers and the assumed
    receiver calibration, not from arbitrary ADC full-scale counts.
    """
    if sample_count not in (256, 512, 1024, 2048, 4096):
        raise ValueError("IQ 点数仅支持 256/512/1024/2048/4096")
    if sample_rate_hz not in (16_000_000, 32_000_000, 62_500_000):
        raise ValueError("采样率仅支持 16/32/62.5 MS/s")
    if not (0 < channel_bandwidth_hz <= sample_rate_hz * 0.8):
        raise ValueError("信道带宽必须在采样率的 80% 以内")
    if not (0 <= noise_figure_db <= 30) or not (0 <= seed <= 2**32 - 1):
        raise ValueError("噪声系数或随机种子超出范围")
    center_frequency_hz = float(observation.get("frequency_hz", 0))
    if not 2.4e9 <= center_frequency_hz <= 2.5e9:
        raise ValueError("当前 CIR 不属于 2.4 GHz 频段，请重新采样")
    if recorded_emitters is not None and not math.isclose(center_frequency_hz, REFERENCE_FREQUENCY_HZ, abs_tol=1):
        raise ValueError("录制信号回放需要 2.412 GHz CIR，请重新采样")

    anchors = observation.get("anchors") or []
    if target_id not in {anchor.get("id") for anchor in anchors}:
        raise ValueError("目标发射源不存在")
    if any("cir_taps" not in anchor or "tx_power_dbm" not in anchor for anchor in anchors):
        raise ValueError("该观测尚无复数 CIR，请重新采集 Sionna RT 样本")
    emitter_by_id = {item["id"]: item for item in recorded_emitters or []}
    if recorded_emitters is not None and set(emitter_by_id) != {anchor["id"] for anchor in anchors}:
        raise ValueError("录制信号与 Sionna 发射源不匹配")

    rng = np.random.default_rng(seed)
    frequencies = np.fft.fftfreq(sample_count, d=1 / sample_rate_hz)
    occupied = np.abs(frequencies) <= channel_bandwidth_hz / 2
    components: dict[str, np.ndarray] = {}
    for anchor in anchors:
        emitter = emitter_by_id.get(anchor["id"])
        frequency_offset_hz = float(emitter["recorded_center_frequency_hz"] - center_frequency_hz) if emitter else 0.0
        if emitter and (sample_rate_hz != int(emitter["sample_rate_hz"]) or abs(frequency_offset_hz) >= sample_rate_hz / 2):
            raise ValueError("录制信号频率或采样率超出接收机窗口")
        taps = anchor["cir_taps"]
        response = np.zeros(sample_count, dtype=np.complex128)
        for tap in taps:
            delay = float(tap["delay_s"])
            coefficient = complex(float(tap["real"]), float(tap["imag"]))
            if not math.isfinite(delay) or delay < 0 or not np.isfinite(coefficient):
                raise ValueError("CIR 含无效的时延或复数系数")
            response += coefficient * np.exp(-2j * np.pi * (frequencies + frequency_offset_hz) * delay)
        if emitter:
            source_samples = np.asarray(emitter["samples"], dtype=np.complex64)
            indices = (np.arange(sample_count) + (seed % len(source_samples))) % len(source_samples)
            source = source_samples[indices].astype(np.complex128)
            source /= math.sqrt(max(float(np.mean(np.abs(source) ** 2)), 1e-30))
        else:
            source = _ofdm_qpsk_frame(rng, sample_count, sample_rate_hz, channel_bandwidth_hz)
        propagated = np.fft.ifft(np.fft.fft(source) * response)
        if emitter:
            carrier = np.exp(2j * np.pi * frequency_offset_hz * np.arange(sample_count) / sample_rate_hz)
            propagated = np.fft.ifft(np.fft.fft(propagated * carrier) * occupied)
        tx_power_mw = 10 ** (float(anchor["tx_power_dbm"]) / 10)
        components[anchor["id"]] = propagated * math.sqrt(tx_power_mw)

    # Thermal noise is kTB at 290 K, raised by the declared receiver NF.
    noise_power_mw = BOLTZMANN * REFERENCE_TEMPERATURE_K * channel_bandwidth_hz * 1000 * 10 ** (noise_figure_db / 10)
    noise_spectrum = (rng.standard_normal(sample_count) + 1j * rng.standard_normal(sample_count)) * occupied
    noise = np.fft.ifft(noise_spectrum)
    noise /= math.sqrt(max(float(np.mean(np.abs(noise) ** 2)), 1e-30))
    noise *= math.sqrt(noise_power_mw)
    iq = (sum(components.values(), start=np.zeros(sample_count, dtype=np.complex128)) + noise).astype(np.complex64)
    powers = {key: float(np.mean(np.abs(value) ** 2)) for key, value in components.items()}
    target_power = powers[target_id]
    interference_power = sum(value for key, value in powers.items() if key != target_id)
    # The ground processor sees the mixed IQ frame. Source-separated powers
    # below are simulator truth supplied for the SINR demonstration.
    rssi_dbm, spectrum = _ground_station_process(iq, sample_rate_hz, center_frequency_hz)
    return {
        "source": "sionna_cir_receiver_model",
        "position_m": observation.get("position_m"),
        "captured_at": observation.get("timestamp"),
        "receiver": {
            "center_frequency_hz": center_frequency_hz,
            "frequency_span_hz": sample_rate_hz,
            "sample_rate_hz": sample_rate_hz,
            "sample_count": sample_count,
            "channel_bandwidth_hz": channel_bandwidth_hz,
            "resolution_hz": sample_rate_hz / sample_count,
            "window": "periodic_hann",
            "equivalent_noise_bandwidth_hz": 1.5 * sample_rate_hz / sample_count,
            "noise_figure_db": noise_figure_db,
            "temperature_k": REFERENCE_TEMPERATURE_K,
            "iq_unit": "sqrt_mW_calibrated_equivalent",
            "waveform": "recorded_protocol_iq_replay" if recorded_emitters is not None else "generic_qpsk_ofdm_64fft_16cp_independent_sources",
            "ofdm_fft_size": 64,
            "ofdm_cyclic_prefix_samples": 16,
            "ofdm_active_subcarriers": min(50, 2 * int((channel_bandwidth_hz / sample_rate_hz * 64) // 2)),
            "seed": seed,
        },
        "target_id": target_id,
        "pipeline": {
            "capture_location": "uav_receiver",
            "transport": "simulated_uplink",
            "processing_location": "ground_station",
            "payload_format": "complex64_interleaved_iq",
            "payload_bytes": sample_count * 8,
            "assumed_uplink_bps": 10_000_000,
            "assumed_fixed_one_way_latency_ms": 20.0,
            "estimated_one_way_latency_ms": round(20.0 + sample_count * 8 * 8 / 10_000_000 * 1000, 3),
        },
        **({"iq": [[round(float(value.real), 10), round(float(value.imag), 10)] for value in iq]} if include_iq else {}),
        "spectrum": spectrum,
        "metrics": {
            "rssi_dbm": rssi_dbm,
            "rssi_method": "mean_abs_iq_squared_calibrated_equivalent",
            "target_power_dbm": _dbm(target_power),
            "interference_power_dbm": _dbm(interference_power) if interference_power > 0 else None,
            "noise_power_dbm": _dbm(noise_power_mw),
            "sinr_db": round(10 * math.log10(max(target_power, 1e-30) / (interference_power + noise_power_mw)), 3),
            "sinr_method": "simulation_source_separated_truth",
            "per_source_power_dbm": {key: _dbm(value) for key, value in powers.items()},
        },
    }


def compact_spectrum(spectrum: dict[str, list[float]], bins: int = 256) -> dict[str, Any]:
    """Average adjacent FFT-bin powers in linear units for a bounded waterfall row."""
    values = spectrum["bin_power_dbm"]
    frequencies = spectrum["frequency_hz"]
    if not values or len(values) != len(frequencies) or len(values) % bins:
        raise ValueError("频谱无法按所需瀑布图宽度聚合")
    group = len(values) // bins
    power = np.asarray(values, dtype=np.float64).reshape(bins, group)
    averaged = 10 * np.log10(np.mean(10 ** (power / 10), axis=1))
    return {
        "start_frequency_hz": float(frequencies[0]),
        "bin_width_hz": float((frequencies[-1] - frequencies[0] + (frequencies[1] - frequencies[0])) / bins),
        "bin_power_dbm": [round(float(value), 2) for value in averaged],
        "source_fft_bins": len(values),
    }
