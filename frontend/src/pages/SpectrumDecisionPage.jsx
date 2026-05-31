import { useCallback, useState } from "react";
import {
  Activity,
  ArrowLeft,
  BarChart3,
  Brain,
  CheckCircle2,
  Gauge,
  Loader2,
  MapPin,
  Play,
  Radio,
  RefreshCw,
  Sliders,
  Users,
  Zap,
} from "lucide-react";

const BASE = `http://${window.location.hostname}:8230`;

async function runAllocation(params) {
  const resp = await fetch(`${BASE}/api/spectrum-decision/allocate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw new Error(detail || `Allocation failed (${resp.status})`);
  }
  return resp.json();
}

const ENV_META = {
  urban: { label: "城市密集区", desc: "高楼密集，NLOS为主，高损耗", icon: "🏙️" },
  suburban: { label: "郊区", desc: "中低层建筑，LOS/NLOS混合", icon: "🏘️" },
  rural: { label: "乡村开阔区", desc: "低损耗，LOS占比高", icon: "🌾" },
};

const SERVICE_COLORS = { eMBB: "var(--acc-cyan)", URLLC: "var(--acc-violet)", mMTC: "var(--acc-amber)" };
const SERVICE_BG = {
  eMBB: "oklch(0.84 0.14 195 / 0.12)",
  URLLC: "oklch(0.74 0.15 295 / 0.12)",
  mMTC: "oklch(0.84 0.14 75 / 0.12)",
};

const MIX_PRESETS = [
  { id: "default", label: "标准配比 (60% eMBB)", mix: { eMBB: 0.6, URLLC: 0.3, mMTC: 0.1 } },
  { id: "embb_heavy", label: "eMBB 为主 (80%)", mix: { eMBB: 0.8, URLLC: 0.15, mMTC: 0.05 } },
  { id: "urllc_heavy", label: "URLLC 为主 (70%)", mix: { eMBB: 0.2, URLLC: 0.7, mMTC: 0.1 } },
  { id: "balanced", label: "均衡配比", mix: { eMBB: 0.4, URLLC: 0.3, mMTC: 0.3 } },
];

export default function SpectrumDecisionPage({ onBack }) {
  const [mode, setMode] = useState("manual"); // "manual" | "agent"
  const [params, setParams] = useState({
    user_request: "",
    num_users: 10,
    total_bandwidth_mhz: 100,
    environment: "urban",
    frequency_mhz: 3500,
    seed: 0,
    service_mix_id: "default",
  });
  const [status, setStatus] = useState("idle");
  const [result, setResult] = useState(null);

  const handleRun = useCallback(async () => {
    setStatus("running");
    setResult(null);
    try {
      const mixPreset = MIX_PRESETS.find((m) => m.id === params.service_mix_id);
      const data = await runAllocation({
        num_users: params.num_users,
        total_bandwidth_mhz: params.total_bandwidth_mhz,
        environment: params.environment,
        frequency_mhz: params.frequency_mhz,
        seed: params.seed || 0,
        service_mix: params.service_mix_id === "default" ? null : mixPreset?.mix,
        use_agent: mode === "agent",
        user_request: mode === "agent" ? params.user_request : "",
      });
      setResult(data);
      setStatus("success");
    } catch (err) {
      setResult({ error: err.message });
      setStatus("error");
    }
  }, [params, mode]);

  const set = (key, val) => setParams((p) => ({ ...p, [key]: val }));

  return (
    <div className="page fp-page">
      <div className="page-head compact">
        <div className="title-block">
          <span className="label">Skill · Spectrum Decision</span>
          <h1>频谱决策 · 资源分配</h1>
          <p className="lede">
            基于比例公平优化的多用户频谱资源分配。支持 eMBB / URLLC / mMTC 三类业务切片，
            结合 3GPP CQI 信道模型与 SLSQP 约束优化。可接入智能体进行自然语言意图理解与结果分析。
          </p>
        </div>
        <div className="actions">
          {onBack && <button className="btn ghost" onClick={onBack}><ArrowLeft size={14} /> 返回</button>}
          <button className="btn primary" onClick={handleRun} disabled={status === "running"}>
            {status === "running" ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
            {status === "running" ? "优化中…" : "运行分配"}
          </button>
        </div>
      </div>

      <div className="fp-body">
        {/* left: params */}
        <aside className="fp-left card">
          <div className="card-head">
            <span className="title"><Sliders size={14} /> 参数配置</span>
          </div>
          <div className="card-body">
            {/* mode toggle */}
            <div className="fp-segment" style={{ marginBottom: 12 }}>
              <button className={mode === "manual" ? "on" : ""} onClick={() => setMode("manual")}>
                手动参数
              </button>
              <button className={mode === "agent" ? "on" : ""} onClick={() => setMode("agent")}>
                <Brain size={11} style={{ marginRight: 2 }} /> 智能体
              </button>
            </div>

            <div className="fp-form">
              {mode === "agent" && (
                <div className="fp-field">
                  <label className="fp-label">需求描述 <span className="fp-required">*</span></label>
                  <textarea className="fp-textarea" rows={3}
                    placeholder="用自然语言描述需求。例：「某大型体育场开幕，预计 5000 人同时使用手机，需要为 15 个 5G 小基站分配 200MHz 频谱，优先保障视频直播用户的体验」"
                    value={params.user_request}
                    onChange={(e) => set("user_request", e.target.value)}
                    disabled={status === "running"} />
                </div>
              )}

              <div className="fp-row-2">
                <div className="fp-field">
                  <label className="fp-label">用户数量</label>
                  <input className="fp-input" type="number" min={1} max={50} value={params.num_users}
                    onChange={(e) => set("num_users", Number(e.target.value))} disabled={status === "running"} />
                </div>
                <div className="fp-field">
                  <label className="fp-label">总带宽 (MHz)</label>
                  <input className="fp-input" type="number" min={10} max={1000} value={params.total_bandwidth_mhz}
                    onChange={(e) => set("total_bandwidth_mhz", Number(e.target.value))} disabled={status === "running"} />
                </div>
              </div>

              <div className="fp-field">
                <label className="fp-label"><MapPin size={10} /> 信道环境</label>
                <select className="fp-select" value={params.environment}
                  onChange={(e) => set("environment", e.target.value)} disabled={status === "running"}>
                  {Object.entries(ENV_META).map(([k, v]) => (
                    <option key={k} value={k}>{v.label} — {v.desc}</option>
                  ))}
                </select>
              </div>

              <div className="fp-row-2">
                <div className="fp-field">
                  <label className="fp-label">载波频率 (MHz)</label>
                  <input className="fp-input" type="number" value={params.frequency_mhz}
                    onChange={(e) => set("frequency_mhz", Number(e.target.value))} disabled={status === "running"} />
                </div>
                <div className="fp-field">
                  <label className="fp-label">随机种子</label>
                  <input className="fp-input" type="number" value={params.seed}
                    onChange={(e) => set("seed", Number(e.target.value))} disabled={status === "running"} />
                </div>
              </div>

              <div className="fp-field">
                <label className="fp-label">业务配比</label>
                <select className="fp-select" value={params.service_mix_id}
                  onChange={(e) => set("service_mix_id", e.target.value)} disabled={status === "running"}>
                  {MIX_PRESETS.map((m) => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </aside>

        {/* center: results */}
        <main className="fp-center card">
          <div className="card-head">
            <span className="title"><BarChart3 size={14} /> 分配结果</span>
            {result && !result.error && (
              <span className="pill" data-tone={result.fairness > 0.7 ? "ok" : "warn"}>
                <span className="dot" /> 公平性 {(result.fairness * 100).toFixed(1)}%
              </span>
            )}
          </div>
          <div className="fp-center-body">
            {status === "idle" && (
              <div className="fp-result-empty">
                <div className="fp-empty-icon"><Gauge size={28} /></div>
                <h3>等待运行分配</h3>
                <p>配置参数后点击"运行分配"启动 CQI-Shannon 建模与 SLSQP 优化。可使用"智能体"模式输入自然语言需求。</p>
              </div>
            )}
            {status === "running" && (
              <div className="fp-result-empty">
                <Loader2 size={28} className="spin" style={{ color: "var(--accent)" }} />
                <h3>优化中…</h3>
                <p>{mode === "agent" ? "智能体正在理解需求、生成场景并运行优化…" : "生成信道数据、运行比例公平优化…"}</p>
              </div>
            )}
            {status === "error" && (
              <div className="fp-result-empty">
                <div className="fp-empty-icon" style={{ color: "var(--err)" }}><Zap size={28} /></div>
                <h3>运行失败</h3>
                <p>{result?.error || "未知错误"}</p>
              </div>
            )}
            {status === "success" && result && <SDResult result={result} />}
          </div>
          {status === "error" && (
            <div className="fp-center-foot">
              <button className="btn" onClick={handleRun}><RefreshCw size={13} /> 重试</button>
            </div>
          )}
        </main>

        {/* right: metrics + agent explanation */}
        <aside className="fp-right card">
          <div className="card-head">
            <span className="title"><Activity size={14} /> 指标与分析</span>
          </div>
          <div className="fp-right-body">
            {result && !result.error ? (
              <>
                {result.agent_explanation && (
                  <SDExplanation text={result.agent_explanation} parsed={result.parsed_intent} />
                )}
                <SDMetrics result={result} />
              </>
            ) : (
              <div className="fp-cite-empty">
                <BarChart3 size={24} />
                <p>运行分配后，指标与智能体分析将在此显示</p>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

/* ── sub-components ── */

function SDExplanation({ text, parsed }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div className="fp-cite-section-label" style={{ color: "var(--acc-violet)" }}>
        <Brain size={11} /> 智能体分析
      </div>
      {parsed && Object.keys(parsed).length > 0 && (
        <div className="fp-debug" style={{ marginBottom: 8 }}>
          <details className="fp-debug">
            <summary><CheckCircle2 size={10} /> 意图识别</summary>
            <div className="fp-debug-body">
              {Object.entries(parsed).map(([k, v]) => (
                <div key={k} className="fp-debug-row">
                  <span className="fp-debug-key">{k}</span>
                  <span className="fp-debug-val">{String(v)}</span>
                </div>
              ))}
            </div>
          </details>
        </div>
      )}
      <p style={{ fontSize: 12, lineHeight: 1.65, color: "var(--ink-2)", margin: "4px 0 0" }}>{text}</p>
    </div>
  );
}

function SDResult({ result }) {
  const allocs = result.allocations || [];
  if (allocs.length === 0) return <p style={{ color: "var(--muted)", padding: 16 }}>无分配结果</p>;

  const maxBw = Math.max(...allocs.map((a) => a.bandwidth_mhz), 1);

  return (
    <div className="sd-result">
      {/* summary */}
      <div className="sd-summary">
        <div className="sd-summary-item">
          <span className="sd-sum-label">总吞吐量</span>
          <span className="sd-sum-value">{result.total_throughput_mbps} Mbps</span>
        </div>
        <div className="sd-summary-item">
          <span className="sd-sum-label">公平指数</span>
          <span className="sd-sum-value mono">{(result.fairness * 100).toFixed(1)}%</span>
        </div>
        <div className="sd-summary-item">
          <span className="sd-sum-label">场景</span>
          <span className="sd-sum-value" style={{ fontSize: 13 }}>{ENV_META[result.environment]?.label || result.environment}</span>
        </div>
      </div>

      {/* allocation table */}
      <div className="sd-table-wrap">
        <table className="sd-table">
          <thead>
            <tr>
              <th>用户</th>
              <th>业务</th>
              <th>CQI</th>
              <th>SNR</th>
              <th>距离</th>
              <th>LOS</th>
              <th>带宽</th>
              <th>速率</th>
              <th>分配</th>
            </tr>
          </thead>
          <tbody>
            {allocs.map((a) => (
              <tr key={a.user_index}>
                <td className="mono" style={{ fontSize: 10 }}>{a.user_id || `#${(a.user_index || 0) + 1}`}</td>
                <td><ServiceBadge service={a.service} /></td>
                <td className="mono">{a.cqi}</td>
                <td className="mono" style={{ fontSize: 10, color: (a.snr_db || 0) > 10 ? "var(--ok)" : "var(--warn)" }}>{a.snr_db ?? "-"} dB</td>
                <td className="mono" style={{ fontSize: 10 }}>{a.distance_m ?? "-"}m</td>
                <td className="mono" style={{ fontSize: 10, color: a.los ? "var(--ok)" : "var(--muted)" }}>{a.los ? "✓" : "—"}</td>
                <td className="mono">{a.bandwidth_mhz} MHz</td>
                <td className="mono">{a.rate_mbps} Mbps</td>
                <td><div className="sd-bar-cell"><div className="sd-bar-bw" style={{ width: `${(a.bandwidth_mhz / maxBw) * 100}%`, background: SERVICE_COLORS[a.service] || "var(--accent)" }} /></div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ServiceBadge({ service }) {
  return (
    <span style={{
      display: "inline-block", padding: "1px 8px", borderRadius: 999,
      fontSize: 10, fontWeight: 600,
      background: SERVICE_BG[service] || "var(--accent-soft)",
      color: SERVICE_COLORS[service] || "var(--accent)",
    }}>{service}</span>
  );
}

function SDMetrics({ result }) {
  const allocs = result.allocations || [];
  const byService = {};
  let totalCqi = 0, losCount = 0;
  for (const a of allocs) {
    byService[a.service] = byService[a.service] || { count: 0, total_bw: 0, total_rate: 0, avg_snr: 0, snr_sum: 0 };
    byService[a.service].count++;
    byService[a.service].total_bw += a.bandwidth_mhz;
    byService[a.service].total_rate += a.rate_mbps;
    byService[a.service].snr_sum += (a.snr_db || 0);
    totalCqi += a.cqi;
    if (a.los) losCount++;
  }
  for (const s of Object.keys(byService)) {
    byService[s].avg_snr = byService[s].snr_sum / byService[s].count;
  }

  return (
    <div>
      <div className="fp-cite-section-label">业务分布</div>
      {Object.entries(byService).map(([svc, stats]) => (
        <div key={svc} className="sd-metric-card">
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 600 }}>
              <ServiceBadge service={svc} />
              <span style={{ marginLeft: 6, color: "var(--muted)", fontSize: 11 }}>{stats.count} 用户</span>
            </span>
            <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>{stats.total_rate.toFixed(0)} Mbps</span>
          </div>
          <div className="fp-cite-score-bar" style={{ height: 6, borderRadius: 3 }}>
            <div className="fp-cite-score-fill" style={{ width: `${(stats.total_bw / result.total_bandwidth_mhz) * 100}%`, background: SERVICE_COLORS[svc] }} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 3 }}>
            <span className="mono" style={{ fontSize: 10, color: "var(--muted-2)" }}>{stats.total_bw.toFixed(1)} MHz</span>
            <span className="mono" style={{ fontSize: 10, color: "var(--muted-2)" }}>SNR avg: {stats.avg_snr.toFixed(1)} dB</span>
          </div>
        </div>
      ))}

      <div className="fp-cite-section-label" style={{ marginTop: 16 }}>CQI 分布</div>
      <div className="sd-cqi-dist">
        {allocs.map((a) => (
          <div key={a.user_index} className="sd-cqi-bar" title={`${a.user_id}: CQI ${a.cqi}, SNR ${a.snr_db}dB, ${a.distance_m}m`}
            style={{ height: `${(a.cqi / 15) * 40 + 8}px`, background: SERVICE_COLORS[a.service] || "var(--accent)" }} />
        ))}
      </div>

      <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
        <div className="mem-ref-row">
          <span className="rr-label">Jain 公平指数</span>
          <span className="rr-value" style={{ color: result.fairness > 0.7 ? "var(--ok)" : "var(--warn)", fontWeight: 700 }}>
            {result.fairness.toFixed(4)}
          </span>
        </div>
        <div className="mem-ref-row">
          <span className="rr-label">平均 CQI</span>
          <span className="rr-value">{(totalCqi / allocs.length).toFixed(1)}</span>
        </div>
        <div className="mem-ref-row">
          <span className="rr-label">LOS 比例</span>
          <span className="rr-value">{((losCount / allocs.length) * 100).toFixed(0)}%</span>
        </div>
        <div className="mem-ref-row">
          <span className="rr-label">载波频率</span>
          <span className="rr-value">{result.frequency_mhz || 3500} MHz</span>
        </div>
      </div>
    </div>
  );
}
