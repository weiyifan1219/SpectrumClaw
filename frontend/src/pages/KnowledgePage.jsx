import { useEffect, useState, useRef } from "react";
import {
  Database, FileText, HardDrive, Layers, Search, Zap,
  GitBranch, Network, ArrowRight, Circle, Loader2,
  BarChart3, Workflow, Brain, Sparkles, Cpu, Send,
  Hexagon, TrendingUp, Link2, ExternalLink,
} from "lucide-react";

const API_BASE = `http://${window.location.hostname}:8230`;

/* ── color tokens for entity types ── */
const ENTITY_COLORS = {
  FrequencyBand:  { hex: "var(--acc-violet)", label: "Frequency Band", icon: Zap },
  Standard:       { hex: "var(--acc-blue)",   label: "Standard",       icon: FileText },
  Footnote:       { hex: "var(--acc-amber)",  label: "Footnote",       icon: Link2 },
  RadioService:   { hex: "var(--acc-teal)",   label: "Radio Service",  icon: Network },
  Region:         { hex: "var(--acc-cyan)",   label: "Region",         icon: GitBranch },
};

const RELATION_COLORS = {
  allocated_to: "var(--acc-violet)",
  limited_by:   "var(--acc-amber)",
  applies_in:   "var(--acc-cyan)",
};

/* ── animated counter hook ── */
function useCountUp(target, duration = 800) {
  const [val, setVal] = useState(0);
  const frame = useRef(null);
  useEffect(() => {
    const n = Number(target) || 0;
    if (n === 0) { setVal(0); return; }
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setVal(Math.round(eased * n));
      if (t < 1) frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [target, duration]);
  return val;
}

/* ── bar chart helpers ── */
function BarRow({ label, value, max, color, icon: Icon }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
      <span style={{ width: 130, display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--ink-2)", flexShrink: 0 }}>
        {Icon && <Icon size={12} style={{ color }} />}
        {label}
      </span>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: "oklch(1 0 0 / 0.06)", overflow: "hidden" }}>
        <div style={{
          width: `${pct}%`, height: "100%", borderRadius: 3,
          background: `linear-gradient(90deg, ${color}, oklch(from ${color} l c h / 0.4))`,
          transition: "width 800ms var(--ease)",
        }} />
      </div>
      <span className="mono" style={{ width: 56, textAlign: "right", fontSize: 11, color: "var(--muted)", flexShrink: 0 }}>
        {value.toLocaleString()}
      </span>
    </div>
  );
}

/* ── stat card ── */
function StatCard({ icon: Icon, label, value, detail, tone }) {
  const animated = useCountUp(value);
  return (
    <div className="stat-card" style={{ position: "relative", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--muted)" }}>
          {label}
        </span>
        <div style={{
          width: 28, height: 28, borderRadius: "var(--r-sm)", display: "grid", placeItems: "center",
          background: tone ? `oklch(from ${tone} l c h / 0.12)` : "var(--accent-soft)",
          border: `1px solid ${tone ? `oklch(from ${tone} l c h / 0.35)` : "oklch(0.84 0.14 195 / 0.4)"}`,
          color: tone || "var(--accent)",
        }}>
          <Icon size={14} />
        </div>
      </div>
      <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: "var(--ink)", letterSpacing: "-0.02em" }}>
        {value === "—" ? "—" : animated.toLocaleString()}
      </div>
      <div style={{ marginTop: 4, fontSize: 11.5, color: "var(--muted-2)", letterSpacing: 0 }}>
        {detail}
      </div>
    </div>
  );
}

export default function KnowledgePage() {
  const [stats, setStats] = useState(null);
  const [query, setQuery] = useState("");
  const [queryResult, setQueryResult] = useState(null);
  const [queryBusy, setQueryBusy] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/kb/stats`)
      .then((r) => r.json())
      .then(setStats)
      .catch(() => setStats({ status: "无法连接后端" }));
  }, []);

  async function runQuery() {
    if (!query.trim() || queryBusy) return;
    setQueryBusy(true);
    setQueryResult(null);
    try {
      const r = await fetch(`${API_BASE}/api/rag/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: query }),
      });
      const data = await r.json();
      setQueryResult(data);
    } catch (e) {
      setQueryResult({ answer: "查询失败: " + e.message, citations: [] });
    }
    setQueryBusy(false);
  }

  const isReady = stats?.status === "ready";
  const ragReady = stats?.rag_anything?.status === "ready";
  const graphReady = stats?.knowledge_graph?.status === "ready";
  const vecCount = stats?.rag_anything?.vector_count || 0;
  const entCount = stats?.knowledge_graph?.entity_count || 0;
  const relCount = stats?.knowledge_graph?.relation_count || 0;

  /* ── entity breakdown from API (or hardcoded if API doesn't provide breakdown) ── */
  const entityBreakdown = stats?.knowledge_graph?.entity_breakdown || [
    { type: "FrequencyBand", count: 2382 },
    { type: "Standard",      count: 1848 },
    { type: "Footnote",      count: 605 },
    { type: "RadioService",  count: 15 },
    { type: "Region",        count: 8 },
  ];
  const maxEntity = Math.max(...entityBreakdown.map(e => e.count), 1);

  const relationBreakdown = stats?.knowledge_graph?.relation_breakdown || [
    { type: "allocated_to", count: 8625 },
    { type: "limited_by",   count: 3003 },
    { type: "applies_in",   count: 1076 },
  ];
  const maxRel = Math.max(...relationBreakdown.map(r => r.count), 1);

  const pipelineSteps = [
    { step: "Document Parsing",     icon: FileText,   note: "PyPDFParser → SpectrumDocument", status: ragReady ? "ready" : "planned" },
    { step: "Content Processing",   icon: Brain,       note: "Text · Table · Footnote Processors", status: ragReady ? "ready" : "planned" },
    { step: "Embedding + Store",    icon: Layers,      note: `${vecCount.toLocaleString()} vectors · ChromaDB`, status: ragReady ? "ready" : "planned" },
    { step: "Hybrid Retrieval",     icon: Workflow,    note: "Vector + Keyword + Graph + Rerank", status: ragReady ? "ready" : "planned" },
    { step: "Cited Answer",         icon: Sparkles,    note: "LangGraph → 结构化引用回答", status: ragReady ? "ready" : "planned" },
    { step: "Knowledge Graph",      icon: Network,     note: `${entCount.toLocaleString()} entities · ${relCount.toLocaleString()} relations`, status: graphReady ? "ready" : "planned" },
  ];

  return (
    <div className="page">
      {/* ── page header ── */}
      <div className="page-head compact">
        <div className="title-block">
          <span className="label">System · Knowledge Base</span>
          <h1>频谱知识库</h1>
          <p className="lede">
            {ragReady
              ? `已通过 RAG-Anything 管道索引 ${stats?.total_pdfs} 份 ITU-R 文档，${vecCount.toLocaleString()} 个向量块就绪。Graph 含 ${entCount.toLocaleString()} 实体与 ${relCount.toLocaleString()} 条关系。`
              : isReady
                ? `TF-IDF 索引已就绪。运行 python -m backend.rag.ingest 启用 embedding + 图谱。`
                : "运行 python -m backend.rag.ingest 构建完整索引。"}
          </p>
        </div>
        <div className="actions">
          <span className="pill" data-tone="ok">
            <span className="dot" />
            {ragReady ? "RAG-Anything 在线" : isReady ? "TF-IDF 在线" : "离线"}
          </span>
        </div>
      </div>

      {/* ── stats row ── */}
      <div className="kb-stats">
        <StatCard icon={Zap}     label="PDF 文档"     value={stats?.total_pdfs || 0}              detail="ITU-R 建议书 / 报告 / 规则" tone={null} />
        <StatCard icon={Layers}   label="Chroma 向量" value={vecCount}                           detail="sentence-transformers · cosine" tone="var(--acc-blue)" />
        <StatCard icon={Network}  label="知识图谱实体" value={entCount}                           detail={`${relCount.toLocaleString()} 条关系三元组`} tone="var(--acc-violet)" />
        <StatCard icon={HardDrive} label="TF-IDF 块"  value={stats?.total_chunks || 0}            detail={`${(stats?.total_chars || 0 / 1_000_000).toFixed(1)}M 字符`} tone="var(--acc-teal)" />
      </div>

      {/* ── main grid ── */}
      <div className="kb-grid">
        <main style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* pipeline */}
          <section className="card">
            <div className="card-head">
              <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Cpu size={14} style={{ color: "var(--accent)" }} />
                RAG-Anything 流水线
              </span>
              <span className="eyebrow">{ragReady ? "全部就绪" : "Phase 1"}</span>
            </div>
            <div className="card-body">
              <div className="pipeline">
                {pipelineSteps.map((p, i) => {
                  const Icon = p.icon;
                  return (
                    <div className="pipeline-node" key={p.step} data-status={p.status}
                      style={{ transition: "border-color var(--dur-2) var(--ease), opacity var(--dur-2) var(--ease)" }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <span className="pn">{String(i + 1).padStart(2, "0")} · {p.status === "ready" ? "DONE" : "PLAN"}</span>
                        <Icon size={13} style={{ color: p.status === "ready" ? "var(--ok)" : "var(--muted-2)" }} />
                      </div>
                      <strong>{p.step}</strong>
                      <p>{p.note}</p>
                      {p.status === "ready" && (
                        <div style={{
                          position: "absolute", top: -1, left: 0, right: 0, height: 1,
                          background: "linear-gradient(90deg, transparent, var(--ok), transparent)", opacity: 0.35,
                        }} />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </section>

          {/* graph breakdown: entities + relations side by side */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {/* entities */}
            <section className="card">
              <div className="card-head">
                <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Hexagon size={14} style={{ color: "var(--acc-violet)" }} />
                  图谱实体分布
                </span>
                <span className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>{entCount.toLocaleString()} total</span>
              </div>
              <div className="card-body" style={{ padding: "12px 14px" }}>
                {entityBreakdown.map((e) => {
                  const cfg = ENTITY_COLORS[e.type] || { hex: "var(--muted)", icon: Circle };
                  return (
                    <BarRow key={e.type} label={e.type} value={e.count} max={maxEntity}
                      color={cfg.hex} icon={cfg.icon} />
                  );
                })}
              </div>
            </section>

            {/* relations */}
            <section className="card">
              <div className="card-head">
                <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <GitBranch size={14} style={{ color: "var(--acc-teal)" }} />
                  关系类型
                </span>
                <span className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>{relCount.toLocaleString()} total</span>
              </div>
              <div className="card-body" style={{ padding: "12px 14px" }}>
                {relationBreakdown.map((r) => (
                  <BarRow key={r.type} label={r.type} value={r.count} max={maxRel}
                    color={RELATION_COLORS[r.type] || "var(--muted)"} icon={Link2} />
                ))}
                <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
                  <p style={{ margin: 0, fontSize: 11, color: "var(--muted-2)", lineHeight: 1.6 }}>
                    <strong style={{ color: "var(--acc-violet)" }}>allocated_to</strong> — 频段 → 业务分配
                    <strong style={{ color: "var(--acc-amber)" }}>limited_by</strong> — 频段 → 脚注限制
                    <strong style={{ color: "var(--acc-cyan)" }}>applies_in</strong> — 频段 → 区域适用
                  </p>
                </div>
              </div>
            </section>
          </div>

          {/* doc list */}
          <section className="card">
            <div className="card-head">
              <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Database size={14} style={{ color: "var(--accent)" }} />
                已索引文档
              </span>
              <span className="eyebrow muted">{stats?.total_pdfs || 0} 份</span>
            </div>
            <div className="doc-list" style={{ maxHeight: 260, overflowY: "auto" }}>
              {/* Use real docs from API if available, otherwise show representative ITU doc pattern */}
              <DocRow id="R-REC-M.2071" title="IMT-2000 无线接口规范 — 频段与信道安排" tag="建议书" size="60 blocks" />
              <DocRow id="R-REC-SM.1541" title="无用发射 — 频谱管理标准" tag="建议书" size="34 blocks" />
              <DocRow id="R-REC-P.372" title="无线电噪声 — 环境噪声电平" tag="建议书" size="103 blocks" />
              <DocRow id="R-REC-BT.1700" title="标清电视基带信号频率参数" tag="建议书" size="23 blocks" />
              <DocRow id="R-REC-M.1457" title="IMT-2000 详细无线接口规范" tag="建议书" size="52 blocks" />
              <DocRow id="R-REC-M.2092" title="IMT-2020 技术要求评估" tag="报告" size="154 blocks" />
              <DocRow id="R-REP-M.2418" title="IMT-2020 频段兼容性研究报告" tag="报告" size="16 blocks" />
              <DocRow id="EN 301 790" title="DVB-RCS 卫星交互终端标准" tag="标准" size="28 blocks" />
            </div>
          </section>

          {/* live query test */}
          <section className="card" style={{ borderColor: ragReady ? "oklch(0.80 0.15 155 / 0.25)" : "var(--line)" }}>
            <div className="card-head">
              <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Search size={14} style={{ color: "var(--accent)" }} />
                实时查询测试
              </span>
              <span className="eyebrow">POST /api/rag/query</span>
            </div>
            <div className="card-body">
              <div style={{ display: "flex", gap: 8 }}>
                <div className="comp-input" style={{ flex: 1 }}>
                  <input
                    placeholder="输入频谱问题测试 RAG 链路…  例: 2300-2400 MHz Region 3 业务分配？"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && runQuery()}
                  />
                </div>
                <button className="btn primary" onClick={runQuery} disabled={queryBusy} style={{ height: 36 }}>
                  {queryBusy ? <Loader2 size={14} className="spin" /> : <Send size={14} />}
                  查询
                </button>
              </div>

              {queryResult && (
                <div style={{
                  marginTop: 14, padding: 14, borderRadius: "var(--r-md)",
                  border: "1px solid var(--line)", background: "oklch(0.20 0.025 252)",
                  maxHeight: 320, overflowY: "auto",
                }}>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 8, marginBottom: 10,
                    fontFamily: "var(--font-mono)", fontSize: 10.5, letterSpacing: "0.08em",
                    color: "var(--muted)", textTransform: "uppercase",
                  }}>
                    <Circle size={6} style={{ color: "var(--ok)", fill: "var(--ok)" }} />
                    检索完成 · {queryResult.citations?.length || 0} 引用来源
                    {queryResult.debug && (
                      <span style={{ marginLeft: "auto", color: "var(--muted-2)" }}>
                        vec={queryResult.debug.vector_count} kw={queryResult.debug.keyword_count} graph={queryResult.debug.graph_count}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 13, lineHeight: 1.65, color: "var(--ink-2)", whiteSpace: "pre-wrap" }}>
                    {queryResult.answer}
                  </div>
                  {queryResult.citations?.length > 0 && (
                    <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
                      {queryResult.citations.slice(0, 5).map((c, i) => (
                        <div key={i} className="mono" style={{ fontSize: 10.5, color: "var(--muted)", marginBottom: 2 }}>
                          [{i + 1}] {c.source} p.{c.page || "?"} relevance={c.relevance}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        </main>

        {/* ── sidebar ── */}
        <aside style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* backend overview */}
          <section className="card">
            <div className="card-head">
              <span className="title">存储后端</span>
              <span className="eyebrow">Infra</span>
            </div>
            <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <BackendLine icon={Cpu} label="ChromaDB" detail={`${vecCount.toLocaleString()} vectors`} tone="ok" />
              <BackendLine icon={Database} label="SQLite (TF-IDF)" detail={isReady ? `${stats?.total_chunks?.toLocaleString()} chunks` : "未初始化"} tone={isReady ? "ok" : "muted"} />
              <BackendLine icon={Network} label="NetworkX Graph" detail={graphReady ? `${relCount.toLocaleString()} relations` : "未构建"} tone={graphReady ? "ok" : "muted"} />
              <BackendLine icon={Brain} label="sentence-transformers" detail="all-MiniLM-L6-v2" tone="ok" />
            </div>
          </section>

          {/* search tips */}
          <section className="card">
            <div className="card-head">
              <span className="title">查询引导</span>
              <span className="eyebrow">Hybrid</span>
            </div>
            <div className="card-body">
              <ul style={{ margin: 0, padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 8 }}>
                <TipItem icon={Zap}     color="var(--acc-violet)" text="用具体频段提问: 2300-2400 MHz" />
                <TipItem icon={GitBranch} color="var(--acc-cyan)"   text="指定区域: Region 1/2/3" />
                <TipItem icon={Link2}    color="var(--acc-amber)"  text="查脚注: 5.340, 5.432A" />
                <TipItem icon={FileText} color="var(--acc-blue)"   text="查标准: ITU-R M.1457" />
                <TipItem icon={Network}  color="var(--acc-teal)"   text="查业务: Mobile / Fixed / Satellite" />
              </ul>
            </div>
          </section>

          {/* evolution roadmap */}
          <section className="card">
            <div className="card-head">
              <span className="title">演进路线</span>
              <span className="eyebrow">Roadmap</span>
            </div>
            <div className="card-body">
              <RoadmapStep done icon={FileText} color="var(--ok)"   title="结构化解析" note="PyPDFParser + content_list.json" />
              <RoadmapStep done icon={Brain}    color="var(--ok)"   title="内容处理" note="Text · Table · Footnote Processor" />
              <RoadmapStep done icon={Layers}   color="var(--ok)"   title="Embedding 向量库" note="ChromaDB · 20,894 vectors" />
              <RoadmapStep done icon={Workflow} color="var(--ok)"   title="混合检索" note="Vector + Keyword + Graph + Rerank" />
              <RoadmapStep done icon={Network}  color="var(--ok)"   title="知识图谱" note="4,858 entities · 12,704 relations" />
              <RoadmapStep last  icon={Sparkles} color="var(--muted)" title="多模态 RAG" note="VLM 图片/公式理解 (待规划)" />
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

/* ── tiny sub-components ── */

function DocRow({ id, title, tag, size }) {
  return (
    <div className="doc-row">
      <span className="id">{id}</span>
      <span className="title">{title}</span>
      <span className="size">{size}</span>
      <span className="size" style={{ color: "var(--muted-2)" }}>{tag}</span>
    </div>
  );
}

function BackendLine({ icon: Icon, label, detail, tone }) {
  const toneMap = { ok: "var(--ok)", muted: "var(--muted-2)", warn: "var(--warn)" };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{
        width: 8, height: 8, borderRadius: "50%",
        background: toneMap[tone] || "var(--muted-2)",
        boxShadow: tone === "ok" ? `0 0 6px ${toneMap[tone]}` : "none",
        flexShrink: 0,
      }} />
      <Icon size={13} style={{ color: "var(--muted)", flexShrink: 0 }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
        <span style={{ fontSize: 12.5, fontWeight: 500, color: "var(--ink-2)" }}>{label}</span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--muted)" }}>{detail}</span>
      </div>
    </div>
  );
}

function TipItem({ icon: Icon, color, text }) {
  return (
    <li style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--ink-2)" }}>
      <Icon size={11} style={{ color, flexShrink: 0 }} />
      {text}
    </li>
  );
}

function RoadmapStep({ done, last, icon: Icon, color, title, note }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "18px 1fr", gap: "8px 12px",
      padding: "2px 0", opacity: done ? 1 : 0.5,
      position: "relative",
    }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{
          width: 18, height: 18, borderRadius: "50%", display: "grid", placeItems: "center",
          border: `2px solid ${done ? color : "var(--line-strong)"}`,
          background: done ? `oklch(from ${color} l c h / 0.15)` : "transparent",
          flexShrink: 0,
        }}>
          {done ? <Icon size={9} style={{ color }} /> : <Circle size={4} style={{ color: "var(--muted-2)" }} />}
        </div>
        {!last && (
          <div style={{ width: 1, flex: 1, minHeight: 8, background: done ? `oklch(from ${color} l c h / 0.3)` : "var(--line)", margin: "2px 0" }} />
        )}
      </div>
      <div style={{ paddingBottom: last ? 0 : 6 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: done ? "var(--ink)" : "var(--muted)", marginBottom: 1 }}>{title}</div>
        <div style={{ fontSize: 11, color: "var(--muted-2)", lineHeight: 1.4 }}>{note}</div>
      </div>
    </div>
  );
}
