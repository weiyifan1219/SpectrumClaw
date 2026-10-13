"""Deterministic previews, IQ selection and signal measurements.

No classifier lives here. Measurements are estimates from raw samples, not
protocol labels or plot pixels. Preview aggregation happens in linear power.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.signal import fftconvolve, firwin

from .capture import Capture

MIN_ANALYSIS_SAMPLES = 64


def _limit(value: int, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer within {low}..{high}")
    return int(value)


def _quality(iq: np.ndarray) -> dict[str, Any]:
    if not len(iq):
        return {"status": "too_short", "protocol_eligible": False, "sample_count": 0}
    powers = np.abs(iq.astype(np.complex128)) ** 2
    return {
        "status": "zero_signal" if float(powers.max()) == 0 else "ok",
        "protocol_eligible": False, "sample_count": int(len(iq)),
        "rms_adc": float(np.sqrt(powers.mean())),
        "zero_pair_fraction": float(np.mean(powers == 0)),
        "clipped_component_fraction": float(np.mean(
            np.concatenate((np.abs(iq.real.astype(np.float64)), np.abs(iq.imag.astype(np.float64)))) >= 32767)),
    }


def _stft(iq: np.ndarray, fs: float, max_rows: int = 128, nfft_cap: int = 1024) -> tuple:
    """Average consecutive STFT rows into a bounded display, without decimation.

    Every full analysis window contributes. At most 128 FFTs are materialized
    per batch; spectrum averages all windows, not only the displayed centers.
    """
    nfft = min(nfft_cap, 2 ** int(math.floor(math.log2(len(iq)))))
    hop = max(1, nfft // 4)
    starts = np.arange(0, len(iq) - nfft + 1, hop, dtype=np.int64)
    rows = min(max_rows, len(starts))
    totals = np.zeros((rows, nfft), dtype=np.float64)
    counts = np.zeros(rows, dtype=np.int64)
    times = np.zeros(rows, dtype=np.float64)
    window = np.hanning(nfft + 1)[:-1]
    denominator = fs * float(np.sum(window * window))
    groups = np.minimum(np.arange(len(starts)) * rows // len(starts), rows - 1)
    offsets = np.arange(nfft)
    peak_psd = 0.0
    for begin in range(0, len(starts), 128):
        batch_starts = starts[begin:begin + 128]
        transformed = np.fft.fftshift(np.fft.fft(iq[batch_starts[:, None] + offsets] * window, axis=1), axes=1)
        psd = np.abs(transformed) ** 2 / denominator
        peak_psd = max(peak_psd, float(psd.max()))
        batch_groups = groups[begin:begin + len(batch_starts)]
        np.add.at(totals, batch_groups, psd)
        np.add.at(counts, batch_groups, 1)
        np.add.at(times, batch_groups, (batch_starts + nfft / 2) / fs)
    averaged = totals / counts[:, None]
    spectrum = np.sum(totals, axis=0) / len(starts)
    # A display cell represents original hop cells, not overlapping Hann
    # window supports. Aggregate groups by their true integer boundaries.
    group_edges = (np.arange(rows + 1) * len(starts) + rows - 1) // rows
    if len(starts) == 1:
        time_edges = np.array([starts[0], starts[0] + nfft], dtype=float) / fs
        time_cells = "single_window_support"
    else:
        hop_edges = (nfft / 2 + (np.arange(len(starts) + 1) - .5) * hop) / fs
        time_edges = hop_edges[group_edges]
        time_cells = "hop_centered_cells_aggregated_by_group"
    return (
        np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs)), times / counts,
        averaged, spectrum,
        {"window": "periodic Hann", "window_samples": nfft, "hop_samples": hop,
         "window_duration_s": nfft / fs, "bin_spacing_hz": fs / nfft,
         "full_window_count": len(starts), "display_rows": rows,
         "reference_peak_psd_adc2_per_hz": peak_psd,
         "time_edges_s": time_edges.tolist(), "time_cell_policy": time_cells,
         "time_aggregation": "linear_power_mean" if len(starts) > rows else "none",
         "tail_samples": int(len(iq) - starts[-1] - nfft)},
    )


def _bin_mean(frequencies: np.ndarray, power: np.ndarray, maximum: int) -> tuple:
    if len(frequencies) <= maximum:
        return frequencies, power
    boundaries = np.linspace(0, len(frequencies), maximum + 1, dtype=int)
    centers = np.array([frequencies[a:b].mean() for a, b in zip(boundaries[:-1], boundaries[1:])])
    values = np.stack([power[..., a:b].mean(axis=-1) for a, b in zip(boundaries[:-1], boundaries[1:])], axis=-1)
    return centers, values


def _relative_db(power: np.ndarray, reference: float) -> np.ndarray:
    return 10 * np.log10(np.maximum(power / max(reference, np.finfo(float).tiny), 1e-12))


def iq_overview_spectrum(capture: Capture) -> dict[str, Any]:
    """One mean-PSD row per IQ file; keep ADC units for a shared batch reference."""
    if capture.mode != 1 or capture.sample_rate_hz is None or capture.points < MIN_ANALYSIS_SAMPLES:
        raise ValueError("IQ 总览需要实际采样率和至少 64 对 IQ")
    freq, _, _, mean, detail = _stft(capture.values, capture.sample_rate_hz, max_rows=1)
    freq += capture.center_frequency_hz
    shown_freq, shown_mean = _bin_mean(freq, mean, 512)
    bins = np.linspace(0, len(freq), min(len(freq), 512) + 1, dtype=int)
    edges = np.r_[max(capture.center_frequency_hz - capture.sample_rate_hz / 2,
                      freq[0] - detail["bin_spacing_hz"] / 2),
                  (freq[:-1] + freq[1:]) / 2,
                  min(capture.center_frequency_hz + capture.sample_rate_hz / 2,
                      freq[-1] + detail["bin_spacing_hz"] / 2)][bins]
    if np.any(np.diff(edges) <= 0):
        raise ValueError("IQ 频率坐标无有效范围")
    return {"frequency_hz": shown_freq, "frequency_edges_hz": edges,
            "mean_psd_adc2_per_hz": shown_mean,
            "duration_s": capture.points / capture.sample_rate_hz,
            "window_samples": detail["window_samples"],
            "full_window_count": detail["full_window_count"]}


def preview_capture(capture: Capture, max_bins: int = 512, max_rows: int = 128) -> dict[str, Any]:
    max_bins = _limit(max_bins, "max_bins", 16, 2048)
    max_rows = _limit(max_rows, "max_rows", 1, 256)
    warnings = list(capture.metadata.get("warnings", []))
    if capture.mode == 0:
        freq = np.linspace(capture.start_frequency_hz, capture.stop_frequency_hz, capture.points)
        reference = float(np.max(capture.values))
        freq, linear = _bin_mean(freq, 10 ** ((capture.values - reference) / 10), max_bins)
        dbm = reference + 10 * np.log10(np.maximum(linear, np.finfo(float).tiny))
        return {"spectrum": {"frequency_hz": freq.tolist(), "power": dbm.tolist(), "unit": "dBm",
                             "frequency_axis": "nominal", "frequency_aggregation": "linear_power_mean"},
                "waterfall": None,
                "quality": {"status": "power_spectrum_only", "protocol_eligible": False}, "warnings": warnings}
    quality = _quality(capture.values)
    if capture.sample_rate_hz is None or capture.points < MIN_ANALYSIS_SAMPLES:
        quality["status"] = "missing_sample_rate" if capture.sample_rate_hz is None else "too_short"
        return {"spectrum": None, "waterfall": None, "quality": quality, "warnings": warnings}
    fs = capture.sample_rate_hz
    freq, times, psd, mean, detail = _stft(capture.values, fs, max_rows)
    freq += capture.center_frequency_hz
    reference = detail["reference_peak_psd_adc2_per_hz"]
    shown_freq, shown_psd = _bin_mean(freq, psd, max_bins)
    _, shown_mean = _bin_mean(freq, mean, max_bins)
    bins = np.linspace(0, len(freq), min(len(freq), max_bins) + 1, dtype=int)
    raw_frequency_edges = np.r_[
        max(capture.center_frequency_hz - fs / 2, freq[0] - detail["bin_spacing_hz"] / 2),
        (freq[:-1] + freq[1:]) / 2,
        min(capture.center_frequency_hz + fs / 2, freq[-1] + detail["bin_spacing_hz"] / 2),
    ]
    frequency_edges = raw_frequency_edges[bins]
    if np.any(np.diff(frequency_edges) <= 0):
        raise ValueError("Sample rate is too small to resolve RF-frequency coordinates at this center frequency")
    quality["protocol_eligible"] = quality["status"] == "ok"
    if detail["time_aggregation"] != "none":
        warnings.append("Preview averages consecutive STFT windows in linear power; raw IQ selection is unchanged.")
    if quality["status"] == "zero_signal":
        warnings.append("All IQ pairs are zero; the displayed floor does not represent detected power.")
    return {
        "spectrum": {"frequency_hz": shown_freq.tolist(), "power": _relative_db(shown_mean, reference).tolist(),
                     "unit": "dB relative", "reference": "capture STFT peak", "frequency_aggregation": "linear_power_mean"},
        "waterfall": {"frequency_hz": shown_freq.tolist(), "time_s": times.tolist(),
                      "frequency_edges_hz": frequency_edges.tolist(),
                      "frequency_cell_policy": "FFT_bin_midpoints_clipped_to_Nyquist",
                      "power": _relative_db(shown_psd, reference).tolist(), "unit": "dB relative",
                      "reference": "capture STFT peak", "time_origin": "first IQ sample in this file",
                      "duration_s": capture.points / fs, **detail},
        "quality": quality, "warnings": warnings,
    }


def _measure(frequencies: np.ndarray, power: np.ndarray, mask: np.ndarray, resolution_hz: float) -> tuple:
    """Noise-subtracted 99% occupied bandwidth, limited to the selected band.

    A peak-to-noise gate avoids reporting the Nyquist span as a white-noise
    signal. This is conservative: full-band noise-like emissions can remain
    inconclusive without a separate noise/reference measurement.
    """
    freq, selected = frequencies[mask], power[mask]
    if not len(freq):
        raise ValueError("Frequency selection contains no resolved FFT/spectrum bins")
    floor = max(float(np.percentile(power, 10)), np.finfo(float).tiny)
    peak = float(np.max(selected))
    margin = float(10 * (np.log10(max(peak, np.finfo(float).tiny)) - np.log10(floor)))
    flatness = float(np.exp(np.mean(np.log(np.maximum(power, np.finfo(float).tiny)))) / max(float(power.mean()), np.finfo(float).tiny))
    detail = {"peak_to_noise_floor_db": margin, "spectral_flatness": flatness,
              "noise_estimator": "10th percentile of full selected-time mean PSD"}
    if peak <= 0 or margin < 8 or (flatness > 0.6 and margin < 13):
        return {"center_frequency_hz": None, "bandwidth_hz": None, "frequency_start_hz": None,
                "frequency_stop_hz": None, "method": "inconclusive_no_distinct_signal",
                "frequency_resolution_hz": resolution_hz}, "no_distinct_signal", detail
    excess = np.maximum(selected - 1.5 * floor, 0)
    cumulative = np.cumsum(excess)
    total = float(cumulative[-1])
    if total <= 0:
        return {"center_frequency_hz": None, "bandwidth_hz": None, "frequency_start_hz": None,
                "frequency_stop_hz": None, "method": "inconclusive_no_distinct_signal",
                "frequency_resolution_hz": resolution_hz}, "no_distinct_signal", detail
    low = min(int(np.searchsorted(cumulative, total * .005)), len(freq) - 1)
    high = min(int(np.searchsorted(cumulative, total * .995)), len(freq) - 1)
    left = float(freq[low] - resolution_hz / 2)
    right = float(freq[high] + resolution_hz / 2)
    measurements = {
        "center_frequency_hz": (left + right) / 2, "bandwidth_hz": right - left,
        "frequency_start_hz": left, "frequency_stop_hz": right,
        "power_centroid_hz": float(np.sum(freq * excess) / total),
        "method": "99_percent_noise_subtracted_occupied_bandwidth",
        "occupied_power_fraction": .99, "frequency_resolution_hz": resolution_hz,
        "edge_truncated": low == 0 or high == len(freq) - 1,
    }
    return measurements, "ok", detail


def analyze_capture(capture: Capture, start_sample: int = 0, stop_sample: int | None = None,
                    frequency_start_hz: float | None = None,
                    frequency_stop_hz: float | None = None) -> dict[str, Any]:
    """Analyze one file. IQ in the return value is intentionally not JSON.

    Model input is cropped raw IQ. For a narrower frequency ROI it is mixed
    to that ROI's center and FIR-filtered; filter edge transients are removed.
    The sample rate is unchanged. Separate captures are never concatenated.
    """
    start_sample = _limit(start_sample, "start_sample", 0, capture.points - 1)
    stop_sample = capture.points if stop_sample is None else _limit(stop_sample, "stop_sample", 1, capture.points)
    if stop_sample <= start_sample:
        raise ValueError("stop_sample must be greater than start_sample (exclusive end)")
    if (frequency_start_hz is None) != (frequency_stop_hz is None):
        raise ValueError("Both frequency bounds must be provided together")
    warnings = list(capture.metadata.get("warnings", []))
    if capture.mode == 1 and capture.sample_rate_hz is None:
        raise ValueError("IQ SAMPLE_RATE is missing; provide a verified explicit sample rate")
    fs = capture.sample_rate_hz
    lower = capture.start_frequency_hz if capture.mode == 0 else capture.center_frequency_hz - fs / 2
    upper = capture.stop_frequency_hz if capture.mode == 0 else capture.center_frequency_hz + fs / 2
    lo, hi = lower, upper
    if frequency_start_hz is not None:
        lo, hi = float(frequency_start_hz), float(frequency_stop_hz)
        if not math.isfinite(lo) or not math.isfinite(hi) or not lower <= lo < hi <= upper:
            raise ValueError("Frequency selection must lie within the capture's measured/Nyquist span")
    selection = {"start_sample": start_sample, "stop_sample": stop_sample,
                 "sample_count": stop_sample - start_sample,
                 "frequency_start_hz": lo, "frequency_stop_hz": hi,
                 "sample_bounds": "start inclusive, stop exclusive", "cross_file_join": False}
    if capture.mode == 0:
        if start_sample != 0 or stop_sample != capture.points:
            raise ValueError("Power spectrum has frequency points, not a time-sample selection")
        frequencies = np.linspace(lower, upper, capture.points)
        reference = float(capture.values.max())
        power = 10 ** ((capture.values - reference) / 10)
        mask = (frequencies >= lo) & (frequencies <= hi)
        measurements, status, detail = _measure(frequencies, power, mask, (upper - lower) / (capture.points - 1))
        measurements["bin_spacing_hz"] = measurements["frequency_resolution_hz"]
        measurements["frequency_resolution_hz"] = max(capture.rbw_hz, measurements["bin_spacing_hz"])
        measurements["rbw_hz"] = capture.rbw_hz
        measurements["frequency_axis"] = "nominal"
        if measurements.get("center_frequency_hz") is not None:
            measurements["frequency_start_hz"] = max(lo, measurements["frequency_start_hz"])
            measurements["frequency_stop_hz"] = min(hi, measurements["frequency_stop_hz"])
            measurements["bandwidth_hz"] = measurements["frequency_stop_hz"] - measurements["frequency_start_hz"]
            measurements["center_frequency_hz"] = (measurements["frequency_start_hz"] + measurements["frequency_stop_hz"]) / 2
        warnings.append("MODE=0 supports spectrum measurements only; protocol recognition requires IQ.")
        return {"measurements": measurements, "selection": selection, "warnings": warnings,
                "quality": {"status": status, "protocol_eligible": False, **detail},
                "iq": None, "sample_rate_hz": None}
    selected = capture.values[start_sample:stop_sample].astype(np.complex64, copy=True)
    quality = _quality(selected)
    selection.update({"start_time_s": start_sample / fs, "stop_time_s": stop_sample / fs,
                      "duration_s": len(selected) / fs, "sample_rate_hz": fs,
                      "sample_rate_source": capture.metadata["sample_rate_source"]})
    empty_measurements = {"center_frequency_hz": None, "bandwidth_hz": None,
                          "frequency_start_hz": None, "frequency_stop_hz": None, "method": "unavailable"}
    if len(selected) < MIN_ANALYSIS_SAMPLES or quality["status"] == "zero_signal":
        quality["status"] = "too_short" if len(selected) < MIN_ANALYSIS_SAMPLES else "zero_signal"
        return {"measurements": empty_measurements, "selection": selection, "warnings": warnings,
                "quality": quality, "iq": selected, "sample_rate_hz": fs}
    freq, _, _, mean, detail = _stft(selected, fs, max_rows=1, nfft_cap=2048)
    freq += capture.center_frequency_hz
    mask = (freq >= lo) & (freq < hi)
    measurements, status, signal_detail = _measure(freq, mean, mask, detail["bin_spacing_hz"])
    quality.update(signal_detail)
    quality["status"] = status
    quality["protocol_eligible"] = status == "ok"
    if status != "ok":
        warnings.append("No distinct signal above estimated noise; a full-band noise-like signal needs a noise/reference measurement.")
    if measurements.get("edge_truncated"):
        warnings.append("Occupied power reaches a selection/capture edge; bandwidth may be truncated.")
    selection["processing"] = "time_crop_only"
    selection["model_center_frequency_hz"] = capture.center_frequency_hz
    selection["model_start_sample"] = start_sample
    selection["model_stop_sample"] = stop_sample
    if lo > lower or hi < upper:
        # Bound the FIR cost; its finite transition width is explicitly exposed.
        midpoint, bandwidth = (lo + hi) / 2, hi - lo
        # Aim for transition <= 1/4 of the selected bandwidth. Bluetooth-sized
        # channels in a wide IQ capture need more than a fixed 257-tap filter.
        desired_taps = max(257, int(math.ceil(13.2 * fs / bandwidth)) | 1)
        taps = min(desired_taps, 4097, (len(selected) // 4) | 1)
        if taps < 17:
            quality.update(status="too_short", protocol_eligible=False)
            warnings.append("Selection is too short for a frequency-selective FIR filter.")
        else:
            shift = midpoint - capture.center_frequency_hz
            mixed = selected * np.exp(-2j * np.pi * shift * np.arange(len(selected)) / fs)
            kernel = firwin(taps, bandwidth / 2, fs=fs, window="hamming")
            filtered = fftconvolve(mixed, kernel, mode="same")
            trim = taps // 2
            selected = filtered[trim:-trim].astype(np.complex64)
            selection.update({"processing": "time_crop_frequency_shift_fir_lowpass",
                              "model_center_frequency_hz": midpoint, "frequency_shift_hz": shift,
                              "filter_taps": taps, "filter_cutoff_hz": bandwidth / 2,
                              "filter_transition_estimate_hz": 3.3 * fs / taps,
                              "filter_trim_samples_each_edge": trim,
                              "model_start_sample": start_sample + trim, "model_stop_sample": stop_sample - trim})
            warnings.append("Frequency selection uses a finite-transition FIR; edge samples are excluded from model input.")
            if bandwidth < 13.2 * fs / taps:
                quality.update(status="filter_resolution_limited", protocol_eligible=False)
                warnings.append("Selected band is narrow relative to the FIR transition; widen the frequency selection or use a dedicated channelizer.")
    selection["model_sample_count"] = len(selected)
    if len(selected) < MIN_ANALYSIS_SAMPLES:
        quality.update(status="too_short", protocol_eligible=False)
        warnings.append("Fewer than 64 usable IQ samples remain after selection/filtering.")
    if measurements.get("center_frequency_hz") is not None:
        measurements["frequency_start_hz"] = max(lo, measurements["frequency_start_hz"])
        measurements["frequency_stop_hz"] = min(hi, measurements["frequency_stop_hz"])
        measurements["bandwidth_hz"] = measurements["frequency_stop_hz"] - measurements["frequency_start_hz"]
        measurements["center_frequency_hz"] = (measurements["frequency_start_hz"] + measurements["frequency_stop_hz"]) / 2
    measurements["duration_s"] = (stop_sample - start_sample) / fs
    measurements["sample_rate_hz"] = fs
    if quality.get("clipped_component_fraction", 0) > .01:
        quality["protocol_eligible"] = False
        quality["status"] = "clipped"
        warnings.append("More than 1% of IQ components reach int16 limits; classification is disabled.")
    return {"measurements": measurements, "selection": selection, "warnings": warnings,
            "quality": quality, "iq": selected, "sample_rate_hz": fs}
