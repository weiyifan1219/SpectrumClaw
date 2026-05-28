import { evolutionLog, memoryLayers } from "../data/mockData.js";

export default function MemoryPage() {
  return (
    <div className="page">
      <div className="page-head">
        <div className="title-block">
          <span className="label">System · Memory & Evolution</span>
          <h1>记忆与进化</h1>
          <p className="lede">
            展示系统的记忆层级、skill 使用反馈、能力版本变化与自动反思摘要。
          </p>
        </div>
      </div>

      <div className="memory-grid">
        {memoryLayers.map((m) => {
          const Icon = m.icon;
          return (
            <div className="mem-card" key={m.label}>
              <div className="top">
                <span className="ico"><Icon size={16} /></span>
                <span className="pct mono">{Math.round(m.fill * 100)}%</span>
              </div>
              <h3>{m.label}</h3>
              <small>{m.chinese} · {m.value}</small>
              <div className="bar"><span className="fill" style={{ "--w": `${m.fill * 100}%` }} /></div>
            </div>
          );
        })}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 20 }} className="mem-cols">
        <section className="card">
          <div className="card-head">
            <span className="title">进化日志</span>
            <span className="eyebrow">Recent · {evolutionLog.length}</span>
          </div>
          <div className="card-body">
            <div className="evo-timeline">
              {evolutionLog.map((e) => (
                <div className="evo-row" key={e.title} data-tone={e.tone}>
                  <div className="ts mono">{e.ts}</div>
                  <div className="title">{e.title}</div>
                  <div className="note">{e.note}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <span className="title">反思队列</span>
            <span className="eyebrow">Self-Reflection</span>
          </div>
          <div className="card-body">
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.7 }}>
              系统将定期回看任务结果与用户反馈,生成 skill 调用模式总结和能力改进项。
              当前为静态规划,接入后端后会切换为真实记录。
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
              {[
                { t: "Skill 调用集中度", v: "Top: Frequency Planning · 0%" },
                { t: "失败样本", v: "0 条" },
                { t: "用户反馈条目", v: "0 条" }
              ].map((row) => (
                <div key={row.t} style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "10px 12px",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--r-md)",
                  background: "oklch(1 0 0 / 0.02)"
                }}>
                  <span style={{ fontSize: 12.5, color: "var(--ink-2)" }}>{row.t}</span>
                  <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>{row.v}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
