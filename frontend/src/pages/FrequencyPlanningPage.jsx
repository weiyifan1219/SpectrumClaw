import { useState } from "react";
import { ArrowLeft, FileSearch, Play, Sparkles } from "lucide-react";
import { fpCitations, fpScenarios, ituBands } from "../data/mockData.js";

export default function FrequencyPlanningPage({ onBack }) {
  const [scenario, setScenario] = useState(fpScenarios[0].id);
  const [mode, setMode] = useState("rag");

  return (
    <div className="page">
      <div className="page-head">
        <div className="title-block">
          <span className="label">Skill · Frequency Planning</span>
          <h1>频率规划工作区</h1>
          <p className="lede">
            在 ITU 文档库基础上,基于 RAG 检索给出可引用的频段使用方案;支持多区域、多业务约束。
          </p>
        </div>
        <div className="actions">
          <button className="btn ghost" onClick={onBack}>
            <ArrowLeft size={14} /> 返回 Console
          </button>
          <button className="btn primary">
            <Play size={14} /> 运行规划
          </button>
        </div>
      </div>

      <div className="skill-detail-grid">
        {/* params */}
        <aside className="card params-card">
          <div className="card-head">
            <span className="title">参数</span>
            <span className="eyebrow">Inputs</span>
          </div>
          <div className="card-body">
            <div className="field">
              <label>场景</label>
              <select className="control" value={scenario} onChange={(e) => setScenario(e.target.value)}>
                {fpScenarios.map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
            </div>

            <div className="field">
              <label>检索模式</label>
              <div className="segment">
                <button className={mode === "rag" ? "on" : ""} onClick={() => setMode("rag")}>RAG</button>
                <button className={mode === "graph" ? "on" : ""} onClick={() => setMode("graph")}>Graph</button>
                <button className={mode === "hybrid" ? "on" : ""} onClick={() => setMode("hybrid")}>Hybrid</button>
              </div>
            </div>

            <div className="field">
              <label>目标频段</label>
              <input className="control" defaultValue="2.4 GHz · ISM" />
            </div>

            <div className="field">
              <label>业务类型</label>
              <input className="control" defaultValue="无人机数据链 · 短距通信" />
            </div>

            <div className="field">
              <label>带宽 (MHz)</label>
              <input className="control" defaultValue="20" />
            </div>

            <div className="field">
              <label>共存约束</label>
              <input className="control" defaultValue="WiFi · Bluetooth" />
            </div>
          </div>
        </aside>

        {/* visualization + result */}
        <main style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <section className="card">
            <div className="card-head">
              <span className="title">ITU 频段使用密度</span>
              <span className="eyebrow">8 个频段 · mock</span>
            </div>
            <div className="band-canvas">
              {ituBands.map((b) => (
                <div className="band-row" key={b.name}>
                  <span className="bn">{b.name}</span>
                  <div className="bar">
                    <span className="fill" style={{ "--w": `${Math.round(b.load * 100)}%` }} />
                    <span className="ticks" />
                  </div>
                  <span className="bu">{b.lo}–{b.hi} {b.unit}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <span className="title">规划结果 · 草稿</span>
              <span className="pill" data-tone="warn"><span className="dot" /> 待运行</span>
            </div>
            <div className="card-body">
              <p style={{ margin: 0, color: "var(--muted)", fontSize: 13.5, lineHeight: 1.7 }}>
                运行后,此处将展示推荐的频段、带宽划分、共存策略,以及对 ITU 文档的引用。
                MVP 阶段先输出 Markdown 与 JSON 两种格式,后续可在 Knowledge Graph 视图中钻取。
              </p>
              <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                <button className="btn"><FileSearch size={13} /> 预览 Markdown</button>
                <button className="btn"><Sparkles size={13} /> 生成示例</button>
              </div>
            </div>
          </section>
        </main>

        {/* citations */}
        <aside className="card">
          <div className="card-head">
            <span className="title">候选引用</span>
            <span className="eyebrow">Top 3</span>
          </div>
          <div className="card-body">
            {fpCitations.map((c) => (
              <div className="cite" key={c.id}>
                <div className="hdr">
                  <strong>{c.id}</strong>
                  <span>{c.page}</span>
                </div>
                <p>{c.excerpt}</p>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
