import { Database, FileText, Search } from "lucide-react";
import { kbDocuments, kbStats, ragPipeline } from "../data/mockData.js";

export default function KnowledgePage() {
  return (
    <div className="page">
      <div className="page-head">
        <div className="title-block">
          <span className="label">System · Knowledge Base</span>
          <h1>频谱知识库</h1>
          <p className="lede">
            第一批资料来自 ITU 文档压缩包,后续按 RAG-Anything 思路扩展为多模态 RAG 与知识图谱。
          </p>
        </div>
        <div className="actions">
          <button className="btn ghost"><Search size={14} /> 检索</button>
          <button className="btn primary"><Database size={14} /> 构建索引</button>
        </div>
      </div>

      <div className="kb-grid">
        <main>
          <div className="kb-stats">
            {kbStats.map((s) => (
              <div className="stat-card" key={s.label}>
                <span className="k">{s.label}</span>
                <div className="v">{s.value}</div>
                <div className="d">{s.detail}</div>
              </div>
            ))}
          </div>

          <section className="card" style={{ marginBottom: 20 }}>
            <div className="card-head">
              <span className="title">RAG 流水线</span>
              <span className="eyebrow">6 stage · MVP</span>
            </div>
            <div className="card-body">
              <div className="pipeline">
                {ragPipeline.map((p, i) => (
                  <div className="pipeline-node" key={p.step} data-status={p.status}>
                    <span className="pn">{String(i + 1).padStart(2, "0")} · {p.status}</span>
                    <strong>{p.step}</strong>
                    <p>{p.note}</p>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <span className="title">资料清单</span>
              <span className="eyebrow">{kbDocuments.length} 份 · ITU</span>
            </div>
            <div className="doc-list">
              {kbDocuments.map((d) => (
                <div className="doc-row" key={d.id}>
                  <span className="id">{d.id}</span>
                  <span className="title">{d.title}</span>
                  <span className="size">{d.tag}</span>
                  <span className="size">{d.size}</span>
                </div>
              ))}
            </div>
          </section>
        </main>

        <aside style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <section className="card">
            <div className="card-head">
              <span className="title">语料指针</span>
              <span className="eyebrow">Corpus</span>
            </div>
            <div className="card-body">
              <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.7 }}>
                <span className="mono" style={{ color: "var(--accent)" }}>itu_documents.zip</span> 当前不解压,
                后续在服务器侧执行 PDF 解析、表格抽取与向量化。
              </p>
              <div style={{
                marginTop: 14,
                padding: 12,
                border: "1px solid var(--line)",
                borderRadius: "var(--r-md)",
                background: "oklch(1 0 0 / 0.02)",
                display: "flex",
                gap: 10,
                alignItems: "center"
              }}>
                <FileText size={18} color="var(--accent)" />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="mono" style={{ fontSize: 12, color: "var(--ink)" }}>itu_documents.zip</div>
                  <div className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>887 MB · pinned</div>
                </div>
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <span className="title">下一步</span>
              <span className="eyebrow">Plan</span>
            </div>
            <div className="card-body">
              <ol style={{ margin: 0, padding: "0 0 0 18px", color: "var(--ink-2)", fontSize: 13, lineHeight: 1.85 }}>
                <li>本地 PDF 解析 + 分块</li>
                <li>构建向量索引 + Top-K 检索</li>
                <li>引用回填到 LLM 答案</li>
                <li>实体抽取 + 关系图谱</li>
              </ol>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
