import { useState } from "react";
import { ArrowLeft, Lock, Play } from "lucide-react";
import { sbScenarios } from "../data/mockData.js";

const blobs = [
  { x: 22, y: 30, r: 90, c: "oklch(0.74 0.18 25 / 0.45)" },
  { x: 68, y: 56, r: 120, c: "oklch(0.84 0.14 80 / 0.40)" },
  { x: 38, y: 72, r: 70, c: "oklch(0.78 0.10 250 / 0.45)" },
  { x: 84, y: 22, r: 50, c: "oklch(0.84 0.14 195 / 0.45)" }
];

const markers = [
  { x: 22, y: 30 },
  { x: 68, y: 56 },
  { x: 38, y: 72 },
  { x: 84, y: 22 }
];

export default function SituationBuildingPage({ onBack }) {
  const [scenario, setScenario] = useState(sbScenarios[0].id);

  return (
    <div className="page">
      <div className="page-head">
        <div className="title-block">
          <span className="label">Skill · Situation Building</span>
          <h1>态势构建工作区</h1>
          <p className="lede">
            重建空间电磁覆盖与威胁分布。当前模块等待用户上传 REM 推理脚本到 4090 服务器后接入。
          </p>
        </div>
        <div className="actions">
          <button className="btn ghost" onClick={onBack}>
            <ArrowLeft size={14} /> 返回 Console
          </button>
          <button className="btn" disabled style={{ opacity: 0.6, cursor: "not-allowed" }}>
            <Lock size={14} /> 等待脚本接入
          </button>
        </div>
      </div>

      <div className="skill-detail-grid">
        <aside className="card params-card">
          <div className="card-head">
            <span className="title">场景</span>
            <span className="eyebrow">Inputs</span>
          </div>
          <div className="card-body">
            <div className="field">
              <label>区域</label>
              <select className="control" value={scenario} onChange={(e) => setScenario(e.target.value)}>
                {sbScenarios.map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>分辨率</label>
              <div className="segment">
                <button className="on">100m</button>
                <button>50m</button>
                <button>25m</button>
              </div>
            </div>
            <div className="field">
              <label>采样点</label>
              <input className="control mono" defaultValue="384 / 1024" />
            </div>
            <div className="field">
              <label>频段</label>
              <input className="control" defaultValue="2.4 GHz · 5.8 GHz" />
            </div>
            <div className="field">
              <label>模型</label>
              <input className="control" defaultValue="UAV-REM v0 (pending upload)" />
            </div>
          </div>
        </aside>

        <main style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <section className="card">
            <div className="card-head">
              <span className="title">REM 覆盖预览</span>
              <span className="pill" data-tone="warn"><span className="dot" /> 模型未连接</span>
            </div>
            <div className="card-body">
              <div className="rem-canvas">
                <div className="rem-grid" />
                {blobs.map((b, i) => (
                  <span
                    key={i}
                    className="rem-blob"
                    style={{
                      left: `${b.x - 10}%`,
                      top: `${b.y - 10}%`,
                      width: `${b.r * 1.6}px`,
                      height: `${b.r * 1.6}px`,
                      background: `radial-gradient(circle, ${b.c}, transparent 70%)`
                    }}
                  />
                ))}
                {markers.map((m, i) => (
                  <span key={i} className="rem-marker" style={{ left: `${m.x}%`, top: `${m.y}%` }} />
                ))}
                <div className="rem-legend">
                  <span className="l-high">High</span>
                  <span className="l-mid">Mid</span>
                  <span className="l-low">Low</span>
                </div>
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <span className="title">告警与异常源</span>
              <span className="eyebrow">检测占位</span>
            </div>
            <div className="card-body" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
              {["Source A · 2.42 GHz", "Source B · 5.15 GHz", "盲区 · 边缘扇区"].map((s, i) => (
                <div key={s} style={{
                  padding: 12,
                  border: "1px solid var(--line)",
                  borderRadius: "var(--r-md)",
                  background: "oklch(1 0 0 / 0.025)"
                }}>
                  <span className="eyebrow">Detection · {String(i + 1).padStart(2, "0")}</span>
                  <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--ink)" }}>{s}</p>
                  <p style={{ margin: "4px 0 0", fontSize: 11.5, color: "var(--muted)" }}>等待真实模型推理结果</p>
                </div>
              ))}
            </div>
          </section>
        </main>

        <aside className="card">
          <div className="card-head">
            <span className="title">运行说明</span>
            <span className="eyebrow">Status</span>
          </div>
          <div className="card-body">
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.7 }}>
              REM 推理依赖 4090 服务器与 <span className="mono" style={{ color: "var(--ink-2)" }}>conda activate Agent</span> 环境。
              用户脚本上传后,前端将通过 WebSocket 拉取实时推理进度与结果,并替换上方占位可视化。
            </p>
            <div style={{
              marginTop: 14,
              padding: 12,
              border: "1px solid var(--line)",
              borderRadius: "var(--r-md)",
              background: "oklch(0.84 0.14 80 / 0.06)"
            }}>
              <span className="eyebrow" style={{ color: "var(--warn)" }}>WAITING UPLOAD</span>
              <p style={{ margin: "6px 0 0", fontSize: 12.5, color: "var(--ink-2)" }}>
                将实验脚本上传至 <span className="mono">/home/lenovo/workspace/Agent_UAV_REM</span> 并配置入口函数后,该 skill 自动激活。
              </p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
