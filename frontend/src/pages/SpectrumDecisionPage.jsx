import { useCallback, useState } from "react";
import {
  Activity,
  ArrowLeft,
  BarChart3,
  Gauge,
  Loader2,
  Play,
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

const SERVICE_COLORS = { eMBB: "var(--acc-cyan)", URLLC: "var(--acc-violet)", mMTC: "var(--acc-amber)" };
const SERVICE_BG = {
  eMBB: "oklch(0.84 0.14 195 / 0.12)",
  URLLC: "oklch(0.74 0.15 295 / 0.12)",
  mMTC: "oklch(0.84 0.14 75 / 0.12)",
};

export default function SpectrumDecisionPage({ onBack }) {
  const [params, setParams] = useState({
    num_users: 10,
    total_bandwidth_mhz: 100,
    seed: 42,
    service_mix: "default", // "default" | "embb_heavy" | "urllc_heavy" | "balanced"
  });
  const [status, setStatus] = useState("idle"); // idle | running | success | error
  const [result, setResult] = useState(null);

  const handleRun = useCallback(async () => {
    const mixMap = {
      default: { eMBB: 0.6, URLLC: 0.3, mMTC: 0.1 },
      embb_heavy: { eMBB: 0.8, URLLC: 0.15, mMTC: 0.05 },
      urllc_heavy: { eMBB: 0.2, URLLC: 0.7, mMTC: 0.1 },
      balanced: { eMBB: 0.4, URLLC: 0.3, mMTC: 0.3 },
    };
    setStatus("running");
    setResult(null);
    try {
      const data = await runAllocation({
        num_users: params.num_users,
        total_bandwidth_mhz: params.total_bandwidth_mhz,
        seed: params.seed,
        service_mix: params.service_mix === "default" ? null : mixMap[params.service_mix],
      });
      setResult(data);
      setStatus("success");
    } catch (err) {
      setResult({ error: err.message });
      setStatus("error");
    }
  }, [params]);

  const set = (key, val) => setParams((p) => ({ ...p, [key]: val }));

  return (
    <div className="page fp-page">
      <div className="page-head compact">
        <div className="title-block">
          <span className="label">Skill · Spectrum Decision</span>
          <h1>频谱决策 · 资源分配</h1>
          <p className="lede">
            基于比例公平优化的多用户频谱资源分配。支持 eMBB / URLLC / mMTC 三类业务切片，
            采用 WirelessAgent 的 CQI-Shannon 速率模型与 SLSQP 约束优化。
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
            <div className="fp-form">
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
              <div className="fp-field">
                <label className="fp-label">业务配比</label>
                <select className="fp-select" value={params.service_mix}
                  onChange={(e) => set("service_mix", e.target.value)} disabled={status === "running"}>
                  <option value="default">默认 (60% eMBB)</option>
                  <option value="embb_heavy">eMBB 为主 (80%)</option>
                  <option value="urllc_heavy">URLLC 为主 (70%)</option>
                  <option value="balanced">均衡 (均分)</option>
                </select>
              </div>
              <div className="fp-field">
                <label className="fp-label">随机种子</label>
                <input className="fp-input" type="number" value={params.seed}
                  onChange={(e) => set("seed", Number(e.target.value))} disabled={status === "running"} />
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
                <p>配置用户数量和总带宽后，点击"运行分配"启动 SLSQP 比例公平优化。</p>
              </div>
            )}

            {status === "running" && (
              <div className="fp-result-empty">
                <Loader2 size={28} className="spin" style={{ color: "var(--accent)" }} />
                <h3>优化中…</h3>
                <p>正在进行 CQI-Shannon 速率计算与 SLSQP 约束优化。</p>
              </div>
            )}

            {status === "error" && (
              <div className="fp-result-empty">
                <div className="fp-empty-icon" style={{ color: "var(--err)" }}><Zap size={28} /></div>
                <h3>运行失败</h3>
                <p>{result?.error || "未知错误"}</p>
              </div>
            )}

            {status === "success" && result && (
              <SDResult result={result} />
            )}
          </div>
          {status === "error" && (
            <div className="fp-center-foot">
              <button className="btn" onClick={handleRun}><RefreshCw size={13} /> 重试</button>
            </div>
          )}
        </main>

        {/* right: metrics */}
        <aside className="fp-right card">
          <div className="card-head">
            <span className="title"><Activity size={14} /> 关键指标</span>
          </div>
          <div className="fp-right-body">
            {result && !result.error ? (
              <SDMetrics result={result} />
            ) : (
              <div className="fp-cite-empty">
                <BarChart3 size={24} />
                <p>运行分配后，指标和分布图将在此显示</p>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

/* ── result sub-components ── */

function SDResult({ result }) {
  const allocs = result.allocations || [];
  if (allocs.length === 0) return <p style={{ color: "var(--muted)", padding: 16 }}>无分配结果</p>;

  const maxBw = Math.max(...allocs.map((a) => a.bandwidth_mhz), 1);
  const maxRate = Math.max(...allocs.map((a) => a.rate_mbps), 1);

  return (
    <div className="sd-result">
      {/* summary bar */}
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
          <span className="sd-sum-label">方法</span>
          <span className="sd-sum-value mono" style={{ fontSize: 11 }}>{result.method}</span>
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
              <th>带宽 (MHz)</th>
              <th>速率 (Mbps)</th>
              <th>分配</th>
            </tr>
          </thead>
          <tbody>
            {allocs.map((a) => (
              <tr key={a.user_index}>
                <td className="mono">{allocs.length <= 15 ? `UE_${String(a.user_index + 1).padStart(3, "0")}` : `#${a.user_index + 1}`}</td>
                <td><ServiceBadge service={a.service} /></td>
                <td className="mono">{a.cqi}</td>
                <td className="mono">{a.bandwidth_mhz}</td>
                <td className="mono">{a.rate_mbps}</td>
                <td>
                  <div className="sd-bar-cell">
                    <div className="sd-bar-bw" style={{ width: `${(a.bandwidth_mhz / maxBw) * 100}%`, background: SERVICE_COLORS[a.service] || "var(--accent)" }} />
                  </div>
                </td>
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
  for (const a of allocs) {
    byService[a.service] = byService[a.service] || { count: 0, total_bw: 0, total_rate: 0 };
    byService[a.service].count++;
    byService[a.service].total_bw += a.bandwidth_mhz;
    byService[a.service].total_rate += a.rate_mbps;
  }

  return (
    <div>
      {/* service breakdown */}
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
            <div className="fp-cite-score-fill" style={{
              width: `${(stats.total_bw / result.total_bandwidth_mhz) * 100}%`,
              background: SERVICE_COLORS[svc] || "var(--accent)",
            }} />
          </div>
          <span className="mono" style={{ fontSize: 10, color: "var(--muted-2)" }}>{stats.total_bw.toFixed(1)} MHz / {result.total_bandwidth_mhz} MHz</span>
        </div>
      ))}

      {/* CQI distribution */}
      <div className="fp-cite-section-label" style={{ marginTop: 16 }}>CQI 分布</div>
      <div className="sd-cqi-dist">
        {allocs.map((a) => (
          <div key={a.user_index} className="sd-cqi-bar" title={`UE_${String(a.user_index + 1).padStart(3, "0")}: CQI ${a.cqi}`}
            style={{
              height: `${(a.cqi / 15) * 40 + 8}px`,
              background: SERVICE_COLORS[a.service] || "var(--accent)",
            }} />
        ))}
      </div>

      {/* Jain's fairness */}
      <div style={{ marginTop: 16, padding: "10px 12px", border: "1px solid var(--line)", borderRadius: "var(--r-sm)", display: "flex", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12 }}>Jain 公平指数</span>
        <span className="mono" style={{ fontSize: 16, fontWeight: 700, color: result.fairness > 0.7 ? "var(--ok)" : "var(--warn)" }}>
          {result.fairness.toFixed(4)}
        </span>
      </div>
    </div>
  );
}
