"""Bounded, read-only decoder for SAM60 SPEC v1 files.

The original nine-field format was written by the x86_64 Ubuntu collector.
Missing BYTE_ORDER therefore means little endian; missing SAMPLE_RATE never
means a guessed rate. IQ is returned in ADC counts, not calibrated dBm.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re
from typing import Any

import numpy as np

MAX_POINTS = 2_000_000
MAX_HEADER_BYTES = 16_384
REQUIRED_FIELDS = {
    "MAGIC", "VERSION", "MODE", "START_FREQ", "STOP_FREQ", "RBW",
    "POINTS", "DATA_TYPE", "TIMESTAMP",
}


@dataclass(frozen=True)
class Capture:
    path: Path
    metadata: dict[str, Any]
    mode: int
    values: np.ndarray
    sample_rate_hz: float | None
    center_frequency_hz: float
    start_frequency_hz: float
    stop_frequency_hz: float
    rbw_hz: float
    points: int


def _number(value: Any, name: str, *, minimum: float = 0, maximum: float = 1e12) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be within {minimum:g}..{maximum:g}")
    return result


def _integer(value: str, name: str, minimum: int, maximum: int) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be within {minimum}..{maximum}")
    return result


def read_capture(path: Path, sample_rate_hz: float | None = None) -> Capture:
    """Read a complete file; reject partial payloads, duplicates and NaN/Inf.

    Callers must resolve IDs beneath their configured inbox before invoking
    this parser. Filename policy and path containment belong to that index.
    """
    path = Path(path)
    if path.name.endswith((".part", ".writing")):
        raise ValueError("Temporary upload files are not captures")
    external_fs = None
    if sample_rate_hz is not None:
        external_fs = _number(sample_rate_hz, "sample_rate_hz", minimum=1e-12, maximum=1e10)
    header: dict[str, str] = {}
    with path.open("rb") as stream:
        header_bytes = 0
        for _ in range(64):
            line = stream.readline(4097)
            header_bytes += len(line)
            if header_bytes > MAX_HEADER_BYTES:
                raise ValueError("SPEC header exceeds the size limit")
            if line in (b"\n", b"\r\n"):
                break
            if len(line) > 4096 or not line.startswith(b"#") or not line.endswith(b"\n"):
                raise ValueError("Incomplete or invalid SPEC header")
            try:
                key, separator, value = line[1:].decode("ascii").strip().partition(":")
            except UnicodeDecodeError as exc:
                raise ValueError("SPEC header must be ASCII") from exc
            if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in header or not value:
                raise ValueError("Invalid or duplicate SPEC header field")
            header[key] = value.strip()
        else:
            raise ValueError("Too many SPEC header fields")
        if not REQUIRED_FIELDS <= header.keys():
            raise ValueError("Missing SPEC fields: " + ", ".join(sorted(REQUIRED_FIELDS - header.keys())))
        if header["MAGIC"] != "SPEC" or header["VERSION"] != "1":
            raise ValueError("Only SPEC version 1 is supported")
        mode = _integer(header["MODE"], "MODE", 0, 1)
        expected_type = "float32" if mode == 0 else "int16_interleaved"
        if header["DATA_TYPE"] != expected_type:
            raise ValueError(f"MODE={mode} requires DATA_TYPE={expected_type}")
        points = _integer(header["POINTS"], "POINTS", 2 if mode == 0 else 1, MAX_POINTS)
        timestamp = _integer(header["TIMESTAMP"], "TIMESTAMP", 0, 253402300799)
        start = _number(header["START_FREQ"], "START_FREQ", minimum=1e-12)
        stop = _number(header["STOP_FREQ"], "STOP_FREQ")
        rbw = _number(header["RBW"], "RBW")
        if mode == 0 and (stop <= start or rbw <= 0):
            raise ValueError("Power spectrum requires STOP_FREQ > START_FREQ and RBW > 0")
        if mode == 1 and (stop != 0 or rbw != 0):
            raise ValueError("SPEC v1 IQ requires STOP_FREQ=0 and RBW=0")
        byte_order = header.get("BYTE_ORDER", "little")
        if byte_order not in {"little", "big"}:
            raise ValueError("BYTE_ORDER must be little or big")
        fs = None
        fs_source = "missing"
        if "SAMPLE_RATE" in header:
            fs = _number(header["SAMPLE_RATE"], "SAMPLE_RATE", minimum=1e-12, maximum=1e10)
            fs_source = "header"
            if external_fs is not None and not math.isclose(fs, external_fs, rel_tol=1e-9, abs_tol=0):
                raise ValueError("External sample rate conflicts with header SAMPLE_RATE")
        elif mode == 1 and external_fs is not None:
            fs, fs_source = external_fs, "explicit_override"
        scale = None
        if "SCALE_TO_V" in header:
            scale = _number(header["SCALE_TO_V"], "SCALE_TO_V", minimum=1e-30, maximum=1e6)
        payload = stream.read(points * 4 + 1)
        if len(payload) != points * 4:
            raise ValueError("Payload length does not match POINTS (4 bytes per point/IQ pair)")
    prefix = "<" if byte_order == "little" else ">"
    if mode == 0:
        values = np.frombuffer(payload, dtype=prefix + "f4").astype(np.float64)
        if not np.isfinite(values).all():
            raise ValueError("Power spectrum contains NaN or infinity")
    else:
        pairs = np.frombuffer(payload, dtype=prefix + "i2").reshape(points, 2)
        values = pairs[:, 0].astype(np.float32) + 1j * pairs[:, 1].astype(np.float32)
    center = start if mode == 1 else (start + stop) / 2
    warnings = []
    if "BYTE_ORDER" not in header:
        warnings.append("Legacy SPEC v1: little-endian x86_64 collector format assumed.")
    if mode == 0:
        warnings.append("Frequency axis is nominal; SPEC v1 does not store the SDK frequency array.")
    elif fs is None:
        warnings.append("SAMPLE_RATE is missing; provide a verified IQ-pairs/second rate before analysis.")
    elif fs_source == "explicit_override":
        warnings.append("Sample rate was explicitly supplied; it was not measured from the payload.")
    if mode == 1:
        warnings.append("IQ amplitude is in ADC counts; relative PSD is not calibrated dBm.")
        warnings.append("Nyquist span is not a guarantee of the receiver's usable bandwidth.")
    metadata = {
        "format": "SPEC", "version": 1, "mode": mode,
        "data_type": expected_type, "points": points, "payload_bytes": points * 4,
        "timestamp": timestamp, "timestamp_resolution_s": 1,
        "timestamp_semantics": "collector_file_write_time",
        "sample_rate_hz": fs, "sample_rate_source": fs_source,
        "center_frequency_hz": center, "start_frequency_hz": start,
        "stop_frequency_hz": stop, "rbw_hz": rbw,
        "duration_s": points / fs if mode == 1 and fs is not None else None,
        "byte_order": byte_order, "byte_order_source": "header" if "BYTE_ORDER" in header else "legacy_x86_64",
        "scale_to_v": scale, "scale_applied": False,
        "amplitude_unit": "dBm" if mode == 0 else "ADC counts",
        "warnings": warnings, "header": dict(header),
    }
    values.flags.writeable = False
    return Capture(path, metadata, mode, values, fs, center, start, stop, rbw, points)
