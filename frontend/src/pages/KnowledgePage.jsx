import { useEffect, useState } from "react";
import { Database, FileText, HardDrive, Layers, Search, Zap } from "lucide-react";
import { kbDocuments } from "../data/mockData.js";

const API_BASE = `http://${window.location.hostname}:8230`;

export default function KnowledgePage() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/kb/stats`)
      .then((r) => r.json())
      .then(setStats)
      .catch(() => setStats({ status: "无法连接后端" }));
  }, []);

  const isReady = stats?.status === "ready";
  const ragReady = stats?.rag_anything?.status === "ready";
  const graphReady = stats?.knowledge_graph?.status === "ready";
  const statCards = [
    { label: "索引状态", value: isReady ? "已就绪" : stats?.status || "加载中…", detail: stats?.backend || "", icon: Zap },
    { label: "PDF 文档", value: stats?.total_pdfs?.toLocaleString() || "—", detail: "ITU-R 建议书 / 报告 / 规则", icon: FileText },
    { label: "Chroma 向量", value: stats?.rag_anything?.vector_count?.toLocaleString() || "—", detail: ragReady ? "embedding + ChromaDB" : "待索引", icon: Layers },
    { label: "知识图谱", value: stats?.knowledge_graph?.entity_count?.toLocaleString() || "—", detail: graphReady ? `${stats?.knowledge_graph?.relation_count} 条关系` : "待构建", icon: HardDrive },
  ];

  const pipelineSteps = [
    { step: "Document Parsing", note: "PyPDFParser → SpectrumDocument + content_list.json", status: ragReady ? "ready" : "planned" },
    { step: "Content Processing", note: "Text / Table / Footnote Processors", status: ragReady ? "ready" : "planned" },
    { step: "Embedding + Vector Store", note: ragReady ? `${stats?.rag_anything?.vector_count?.toLocaleString()} vectors · ChromaDB` : "sentence-transformers + Chroma", status: ragReady ? "ready" : "planned" },
    { step: "Hybrid Retrieval", note: "Vector + Keyword(TF-IDF) + Graph + Rerank", status: ragReady ? "ready" : "planned" },
    { step: "Cited Answer", note: "LangGraph RAG → 结论/依据/限制/来源/不确定性", status: ragReady ? "ready" : "planned" },
    { step: "Knowledge Graph", note: graphReady ? `${stats?.knowledge_graph?.entity_count} entities · ${stats?.knowledge_graph?.relation_count} relations` : "Spectrum entities & relations", status: graphReady ? "ready" : "planned" },
  ];

  return (
    <div className="page">
      <div className="page-head compact">
        <div className="title-block">
          <span className="label">System · Knowledge Base</span>
          <h1>频谱知识库</h1>
          <p className="lede">
            {isReady
              ? `已索引 ${stats.total_pdfs} 份 ITU-R 文档，共 ${stats.total_chunks?.toLocaleString()} 个文本块。可在 Console 对话中通过「search_knowledge_base」工具检索。`
              : "第一批资料来自 ITU 文档压缩包。运行 python -m backend.knowledge.ingest 构建索引。"}
          </p>
        </div>
        <div className="actions">
          <button className="btn ghost"><Search size={14} /> 检索测试</button>
          <button className="btn primary"><Database size={14} /> {isReady ? "重建索引" : "构建索引"}</button>
        </div>
      </div>

      <div className="kb-grid">
        <main>
          <div className="kb-stats">
            {statCards.map((s) => (
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
              <span className="eyebrow">{isReady ? "Phase 1 完成" : "待构建"}</span>
            </div>
            <div className="card-body">
              <div className="pipeline">
                {pipelineSteps.map((p, i) => (
                  <div className="pipeline-node" key={p.step} data-status={p.status}>
                    <span className="pn">{String(i + 1).padStart(2, "0")} · {p.status === "ready" ? "done" : p.status}</span>
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
              <span className="eyebrow">{kbDocuments.length} 份 · ITU 示例</span>
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
              <span className="title">存储后端</span>
              <span className="eyebrow">Storage</span>
            </div>
            <div className="card-body">
              <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.7 }}>
                当前使用 <span className="mono" style={{ color: "var(--accent)" }}>SQLite</span> 本地存储。
                后续可通过 <span className="mono">SPECTRUMCLAW_KB_BACKEND</span> 切换至 Postgres + pgvector 或 Qdrant。
              </p>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <span className="title">演进路线</span>
              <span className="eyebrow">对标 RAG-Anything</span>
            </div>
            <div className="card-body">
              <ol style={{ margin: 0, padding: "0 0 0 18px", color: "var(--ink-2)", fontSize: 13, lineHeight: 1.85 }}>
                <li><span style={{ color: "var(--ok)" }}>✅ 文本 RAG — pypdf + TF-IDF + SQLite</span></li>
                <li>Embedding 语义检索 — DeepSeek Embedding API / BGE</li>
                <li>结构化知识图谱 — 频谱实体 + 关系网络</li>
                <li>多模态 RAG — 表格 / 公式 / 频谱图 VLM</li>
              </ol>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
