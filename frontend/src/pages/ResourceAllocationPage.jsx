import { Fragment, useState } from "react";
import { ArrowLeft, Play } from "lucide-react";
import { raMockMatrix, raPolicies } from "../data/mockData.js";

function cellColor(v) {
  // map [0,1] to brand cyan with varying alpha + chroma
  const a = 0.10 + v * 0.65;
  return `oklch(0.84 0.14 195 / ${a.toFixed(2)})`;
}

export default function ResourceAllocationPage({ onBack }) {
  const [policy, setPolicy] = useState(raPolicies[2].id);
  const channels = ["CH-01", "CH-02", "CH-03", "CH-04", "CH-05", "CH-06"];
  const users = ["U-1", "U-2", "U-3", "U-4", "U-5", "U-6", "U-7", "U-8"];

  return (
    <div className="page">
      <div className="page-head">
        <div className="title-block">
          <span className="label">Skill · Resource Allocation</span>
          <h1>资源分配工作区</h1>
          <p className="lede">
            在频段、功率、时隙等多维约束下,求解多用户资源最优分配。聚合 spectrum_decision 历史模块。
          </p>
        </div>
        <div className="actions">
          <button className="btn ghost" onClick={onBack}>
            <ArrowLeft size={14} /> 返回 Console
          </button>
          <button className="btn primary"><Play size={14} /> 求解</button>
        </div>
      </div>

      <div className="skill-detail-grid">
        <aside className="card params-card">
          <div className="card-head">
            <span className="title">约束</span>
            <span className="eyebrow">Constraints</span>
          </div>
          <div className="card-body">
            <div className="field">
              <label>策略</label>
              <div className="segment">
                {raPolicies.map((p) => (
                  <button key={p.id} className={policy === p.id ? "on" : ""} onClick={() => setPolicy(p.id)}>
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="field">
              <label>用户数</label>
              <input className="control mono" defaultValue="8" />
            </div>
            <div className="field">
              <label>频段数</label>
              <input className="control mono" defaultValue="6" />
            </div>
            <div className="field">
              <label>总带宽 (MHz)</label>
              <input className="control mono" defaultValue="100" />
            </div>
            <div className="field">
              <label>最大功率 (dBm)</label>
              <input className="control mono" defaultValue="23" />
            </div>
            <div className="field">
              <label>最低 SINR (dB)</label>
              <input className="control mono" defaultValue="6" />
            </div>
            <div className="field">
              <label>求解器</label>
              <select className="control">
                <option>Lagrangian · MVP</option>
                <option>Genetic · 后续</option>
                <option>RL Policy · 后续</option>
              </select>
            </div>
          </div>
        </aside>

        <main style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <section className="card">
            <div className="card-head">
              <span className="title">分配矩阵 · 信道 × 用户</span>
              <span className="eyebrow">{raPolicies.find((p) => p.id === policy)?.note}</span>
            </div>
            <div className="alloc-canvas">
              <div className="alloc-matrix">
                <span></span>
                {users.map((u) => (
                  <span className="alloc-h" key={u}>{u}</span>
                ))}
                {channels.map((ch, ci) => (
                  <Fragment key={ch}>
                    <span className="alloc-row-label">{ch}</span>
                    {raMockMatrix[ci].map((v, ui) => (
                      <span className="alloc-cell" key={`c-${ci}-${ui}`} style={{ background: cellColor(v) }}>
                        <span className="v">{v.toFixed(2)}</span>
                      </span>
                    ))}
                  </Fragment>
                ))}
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <span className="title">关键指标</span>
              <span className="eyebrow">Mock</span>
            </div>
            <div className="card-body" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
              {[
                { k: "总吞吐", v: "642.4", u: "Mbps" },
                { k: "Jain 公平性", v: "0.91", u: "—" },
                { k: "平均 SINR", v: "12.7", u: "dB" },
                { k: "迭代次数", v: "84", u: "次" }
              ].map((m) => (
                <div key={m.k} style={{
                  padding: "14px 16px",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--r-md)",
                  background: "oklch(1 0 0 / 0.02)"
                }}>
                  <span className="eyebrow">{m.k}</span>
                  <div style={{
                    marginTop: 8,
                    fontFamily: "var(--font-mono)",
                    fontSize: 22,
                    fontWeight: 600,
                    color: "var(--ink)",
                    letterSpacing: "-0.01em"
                  }}>
                    {m.v} <span style={{ fontSize: 12, color: "var(--muted)", marginLeft: 4 }}>{m.u}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </main>

        <aside className="card">
          <div className="card-head">
            <span className="title">策略说明</span>
            <span className="eyebrow">Notes</span>
          </div>
          <div className="card-body">
            {raPolicies.map((p) => (
              <div key={p.id} className="cite">
                <div className="hdr">
                  <strong>{p.label}</strong>
                  <span>{p.id === policy ? "当前" : ""}</span>
                </div>
                <p>{p.note}</p>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
