from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import BinaryIO
import uuid

import numpy as np

from .capture import read_capture
from .dsp import analyze_capture, preview_capture, iq_overview_spectrum
from .model import ProtocolModel, spec_input_provenance

FRAME_NAME = re.compile(r"frame-\d+\.(?:txt|spec)$")
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def configured_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


class CaptureChanged(ValueError):
    pass


class AnalysisBusy(RuntimeError):
    pass


class UploadTooLarge(ValueError):
    pass


class WirelessService:
    """Index immutable final SFTP frames, never operate on arbitrary client paths."""

    def __init__(self, inbox: Path, db_path: Path, manifest: Path | None = None,
                 poll_interval_s: float = 1.0, max_file_bytes: int = 64 * 1024 * 1024):
        self.root = Path(inbox).resolve()
        self.db_path = Path(db_path).resolve()
        self.poll_interval_s = max(.2, float(poll_interval_s))
        self.max_file_bytes = int(max_file_bytes)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.model = ProtocolModel(manifest)
        self._scan_lock = threading.Lock()
        self._preview_lock = threading.Lock()
        self._analysis_slots = threading.BoundedSemaphore(2)
        self._preview_cache = OrderedDict()
        self._iq_overview_cache = OrderedDict()
        self._stop = threading.Event()
        self._thread = None
        self._lifecycle_lock = threading.Lock()
        self.last_scan_at = None
        self.last_scan_ms = None
        self.last_error = None
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY, relative_path TEXT UNIQUE NOT NULL,
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, metadata TEXT NOT NULL, received_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS invalid_files (
                    relative_path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER,
                    reason TEXT NOT NULL, observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analyses (
                    id TEXT PRIMARY KEY, record_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS records_received ON records(received_at);
                CREATE INDEX IF NOT EXISTS analyses_created ON analyses(created_at);
            """)

    @contextmanager
    def _db(self):
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _safe_path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("记录路径超出采集根目录")
        return path

    def _index_file(self, path: Path, sample_rate_hz: float | None = None,
                    uploaded_filename: str | None = None):
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("不索引根目录之外或符号链接记录")
        relative = path.relative_to(self.root).as_posix()
        before = path.stat()
        if before.st_size > self.max_file_bytes:
            raise UploadTooLarge("文件超过配置的大小限制")
        capture = read_capture(path, sample_rate_hz=sample_rate_hz)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise CaptureChanged("文件正在变化，等待下一轮完整记录")
        record_id = hashlib.sha256((relative + "\0" + digest).encode()).hexdigest()[:32]
        received = utc_now()
        metadata = dict(capture.metadata)
        metadata.update({
            "id": record_id, "filename": path.name, "session": path.parent.relative_to(self.root).as_posix(),
            "mode": capture.mode, "points": capture.points,
            "center_frequency_hz": capture.center_frequency_hz,
            "start_frequency_hz": capture.start_frequency_hz,
            "stop_frequency_hz": capture.stop_frequency_hz,
            "rbw_hz": capture.rbw_hz, "sample_rate_hz": capture.sample_rate_hz,
            "received_at": received, "sha256": digest, "size_bytes": after.st_size,
            "relative_path": relative,
        })
        if sample_rate_hz is not None and metadata.get("sample_rate_source") != "header":
            metadata["sample_rate_source"] = "explicit_upload"
        if uploaded_filename:
            metadata["uploaded_filename"] = uploaded_filename
        with self._db() as db:
            db.execute("DELETE FROM records WHERE relative_path=?", (relative,))
            db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?)",
                       (record_id, relative, after.st_size, after.st_mtime_ns, digest, encode(metadata), received))
            db.execute("DELETE FROM invalid_files WHERE relative_path=?", (relative,))
        return metadata

    def scan(self):
        if not self._scan_lock.acquire(blocking=False):
            return self.status()
        began = time.perf_counter()
        try:
            with self._db() as db:
                known = {row["relative_path"]: (row["size"], row["mtime_ns"])
                         for row in db.execute("SELECT relative_path,size,mtime_ns FROM records")}
                invalid = {row["relative_path"]: (row["size"], row["mtime_ns"])
                           for row in db.execute("SELECT relative_path,size,mtime_ns FROM invalid_files")}
            observed = set()
            for path in sorted(self.root.rglob("frame-*")):
                if not FRAME_NAME.fullmatch(path.name) or not path.is_file():
                    continue
                relative = path.relative_to(self.root).as_posix()
                observed.add(relative)
                try:
                    if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                        continue
                    stat = path.stat()
                    signature = (stat.st_size, stat.st_mtime_ns)
                    if signature == known.get(relative) or signature == invalid.get(relative):
                        continue
                    self._index_file(path)
                except (ValueError, OSError, KeyError, OverflowError) as exc:
                    try:
                        stat = path.stat()
                        signature = (stat.st_size, stat.st_mtime_ns)
                    except OSError:
                        signature = (-1, -1)
                    with self._db() as db:
                        db.execute("DELETE FROM records WHERE relative_path=?", (relative,))
                        db.execute("INSERT OR REPLACE INTO invalid_files VALUES (?,?,?,?,?)",
                                   (relative, *signature, str(exc)[:400], utc_now()))
            missing = (set(known) | set(invalid)) - observed
            with self._db() as db:
                for relative in missing:
                    db.execute("DELETE FROM records WHERE relative_path=?", (relative,))
                    db.execute("DELETE FROM invalid_files WHERE relative_path=?", (relative,))
            self.last_error = None
            self.last_scan_at = utc_now()
        except OSError as exc:
            self.last_error = str(exc)
        finally:
            self.last_scan_ms = round((time.perf_counter() - began) * 1000, 2)
            self._scan_lock.release()
        return self.status()

    def _watch(self):
        while not self._stop.is_set():
            try:
                self.scan()
            except Exception as exc:
                self.last_error = str(exc)[:400]
            self._stop.wait(self.poll_interval_s)

    def start(self):
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._watch, name="wireless-capture-index", daemon=True)
            self._thread.start()

    def stop(self):
        with self._lifecycle_lock:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=5)

    def status(self):
        with self._db() as db:
            count = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            invalid = db.execute("SELECT COUNT(*) FROM invalid_files").fetchone()[0]
            errors = [dict(row) for row in db.execute("SELECT relative_path,reason FROM invalid_files ORDER BY observed_at DESC LIMIT 10")]
        return {"watching": bool(self._thread and self._thread.is_alive() and not self._stop.is_set()),
                "root": str(self.root), "poll_interval_s": self.poll_interval_s,
                "record_count": count, "invalid_count": invalid, "invalid_files": errors,
                "last_scan_at": self.last_scan_at, "last_scan_ms": self.last_scan_ms,
                "last_error": self.last_error, "model": self.model.status(),
                "supported_targets": ["Wi-Fi", "Bluetooth", "ZigBee"], "extension_targets": ["LTE", "5G NR"]}

    def list_sessions(self):
        with self._db() as db:
            rows = db.execute(
                "SELECT json_extract(metadata, '$.session') AS session "
                "FROM records GROUP BY session "
                "ORDER BY MAX(received_at) DESC, session DESC"
            ).fetchall()
        return {"sessions": [row["session"] for row in rows]}

    def list_records(self, limit: int = 500, session: str | None = None, offset: int = 0):
        # Filter in SQL before pagination; session never opens a client path.
        limit, offset = min(max(limit, 1), 2000), max(offset, 0)
        where = " WHERE json_extract(metadata, '$.session')=?" if session is not None else ""
        params = (session,) if session is not None else ()
        with self._db() as db:
            total = db.execute("SELECT COUNT(*) FROM records" + where, params).fetchone()[0]
            rows = db.execute(
                "SELECT metadata FROM records" + where +
                " ORDER BY received_at DESC, id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return {"records": [json.loads(row[0]) for row in rows], "total": total,
                "offset": offset, "limit": limit}

    def get_record(self, record_id: str):
        with self._db() as db:
            row = db.execute("SELECT metadata FROM records WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise KeyError("采集记录不存在，或文件已经变化/移除")
        return json.loads(row[0])

    def _capture_for(self, record: dict, sample_rate_hz: float | None = None):
        path = self._safe_path(record["relative_path"])
        if (not path.is_file() or path.stat().st_size != record["size_bytes"]
                or path.stat().st_size > self.max_file_bytes
                or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]):
            raise CaptureChanged("原文件已变化或移除，请刷新后重新选择")
        if sample_rate_hz is None and record.get("sample_rate_source") == "explicit_upload":
            sample_rate_hz = record.get("sample_rate_hz")
        return read_capture(path, sample_rate_hz=sample_rate_hz)

    def upload(self, stream: BinaryIO, filename: str, sample_rate_hz: float | None = None):
        if Path(filename).suffix.lower() not in {".txt", ".spec"}:
            raise ValueError("请上传 SPEC 格式的 .txt 或 .spec 文件")
        if sample_rate_hz is not None and (not math.isfinite(sample_rate_hz) or sample_rate_hz <= 0):
            raise ValueError("显式采样率必须是正的有限数值")
        session = self.root / ("capture-http-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12])
        session.mkdir()
        final = session / "frame-0000000001.spec"
        # Non-frame name is invisible to the watcher while the parser validates it.
        temporary = session / "upload-validation.tmp"
        try:
            count = 0
            with temporary.open("xb") as output:
                while chunk := stream.read(1024 * 1024):
                    count += len(chunk)
                    if count > self.max_file_bytes:
                        raise UploadTooLarge("上传超过大小限制")
                    output.write(chunk)
                output.flush()
                import os
                os.fsync(output.fileno())
            read_capture(temporary, sample_rate_hz=sample_rate_hz)
            # Keep the watcher from indexing before explicit upload metadata is stored.
            with self._scan_lock:
                temporary.replace(final)
                return self._index_file(final, sample_rate_hz, Path(filename).name)
        finally:
            if temporary.exists():
                temporary.unlink()
            if not any(session.iterdir()):
                session.rmdir()

    def preview(self, record_id: str, sample_rate_hz: float | None = None):
        record = self.get_record(record_id)
        capture = self._capture_for(record, sample_rate_hz)
        key = (record_id, capture.sample_rate_hz)
        with self._preview_lock:
            if key in self._preview_cache:
                self._preview_cache.move_to_end(key)
                return self._preview_cache[key]
        started = time.perf_counter()
        result = preview_capture(capture)
        result["record"] = {**record, **capture.metadata, "id": record_id}
        result["preview_ms"] = round((time.perf_counter() - started) * 1000, 2)
        encode(result)
        with self._preview_lock:
            self._preview_cache[key] = result
            while len(self._preview_cache) > 8:
                self._preview_cache.popitem(last=False)
        return result

    def iq_waterfall(self, session: str | None, limit: int = 128, sample_rate_hz: float | None = None):
        if sample_rate_hz is not None and (not math.isfinite(sample_rate_hz) or sample_rate_hz <= 0):
            raise ValueError("批次采样率必须是正的有限数值")
        # Filter by session before limiting, so an older batch remains accessible.
        with self._db() as db:
            if session is None:
                row = db.execute("SELECT json_extract(metadata, '$.session') FROM records "
                                 "WHERE json_extract(metadata, '$.mode')=1 ORDER BY received_at DESC LIMIT 1").fetchone()
                session = row[0] if row else None
            rows = db.execute("SELECT metadata FROM records WHERE json_extract(metadata, '$.session')=? "
                              "AND json_extract(metadata, '$.mode')=1 "
                              "ORDER BY CAST(substr(json_extract(metadata, '$.filename'), 7) AS INTEGER) DESC LIMIT ?",
                              (session, min(128, max(1, limit)))).fetchall()
        records = [json.loads(row[0]) for row in rows]
        selected, spectra, skipped = [], [], []
        frequencies = edges = None
        for record in records:
            # A batch fallback never replaces a header or an explicit upload rate.
            fallback = sample_rate_hz if record.get("sample_rate_hz") is None else None
            capture = self._capture_for(record, fallback)
            if capture.sample_rate_hz is None or capture.points < 64:
                skipped.append(record["id"])
                continue
            key = (record["id"], capture.sample_rate_hz)
            with self._preview_lock:
                row = self._iq_overview_cache.get(key)
                if row is not None:
                    self._iq_overview_cache.move_to_end(key)
            if row is None:
                row = iq_overview_spectrum(capture)
                with self._preview_lock:
                    self._iq_overview_cache[key] = row
                    while len(self._iq_overview_cache) > 256:
                        self._iq_overview_cache.popitem(last=False)
            if frequencies is None:
                frequencies, edges = row["frequency_hz"], row["frequency_edges_hz"]
            elif not np.array_equal(frequencies, row["frequency_hz"]) or not np.array_equal(edges, row["frequency_edges_hz"]):
                break
            selected.append({**record, "duration_s": row["duration_s"], "effective_sample_rate_hz": capture.sample_rate_hz})
            spectra.append(row["mean_psd_adc2_per_hz"])
        warnings = ["每行是一条 IQ 记录的平均功率谱；记录之间有采集间隙，行距不代表连续时间。",
                    "总览共用批次功率参照，不逐条归一化；幅度基于 ADC 计数，非校准 dBm，接收增益变化会影响比较。",
                    "平均谱用于查找记录，短突发可能被平均削弱；点击一行查看单条 IQ 时频细节。"]
        if skipped:
            warnings.append(f"跳过 {len(skipped)} 条缺采样率或过短的 IQ；可为缺采样率记录应用批次设置。")
        if not selected:
            return {"session": session, "waterfall": None, "spectrum": None,
                    "warnings": warnings + ["暂无可绘制的 IQ 总览，请先应用批次采样率。"], "skipped_record_ids": skipped}
        selected.reverse()
        matrix = np.stack(spectra[::-1])
        reference = max(float(matrix.max()), np.finfo(float).tiny)
        relative = lambda value: (10 * np.log10(np.maximum(value / reference, 1e-12))).tolist()
        x = frequencies.tolist()
        return {"session": session, "waterfall": {
                    "frequency_hz": x, "frequency_edges_hz": edges.tolist(), "time_s": None,
                    "power": relative(matrix), "unit": "dB relative", "record_mode": "iq",
                    "row_ids": [r["id"] for r in selected],
                    "frame_numbers": [int(Path(r["filename"]).stem.split("-")[1]) for r in selected],
                    "timestamp_seconds": [r.get("timestamp") for r in selected],
                    "duration_seconds": [r["duration_s"] for r in selected],
                    "axis": "frame_index", "reference": "batch peak mean PSD",
                    "reference_psd_adc2_per_hz": reference, "row_aggregation": "mean PSD within each IQ file"},
                "spectrum": {"frequency_hz": x, "power": relative(matrix[-1]),
                             "mean_power": relative(matrix.mean(axis=0)), "max_hold": relative(matrix.max(axis=0)),
                             "unit": "dB relative"}, "warnings": warnings, "skipped_record_ids": skipped}

    def waterfall(self, session: str | None = None, limit: int = 128, mode: int = 0,
                  sample_rate_hz: float | None = None):
        if mode == 1:
            return self.iq_waterfall(session, limit, sample_rate_hz)
        # Query the requested mode/batch before limiting. Activity elsewhere
        # must never hide an older batch's most recent compatible sweeps.
        with self._db() as db:
            if session is None:
                row = db.execute("SELECT json_extract(metadata, '$.session') FROM records "
                                 "WHERE json_extract(metadata, '$.mode')=0 "
                                 "ORDER BY received_at DESC, id DESC LIMIT 1").fetchone()
                session = row[0] if row else None
            rows = db.execute("SELECT metadata FROM records WHERE json_extract(metadata, '$.session')=? "
                              "AND json_extract(metadata, '$.mode')=0 "
                              "ORDER BY CAST(substr(json_extract(metadata, '$.filename'), 7) AS INTEGER) DESC, id DESC LIMIT ?",
                              (session, min(128, max(1, limit)))).fetchall()
        records = [json.loads(row[0]) for row in rows]
        if not records:
            return {"session": session, "waterfall": None, "spectrum": None,
                    "warnings": ["本批次没有功率谱；IQ 请查看单文件时频图。"]}
        latest = records[0]
        configuration = lambda r: (r["start_frequency_hz"], r["stop_frequency_hz"], r["rbw_hz"], r["points"])
        current = configuration(latest)
        # Use the last contiguous configuration only, no mismatched frequency grids.
        selected = []
        for record in records:
            if configuration(record) != current:
                break
            selected.append(record)
        selected.reverse()
        # Reduce each frame before retaining it: 128 full 2M-point arrays would
        # otherwise exhaust memory on a busy server.
        points = current[3]
        edges = np.linspace(0, points, min(points, 512) + 1, dtype=int)
        rows = []
        for record in selected:
            capture = self._capture_for(record)
            reference = float(capture.values.max())
            linear = 10 ** ((capture.values.astype(float) - reference) / 10)
            mean = np.add.reduceat(linear, edges[:-1]) / np.diff(edges)
            rows.append(reference + 10 * np.log10(np.maximum(mean, 1e-300)))
        matrix = np.stack(rows)
        frequencies = np.linspace(current[0], current[1], points)
        x = [float(frequencies[a:b].mean()) for a, b in zip(edges[:-1], edges[1:])]
        frequency_edges = np.concatenate(([frequencies[0]], (frequencies[:-1] + frequencies[1:]) / 2, [frequencies[-1]]))[edges]
        peak = matrix.max(axis=0)
        average = peak + 10 * np.log10(np.mean(10 ** ((matrix - peak) / 10), axis=0))
        return {"session": session, "waterfall": {"frequency_hz": x, "frequency_edges_hz": frequency_edges.tolist(), "time_s": None,
                    "power": matrix.tolist(), "unit": "dBm", "row_ids": [r["id"] for r in selected],
                    "frame_numbers": [int(Path(r["filename"]).stem.split("-")[1]) for r in selected],
                    "timestamp_seconds": [r.get("timestamp") for r in selected], "axis": "frame_index",
                    "frequency_axis": "nominal", "frequency_reduction": "linear_power_mean"},
                "spectrum": {"frequency_hz": x, "power": matrix[-1].tolist(),
                             "max_hold": peak.tolist(), "mean_power": average.tolist(), "unit": "dBm"},
                "warnings": ["每行是独立扫描，行间不代表等间隔时间；频率轴为请求范围的名义坐标。",
                             "显示按频率箱在线性功率域取均值，原始记录保持不变。"]}

    def analyze(self, record_id: str, *, sample_rate_hz=None, start_sample=0, stop_sample=None,
                frequency_start_hz=None, frequency_stop_hz=None):
        if not self._analysis_slots.acquire(blocking=False):
            raise AnalysisBusy("分析队列忙，请稍后重试")
        began = time.perf_counter()
        try:
            record = self.get_record(record_id)
            capture = self._capture_for(record, sample_rate_hz)
            selected = analyze_capture(capture, start_sample=start_sample, stop_sample=stop_sample,
                                       frequency_start_hz=frequency_start_hz, frequency_stop_hz=frequency_stop_hz)
            iq = selected.pop("iq", None)
            selected_rate = selected.pop("sample_rate_hz", capture.sample_rate_hz)
            measurement_ms = (time.perf_counter() - began) * 1000
            quality = selected.get("quality", {})
            if iq is None or not quality.get("protocol_eligible", False):
                protocol = {"status": "ineligible", "label": None, "confidence": None,
                            "reason": "该选区不具备有效 IQ 或信号质量不足，不能进行协议分类。",
                            "classes": [], "model_id": None, "inference_ms": 0}
            else:
                protocol = self.model.predict(iq, selected_rate,
                                              input_provenance=spec_input_provenance(selected["selection"]))
            result = {**selected, "id": uuid.uuid4().hex, "record_id": record_id,
                      "created_at": utc_now(), "status": "completed",
                      "protocol": protocol, "source": record,
                      "sample_rate_hz": capture.sample_rate_hz,
                      "sample_rate_source": capture.metadata.get("sample_rate_source"),
                      "timing_ms": {"measurement": round(measurement_ms, 2),
                                    "total": round((time.perf_counter() - began) * 1000, 2)},
                      "schema_version": "wireless-analysis-v1"}
            with self._db() as db:
                db.execute("INSERT INTO analyses VALUES (?,?,?,?)", (result["id"], record_id, result["created_at"], encode(result)))
            return result
        finally:
            self._analysis_slots.release()

    def list_analyses(self, limit=100):
        with self._db() as db:
            rows = db.execute("SELECT result FROM analyses ORDER BY created_at DESC LIMIT ?", (min(max(limit, 1), 500),)).fetchall()
        return {"analyses": [json.loads(row[0]) for row in rows]}

    def get_analysis(self, analysis_id: str):
        with self._db() as db:
            row = db.execute("SELECT result FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        if row is None:
            raise KeyError("分析记录不存在")
        return json.loads(row[0])


@lru_cache(maxsize=1)
def get_wireless_service() -> WirelessService:
    from ...config import get_settings
    settings = get_settings()
    return WirelessService(configured_path(settings.wireless_inbox), configured_path(settings.wireless_db_path),
                           configured_path(settings.wireless_model_manifest) if settings.wireless_model_manifest else None,
                           settings.wireless_poll_interval_s, settings.wireless_max_file_bytes)
