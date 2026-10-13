"""Versioned, optional ResNet2D protocol inference from *raw complex IQ*.

Torch is deliberately imported only when loading a configured model. Missing
weights are a supported state; never substitute random weights or a heuristic
protocol label. The configured manifest defines preprocessing and model dimensions.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time
from typing import Any

import numpy as np

SCHEMA = "spectrumclaw.wireless-resnet2d/v1"
CHANNELIZATION_CONTRACT = "spectrumclaw.iq-selection/v1"
PROCESSING_METHODS = ("time_crop_only", "time_crop_frequency_shift_fir_lowpass")
MAX_IQ_SAMPLES = 8_000_000
MAX_WEIGHTS_BYTES = 256 * 1024 * 1024


def _integer(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def validate_manifest(manifest: dict, *, require_weights: bool = True) -> dict:
    """Validate all values that change tensor semantics or resource bounds."""
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError(f"manifest schema must be {SCHEMA}")
    model_id = manifest.get("model_id")
    if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 160:
        raise ValueError("model_id must be a nonempty string of at most 160 characters")
    classes = manifest.get("classes")
    if (not isinstance(classes, list) or not 2 <= len(classes) <= 32
            or any(not isinstance(x, str) or not x.strip() or len(x) > 64 for x in classes)
            or len(set(classes)) != len(classes)):
        raise ValueError("classes must be 2..32 distinct nonempty labels, in training order")
    arch = manifest.get("architecture", {})
    if arch.get("name") != "resnet2d_small_v1" or arch.get("base_channels") not in (8, 16, 32):
        raise ValueError("unsupported ResNet2D architecture")
    channel = manifest.get("channelization", {})
    processing = channel.get("accepted_processing")
    if (channel.get("contract") != CHANNELIZATION_CONTRACT
            or not isinstance(processing, list) or not processing
            or any(method not in PROCESSING_METHODS for method in processing)
            or len(set(processing)) != len(processing)
            or not isinstance(channel.get("allow_prepared_npz"), bool)):
        raise ValueError("channelization must declare the versioned IQ selection contract and accepted processing")
    inp, stft = manifest.get("input", {}), manifest.get("stft", {})
    fs = inp.get("sample_rate_hz")
    if isinstance(fs, bool) or not isinstance(fs, (int, float)) or not np.isfinite(fs) or not 0 < fs <= 250e6:
        raise ValueError("input.sample_rate_hz must be finite and in (0, 250e6]")
    n = _integer(inp.get("window_samples"), "window_samples", 256, 262144)
    _integer(inp.get("window_hop_samples"), "window_hop_samples", 1, n)
    _integer(inp.get("max_windows"), "max_windows", 1, 32)
    if inp.get("resample_policy") not in ("reject", "polyphase"):
        raise ValueError("resample_policy must explicitly be reject or polyphase")
    if inp.get("iq_normalization") != "rms_per_window":
        raise ValueError("unsupported IQ normalization")
    seg = _integer(stft.get("nperseg"), "nperseg", 16, min(n, 4096))
    _integer(stft.get("hop_samples"), "STFT hop_samples", 1, seg)
    nfft = _integer(stft.get("nfft"), "nfft", seg, 4096)
    frames = 1 + (n - seg) // stft["hop_samples"]
    if frames * nfft > 2_000_000:
        raise ValueError("STFT exceeds the per-window tensor budget")
    expected = {"window": "hann_periodic", "spectrum": "two_sided_fftshift",
                "normalization": "peak_relative_log_power"}
    if any(stft.get(k) != v for k, v in expected.items()):
        raise ValueError("unsupported STFT preprocessing; use the versioned contract")
    floor = stft.get("floor_db")
    if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not np.isfinite(floor) or not -160 <= floor <= -20:
        raise ValueError("floor_db must be in [-160, -20]")
    threshold = manifest.get("decision", {}).get("confidence_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        raise ValueError("confidence_threshold must be in (0, 1]")
    runtime = manifest.get("runtime", {})
    if runtime.get("device") not in ("cpu", "cuda", "auto"):
        raise ValueError("runtime.device must be cpu, cuda, or auto")
    _integer(runtime.get("batch_size"), "batch_size", 1, 32)
    # Bound the complete feature set, not just one STFT or one inference batch.
    if frames * nfft * inp["max_windows"] > 8_000_000:
        raise ValueError("STFT feature set exceeds the analysis tensor budget")
    if require_weights:
        weights = manifest.get("weights", {})
        path, digest = weights.get("path"), weights.get("sha256")
        if not isinstance(path, str) or not path or Path(path).is_absolute():
            raise ValueError("weights.path must be relative to the manifest directory")
        if not isinstance(digest, str) or len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest):
            raise ValueError("weights.sha256 must be a lowercase SHA256 digest")
    return manifest


def spec_input_provenance(selection: dict) -> dict:
    """Bind input to the shared SPEC DSP selection, without fabricating metadata.

    Both the online service and SPEC training call analyze_capture() first, then
    this helper. Changing that DSP channelizer requires a new contract version.
    """
    keys = ("processing", "sample_rate_hz", "model_sample_count", "model_start_sample",
            "model_stop_sample", "start_sample", "stop_sample", "frequency_start_hz",
            "frequency_stop_hz", "model_center_frequency_hz", "frequency_shift_hz",
            "filter_taps", "filter_cutoff_hz", "filter_transition_estimate_hz",
            "filter_trim_samples_each_edge")
    return {"contract": CHANNELIZATION_CONTRACT, "source": "spec_dsp",
            "selection": {key: selection[key] for key in keys if key in selection}}


def validate_input_provenance(iq, sample_rate_hz, manifest, provenance):
    """Require compatible upstream selection semantics before STFT inference."""
    if not isinstance(provenance, dict) or provenance.get("contract") != CHANNELIZATION_CONTRACT:
        raise ValueError("explicit versioned input_provenance is required for protocol inference")
    source = provenance.get("source")
    channel = manifest["channelization"]
    if source not in ("spec_dsp", "prepared_npz"):
        raise ValueError("input provenance source must be spec_dsp or explicitly prepared_npz")
    if source == "prepared_npz":
        if not channel["allow_prepared_npz"]:
            raise ValueError("prepared NPZ inputs are disabled by the model manifest")
        preparation = provenance.get("preparation", {})
        if (preparation.get("operator_confirmed") is not True
                or not isinstance(preparation.get("recipe"), str) or not preparation["recipe"].strip()
                or not isinstance(preparation.get("source_recording"), str) or not preparation["source_recording"].strip()
                or len(preparation["recipe"]) > 2000 or len(preparation["source_recording"]) > 500):
            raise ValueError("prepared NPZ needs operator_confirmed, preparation recipe and source_recording")
    selected = provenance.get("selection")
    if not isinstance(selected, dict) or selected.get("processing") not in channel["accepted_processing"]:
        raise ValueError("upstream selection processing does not match the model manifest")
    count = _integer(selected.get("model_sample_count"), "model_sample_count", 1, MAX_IQ_SAMPLES)
    if np.asarray(iq).ndim != 1 or count != np.asarray(iq).size:
        raise ValueError("selection provenance sample count disagrees with model IQ")
    start = _integer(selected.get("model_start_sample"), "model_start_sample", 0, MAX_IQ_SAMPLES)
    stop = _integer(selected.get("model_stop_sample"), "model_stop_sample", 1, MAX_IQ_SAMPLES)
    if stop - start != count:
        raise ValueError("selection provenance start/stop disagree with model IQ")
    def finite(name):
        value = selected.get(name)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not np.isfinite(value):
            raise ValueError(f"selection provenance requires finite {name}")
        return float(value)
    fs = finite("sample_rate_hz")
    if fs <= 0 or not np.isclose(fs, sample_rate_hz, rtol=1e-9, atol=0):
        raise ValueError("selection provenance sample rate disagrees with model IQ")
    if finite("model_center_frequency_hz") <= 0:
        raise ValueError("selection provenance center frequency must be positive")
    lo, hi = finite("frequency_start_hz"), finite("frequency_stop_hz")
    if hi <= lo or hi-lo > fs * (1 + 1e-9):
        raise ValueError("selection provenance frequency bounds are invalid")
    if selected["processing"] == "time_crop_frequency_shift_fir_lowpass":
        taps = _integer(selected.get("filter_taps"), "filter_taps", 17, 4097)
        trim = _integer(selected.get("filter_trim_samples_each_edge"), "filter trim", 1, 2048)
        if taps % 2 != 1 or trim != taps // 2:
            raise ValueError("selection provenance FIR length/trim is incompatible")
        finite("frequency_shift_hz")
        cutoff = finite("filter_cutoff_hz")
        transition = finite("filter_transition_estimate_hz")
        if (not 0 < cutoff < fs / 2 or not np.isclose(2*cutoff, hi-lo, rtol=1e-9)
                or not np.isclose(transition, 3.3*fs/taps, rtol=1e-9)):
            raise ValueError("selection provenance FIR cutoff/transition is incompatible")
    # Copy only JSON values, preventing callers from mutating saved evidence.
    return json.loads(json.dumps(provenance, allow_nan=False))


def prepare_features(iq: np.ndarray, sample_rate_hz: float, manifest: dict) -> tuple[np.ndarray, dict]:
    """Return (windows, 1, frequency, time) float32 tensors and provenance.

    No padding of a short capture, no inferred sample rate, no concatenation of
    separate files. STFT uses complete periodic-Hann windows only. If explicitly
    enabled in the manifest, scipy.resample_poly supplies anti-alias filtering.
    """
    validate_manifest(manifest, require_weights=False)
    iq = np.asarray(iq)
    if iq.ndim != 1 or not np.iscomplexobj(iq):
        raise ValueError("model input must be one-dimensional complex IQ, not power spectra or images")
    if not 1 <= iq.size <= MAX_IQ_SAMPLES:
        raise ValueError(f"selected IQ must contain 1..{MAX_IQ_SAMPLES} samples")
    if not np.all(np.isfinite(iq)):
        raise ValueError("IQ contains NaN or infinity")
    if isinstance(sample_rate_hz, bool) or not np.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("a positive finite actual sample rate is required")
    inp, stft = manifest["input"], manifest["stft"]
    target_fs = float(inp["sample_rate_hz"])
    source_samples = int(iq.size)
    iq = iq.astype(np.complex128, copy=False)
    resampled = not np.isclose(sample_rate_hz, target_fs, rtol=1e-9, atol=0)
    if resampled:
        if inp["resample_policy"] != "polyphase":
            raise ValueError(f"sample rate mismatch: received {sample_rate_hz}, model requires {target_fs}")
        ratio = Fraction(target_fs / float(sample_rate_hz)).limit_denominator(1000)
        if ratio.numerator > 1000 or not np.isclose(float(ratio), target_fs / sample_rate_hz, rtol=1e-9):
            raise ValueError("sample rate ratio is not supported by the bounded polyphase resampler")
        if int(np.ceil(iq.size * float(ratio))) > MAX_IQ_SAMPLES:
            raise ValueError("resampled IQ would exceed the input sample budget")
        from scipy.signal import resample_poly
        iq = resample_poly(iq, ratio.numerator, ratio.denominator)
    n, hop = inp["window_samples"], inp["window_hop_samples"]
    if iq.size < n:
        raise ValueError(f"selection is too short: need {n} samples at {target_fs:g} S/s; received {iq.size}")
    starts = np.arange(0, iq.size - n + 1, hop, dtype=np.int64)
    available = len(starts)
    if len(starts) > inp["max_windows"]:
        starts = starts[np.linspace(0, len(starts) - 1, inp["max_windows"], dtype=int)]
    seg, fft_n, stft_hop = stft["nperseg"], stft["nfft"], stft["hop_samples"]
    hann = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(seg) / seg)
    features = []
    for start in starts:
        frame = iq[start:start + n]
        # Scale before RMS to avoid overflow even for corrupt, very large inputs.
        peak = float(np.max(np.abs(frame)))
        if not np.isfinite(peak) or peak <= 1e-20:
            raise ValueError("selection contains a zero-energy or numerically negligible window")
        frame = frame / peak
        frame = frame / np.sqrt(np.mean(np.abs(frame) ** 2))
        windows = np.lib.stride_tricks.sliding_window_view(frame, seg)[::stft_hop]
        spectrum = np.fft.fftshift(np.fft.fft(windows * hann, n=fft_n, axis=-1), axes=-1)
        power = np.abs(spectrum) ** 2
        max_power = float(power.max())
        if not np.isfinite(max_power) or max_power <= 0:
            raise ValueError("selection has no finite STFT energy")
        floor = float(stft["floor_db"])
        relative_db = 10 * np.log10(np.maximum(power / max_power, 10 ** (floor / 10)))
        feature = np.clip((relative_db - floor) / -floor, 0, 1)
        features.append(feature.T[None, :, :].astype(np.float32))
    return np.stack(features), {
        "source_sample_rate_hz": float(sample_rate_hz), "model_sample_rate_hz": target_fs,
        "source_samples": source_samples, "resampled": bool(resampled),
        "windows_available": available, "windows_used": len(starts),
        "window_start_samples_after_resample": starts.tolist(),
        "window_samples": n, "feature_shape": list(features[0].shape),
        "normalization": stft["normalization"],
    }


def build_resnet2d(num_classes: int, base_channels: int = 16):
    """Small four-stage residual network; no torchvision dependency."""
    import torch.nn as nn

    class Block(nn.Module):
        def __init__(self, channels_in, channels_out, stride=1):
            super().__init__()
            self.body = nn.Sequential(
                nn.Conv2d(channels_in, channels_out, 3, stride, 1, bias=False),
                nn.BatchNorm2d(channels_out), nn.ReLU(inplace=True),
                nn.Conv2d(channels_out, channels_out, 3, 1, 1, bias=False),
                nn.BatchNorm2d(channels_out),
            )
            self.skip = nn.Identity() if channels_in == channels_out and stride == 1 else nn.Sequential(
                nn.Conv2d(channels_in, channels_out, 1, stride, bias=False), nn.BatchNorm2d(channels_out))
            self.relu = nn.ReLU(inplace=True)

        def forward(self, x):
            return self.relu(self.body(x) + self.skip(x))

    class ResNet(nn.Module):
        def __init__(self):
            super().__init__()
            c = base_channels
            self.stem = nn.Sequential(nn.Conv2d(1, c, 3, 1, 1, bias=False), nn.BatchNorm2d(c), nn.ReLU(inplace=True))
            self.blocks = nn.Sequential(Block(c, c), Block(c, 2*c, 2), Block(2*c, 4*c, 2), Block(4*c, 8*c, 2))
            self.pool = nn.AdaptiveAvgPool2d(1)
            self.classifier = nn.Linear(8*c, num_classes)

        def forward(self, x):
            return self.classifier(self.pool(self.blocks(self.stem(x))).flatten(1))

    if not 2 <= num_classes <= 32 or base_channels not in (8, 16, 32):
        raise ValueError("unsupported model dimensions")
    return ResNet()


class ProtocolModel:
    """Cached inference adapter. A lock bounds concurrent GPU memory usage."""
    def __init__(self, manifest_path: Path | None = None):
        self.manifest_path = Path(manifest_path).expanduser().resolve() if manifest_path else None
        self._lock = threading.RLock()
        self._status_lock = threading.Lock()
        self._manifest = None
        self._model = None
        self._device = None
        self._fingerprint = None
        self._status_snapshot = self._result(
            "not_configured" if self.manifest_path is None else "unavailable",
            "No model manifest configured." if self.manifest_path is None else "Model configuration has not been checked yet.",
            loaded=False, device=None, busy=False)

    def _configuration(self):
        if self.manifest_path is None:
            return None, None, "not_configured", "No trained protocol model manifest has been configured."
        try:
            if self.manifest_path.stat().st_size > 65536:
                raise ValueError("manifest exceeds 64 KiB")
            manifest = validate_manifest(json.loads(self.manifest_path.read_text(encoding="utf-8")))
            root = self.manifest_path.parent
            weights = (root / manifest["weights"]["path"]).resolve()
            if not weights.is_relative_to(root):
                raise ValueError("weights path must remain inside the manifest directory")
            if not weights.is_file() or not 0 < weights.stat().st_size <= MAX_WEIGHTS_BYTES:
                raise ValueError("weights file is missing, empty, or exceeds 256 MiB")
            return manifest, weights, "configured", None
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            return None, None, "unavailable", f"Invalid model configuration: {exc}"

    @staticmethod
    def _result(status, reason=None, manifest=None, **kwargs):
        return {"status": status, "label": None, "confidence": None, "reason": reason,
                "classes": manifest["classes"] if manifest else [],
                "model_id": manifest["model_id"] if manifest else None,
                "inference_ms": None, **kwargs}

    def _publish_status(self, result):
        with self._status_lock:
            self._status_snapshot = dict(result)

    def status(self) -> dict:
        # Never make the ingestion watcher or UI status wait behind slow CPU
        # inference, CUDA startup or weight hashing. Refresh only when idle.
        if not self._lock.acquire(blocking=False):
            with self._status_lock:
                return {**self._status_snapshot, "busy": True, "cached": True}
        try:
            manifest, _, state, reason = self._configuration()
            if manifest is not None and importlib.util.find_spec("torch") is None:
                state, reason = "unavailable", "PyTorch is not installed; signal parsing and parameter measurement remain available."
            result = self._result(state, reason, manifest,
                                loaded=self._model is not None,
                                device=str(self._device) if self._device is not None else None,
                                busy=False, cached=False)
            self._publish_status(result)
            return result
        finally:
            self._lock.release()

    def _load(self, manifest, weights):
        import torch
        st = weights.stat()
        signature = (json.dumps(manifest, sort_keys=True), st.st_mtime_ns, st.st_size)
        if self._model is not None and signature == self._fingerprint:
            return
        digest = hashlib.sha256()
        with weights.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != manifest["weights"]["sha256"]:
            raise ValueError("model weights SHA256 does not match the manifest")
        device = manifest["runtime"]["device"]
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise ValueError("manifest requests CUDA but CUDA is unavailable")
        model = build_resnet2d(len(manifest["classes"]), manifest["architecture"]["base_channels"])
        state = torch.load(weights, map_location="cpu", weights_only=True)
        if not isinstance(state, dict):
            raise ValueError("checkpoint must contain a plain state_dict")
        model.load_state_dict(state, strict=True)
        model.to(device).eval()
        self._model, self._manifest, self._device, self._fingerprint = model, manifest, device, signature

    def predict(self, iq: np.ndarray, sample_rate_hz: float, *, input_provenance: dict | None = None) -> dict:
        started = time.perf_counter()
        with self._lock:
            manifest, weights, state, reason = self._configuration()
            self._publish_status(self._result(state, reason, manifest,
                                 loaded=self._model is not None, device=self._device, busy=True))
            if manifest is None:
                return self._result(state, reason)
            try:
                upstream = validate_input_provenance(iq, sample_rate_hz, manifest, input_provenance)
                features, provenance = prepare_features(iq, sample_rate_hz, manifest)
                provenance["input_provenance"] = upstream
            except (ValueError, TypeError, ImportError) as exc:
                return self._result("invalid_input", str(exc), manifest)
            try:
                import torch
                self._load(manifest, weights)
                self._publish_status(self._result("configured", None, manifest,
                                     loaded=True, device=self._device, busy=True))
                batches = []
                batch_size = manifest["runtime"]["batch_size"]
                with torch.inference_mode():
                    for start in range(0, len(features), batch_size):
                        tensor = torch.from_numpy(features[start:start+batch_size]).to(self._device)
                        logits = self._model(tensor)
                        if not torch.isfinite(logits).all():
                            raise ValueError("model produced non-finite logits")
                        batches.append(torch.softmax(logits, dim=1).cpu().numpy())
                scores = np.concatenate(batches).mean(axis=0)
                winner = int(scores.argmax())
                confidence = float(scores[winner])
                known = confidence >= manifest["decision"]["confidence_threshold"]
                return self._result("ok" if known else "unknown",
                    None if known else "Confidence is below the configured validation threshold.", manifest,
                    label=manifest["classes"][winner] if known else None, confidence=confidence,
                    probabilities={name: float(scores[j]) for j, name in enumerate(manifest["classes"])},
                    preprocessing=provenance, device=str(self._device),
                    inference_ms=round((time.perf_counter() - started) * 1000, 3),
                    confidence_kind="mean_window_softmax_not_calibrated_probability")
            except Exception as exc:
                # Configuration/load/runtime failures must not masquerade as a label.
                return self._result("unavailable", f"Model inference unavailable: {exc}", manifest,
                                    inference_ms=round((time.perf_counter()-started)*1000, 3))
