"""Read-only replay of protocol-recognition selections as simulated emitters."""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from ..wireless_recognition.dsp import analyze_capture
from ..wireless_recognition.service import get_wireless_service


REPLAY_SAMPLE_RATE_HZ = 62_500_000
_LOCK = threading.Lock()
_CACHE: tuple[float, list[dict[str, Any]]] | None = None


def _candidate_rank(analysis: dict[str, Any]) -> tuple[float, float]:
    selection = analysis["selection"]
    span = float(selection["frequency_stop_hz"]) - float(selection["frequency_start_hz"])
    return (span, -float(analysis["protocol"]["confidence"]))


def _public(emitter: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in emitter.items() if key != "samples"}


def load_recorded_emitters(*, refresh: bool = False) -> list[dict[str, Any]]:
    """Choose three prior-labeled, bounded selections from immutable SPEC records.

    The recordings are receiver captures in ADC counts, so their absolute
    amplitude is deliberately discarded. They are replay stimuli, not clean
    original transmitter waveforms or proof of a new on-air protocol.
    """
    global _CACHE
    with _LOCK:
        if not refresh and _CACHE is not None and time.monotonic() - _CACHE[0] < 60:
            return _CACHE[1]
        service = get_wireless_service()
        analyses = service.list_analyses(limit=500)["analyses"]
        candidates = [item for item in analyses if (
            item.get("protocol", {}).get("status") == "ok"
            and item["protocol"].get("label") in ("Wi-Fi", "Bluetooth")
            and float(item["protocol"].get("confidence") or 0) >= 0.8
            and item.get("quality", {}).get("protocol_eligible") is True
            and abs(float(item.get("sample_rate_hz") or 0) - REPLAY_SAMPLE_RATE_HZ) < 1
            and item.get("selection", {}).get("model_sample_count", 0) >= 1024
        )]
        wifi = sorted((item for item in candidates if item["protocol"]["label"] == "Wi-Fi"), key=_candidate_rank)
        bluetooth = sorted((item for item in candidates if item["protocol"]["label"] == "Bluetooth"), key=_candidate_rank)
        chosen: list[dict[str, Any]] = []
        used_records: set[str] = set()
        for anchor_id, options in (("tx-02", bluetooth), ("tx-01", wifi), ("tx-03", wifi)):
            item = next((row for row in options if row["record_id"] not in used_records), None)
            if item is None:
                raise ValueError("无线协议识别缺少足够的已标注 IQ 记录，无法建立三发射源回放")
            used_records.add(item["record_id"])
            selected = item["selection"]
            record = service.get_record(item["record_id"])
            capture = service._capture_for(record, sample_rate_hz=REPLAY_SAMPLE_RATE_HZ)
            result = analyze_capture(
                capture,
                start_sample=int(selected["start_sample"]),
                stop_sample=int(selected["stop_sample"]),
                frequency_start_hz=float(selected["frequency_start_hz"]),
                frequency_stop_hz=float(selected["frequency_stop_hz"]),
            )
            samples = result["iq"]
            if samples is None or len(samples) < 1024 or not np.all(np.isfinite(samples)):
                raise ValueError("协议识别选区缺少可回放的有效 IQ")
            center = float(result["selection"]["model_center_frequency_hz"])
            chosen.append({
                "id": anchor_id,
                "protocol_prior": item["protocol"]["label"],
                "prior_confidence": round(float(item["protocol"]["confidence"]), 4),
                "model_id": item["protocol"]["model_id"],
                "analysis_id": item["id"],
                "record_id": item["record_id"],
                "recorded_center_frequency_hz": center,
                "sample_rate_hz": REPLAY_SAMPLE_RATE_HZ,
                "source_sample_count": int(len(samples)),
                "source_kind": "recorded_receiver_iq_replay",
                "samples": np.asarray(samples, dtype=np.complex64),
            })
        chosen.sort(key=lambda item: item["id"])
        _CACHE = (time.monotonic(), chosen)
        return chosen


def recorded_emitter_summary() -> list[dict[str, Any]]:
    return [_public(item) for item in load_recorded_emitters()]
