import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowLeft, Download, FileAudio, Pause, Play, Radio, RefreshCw, ScanLine, Upload, Waves } from "lucide-react";
import {
  analyzeWirelessRecord, exportWirelessAnalysis, fetchWirelessAnalyses,
  fetchWirelessAnalysis, fetchWirelessRecords, fetchWirelessSessions, fetchWirelessStatus, fetchWirelessWaterfall,
  previewWirelessRecord, scanWirelessRecords, uploadWirelessRecord,
} from "../lib/api.js";
import "../styles/wireless-recognition.css";
import { batchRateKey, protocolPresentation, recordPageInfo, resolveIQRate } from "../lib/wireless-view.js";

const RECORD_PAGE_SIZE = 300;
const BATCH_RATE_STORAGE = "spectrumclaw.wireless.batch-rates.v1";
function storedBatchRates() {
  try {
    const value = JSON.parse(localStorage.getItem(BATCH_RATE_STORAGE) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}

const number = (v) => v !== null && v !== "" && v !== undefined && Number.isFinite(Number(v));
const fmt = (v, digits = 3) => number(v) ? Number(v).toLocaleString("zh-CN", { maximumFractionDigits: digits }) : "—";
const mhz = (v) => number(v) ? `${fmt(Number(v) / 1e6, 6)} MHz` : "—";
const timestamp = (v) => {
  if (!v) return "—";
  const d = new Date(typeof v === "number" ? v * 1000 : v);
  return Number.isNaN(d.valueOf()) ? String(v) : d.toLocaleString("zh-CN", { hour12: false });
};
const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
const modeIQ = (record) => Number(record?.mode) === 1;
const colorStops = [[11, 18, 45], [29, 66, 135], [10, 167, 205], [33, 211, 157], [229, 213, 71], [241, 111, 37], [189, 34, 54]];

function colorAt(value) {
  const p = clamp(value, 0, 1) * (colorStops.length - 1);
  const i = Math.min(Math.floor(p), colorStops.length - 2);
  return colorStops[i].map((v, c) => Math.round(v + (colorStops[i + 1][c] - v) * (p - i)));
}

function frequencyBounds(spectrum, record, fs) {
  if (modeIQ(record) && Number(fs) > 0 && number(record?.center_frequency_hz ?? record?.start_frequency_hz)) {
    const fc = Number(record.center_frequency_hz ?? record.start_frequency_hz);
    return [fc - Number(fs) / 2, fc + Number(fs) / 2];
  }
  if (!modeIQ(record) && number(record?.start_frequency_hz) && number(record?.stop_frequency_hz)) return [Number(record.start_frequency_hz), Number(record.stop_frequency_hz)];
  const f = spectrum?.frequency_hz;
  if (f?.length > 1 && number(f[0]) && number(f[f.length - 1])) return [f[0], f[f.length - 1]];
  return null;
}

function domainFrom(values, fallback = [-120, -20]) {
  let lo = Infinity, hi = -Infinity;
  for (const row of values || []) for (const value of Array.isArray(row) ? row : [row]) {
    if (number(value)) { lo = Math.min(lo, Number(value)); hi = Math.max(hi, Number(value)); }
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return fallback;
  if (hi - lo < 1) return [lo - 1, hi + 1];
  return [lo, hi];
}

function axisEdges(explicit, centers, singleWidth = 1) {
  if (Array.isArray(explicit) && explicit.length === centers.length + 1
      && explicit.every((v, i) => Number.isFinite(v) && (!i || v > explicit[i - 1]))) return explicit;
  if (!centers.length) return [];
  if (centers.length === 1) return [centers[0] - singleWidth / 2, centers[0] + singleWidth / 2];
  return [centers[0] - (centers[1] - centers[0]) / 2,
    ...centers.slice(1).map((v, i) => (v + centers[i]) / 2),
    centers[centers.length - 1] + (centers[centers.length - 1] - centers[centers.length - 2]) / 2];
}

function SpectrumPlot({ spectrum, waterfall, bounds, selection, onSelect, onInteraction }) {
  const [drag, setDrag] = useState(null);
  const svgRef = useRef(null);
  const width = 1000, height = 168;
  const curves = useMemo(() => {
    if (!spectrum?.power?.length) return [];
    const result = [{ label: "所选记录", color: "#56d9e6", data: spectrum.power }];
    const matrix = waterfall?.power;
    const freq = waterfall?.frequency_hz;
    if (matrix?.length && freq?.length === spectrum.frequency_hz?.length && freq.every((f, i) => Math.abs(f - spectrum.frequency_hz[i]) < 1)) {
      const max = [], mean = [];
      for (let i = 0; i < freq.length; i++) {
        let peak = -Infinity, sum = 0, n = 0;
        for (const row of matrix) if (number(row[i])) { peak = Math.max(peak, Number(row[i])); sum += 10 ** (Number(row[i]) / 10); n++; }
        max.push(n ? peak : null);
        mean.push(n ? 10 * Math.log10(Math.max(sum / n, 1e-30)) : null);
      }
      result.push({ label: "批次平均", color: "#9bdd75", data: mean }, { label: "最大保持", color: "#ffbe63", data: max });
    }
    return result;
  }, [spectrum, waterfall]);
  const [ymin, ymax] = useMemo(() => domainFrom(curves.map((x) => x.data)), [curves]);
  if (!bounds || !curves.length) return <div className="wr-chart-empty">选择一条完整记录后显示频谱</div>;
  const span = Math.max(1, bounds[1] - bounds[0]);
  const position = (e) => clamp((e.clientX - svgRef.current.getBoundingClientRect().left) / svgRef.current.getBoundingClientRect().width, 0, 1);
  const left = drag ? Math.min(drag.start, drag.end) : clamp((Number(selection?.frequency_start_hz) - bounds[0]) / span, 0, 1);
  const right = drag ? Math.max(drag.start, drag.end) : clamp((Number(selection?.frequency_stop_hz) - bounds[0]) / span, 0, 1);
  return <div className="wr-spectrum">
    <div className="wr-chart-key"><span>{spectrum.unit || "dB"}</span>{curves.map((c) => <span key={c.label}><i style={{ background: c.color }} />{c.label}</span>)}</div>
    <div className="wr-spectrum-plot">
      <div className="wr-y-labels">{[ymax, (ymin + ymax) / 2, ymin].map((v, i) => <span key={i}>{fmt(v, 0)}</span>)}</div>
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="频谱曲线；可拖动选择频段"
        onPointerDown={(e) => { if (e.button !== 0) return; onInteraction(); const x = position(e); e.currentTarget.setPointerCapture(e.pointerId); setDrag({ start: x, end: x }); }}
        onPointerMove={(e) => { if (drag) setDrag({ ...drag, end: position(e) }); }}
        onPointerUp={(e) => { if (!drag) return; const end = position(e); if (Math.abs(end - drag.start) > 0.003) onSelect({ frequency_start_hz: bounds[0] + Math.min(end, drag.start) * span, frequency_stop_hz: bounds[0] + Math.max(end, drag.start) * span }); setDrag(null); }}
        onPointerCancel={() => setDrag(null)}>
        {[0, 0.25, 0.5, 0.75, 1].map((v) => <g key={v}><line x1={v * width} x2={v * width} y1="0" y2={height} /><line x1="0" x2={width} y1={v * height} y2={v * height} /></g>)}
        {curves.slice().reverse().map((c) => <polyline key={c.label} fill="none" stroke={c.color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" points={c.data.map((v, i) => `${(spectrum.frequency_hz[i] - bounds[0]) / span * width},${height - (Number(v) - ymin) / (ymax - ymin) * height}`).join(" ")} />)}
        {Number.isFinite(left) && Number.isFinite(right) && right > left && <rect className="wr-roi" x={left * width} y="0" width={(right - left) * width} height={height} />}
      </svg>
    </div>
    <div className="wr-x-labels">{[0, 0.25, 0.5, 0.75, 1].map((v) => <span key={v}>{fmt((bounds[0] + v * span) / 1e6, 3)}</span>)}</div>
    <span className="wr-axis-title">频率 / MHz · 拖动曲线选择频段</span>
  </div>;
}

function WaterfallPlot({ data, iq, sampleRate, points, selection, onSelect, onRowSelect, onInteraction }) {
  const canvasRef = useRef(null);
  const overlayRef = useRef(null);
  const [drag, setDrag] = useState(null);
  const source = drag?.source || data;
  const matrix = source?.power || [];
  const rows = matrix.length, columns = matrix[0]?.length || 0;
  const frequencyEdges = useMemo(() => axisEdges(source?.frequency_edges_hz, source?.frequency_hz || []), [source]);
  const timeEdges = useMemo(() => iq
    ? axisEdges(source?.time_edges_s, source?.time_s || [], sampleRate > 0 ? Number(source?.window_samples || points) / sampleRate : 1)
    : Array.from({ length: rows + 1 }, (_, i) => i), [source, iq, rows, sampleRate, points]);
  const [lo, hi] = useMemo(() => domainFrom(matrix), [matrix]);
  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs || !rows || !columns || frequencyEdges.length !== columns + 1 || timeEdges.length !== rows + 1) return;
    // Cells can be unequal in width or height after grouped preview reduction.
    // Raster placement and pointer coordinates share exactly the same domains.
    cvs.width = Math.max(1024, columns); cvs.height = Math.max(512, rows);
    const ctx = cvs.getContext("2d");
    const fMin = frequencyEdges[0], fSpan = frequencyEdges.at(-1) - fMin;
    const tMin = timeEdges[0], tSpan = timeEdges.at(-1) - tMin;
    if (!(fSpan > 0) || !(tSpan > 0)) return;
    ctx.clearRect(0, 0, cvs.width, cvs.height);
    for (let y = 0; y < rows; y++) for (let x = 0; x < columns; x++) {
      const v = matrix[y][x];
      const color = number(v) ? colorAt((Number(v) - lo) / (hi - lo)) : [11, 18, 30];
      const left = (frequencyEdges[x] - fMin) / fSpan * cvs.width;
      const right = (frequencyEdges[x + 1] - fMin) / fSpan * cvs.width;
      const top = (timeEdges[y] - tMin) / tSpan * cvs.height;
      const bottom = (timeEdges[y + 1] - tMin) / tSpan * cvs.height;
      ctx.fillStyle = `rgb(${color.join(",")})`;
      ctx.fillRect(Math.floor(left), Math.floor(top), Math.ceil(right) - Math.floor(left), Math.ceil(bottom) - Math.floor(top));
    }
  }, [matrix, rows, columns, lo, hi, frequencyEdges, timeEdges]);
  if (!rows || !columns || !source.frequency_hz?.length) return <div className="wr-chart-empty">{iq ? "此记录暂无可用 IQ 时频预览；请检查采样率" : "等待同一批次、同配置的完整记录；旧 IQ 请先应用批次采样率"}</div>;
  const f0 = frequencyEdges[0], f1 = frequencyEdges.at(-1);
  const span = f1 - f0;
  const t0 = timeEdges[0], t1 = timeEdges.at(-1);
  const timespan = t1 - t0;
  if (!(span > 0) || !(timespan > 0) || timeEdges.length !== rows + 1) return <div className="wr-chart-empty">预览坐标无有效范围，无法选择片段</div>;
  const getPoint = (e) => {
    const box = overlayRef.current.getBoundingClientRect();
    return { x: clamp((e.clientX - box.left) / box.width, 0, 1), y: clamp((e.clientY - box.top) / box.height, 0, 1) };
  };
  let rectangle = null;
  if (drag) rectangle = { x: Math.min(drag.start.x, drag.end.x), y: Math.min(drag.start.y, drag.end.y), w: Math.abs(drag.start.x - drag.end.x), h: Math.abs(drag.start.y - drag.end.y) };
  else if (iq && selection && sampleRate > 0) {
    const x0 = clamp((selection.frequency_start_hz - f0) / span, 0, 1), x1 = clamp((selection.frequency_stop_hz - f0) / span, 0, 1);
    const y0 = clamp((selection.start_sample / sampleRate - t0) / timespan, 0, 1), y1 = clamp((selection.stop_sample / sampleRate - t0) / timespan, 0, 1);
    rectangle = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  function finish(e) {
    if (!drag) return;
    const end = getPoint(e);
    if (!iq) {
      const rowCount = drag.rowIds?.length || rows;
      const row = Math.min(rowCount - 1, Math.floor(end.y * rowCount));
      if (drag.rowIds?.[row]) onRowSelect(drag.rowIds[row]);
    } else if (sampleRate > 0 && Math.abs(end.x - drag.start.x) > 0.004 && Math.abs(end.y - drag.start.y) > 0.004) {
      onSelect({
        frequency_start_hz: f0 + Math.min(end.x, drag.start.x) * span,
        frequency_stop_hz: f0 + Math.max(end.x, drag.start.x) * span,
        start_sample: clamp(Math.floor((t0 + Math.min(end.y, drag.start.y) * timespan) * sampleRate), 0, points - 1),
        stop_sample: clamp(Math.ceil((t0 + Math.max(end.y, drag.start.y) * timespan) * sampleRate), 1, points),
      });
    }
    setDrag(null);
  }
  return <div className="wr-waterfall">
    <div className="wr-waterfall-grid">
      <div className="wr-y-labels">{[0, 0.5, 1].map((fraction) => <span key={fraction}>{iq ? `${fmt((t0 + fraction * timespan) * 1000, 3)} ms` : `#${source.frame_numbers?.[Math.min(rows - 1, Math.floor(fraction * (rows - 1)))] ?? Math.min(rows, Math.floor(fraction * (rows - 1)) + 1)}`}</span>)}</div>
      <div className="wr-waterfall-image">
        <canvas ref={canvasRef} aria-label={iq ? "IQ 时频图" : source.record_mode === "iq" ? "IQ 批次瀑布总览" : "逐条扫描频谱瀑布图"} />
        <svg ref={overlayRef} viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-label={iq ? "拖动选择时间和频率片段" : "点击瀑布图选择一条记录"}
          onPointerDown={(e) => { if (e.button !== 0) return; onInteraction(); const p = getPoint(e); e.currentTarget.setPointerCapture(e.pointerId); setDrag({ start: p, end: p, rowIds: source.row_ids, source }); }}
          onPointerMove={(e) => { if (drag) setDrag({ ...drag, end: getPoint(e) }); }}
          onPointerUp={finish} onPointerCancel={() => setDrag(null)}>
          {iq && rectangle && rectangle.w > 0 && rectangle.h > 0 && <rect className="wr-roi" x={rectangle.x * 1000} y={rectangle.y * 1000} width={rectangle.w * 1000} height={rectangle.h * 1000} />}
          {!iq && source.row_ids?.includes(selection?.record_id) && <rect className="wr-roi" x="0" width="1000" y={source.row_ids.indexOf(selection.record_id) / rows * 1000} height={1000 / rows} />}
        </svg>
      </div>
      <div className="wr-color-scale"><span>{fmt(hi, 1)}</span><i /><span>{fmt(lo, 1)}</span><small>{source.unit || "dB"}</small></div>
    </div>
    <div className="wr-x-labels">{[0, 0.25, 0.5, 0.75, 1].map((v) => <span key={v}>{fmt((f0 + v * span) / 1e6, 3)}</span>)}</div>
    <span className="wr-axis-title">频率 / MHz · {iq ? "拖框选择时间与频率，选区对应原始 IQ 样本" : source.record_mode === "iq" ? `${rows} 条 IQ 记录的平均谱，每条一行；点击进入单条时频图，行距不代表连续时间` : `${rows} 条扫描，每条一行；点击选中记录，行距不代表经过时间`}</span>
    {(!source.frequency_edges_hz || (iq && !source.time_edges_s)) && <span className="wr-axis-title">服务未提供显示单元边界，当前按中心坐标估算；精确选区请更新后端。</span>}
  </div>;
}

export default function WirelessRecognitionPage({ active = true, onBack }) {
  const [status, setStatus] = useState(null);
  const [records, setRecords] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [recordOffset, setRecordOffset] = useState(0);
  const [recordTotal, setRecordTotal] = useState(0);
  const [recordsLoading, setRecordsLoading] = useState(true);
  const [analyses, setAnalyses] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [session, setSession] = useState("");
  const [live, setLive] = useState(true);
  const [followLatest, setFollowLatest] = useState(true);
  const [preview, setPreview] = useState(null);
  const [batch, setBatch] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [batchError, setBatchError] = useState("");
  const [busy, setBusy] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [rateInput, setRateInput] = useState("");
  const [rates, setRates] = useState({});
  const [batchRates, setBatchRates] = useState(storedBatchRates);
  const [iqView, setIqView] = useState("overview");
  const [roi, setRoi] = useState({ start: "0", stop: "", low: "", high: "" });
  const uploadRef = useRef(null);
  const singleRateScopes = useRef({});
  const mounted = useRef(true);
  const refreshRequest = useRef(0);
  const currentQuery = useRef("");
  const queryKey = JSON.stringify([session, recordOffset]);
  currentQuery.current = queryKey;
  const previewKey = useRef("");
  const selectionVersion = useRef(0);
  const pinnedRecord = useRef(null);
  const listedRecord = records.find((record) => record.id === selectedId) || null;
  if (listedRecord) pinnedRecord.current = listedRecord;
  // A fixed selection may leave the moving list window while new files arrive.
  const chosen = listedRecord || (pinnedRecord.current?.id === selectedId ? pinnedRecord.current : null);
  const record = preview?.record?.id === selectedId ? { ...chosen, ...preview.record } : chosen;
  const iq = modeIQ(record);
  const rateScope = batchRateKey(status?.root, record?.session);
  const currentBatchRate = Number(batchRates[rateScope]) || 0;
  const rateChoice = resolveIQRate(chosen || record, rates[selectedId], currentBatchRate);
  const fs = rateChoice.rate;
  const iqOverview = iq && iqView === "overview";
  const bounds = frequencyBounds(preview?.spectrum, record, fs);
  const filtered = records;
  const pageInfo = recordPageInfo(recordTotal, recordOffset, RECORD_PAGE_SIZE);
  const selection = {
    record_id: selectedId,
    start_sample: Number(roi.start), stop_sample: Number(roi.stop),
    frequency_start_hz: Number(roi.low) * 1e6, frequency_stop_hz: Number(roi.high) * 1e6,
  };
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const changeRecordPage = useCallback((nextSession, nextOffset, follow = false) => {
    // Invalidate requests immediately, before React renders the next query.
    currentQuery.current = JSON.stringify([nextSession, nextOffset]);
    refreshRequest.current += 1;
    selectionVersion.current += 1;
    previewKey.current = "";
    setSession(nextSession); setRecordOffset(nextOffset); setFollowLatest(follow);
    setRecords([]); setRecordTotal(0); setSelectedId(null);
    pinnedRecord.current = null;
    setPreview(null); setBatch(null); setResult(null);
    setPreviewError(""); setBatchError(""); setError(""); setPreviewLoading(false);
    setRoi({ start: "0", stop: "", low: "", high: "" });
    setRecordsLoading(true);
  }, []);

  const refresh = useCallback(async () => {
    if (currentQuery.current !== queryKey) return;
    const request = ++refreshRequest.current;
    const current = () => mounted.current && request === refreshRequest.current && currentQuery.current === queryKey;
    try {
      const [state, list, batches] = await Promise.all([
        fetchWirelessStatus(),
        fetchWirelessRecords({ session, offset: recordOffset, limit: RECORD_PAGE_SIZE }),
        fetchWirelessSessions(),
      ]);
      if (!current()) return;
      setStatus(state); setSessions(batches.sessions || []);
      const pagination = recordPageInfo(list.total, recordOffset, RECORD_PAGE_SIZE);
      if (recordOffset > pagination.lastOffset) {
        changeRecordPage(session, pagination.lastOffset);
        return;
      }
      setRecords(list.records || []); setRecordTotal(pagination.total); setError("");
    } catch (err) { if (current()) setError(err.message); }
    finally { if (current()) setRecordsLoading(false); }
  }, [queryKey, session, recordOffset, changeRecordPage]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false, timer;
    async function tick() {
      await refresh();
      if (!cancelled && live) timer = setTimeout(tick, Math.max(1000, Number(status?.poll_interval_s || 2) * 1000));
    }
    tick();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [active, live, refresh, status?.poll_interval_s]);

  useEffect(() => {
    if (!active) return;
    let disposed = false;
    fetchWirelessAnalyses().then((data) => { if (!disposed) setAnalyses(data.analyses || []); }).catch(() => {});
    return () => { disposed = true; };
  }, [active]);

  useEffect(() => {
    if (!active || recordsLoading) return;
    if (!filtered.length) {
      if (!recordTotal && selectedId) {
        invalidateResult(); setSelectedId(null); setPreview(null); setBatch(null);
        pinnedRecord.current = null;
        previewKey.current = "";
        setRoi({ start: "0", stop: "", low: "", high: "" });
      }
      return;
    }
    if ((!selectedId || followLatest) && selectedId !== filtered[0].id) {
      invalidateResult();
      setSelectedId(filtered[0].id);
    }
  }, [active, filtered, followLatest, selectedId, recordsLoading, recordTotal]);

  useEffect(() => {
    if (!selectedId || !active) return;
    const requestKey = `${selectedId}:${fs}:${rateChoice.source}`;
    if (previewKey.current === requestKey) return;
    let disposed = false;
    previewKey.current = "";
    setPreview(null); setPreviewError(""); setPreviewLoading(true);
    previewWirelessRecord(selectedId, rateChoice.override ? { sample_rate_hz: rateChoice.override } : {})
      .then((data) => {
        if (disposed) return;
        invalidateResult();
        previewKey.current = requestKey;
        setPreview(data);
        const r = data.record;
        const b = frequencyBounds(data.spectrum, r, fs || r?.sample_rate_hz);
        setRoi({ start: "0", stop: String(r?.points || ""), low: b ? String(b[0] / 1e6) : "", high: b ? String(b[1] / 1e6) : "" });
      }).catch((err) => { if (!disposed) setPreviewError(err.message); })
      .finally(() => { if (!disposed) setPreviewLoading(false); });
    return () => { disposed = true; };
  }, [selectedId, active, fs, rateChoice.source]);

  const batchVersion = filtered.filter((r) => modeIQ(r) === iq && r.session === record?.session).map((r) => r.id).join("|");
  useEffect(() => {
    if (!active || !record || !record.session) { setBatch(null); return; }
    let disposed = false;
    setBatch(null); setBatchError("");
    const options = iq ? { mode: 1, ...(currentBatchRate > 0 ? { sample_rate_hz: currentBatchRate } : {}) } : {};
    fetchWirelessWaterfall(record.session, options).then((data) => { if (!disposed) setBatch(data); }).catch((err) => { if (!disposed) { setBatch(null); setBatchError(err.message); } });
    return () => { disposed = true; };
  }, [active, record?.session, iq, batchVersion, currentBatchRate]);

  function invalidateResult() { selectionVersion.current += 1; setResult(null); }
  function choose(id) { invalidateResult(); setFollowLatest(false); setSelectedId(id); if (iqOverview || modeIQ(records.find((r) => r.id === id))) setIqView("detail"); }
  function selectROI(values) {
    invalidateResult();
    setFollowLatest(false);
    setRoi((old) => ({
      start: values.start_sample != null ? String(values.start_sample) : old.start,
      stop: values.stop_sample != null ? String(values.stop_sample) : old.stop,
      low: values.frequency_start_hz != null ? String(Number((values.frequency_start_hz / 1e6).toFixed(9))) : old.low,
      high: values.frequency_stop_hz != null ? String(Number((values.frequency_stop_hz / 1e6).toFixed(9))) : old.high,
    }));
  }
  function updateRoi(key, value) { invalidateResult(); setFollowLatest(false); setRoi((old) => ({ ...old, [key]: value })); }
  function resetROI() {
    if (!bounds) return;
    selectROI({ start_sample: 0, stop_sample: record.points, frequency_start_hz: bounds[0], frequency_stop_hz: bounds[1] });
  }
  async function scan() {
    setBusy("scan"); setError("");
    try { await scanWirelessRecords(); await refresh(); } catch (err) { setError(err.message); }
    finally { setBusy(""); }
  }
  async function upload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy("upload"); setError("");
    try {
      const rate = rateInput.trim() ? Number(rateInput) * 1e6 : undefined;
      if (rate != null && (!Number.isFinite(rate) || rate <= 0)) throw new Error("采样率必须为大于 0 的数值");
      const response = await uploadWirelessRecord(file, rate);
      const item = response.record || response;
      if (item.id) changeRecordPage(item.session || "", 0);
      else await refresh();
    } catch (err) { setError(err.message); }
    finally { setBusy(""); event.target.value = ""; }
  }
  function applyRate() {
    const value = Number(rateInput) * 1e6;
    if (!selectedId || !Number.isFinite(value) || value <= 0) { setError("请先选择记录，并输入已确认的正数采样率（MS/s）"); return; }
    singleRateScopes.current[selectedId] = rateScope;
    invalidateResult(); setError(""); setFollowLatest(false); setRates((old) => ({ ...old, [selectedId]: value }));
  }
  function applyBatchRate(clear = false) {
    const value = Number(rateInput) * 1e6;
    if (!rateScope || (!clear && (!Number.isFinite(value) || value <= 0 || value > 1e10))) {
      setError("请先选择一个 IQ 批次，并填写有效采样率（MS/s）"); return;
    }
    const next = { ...batchRates };
    if (clear) delete next[rateScope]; else next[rateScope] = value;
    invalidateResult(); setError(""); setFollowLatest(false);
    setBatchRates(next);
    // Applying a batch setting replaces temporary per-record settings in that batch.
    setRates((old) => Object.fromEntries(Object.entries(old).filter(([id]) => singleRateScopes.current[id] !== rateScope)));
    try { localStorage.setItem(BATCH_RATE_STORAGE, JSON.stringify(next)); }
    catch { setError("批次设置已应用，但浏览器无法保存；刷新后需要重新应用。"); }
    setIqView("overview");
  }
  const validation = !record ? "请选择一条记录" : !preview ? "预览完成后可分析" :
    iqOverview ? "点击总览中的一行，进入单条 IQ 时频图后选择片段" :
    iq && !(fs > 0) ? "IQ 分析需要实际采样率，请在左侧填写并应用" :
    !roi.low.trim() || !roi.high.trim() || !Number.isFinite(selection.frequency_start_hz) || !Number.isFinite(selection.frequency_stop_hz) || selection.frequency_stop_hz <= selection.frequency_start_hz ? "终止频率须大于起始频率" :
    bounds && (selection.frequency_start_hz < bounds[0] - 1 || selection.frequency_stop_hz > bounds[1] + 1) ? "选区频率超出本条记录范围" :
    iq && (!roi.start.trim() || !roi.stop.trim() || !Number.isInteger(selection.start_sample) || !Number.isInteger(selection.stop_sample) || selection.start_sample < 0 || selection.stop_sample <= selection.start_sample || selection.stop_sample > record.points) ? "样本区间须为 0 ≤ 起点 < 终点 ≤ 点数的整数" : "";

  async function analyze() {
    if (validation) { setError(validation); return; }
    const id = selectedId;
    invalidateResult();
    const version = selectionVersion.current;
    setFollowLatest(false); setBusy("analyze"); setError("");
    try {
      const { record_id, ...request } = selection;
      const data = await analyzeWirelessRecord(id, { ...request, ...(fs > 0 && iq ? { sample_rate_hz: fs } : {}) });
      if (!mounted.current) return;
      if (version === selectionVersion.current) setResult(data);
      setAnalyses((old) => [data, ...old.filter((item) => item.id !== data.id)]);
    } catch (err) { if (mounted.current && version === selectionVersion.current) setError(err.message); }
    finally { if (mounted.current) setBusy(""); }
  }
  async function openAnalysis(id) {
    invalidateResult();
    const version = selectionVersion.current;
    setFollowLatest(false);
    setBusy("history"); setError("");
    try { const data = await fetchWirelessAnalysis(id); if (mounted.current && version === selectionVersion.current) setResult({ ...data, historical: true }); }
    catch (err) { if (mounted.current && version === selectionVersion.current) setError(err.message); }
    finally { if (mounted.current) setBusy(""); }
  }
  async function download(id) {
    setError("");
    try {
      const blob = await exportWirelessAnalysis(id);
      const url = URL.createObjectURL(blob), anchor = document.createElement("a");
      anchor.href = url; anchor.download = `wireless-analysis-${id}.json`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) { setError(err.message); }
  }
  const model = status?.model;
  const modelConfigured = ["configured", "ready", "ok"].includes(model?.status);
  const modelReady = modelConfigured && (model?.loaded || model?.status === "ready");
  const modelLabel = modelReady ? "协议模型已加载" : modelConfigured ? "协议模型已配置 · 首次分析加载" : model?.status === "unavailable" ? "协议模型不可用" : "协议模型待训练 / 挂载";
  const protocolView = protocolPresentation(result?.protocol);
  const measurements = result?.measurements;
  const waterfall = useMemo(() => {
    if (iq && !iqOverview) return preview?.waterfall;
    const value = batch?.waterfall;
    if (!value) return null;
    // Server rows are chronological. Display newest first while preserving row identity.
    return { ...value, power: value.power?.slice().reverse(), row_ids: value.row_ids?.slice().reverse(), frame_numbers: value.frame_numbers?.slice().reverse() };
  }, [iq, iqOverview, preview?.waterfall, batch?.waterfall]);

  return <main className="page wr-page">
    <header className="page-head">
      <div className="title-block"><span className="label">Live signals · Wireless recognition</span><h1>无线协议识别</h1><p className="lede">接收真实采集记录，在频谱与时频图中选择信号片段，测量参数并调用协议识别模型。</p></div>
      <div className="actions"><button className="btn ghost" onClick={onBack}><ArrowLeft size={14} />返回控制台</button></div>
    </header>
    <div className="wr-status-strip">
      <span><i className={status?.watching ? "wr-dot on" : "wr-dot"} />{status?.watching ? "接收目录监测中" : "目录监测未运行"}</span>
      <span>完整记录 <strong>{fmt(status?.record_count ?? records.length, 0)}</strong></span>
      <span>异常记录 <strong>{fmt(status?.invalid_count ?? 0, 0)}</strong></span>
      <span><Activity size={13} />{modelLabel}</span>
      <span className="wr-status-time">最近扫描 {timestamp(status?.last_scan_at)}</span>
    </div>
    {error && <div className="wr-error" role="alert">{error}</div>}
    {status?.last_error && <div className="wr-error" role="status">目录监测：{status.last_error}</div>}
    <div className="wr-layout">
      <aside className="card wr-source">
        <div className="wr-card-heading"><h2><Radio size={16} />数据接入</h2><span className="pill">SPEC</span></div>
        <div className="wr-source-body">
          <label className="wr-field"><span>服务器接收目录</span><code className="wr-root">{status?.root || "等待服务连接"}</code></label>
          <p className="wr-help">沿用采集端 SFTP 上传。完整文件入库后自动出现；上传中的临时文件不参与分析。</p>
          <div className="wr-button-row">
            <button className="btn" onClick={scan} disabled={!!busy}><RefreshCw size={13} />{busy === "scan" ? "扫描中" : "立即扫描"}</button>
            <button className="btn" onClick={() => setLive(!live)}>{live ? <Pause size={13} /> : <Play size={13} />}{live ? "暂停刷新" : "实时刷新"}</button>
          </div>
          <p className="wr-help">暂停刷新只冻结本页，采集端和服务器接收继续运行。</p>
          <label className="wr-field"><span>采集批次</span><select value={session} onChange={(e) => changeRecordPage(e.target.value, 0, true)}><option value="">全部批次</option>{[...new Set([...sessions, ...(session ? [session] : [])])].map((s) => <option key={s} value={s}>{s}</option>)}</select></label>
          <label className="wr-follow"><input type="checkbox" checked={followLatest} onChange={(e) => { if (e.target.checked && recordOffset > 0) changeRecordPage(session, 0, true); else setFollowLatest(e.target.checked); }} />跟随最新记录<span>共 {recordTotal} 条</span></label>
          <div className="wr-records" aria-label="采集记录列表">
            {!filtered.length && <div className="wr-empty-small">{recordsLoading ? "正在读取记录…" : "暂无完整记录。上传 SPEC 文件，或将采集端目标目录设置为上方接收目录。"}</div>}
            {filtered.map((item) => <button key={item.id} className={`wr-record ${item.id === selectedId ? "selected" : ""}`} onClick={() => choose(item.id)} title={`${item.session || ""}/${item.filename}`}><FileAudio size={15} /><span><strong>{item.filename || item.id}</strong><small>{modeIQ(item) ? "IQ" : "功率谱"} · {fmt(item.points, 0)} 点 · {timestamp(item.timestamp)}</small></span></button>)}
          </div>
          <nav className="wr-record-pagination" aria-label="采集记录分页">
            <button className="btn sm" disabled={recordsLoading || !pageInfo.hasPrevious} onClick={() => changeRecordPage(session, Math.max(0, recordOffset - RECORD_PAGE_SIZE))}>上一页</button>
            <span>{recordsLoading ? "读取中…" : `第 ${pageInfo.page} / ${pageInfo.pages} 页`}</span>
            <button className="btn sm" disabled={recordsLoading || !pageInfo.hasNext} onClick={() => changeRecordPage(session, recordOffset + RECORD_PAGE_SIZE)}>下一页</button>
          </nav>
          <div className="wr-import">
            <label className="wr-field"><span>实际采样率 / MS/s</span><input aria-label="实际采样率 MS/s" type="number" min="0" step="any" placeholder="填写实际值，不作默认假设" value={rateInput} onChange={(e) => setRateInput(e.target.value)} /></label>
            <div className="wr-button-row"><button className="btn" onClick={() => uploadRef.current?.click()} disabled={!!busy}><Upload size={13} />{busy === "upload" ? "上传中" : "上传 SPEC"}</button><button className="btn" disabled={!iq || !!busy || record?.sample_rate_source === "header"} onClick={applyRate}>应用到所选 IQ</button></div>
            <div className="wr-button-row"><button className="btn" disabled={!iq || !rateScope || !!busy} onClick={() => applyBatchRate()}>应用到当前批次</button>{currentBatchRate > 0 && <button className="btn ghost" onClick={() => applyBatchRate(true)}>清除批次设置</button>}</div>
            {rates[selectedId] && <button className="btn sm ghost" onClick={() => { invalidateResult(); setRates((old) => { const next = { ...old }; delete next[selectedId]; return next; }); }}>清除所选记录的手填采样率</button>}
            <input hidden ref={uploadRef} type="file" accept=".txt,.spec" onChange={upload} />
          </div>
        </div>
      </aside>
      <div className="wr-main">
        <section className="card wr-signals">
          <div className="wr-card-heading"><h2><Waves size={16} />频谱与信号片段</h2><span className={`wr-selection-state ${followLatest ? "following" : ""}`}>{followLatest ? "跟随最新" : "记录已固定 · 新文件不改变选区"}</span></div>
          <div className="wr-selected-record"><strong>{record?.filename || "尚未选择记录"}</strong><span>{record ? `${iq ? "IQ" : "功率谱"} · ${fmt(record.points, 0)} 点` : ""}</span><span>{iq && fs > 0 ? `Fs ${fmt(fs / 1e6, 6)} MS/s · ${fmt(record.points / fs * 1000, 6)} ms` : !iq && record ? `RBW ${fmt(record.rbw_hz / 1000)} kHz` : ""}</span></div>
          {iq && <div className="wr-display-options" role="group" aria-label="IQ 视图"><button className={`btn ${iqOverview ? "primary" : "ghost"}`} aria-pressed={iqOverview} onClick={() => setIqView("overview")}>批次瀑布总览</button><button className={`btn ${!iqOverview ? "primary" : "ghost"}`} aria-pressed={!iqOverview} onClick={() => setIqView("detail")}>单条 IQ 时频图</button><span>总览最多最近 128 条同配置记录；点击一行进入细节</span></div>}
          {previewError && <div className="wr-error" role="alert">{previewError}</div>}
          {record && iq && !(fs > 0) && <div className="wr-error" role="status">此 IQ 记录未保存采样率。请在左侧填写采集时实际的采样率并应用，之后才能计算频率、时间坐标和执行识别。</div>}
          {previewLoading ? <div className="wr-chart-empty">正在读取真实记录并计算预览…</div> : <>
            <SpectrumPlot key={`spectrum-${selectedId}-${fs}`} spectrum={preview?.spectrum} waterfall={!iq ? waterfall : null} bounds={bounds} selection={selection} onSelect={selectROI} onInteraction={() => setFollowLatest(false)} />
            <div className="wr-chart-section-title">{iqOverview ? "IQ 批次 / 平均谱瀑布" : iq ? "IQ 时频图 / STFT" : "采集批次 / 逐帧瀑布"}<span>{iq && !iqOverview ? "单文件内时间轴" : "记录序号轴 · 最新在上"}</span></div>
            <WaterfallPlot key={`waterfall-${selectedId}-${fs}-${iqView}`} data={waterfall} iq={iq && !iqOverview} sampleRate={fs} points={record?.points || 0} selection={selection} onSelect={selectROI} onRowSelect={choose} onInteraction={() => setFollowLatest(false)} />
          </>}
          {batchError && <div className="wr-error" role="status">瀑布图：{batchError}</div>}
          {(!iq || iqOverview) && waterfall?.row_ids?.length && !waterfall.row_ids.includes(selectedId) ? <p className="wr-help" style={{ padding: "0 16px" }}>瀑布图显示该批次最近一组同配置记录；当前选中的旧记录不在此图中，上方曲线仍对应所选记录。</p> : null}
        </section>
        <section className="card wr-analysis-control">
          <div className="wr-card-heading"><h2><ScanLine size={16} />选区与分析</h2><button className="btn sm" onClick={resetROI} disabled={!preview}>恢复整条记录</button></div>
          <div className="wr-roi-fields">
            <label className="wr-field"><span>起始频率 / MHz</span><input type="number" step="any" value={roi.low} onChange={(e) => updateRoi("low", e.target.value)} disabled={!preview} /></label>
            <label className="wr-field"><span>终止频率 / MHz</span><input type="number" step="any" value={roi.high} onChange={(e) => updateRoi("high", e.target.value)} disabled={!preview} /></label>
            <label className="wr-field"><span>起始样本（含）</span><input type="number" min="0" step="1" value={roi.start} onChange={(e) => updateRoi("start", e.target.value)} disabled={!iq || !preview} /></label>
            <label className="wr-field"><span>终止样本（不含）</span><input type="number" min="1" max={record?.points || undefined} step="1" value={roi.stop} onChange={(e) => updateRoi("stop", e.target.value)} disabled={!iq || !preview} /></label>
          </div>
          <div className="wr-analysis-footer"><div><p>{iq ? fs > 0 ? `所选 ${fmt(selection.stop_sample - selection.start_sample, 0)} 对 IQ · ${fmt((selection.stop_sample - selection.start_sample) / fs * 1000, 6)} ms` : "IQ 采样率尚未确认" : "功率谱支持参数测量；协议模型需要 IQ 记录"}</p><small>{validation || (modelConfigured && iq ? "将使用当前协议模型分析所选原始 IQ" : "当前可测量参数；协议结果将在模型训练并挂载后提供")}</small></div><button className="btn primary" onClick={analyze} disabled={!!busy || !!validation}><Play size={14} />{busy === "analyze" ? "分析中…" : "分析所选片段"}</button></div>
        </section>
        <section className="card wr-result">
          <div className="wr-card-heading"><h2>识别结果与参数</h2>{result && <button className="btn sm" onClick={() => download(result.id)}><Download size={13} />导出 JSON</button>}</div>
          {result ? <>
            <div className="wr-result-meta"><span>{result.historical ? "历史分析" : "当前选区分析"}</span><span>记录 {result.source?.filename || result.record_id}</span><span>{timestamp(result.created_at)}</span><span>耗时 {fmt(typeof result.timing_ms === "number" ? result.timing_ms : result.timing_ms?.total, 1)} ms</span></div>
            <div className="wr-result-meta"><span>结果选区：{mhz(result.selection?.frequency_start_hz)} ～ {mhz(result.selection?.frequency_stop_hz)}</span><span>样本 [{fmt(result.selection?.start_sample, 0)}, {fmt(result.selection?.stop_sample, 0)})</span>{result.historical && <span>历史结果保留原分析选区，不代表上方当前选区</span>}</div>
            <div className="wr-metrics"><div><span>中心频率</span><strong>{mhz(measurements?.center_frequency_hz)}</strong></div><div><span>占用带宽</span><strong>{mhz(measurements?.bandwidth_hz)}</strong></div><div><span>协议种类</span><strong className="wr-protocol-value" data-tone={protocolView.tone}>{protocolView.label}</strong></div><div><span>模型置信度</span><strong className="wr-protocol-value" data-tone={protocolView.tone}>{protocolView.confidenceText}</strong></div></div>
            {protocolView.reason && <p className="wr-result-reason" data-tone={protocolView.tone} role="status">{protocolView.reason}</p>}
          </> : <div className="wr-empty-small">尚未分析。先固定一条记录，在图上或表单中选择片段，然后点击“分析所选片段”。</div>}
        </section>
      </div>
    </div>
    <div className="wr-bottom-grid">
      <section className="card wr-history"><div className="wr-card-heading"><h2>分析历史</h2><span>{analyses.length} 条</span></div><div className="wr-history-table">{analyses.length ? <table><thead><tr><th>时间</th><th>记录</th><th>协议 / 状态</th><th>结果</th></tr></thead><tbody>{analyses.slice(0, 30).map((item) => { const itemProtocol = protocolPresentation(item.protocol); return <tr key={item.id}><td>{timestamp(item.created_at)}</td><td title={item.record_id}>{item.record_id?.slice(0, 14) || "—"}</td><td data-tone={itemProtocol.tone}>{itemProtocol.label}</td><td><button className="btn sm" disabled={!!busy} onClick={() => openAnalysis(item.id)}>查看</button><button className="btn sm ghost" onClick={() => download(item.id)} aria-label={`导出分析 ${item.id}`}><Download size={13} /></button></td></tr>; })}</tbody></table> : <div className="wr-empty-small">完成一次分析后，结果会保存在服务器并显示于此。</div>}</div></section>
    </div>
  </main>;
}
