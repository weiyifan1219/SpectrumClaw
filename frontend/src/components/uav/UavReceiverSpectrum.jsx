import { useEffect, useRef, useState } from "react";
import { Activity, Pause, Play, Radio, Waves } from "lucide-react";
import { fetchUavSpectrumFrame } from "../../lib/api.js";

const SAMPLE_RATE_HZ = 62_500_000;
const CENTER_HZ = 2_412_000_000;
const WATERFALL_BINS = 256;
const WATERFALL_ROWS = 112;
const DB_MIN = -132;
const DB_MAX = -35;
const STOPS = [[7, 16, 39], [21, 65, 133], [18, 159, 204], [37, 211, 165], [231, 211, 77], [246, 117, 49]];

function colorAt(dbm) {
  const position = Math.max(0, Math.min(1, (dbm - DB_MIN) / (DB_MAX - DB_MIN))) * (STOPS.length - 1);
  const index = Math.min(STOPS.length - 2, Math.floor(position));
  return STOPS[index].map((value, channel) => Math.round(value + (STOPS[index + 1][channel] - value) * (position - index)));
}

function spectrumTrace(values) {
  return values.map((value, index) => {
    const height = Math.max(0, Math.min(100, (value - DB_MIN) / (DB_MAX - DB_MIN) * 100));
    return `${(index / Math.max(1, values.length - 1) * 100).toFixed(2)},${(100 - height).toFixed(2)}`;
  }).join(" ");
}

function WaterfallCanvas({ frame, resetKey }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    canvas.width = WATERFALL_BINS;
    canvas.height = WATERFALL_ROWS;
    canvas.getContext("2d").fillStyle = "#071027";
    canvas.getContext("2d").fillRect(0, 0, WATERFALL_BINS, WATERFALL_ROWS);
  }, [resetKey]);
  useEffect(() => {
    const values = frame?.spectrum?.bin_power_dbm;
    const canvas = ref.current;
    if (!canvas || values?.length !== WATERFALL_BINS) return;
    const context = canvas.getContext("2d");
    const previous = context.getImageData(0, 0, WATERFALL_BINS, WATERFALL_ROWS - 1);
    context.putImageData(previous, 0, 1);
    const line = context.createImageData(WATERFALL_BINS, 1);
    values.forEach((value, column) => {
      const color = colorAt(value);
      line.data.set([color[0], color[1], color[2], 255], column * 4);
    });
    context.putImageData(line, 0, 0);
  }, [frame]);
  return <canvas ref={ref} role="img" aria-label="实时接收功率谱瀑布图；顶部为最新采样帧" />;
}

function mhz(value) { return `${(value / 1e6).toFixed(2)} MHz`; }

export default function UavReceiverSpectrum({ runtimeState, active = true, selectedTransmitter = "all", onSelectTransmitter, onFrame }) {
  const [targetId, setTargetId] = useState("tx-01");
  const [sampleCount, setSampleCount] = useState(1024);
  const [bandwidthHz, setBandwidthHz] = useState(40_000_000);
  const [paused, setPaused] = useState(false);
  const [frame, setFrame] = useState(null);
  const [framesSeen, setFramesSeen] = useState(0);
  const [error, setError] = useState("");
  const [documentVisible, setDocumentVisible] = useState(() => document.visibilityState === "visible");
  const running = active && documentVisible && runtimeState === "running" && !paused;
  const resetKey = `${targetId}:${sampleCount}:${bandwidthHz}`;
  const spanStart = CENTER_HZ - SAMPLE_RATE_HZ / 2;
  const spanEnd = CENTER_HZ + SAMPLE_RATE_HZ / 2;
  const bandLeft = (SAMPLE_RATE_HZ - bandwidthHz) / (2 * SAMPLE_RATE_HZ) * 100;
  const bandWidth = bandwidthHz / SAMPLE_RATE_HZ * 100;
  const emitters = frame?.emitters || [];
  const values = frame?.spectrum?.bin_power_dbm || [];
  const tracePoints = spectrumTrace(values);

  useEffect(() => {
    const update = () => setDocumentVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  useEffect(() => {
    if (selectedTransmitter !== "all" && selectedTransmitter !== targetId) setTargetId(selectedTransmitter);
  }, [selectedTransmitter, targetId]);

  function chooseTarget(id) {
    setTargetId(id);
    onSelectTransmitter?.(id);
  }

  useEffect(() => {
    setFrame(null);
    setFramesSeen(0);
  }, [resetKey]);

  useEffect(() => {
    if (!running) return undefined;
    let stopped = false;
    let timer;
    async function tick() {
      try {
        const next = await fetchUavSpectrumFrame({
          target_id: targetId,
          sample_rate_hz: SAMPLE_RATE_HZ,
          sample_count: sampleCount,
          channel_bandwidth_hz: bandwidthHz,
          noise_figure_db: 6,
        });
        if (stopped) return;
        setFrame(next);
        onFrame?.(next);
        setFramesSeen((count) => count + 1);
        setError("");
        timer = setTimeout(tick, 500);
      } catch (reason) {
        if (stopped) return;
        setError(reason.message || "接收帧处理失败");
        timer = setTimeout(tick, 2000);
      }
    }
    void tick();
    return () => { stopped = true; clearTimeout(timer); };
  }, [running, targetId, sampleCount, bandwidthHz, onFrame]);

  const stateLabel = runtimeState !== "running" ? "等待仿真" : paused || !active || !documentVisible ? "已暂停" : error ? "重连中" : frame?.current ? "实时接收" : "等待信道更新";
  return <section className="card uav-receiver-panel uav-live-receiver" aria-label="实时机载频谱接收与协议先验">
    <header className="uav-receiver-head">
      <div><span className="eyebrow">AIRBORNE RECEIVER · LIVE SPECTRUM</span><h2><Radio size={19} /> 实时频谱接收</h2><p>协议识别中的采集片段作为发射源回放，经 Sionna 信道传播；地面站持续绘制接收功率谱。</p></div>
      <span className="uav-spectrum-compute-state" data-state={running && frame?.current ? "current" : "idle"}><i className={running ? "uav-live-dot" : ""} /> {stateLabel}</span>
    </header>

    <div className="uav-receiver-controls">
      <label>观察目标<select value={targetId} onChange={(event) => chooseTarget(event.target.value)}>{["tx-01", "tx-02", "tx-03"].map((id) => <option key={id} value={id}>{id}</option>)}</select></label>
      <label>中心频率<input readOnly value="2412 MHz" /></label>
      <label>采样率<input readOnly value="62.5 MS/s" /></label>
      <label>FFT 点数<select value={sampleCount} onChange={(event) => setSampleCount(Number(event.target.value))}>{[1024, 2048, 4096].map((count) => <option key={count} value={count}>{count} 点</option>)}</select></label>
      <label>接收带宽<select value={bandwidthHz} onChange={(event) => setBandwidthHz(Number(event.target.value))}>{[30, 40].map((width) => <option key={width} value={width * 1e6}>{width} MHz</option>)}</select></label>
      <button type="button" onClick={() => setPaused((value) => !value)} disabled={runtimeState !== "running"}>{paused ? <Play size={13} /> : <Pause size={13} />} {paused ? "继续接收" : "暂停接收"}</button>
    </div>

    <div className="uav-receiver-band">
      <div className="uav-receiver-band-title"><strong>瞬时接收窗口</strong><span>{mhz(spanStart)} – {mhz(spanEnd)} · 单帧 {(sampleCount / SAMPLE_RATE_HZ * 1e6).toFixed(1)} μs · 约 2 帧/秒</span></div>
      <div className="uav-receiver-band-track"><i className="uav-receiver-band-channel" style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }} /><i className="uav-receiver-band-center" />{emitters.map((emitter) => <span key={emitter.id} className="uav-receiver-source-marker" style={{ left: `${(emitter.recorded_center_frequency_hz - spanStart) / SAMPLE_RATE_HZ * 100}%` }} title={`${emitter.id} · ${emitter.protocol_prior} · ${mhz(emitter.recorded_center_frequency_hz)}`} />)}</div>
      <div className="uav-receiver-band-ticks"><span>{mhz(spanStart)}</span><strong>接收带宽 {bandwidthHz / 1e6} MHz</strong><span>{mhz(spanEnd)}</span></div>
    </div>

    <div className="uav-receiver-source-priors" aria-label="来自无线协议识别的发射源先验">
      {emitters.length ? emitters.map((emitter) => <button type="button" key={emitter.id} className={targetId === emitter.id ? "selected" : ""} aria-pressed={targetId === emitter.id} onClick={() => chooseTarget(emitter.id)}><span>{emitter.id} · {emitter.protocol_prior}</span><strong>{(emitter.prior_confidence * 100).toFixed(1)}%</strong><small>{mhz(emitter.recorded_center_frequency_hz)} · 记录 {emitter.record_id.slice(0, 8)}</small></button>) : <div className="uav-receiver-source-wait">等待协议识别记录与 Sionna 信道就绪…</div>}
    </div>

    {error && <p className="uav-receiver-error">{error}</p>}
    <div className="uav-receiver-metrics">
      <div><small>RSSI · 混合接收功率</small><strong>{frame ? `${frame.metrics.rssi_dbm.toFixed(1)} dBm` : "—"}</strong></div>
      <div><small>SINR · {targetId} 仿真真值</small><strong>{frame ? `${frame.metrics.sinr_db.toFixed(1)} dB` : "—"}</strong></div>
      <div><small>FFT 频点间隔</small><strong>{(SAMPLE_RATE_HZ / sampleCount / 1000).toFixed(2)} kHz</strong></div>
      <div><small>已接收帧 / 当前 CIR</small><strong>{framesSeen} <span className="uav-receiver-metric-sep">/</span> {frame?.current ? "当前" : "待更新"}</strong></div>
    </div>

    <div className="uav-live-waterfall-wrap">
      <div className="uav-live-plot-head"><span><Waves size={15} /> 实时频谱瀑布图</span><small>上方最新 · 每行一帧 · 浏览器只保留最近 {WATERFALL_ROWS} 行</small></div>
      <div className="uav-live-waterfall"><WaterfallCanvas frame={frame} resetKey={resetKey} />{!frame && <div className="uav-live-waterfall-empty">{runtimeState === "running" ? "正在接收首帧…" : "启动低空仿真后显示实时频谱"}</div>}</div>
      <div className="uav-live-axis"><span>{mhz(spanStart)}</span><span>2412 MHz</span><span>{mhz(spanEnd)}</span></div>
      <div className="uav-live-scale"><span>{DB_MIN} dBm/频点</span><i /><span>{DB_MAX} dBm/频点</span></div>
    </div>

    <div className="uav-live-spectrum-wrap">
      <div className="uav-live-plot-head"><span><Activity size={15} /> 当前接收功率谱</span><small>{values.length ? `${values.length} 个显示频点 · 原始 ${frame.spectrum.source_fft_bins} 点 FFT` : "等待首帧"}</small></div>
      <div className="uav-live-spectrum-chart">
        <div className="uav-live-power-axis"><span>-35</span><span>-85</span><span>-132</span></div>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="当前接收功率谱">
          <defs><linearGradient id="uav-spectrum-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#f7b548" stopOpacity=".32" /><stop offset="100%" stopColor="#f7b548" stopOpacity="0" /></linearGradient></defs>
          {values.length > 0 && <polygon points={`0,100 ${tracePoints} 100,100`} fill="url(#uav-spectrum-fill)" />}
          {emitters.map((emitter) => <line key={emitter.id} className="uav-live-source-line" x1={(emitter.recorded_center_frequency_hz - spanStart) / SAMPLE_RATE_HZ * 100} x2={(emitter.recorded_center_frequency_hz - spanStart) / SAMPLE_RATE_HZ * 100} y1="0" y2="100" />)}
          <polyline points={tracePoints} />
        </svg>
      </div>
      <div className="uav-live-spectrum-axis"><span>{mhz(spanStart)}</span><span>2412 MHz</span><span>{mhz(spanEnd)}</span></div>
    </div>
  </section>;
}
