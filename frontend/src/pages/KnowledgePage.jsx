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
  const statCards = [
    { label: "索引状态", value: isReady ? "已就绪" : stats?.status || "加载中…", detail: stats?.backend || "", icon: Zap },
    { label: "PDF 文档", value: stats?.total_pdfs?.toLocaleString() || "—", detail: "ITU-R 建议书 / 报告 / 规则", icon: FileText },
    { label: "文本块", value: stats?.total_chunks?.toLocaleString() || "—", detail: "段落级分块", icon: Layers },
    { label: "字符总量", value: stats?.total_chars ? `${(stats.total_chars / 1_000_000).toFixed(1)}M` : "—", detail: `${stats?.index_features?.toLocaleString() || 0} 维 TF-IDF`, icon: HardDrive },
  ];

  const pipelineSteps = [
    { step: "Raw PDFs", note: "804 份 ITU-R 文档 (1GB)", status: "ready" },
    { step: "PDF Parser", note: "pypdf 文本提取", status: isReady ? "ready" : "planned" },
    { step: "Chunk + Index", note: stats ? `${stats.total_chunks?.toLocaleString()} chunks · TF-IDF` : "段落级分块 + 向量化", status: isReady ? "ready" : "planned" },
    { step: "Retriever", note: "余弦相似度 Top-K", status: isReady ? "ready" : "planned" },
    { step: "Cited Answer", note: "LLM 综合 + 文档编号引用", status: isReady ? "ready" : "planned" },
    { step: "Knowledge Graph", note: "频谱实体/关系提取 · Phase 2", status: "future" },
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
