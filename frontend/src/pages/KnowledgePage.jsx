import { useEffect, useState, useRef, useCallback } from "react";
import {
  FileText, HardDrive, Layers, Search, Zap,
  GitBranch, Network, Circle, Loader2, ArrowRight, Send,
  Workflow, Brain, Sparkles, Cpu, Hexagon, Link2,
  RotateCcw, Info, X,
  Upload, CheckCircle2, AlertCircle, Clock, File, Eye,
} from "lucide-react";
import Markdown from "../components/Markdown.jsx";
import { usePersistentState } from "../lib/usePersistentState.js";
import {
  runRagStream, fetchKbStats, fetchRagStatus, fetchRagDocs,
  fetchGraphEntities, fetchGraphEntity, uploadRagDoc, ragDocPdfUrl,
} from "../lib/api.js";

const STATS_TIMEOUT_MS = 60_000;
const FALLBACK_STATS = {
  status: "degraded",
  total_pdfs: 0,
  total_chunks: 0,
  total_chars: 0,
  rag_pipeline: { status: "unknown", vector_count: 0 },
  knowledge_graph: { status: "unknown", entity_count: 0, relation_count: 0 },
};

// Module-level cache so re-entering the page shows the last known stats
// instantly instead of flashing "正在连接后端..." on every mount. The fetch
// still runs in the background to refresh, but the UI never goes blank again.
let statsCache = null;
let ragStatusCache = null;

/* ── entity color palette (bright, high-contrast) ── */
const ETYPE = {
  FrequencyBand: { hex: "#a78bfa", bg: "rgba(167,139,250,0.15)", label: "FrequencyBand" },
  Standard:      { hex: "#22d3ee", bg: "rgba(34,211,238,0.15)", label: "Standard" },
  Footnote:      { hex: "#fbbf24", bg: "rgba(251,191,36,0.15)", label: "Footnote" },
  RadioService:  { hex: "#2dd4bf", bg: "rgba(45,212,191,0.15)", label: "RadioService" },
  Region:        { hex: "#60a5fa", bg: "rgba(96,165,250,0.15)", label: "Region" },
  Document:      { hex: "#f472b6", bg: "rgba(244,114,182,0.15)", label: "Document" },
};
const ETYPE_ICONS = { FrequencyBand: Zap, Standard: FileText, Footnote: Link2, RadioService: Network, Region: GitBranch, Document: File };
const REL_COLORS = { allocated_to: "#a78bfa", limited_by: "#fbbf24", applies_in: "#60a5fa", mentioned_in: "#f472b6" };

/* ── query example presets ── */
const QUERY_EXAMPLES = [
  "航空移动业务使用哪些频段？",
  "海上移动业务的频率分配包括哪些频段？",
  "射电天文业务受保护的频段有哪些？",
  "What frequency bands are allocated to the mobile-satellite service?",
];

/* ── shared PDF preview modal ── */
function PdfPreviewModal({ preview, onClose }) {
  if (!preview) return null;
  const url = ragDocPdfUrl(preview.docId, { filename: preview.filename, page: preview.page });
  return (
    <div onClick={onClose}
      style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.65)", backdropFilter: "blur(2px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div onClick={e => e.stopPropagation()}
        style={{ width: "min(960px, 92vw)", height: "92vh", display: "flex", flexDirection: "column", borderRadius: "var(--r-lg, 12px)", border: "1px solid var(--line-2)", background: "var(--bg-1, #15171f)", overflow: "hidden", boxShadow: "0 24px 64px rgba(0,0,0,0.6)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderBottom: "1px solid var(--line)", flexShrink: 0 }}>
          <FileText size={15} style={{ color: "var(--accent)", flexShrink: 0 }} />
          <span style={{ flex: 1, fontSize: 13, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{preview.filename}</span>
          {preview.page && <span className="pill" data-tone="info" style={{ fontSize: 10 }}>第 {preview.page} 页</span>}
          <a className="btn ghost sm" href={url} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}>新标签打开</a>
          <button className="btn ghost sm" onClick={onClose}><X size={14} /></button>
        </div>
        <iframe title={preview.filename} src={url} style={{ flex: 1, border: 0, width: "100%", background: "#525659" }} />
      </div>
    </div>
  );
}

/* ── animated counter ── */
function useCountUp(target, d = 800) {
  const [v, sv] = useState(0);
  const rf = useRef(null);
  useEffect(() => {
    const n = Number(target) || 0;
    if (!n) { sv(0); return; }
    const s = performance.now();
    const tick = (now) => { const t = Math.min((now - s) / d, 1); sv(Math.round((1 - Math.pow(1 - t, 3)) * n)); if (t < 1) rf.current = requestAnimationFrame(tick); };
    rf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rf.current);
  }, [target, d]);
  return v;
}

/* ── StatCard ── */
function StatCard({ icon: I, label, value, detail, tone }) {
  const a = useCountUp(value);
  return (
    <div className="stat-card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--muted)" }}>{label}</span>
        <div style={{ width: 28, height: 28, borderRadius: "var(--r-sm)", display: "grid", placeItems: "center", background: tone ? `rgba(${tone},0.12)` : "var(--accent-soft)", border: `1px solid ${tone ? `rgba(${tone},0.35)` : "oklch(0.84 0.14 195 / 0.4)"}`, color: tone ? `rgb(${tone})` : "var(--accent)" }}>
          <I size={14} />
        </div>
      </div>
      <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: "var(--ink)", letterSpacing: "-0.02em" }}>{value === "—" ? "—" : a.toLocaleString()}</div>
      <div style={{ marginTop: 4, fontSize: 11.5, color: "var(--muted-2)" }}>{detail}</div>
    </div>
  );
}

/* ── BarRow ── */
function BarRow({ label, value, max, color, icon: I }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 7 }}>
      <span style={{ width: 120, display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--ink-2)", flexShrink: 0 }}>
        {I && <I size={11} style={{ color }} />}{label}
      </span>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: "oklch(1 0 0 / 0.06)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", borderRadius: 3, background: `linear-gradient(90deg, ${color}, transparent)`, transition: "width 800ms var(--ease)" }} />
      </div>
      <span className="mono" style={{ width: 50, textAlign: "right", fontSize: 11, color: "var(--muted)", flexShrink: 0 }}>{value.toLocaleString()}</span>
    </div>
  );
}

/* ═══════════════════════════════════ OVERVIEW TAB ═══════════════════════════════════ */
function OverviewTab({ stats, ragReady, graphReady }) {
  const [query, setQuery] = usePersistentState("sc_kb_query", "");
  const [answer, setAnswer] = usePersistentState("sc_kb_answer", "");
  const [citations, setCitations] = usePersistentState("sc_kb_citations", []);
  const [debug, setDebug] = usePersistentState("sc_kb_debug", null);
  const [stages, setStages] = usePersistentState("sc_kb_stages", []);   // [{stage,label,status,counts}]
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState("");
  const [showDbg, setShowDbg] = useState(false);
  const [history, setHistory] = usePersistentState("sc_kb_history", []);
  const [ragStatus, setRagStatus] = useState(ragStatusCache);
  const [preview, setPreview] = useState(null);
  const vc = stats?.rag_pipeline?.vector_count || 0;
  const ec = stats?.knowledge_graph?.entity_count || 0;
  const rc = stats?.knowledge_graph?.relation_count || 0;
  const answerRef = useRef("");

  useEffect(() => {
    let alive = true;
    const tick = () => fetchRagStatus()
      .then(d => { if (!alive) return; ragStatusCache = d; setRagStatus(d); })
      .catch(() => {});
    tick();
    const iv = setInterval(tick, 30_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  const STAGE_LABELS = {
    query_analysis: "查询解析",
    retrieval: "混合检索",
    rerank: "重排序",
    answer: "生成回答",
  };

  function run(q) {
    const question = (q ?? query).trim();
    if (!question || busy) return;
    setBusy(true);
    setAnswer(""); answerRef.current = "";
    setCitations([]); setDebug(null); setErrMsg("");
    setStages([]);

    runRagStream(question, (ev) => {
      if (ev.type === "stage") {
        setStages((s) => [...s, { stage: ev.stage, label: STAGE_LABELS[ev.stage] || ev.label || ev.stage, status: "active" }]);
      } else if (ev.type === "stage_done") {
        setStages((s) => s.map((x) => x.stage === ev.stage ? { ...x, status: "done", counts: ev.counts, count: ev.count } : x));
      } else if (ev.type === "content") {
        answerRef.current += ev.data;
        setAnswer(answerRef.current);
      } else if (ev.type === "done") {
        setCitations(ev.citations || []);
        setDebug(ev.debug || null);
        setBusy(false);
        setHistory((h) => [question, ...h.filter((x) => x !== question)].slice(0, 6));
      } else if (ev.type === "error") {
        setErrMsg(ev.data || "查询失败");
        setBusy(false);
      }
    });
  }

  const steps = [
    { step: "Document Parsing",   icon: FileText,  note: "PyPDF + MinerU/Docling/PaddleOCR", status: ragReady ? "ready" : "planned" },
    { step: "Content Processing", icon: Brain,     note: "6 Modal Processors", status: ragReady ? "ready" : "planned" },
    { step: "Embedding + Store",  icon: Layers,    note: `${vc.toLocaleString()} vectors`, status: ragReady ? "ready" : "planned" },
    { step: "Hybrid Retrieval",   icon: Workflow,  note: "Vector + KW + Graph", status: ragReady ? "ready" : "planned" },
    { step: "Cited Answer",       icon: Sparkles,  note: "LangGraph → 带引用回答", status: ragReady ? "ready" : "planned" },
    { step: "Knowledge Graph",    icon: Network,   note: `${ec.toLocaleString()} entities`, status: graphReady ? "ready" : "planned" },
  ];

  const eb = stats?.knowledge_graph?.entity_breakdown || [];
  const me = Math.max(...eb.map(e => e.count), 1);
  const totalCharsM = ((stats?.total_chars || 0) / 1_000_000).toFixed(1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* stats row */}
      <div className="kb-stats">
        <StatCard icon={Zap} label="PDF 文档" value={stats?.total_pdfs || 0} detail="ITU-R 建议书 / 报告 / 规则" tone="167,139,250" />
        <StatCard icon={Layers} label="Chroma 向量" value={vc} detail="sentence-transformers · cosine" tone="34,211,238" />
        <StatCard icon={Network} label="图谱实体" value={ec} detail={`${rc.toLocaleString()} 条关系`} tone="167,139,250" />
        <StatCard icon={HardDrive} label="文本块" value={stats?.total_chunks || 0} detail={`${totalCharsM}M 字符`} tone="45,212,191" />
      </div>

      {/* pipeline + entity bars: side by side */}
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 14 }}>
        {/* pipeline */}
        <section className="card">
          <div className="card-head">
            <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}><Cpu size={14} style={{ color: "var(--accent)" }} />RAG 流水线</span>
            <span className="eyebrow">{ragReady ? "ALL READY" : "Partial"}</span>
          </div>
          <div className="card-body" style={{ padding: "14px 12px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 0, alignItems: "start" }}>
              {steps.map((p, i) => {
                const I = p.icon;
                return (
                  <div key={p.step} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: "8px 4px", position: "relative" }}>
                    {/* connector */}
                    {i < steps.length - 1 && (
                      <div style={{ position: "absolute", top: 20, right: -4, width: 8, height: 1, background: p.status === "ready" ? "var(--ok)" : "var(--line-strong)", zIndex: 0 }} />
                    )}
                    <div style={{ width: 28, height: 28, borderRadius: "50%", display: "grid", placeItems: "center", border: `2px solid ${p.status === "ready" ? "var(--ok)" : "var(--line-strong)"}`, background: p.status === "ready" ? "oklch(0.80 0.15 155 / 0.12)" : "transparent", color: p.status === "ready" ? "var(--ok)" : "var(--muted)", zIndex: 1 }}>
                      <I size={12} />
                    </div>
                    <span style={{ fontSize: 11.5, fontWeight: 600, color: p.status === "ready" ? "var(--ink)" : "var(--muted)", textAlign: "center", lineHeight: 1.3 }}>{p.step}</span>
                    <span className="mono" style={{ fontSize: 9.5, color: "var(--muted-2)", textAlign: "center", lineHeight: 1.3 }}>{p.note}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        {/* entity bars */}
        <section className="card">
          <div className="card-head">
            <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}><Hexagon size={14} style={{ color: "#a78bfa" }} />图谱实体</span>
            <span className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>{ec.toLocaleString()} total</span>
          </div>
          <div className="card-body" style={{ padding: "12px 14px" }}>
            {eb.map(e => { const c = ETYPE[e.type] || { hex: "var(--muted)" }; const Ic = ETYPE_ICONS[e.type] || Circle; return <BarRow key={e.type} label={e.type} value={e.count} max={me} color={c.hex} icon={Ic} />; })}
          </div>
        </section>
      </div>

      {/* index status */}
      {ragStatus && (ragStatus.registry.indexed > 0 || ragStatus.registry.failed > 0) && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <span className="pill" data-tone="ok"><span className="dot" />已索引: {ragStatus.registry.indexed}</span>
          {ragStatus.registry.failed > 0 && <span className="pill" data-tone="warn"><span className="dot" />失败: {ragStatus.registry.failed}</span>}
          {ragStatus.registry.indexing > 0 && <span className="pill" data-tone="info"><span className="dot" />索引进度: {ragStatus.registry.indexing}</span>}
          <span className="pill"><span className="dot" />Chroma: {ragStatus.health?.chroma ? "OK" : "Missing"}</span>
          <span className="pill"><span className="dot" />Graph: {ragStatus.health?.graph ? "OK" : "Missing"}</span>
        </div>
      )}
      {ragStatus?.recent_failures?.length > 0 && (
        <div style={{ padding: "8px 14px", borderRadius: "var(--r-md)", border: "1px solid oklch(0.84 0.14 80 / 0.35)", background: "oklch(0.84 0.14 80 / 0.06)" }}>
          {ragStatus.recent_failures.map((f, i) => (
            <div key={i} className="mono" style={{ fontSize: 11, color: "var(--warn)", marginBottom: 2 }}>
              {f.file}: {f.error}
            </div>
          ))}
        </div>
      )}

      {/* live query — visual center, largest */}
      <section className="card" style={{ borderColor: ragReady ? "oklch(0.80 0.15 155 / 0.25)" : "var(--line)", minHeight: 360 }}>
        <div className="card-head">
          <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}><Search size={14} style={{ color: "var(--accent)" }} />实时查询</span>
          <span className="eyebrow">POST /api/rag/stream · SSE</span>
        </div>
        <div className="card-body" style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 280 }}>
          {/* input area */}
          <div style={{ display: "flex", gap: 8 }}>
            <div className="comp-input" style={{ flex: 1, height: 44 }}>
              <input placeholder="输入频谱问题…  例: 航空移动业务使用哪些频段？"
                value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === "Enter" && run()} style={{ fontSize: 13.5 }} />
            </div>
            <button className="btn primary" onClick={() => run()} disabled={busy} style={{ height: 44, padding: "0 18px" }}>
              {busy ? <Loader2 size={14} className="spin" /> : <Send size={14} />}
              <span style={{ marginLeft: 4 }}>{busy ? "生成中" : "查询"}</span>
            </button>
          </div>

          {/* examples / history chips */}
          {!answer && !busy && !errMsg && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
              {(history.length ? history : QUERY_EXAMPLES).map((ex, i) => (
                <button key={i} onClick={() => { setQuery(ex); run(ex); }}
                  className="mono" style={{ height: 26, padding: "0 10px", borderRadius: 999, border: "1px solid var(--line-2)", background: "transparent", color: "var(--muted)", fontSize: 11, cursor: "pointer", display: "flex", alignItems: "center", gap: 5 }}>
                  {history.length ? <Clock size={10} /> : <Sparkles size={10} />}{ex}
                </button>
              ))}
            </div>
          )}

          {/* stage progress */}
          {stages.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 14 }}>
              {stages.map((s, i) => (
                <span key={i} className="pill" data-tone={s.status === "done" ? "ok" : "info"} style={{ fontSize: 11 }}>
                  {s.status === "done" ? <CheckCircle2 size={11} /> : <Loader2 size={11} className="spin" />}
                  {s.label}
                  {s.counts && <span className="mono" style={{ marginLeft: 4, color: "var(--muted-2)" }}>v{s.counts.vector ?? "?"}/k{s.counts.keyword ?? "?"}/g{s.counts.graph ?? "?"}</span>}
                  {s.count != null && <span className="mono" style={{ marginLeft: 4, color: "var(--muted-2)" }}>{s.count}</span>}
                </span>
              ))}
            </div>
          )}

          {/* error */}
          {errMsg && (
            <div style={{ marginTop: 14, padding: "10px 14px", borderRadius: "var(--r-md)", border: "1px solid oklch(0.65 0.2 25 / 0.4)", background: "oklch(0.65 0.2 25 / 0.08)", display: "flex", alignItems: "center", gap: 8 }}>
              <AlertCircle size={14} style={{ color: "var(--danger, #f87171)", flexShrink: 0 }} />
              <span style={{ fontSize: 12.5, color: "var(--danger, #f87171)" }}>{errMsg}</span>
            </div>
          )}

          {/* results — streaming answer */}
          {(answer || (busy && stages.length > 0)) && (
            <div style={{ flex: 1, marginTop: 14, padding: 14, borderRadius: "var(--r-md)", border: "1px solid var(--line)", background: "oklch(0.20 0.025 252)", overflowY: "auto", minHeight: 200 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, fontFamily: "var(--font-mono)", fontSize: 10.5, letterSpacing: "0.08em", color: "var(--muted)", textTransform: "uppercase" }}>
                <Circle size={6} style={{ color: busy ? "var(--accent)" : "var(--ok)", fill: busy ? "var(--accent)" : "var(--ok)" }} />
                {busy ? "生成中…" : `${citations?.length || 0} 引用来源`}
                {debug && <span style={{ marginLeft: "auto", color: "var(--muted-2)" }}>vec={debug.vector_count} kw={debug.keyword_count} graph={debug.graph_count}</span>}
                {debug && <button className="btn ghost sm" onClick={() => setShowDbg(!showDbg)} style={{ fontSize: 10, padding: "0 6px" }}>{showDbg ? "隐藏" : "调试"}</button>}
              </div>
              <div style={{ fontSize: 13.5, lineHeight: 1.7, color: "var(--ink)", maxWidth: "100%" }}>
                <Markdown>{answer}</Markdown>
                {busy && <span className="cursor-blink" />}
              </div>
              {showDbg && debug && (
                <pre className="mono" style={{ marginTop: 10, padding: 10, borderRadius: "var(--r-md)", border: "1px solid var(--line)", background: "oklch(0.16 0.02 252)", fontSize: 10.5, color: "var(--muted-2)", maxHeight: 180, overflowY: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{JSON.stringify(debug, null, 2)}</pre>
              )}
              {citations?.length > 0 && (
                <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                    <FileText size={11} style={{ color: "var(--muted)" }} />
                    <span className="mono" style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--muted)" }}>原文出处 · 点击查看 PDF</span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {citations.slice(0, 8).map((c, i) => {
                      const fname = (c.source || "").split("/").pop() || c.doc_id || "未知文档";
                      const hasPage = c.page != null && c.page !== "" && c.page !== "?";
                      const rel = typeof c.relevance === "number" ? c.relevance : null;
                      const open = () => setPreview({ docId: c.doc_id || "_", filename: fname, page: hasPage ? c.page : undefined });
                      return (
                        <button key={i} onClick={open}
                          style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderRadius: "var(--r-md)", border: "1px solid var(--line)", background: "oklch(0.18 0.02 252)", cursor: "pointer", textAlign: "left", transition: "border-color 0.15s ease, background 0.15s ease" }}
                          onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.background = "oklch(0.22 0.03 252)"; }}
                          onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.background = "oklch(0.18 0.02 252)"; }}>
                          <span className="mono" style={{ fontSize: 10, color: "var(--accent)", flexShrink: 0 }}>[{i + 1}]</span>
                          <span style={{ flex: 1, fontSize: 12, color: "var(--ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{fname}</span>
                          {hasPage
                            ? <span className="pill" data-tone="ok" style={{ fontSize: 9.5, flexShrink: 0 }}>第 {c.page} 页</span>
                            : <span className="pill" style={{ fontSize: 9.5, flexShrink: 0, color: "var(--muted)" }}>候选页</span>}
                          {rel != null && <span className="mono" style={{ fontSize: 9.5, color: "var(--muted-2)", flexShrink: 0, width: 52, textAlign: "right" }}>{(rel * 100).toFixed(0)}%</span>}
                          <Eye size={12} style={{ color: "var(--muted-2)", flexShrink: 0 }} />
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      <PdfPreviewModal preview={preview} onClose={() => setPreview(null)} />
    </div>
  );
}

/* ═══════════════════════════════════ KNOWLEDGE GRAPH TAB ═══════════════════════════════════ */

/* ── tooltip component for canvas nodes ── */
function GraphTooltip({ node, pos }) {
  if (!node) return null;
  const c = ETYPE[node.type] || {};
  return (
    <div style={{ position: "absolute", left: pos.x + 16, top: pos.y + 12, zIndex: 20,
      padding: "8px 12px", borderRadius: "var(--r-md)", border: `1px solid ${c.hex || "var(--line-2)"}`,
      background: "oklch(0.22 0.03 252 / 0.96)", boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
      maxWidth: 280, pointerEvents: "none" }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: c.hex || "var(--ink)", marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{node.label}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="pill" style={{ fontSize: 9.5, borderColor: `${c.hex}55`, color: c.hex }}>{node.type}</span>
        {node.degree !== undefined && <span className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>{node.degree} 连接</span>}
      </div>
    </div>
  );
}

function GraphTab({ stats, graphReady }) {
  const canvasRef = useRef(null);
  const wrapRef = useRef(null);
  const [entities, setEntities] = useState([]);
  const [relations, setRelations] = useState([]);
  const [filterType, setFilterType] = useState("");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(150);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);
  const [selRels, setSelRels] = useState([]);
  const [tooltip, setTooltip] = useState(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  // simulation refs (persist across renders)
  const nodesRef = useRef([]);
  const edgesRef = useRef([]);
  const animRef = useRef(null);
  const viewRef = useRef({ scale: 1, tx: 0, ty: 0 }); // pan/zoom transform
  const hoverRef = useRef(null);   // hovered node id
  const selectedRef = useRef(null); // selected node id (for highlight)
  const dragRef = useRef(null);    // { node } when dragging a node
  const panRef = useRef(null);     // { x, y } when panning
  const alphaRef = useRef(1);      // simulation "energy"

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fetchGraphEntities({ type: filterType, search, limit });
      setEntities(d.entities || []);
      setRelations(d.relations || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [filterType, search, limit]);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  async function clickEntity(name) {
    selectedRef.current = name;
    try {
      const d = await fetchGraphEntity(name);
      setSelected(d.entity);
      setSelRels(d.relations || []);
    } catch (e) { console.error(e); }
  }

  // helper: screen → world coords
  const toWorld = (sx, sy) => {
    const v = viewRef.current;
    return { x: (sx - v.tx) / v.scale, y: (sy - v.ty) / v.scale };
  };
  const pickNode = (sx, sy) => {
    const { x, y } = toWorld(sx, sy);
    const nodes = nodesRef.current;
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const dx = x - n.x, dy = y - n.y;
      if (dx * dx + dy * dy < (n.r + 3) * (n.r + 3)) return n;
    }
    return null;
  };

  /* ── Obsidian-style force simulation + render ── */
  useEffect(() => {
    if (entities.length === 0) { nodesRef.current = []; edgesRef.current = []; return; }
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext("2d");

    // degree map for node sizing
    const degree = {};
    for (const r of relations) { degree[r.source] = (degree[r.source] || 0) + 1; degree[r.target] = (degree[r.target] || 0) + 1; }
    const maxDeg = Math.max(1, ...Object.values(degree));

    const nMap = {};
    const nodes = entities.map((e) => {
      const deg = degree[e.name] || 0;
      const r = 4 + Math.sqrt(deg / maxDeg) * 12; // 4..16 px by degree
      const n = {
        id: e.name, type: e.type, label: e.name, degree: deg, r,
        x: (Math.random() - 0.5) * 400, y: (Math.random() - 0.5) * 400, vx: 0, vy: 0,
        color: (ETYPE[e.type] || {}).hex || "#888",
      };
      nMap[e.name] = n;
      return n;
    });

    const edgeSet = new Set();
    const edges = [];
    const adj = {}; // adjacency for highlight
    for (const r of relations) {
      if (!nMap[r.source] || !nMap[r.target]) continue;
      const key = [r.source, r.target].sort().join("||");
      if (edgeSet.has(key)) continue;
      edgeSet.add(key);
      edges.push({ source: nMap[r.source], target: nMap[r.target], type: r.relation });
      (adj[r.source] ||= new Set()).add(r.target);
      (adj[r.target] ||= new Set()).add(r.source);
    }

    nodesRef.current = nodes; edgesRef.current = edges;
    alphaRef.current = 1;

    // fit view to canvas initially
    const fit = () => {
      const W = cvs.offsetWidth, H = cvs.offsetHeight;
      viewRef.current = { scale: 1, tx: W / 2, ty: H / 2 };
    };
    fit();

    let running = true;
    const damp = 0.86, springLen = 70, springK = 0.03, rep = 1400, gravity = 0.012;

    function step() {
      if (!running) return;
      const cvsEl = canvasRef.current;
      if (!cvsEl) return;
      const dpr = window.devicePixelRatio || 1;
      const W = cvsEl.offsetWidth, H = cvsEl.offsetHeight;
      if (cvsEl.width !== W * dpr || cvsEl.height !== H * dpr) { cvsEl.width = W * dpr; cvsEl.height = H * dpr; }

      const alpha = alphaRef.current;
      if (alpha > 0.005) {
        // gravity toward origin (world center)
        for (const n of nodes) { n.vx -= n.x * gravity * alpha; n.vy -= n.y * gravity * alpha; }
        // repulsion (Barnes-Hut would be better, but n is bounded by limit)
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            const a = nodes[i], b = nodes[j];
            const dx = b.x - a.x, dy = b.y - a.y;
            const d2 = dx * dx + dy * dy || 1;
            const d = Math.sqrt(d2);
            const f = (rep / d2) * alpha;
            const fx = (dx / d) * f, fy = (dy / d) * f;
            a.vx -= fx; a.vy -= fy; b.vx += fx; b.vy += fy;
          }
        }
        // springs
        for (const e of edges) {
          const dx = e.target.x - e.source.x, dy = e.target.y - e.source.y;
          const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const f = (d - springLen) * springK * alpha;
          const fx = (dx / d) * f, fy = (dy / d) * f;
          e.source.vx += fx; e.source.vy += fy; e.target.vx -= fx; e.target.vy -= fy;
        }
        for (const n of nodes) {
          if (dragRef.current && dragRef.current.node === n) continue;
          n.vx *= damp; n.vy *= damp; n.x += n.vx; n.y += n.vy;
        }
        alphaRef.current *= 0.992; // cool down
      }

      // ── render ──
      const v = viewRef.current;
      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, W, H);
      ctx.translate(v.tx, v.ty);
      ctx.scale(v.scale, v.scale);

      const hoverId = hoverRef.current;
      const selId = selectedRef.current;
      // selection wins: once a node is selected, hover no longer steals the highlight.
      const focusId = selId || hoverId;
      const focusSet = focusId ? (adj[focusId] || new Set()) : null;
      const isDim = (id) => focusId && id !== focusId && !(focusSet && focusSet.has(id));

      // edges
      for (const e of edges) {
        const hot = focusId && (e.source.id === focusId || e.target.id === focusId);
        ctx.beginPath();
        ctx.moveTo(e.source.x, e.source.y);
        ctx.lineTo(e.target.x, e.target.y);
        if (hot) { ctx.strokeStyle = "oklch(0.85 0.12 195 / 0.55)"; ctx.lineWidth = 1.2 / v.scale; }
        else { ctx.strokeStyle = focusId ? "oklch(1 0 0 / 0.03)" : "oklch(1 0 0 / 0.10)"; ctx.lineWidth = 0.6 / v.scale; }
        ctx.stroke();
      }
      // nodes
      for (const n of nodes) {
        const dim = isDim(n.id);
        ctx.globalAlpha = dim ? 0.25 : 1;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = n.color;
        ctx.fill();
        if (n.id === focusId) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 / v.scale; ctx.stroke(); }
        else { ctx.strokeStyle = "oklch(0.16 0.02 252)"; ctx.lineWidth = 1.2 / v.scale; ctx.stroke(); }
        // labels: focus node always; when a node is *selected*, also label its neighbors.
        const isNeighborLabel = selId && focusSet && focusSet.has(n.id);
        if (n.id === focusId || isNeighborLabel) {
          ctx.globalAlpha = 1;
          ctx.fillStyle = n.id === focusId ? "oklch(0.96 0.01 252)" : "oklch(0.82 0.01 252)";
          ctx.font = `${Math.max(10, (n.id === focusId ? 12 : 10.5) / v.scale)}px var(--font-mono, monospace)`;
          ctx.textAlign = "center";
          const lbl = n.label.length > 28 ? n.label.slice(0, 26) + "…" : n.label;
          ctx.fillText(lbl, n.x, n.y + n.r + 12 / v.scale);
        }
      }
      ctx.globalAlpha = 1;
      ctx.restore();
      animRef.current = requestAnimationFrame(step);
    }
    step();
    return () => { running = false; if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, [entities, relations]);

  /* ── pointer handlers: hover, drag node, pan, zoom ── */
  const onPointerDown = useCallback((e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    const hit = pickNode(sx, sy);
    if (hit) {
      dragRef.current = { node: hit, moved: false };
      alphaRef.current = Math.max(alphaRef.current, 0.3);
    } else {
      panRef.current = { x: sx, y: sy, tx: viewRef.current.tx, ty: viewRef.current.ty };
    }
    canvasRef.current.setPointerCapture?.(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    setMousePos({ x: sx, y: sy });

    if (dragRef.current) {
      const w = toWorld(sx, sy);
      const n = dragRef.current.node;
      n.x = w.x; n.y = w.y; n.vx = 0; n.vy = 0;
      dragRef.current.moved = true;
      alphaRef.current = Math.max(alphaRef.current, 0.2);
      return;
    }
    if (panRef.current) {
      const p = panRef.current;
      viewRef.current.tx = p.tx + (sx - p.x);
      viewRef.current.ty = p.ty + (sy - p.y);
      return;
    }
    // hover
    const hit = pickNode(sx, sy);
    hoverRef.current = hit ? hit.id : null;
    setTooltip(hit ? { ...hit } : null);
    canvasRef.current.style.cursor = hit ? "pointer" : "grab";
  }, []);

  const onPointerUp = useCallback((e) => {
    const wasDrag = dragRef.current && dragRef.current.moved;
    const clickedNode = dragRef.current && !dragRef.current.moved ? dragRef.current.node : null;
    const wasPanning = panRef.current && (Math.abs(panRef.current.tx - viewRef.current.tx) > 2 || Math.abs(panRef.current.ty - viewRef.current.ty) > 2);
    dragRef.current = null;
    panRef.current = null;
    canvasRef.current.releasePointerCapture?.(e.pointerId);

    if (wasDrag) return;
    if (clickedNode) {
      // toggle: clicking the already-selected node clears the highlight
      if (selectedRef.current === clickedNode.id) {
        selectedRef.current = null;
        setSelected(null);
        setSelRels([]);
      } else {
        clickEntity(clickedNode.id);
      }
    } else if (!wasPanning) {
      // click on empty space (not a pan) → clear highlight
      if (selectedRef.current) {
        selectedRef.current = null;
        setSelected(null);
        setSelRels([]);
      }
    }
  }, []);

  // wheel zoom — native non-passive listener so we only preventDefault inside
  // the canvas (page keeps scrolling normally when the cursor is outside).
  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const onWheelNative = (e) => {
      e.preventDefault(); // only fires for events on the canvas itself
      const rect = cvs.getBoundingClientRect();
      const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
      const v = viewRef.current;
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const newScale = Math.max(0.2, Math.min(5, v.scale * factor));
      v.tx = sx - (sx - v.tx) * (newScale / v.scale);
      v.ty = sy - (sy - v.ty) * (newScale / v.scale);
      v.scale = newScale;
    };
    cvs.addEventListener("wheel", onWheelNative, { passive: false });
    return () => cvs.removeEventListener("wheel", onWheelNative);
  }, []);

  const resetView = () => {
    const cvs = canvasRef.current;
    if (cvs) viewRef.current = { scale: 1, tx: cvs.offsetWidth / 2, ty: cvs.offsetHeight / 2 };
    alphaRef.current = 1;
  };

  const types = ["FrequencyBand", "Standard", "Footnote", "Document", "RadioService", "Region"];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 14 }}>
      {/* left: canvas + controls */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {/* controls bar */}
        <div className="card">
          <div className="card-body" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", flexWrap: "wrap" }}>
            <span className="mono" style={{ fontSize: 10, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--muted)", marginRight: 4 }}>类型</span>
            {types.map(t => {
              const c = ETYPE[t] || {};
              const active = filterType === t;
              return (
                <button key={t} onClick={() => { setFilterType(active ? "" : t); setSelected(null); selectedRef.current = null; }}
                  style={{ height: 26, padding: "0 10px", borderRadius: 999, border: `1px solid ${active ? c.hex : "var(--line-2)"}`, cursor: "pointer", background: active ? c.bg : "transparent", color: active ? c.hex : "var(--muted)", fontSize: 11, fontWeight: 500, transition: "all 0.15s ease" }}>{t}</button>
              );
            })}
            <div style={{ flex: 1, minWidth: 80 }} />
            <div className="comp-input" style={{ width: 160, height: 28 }}>
              <input placeholder="搜索实体…" value={search} onChange={e => setSearch(e.target.value)} style={{ fontSize: 11.5 }} />
            </div>
            <span className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>节点</span>
            <select value={limit} onChange={e => setLimit(Number(e.target.value))}
              style={{ height: 28, borderRadius: 6, background: "transparent", border: "1px solid var(--line-2)", color: "var(--ink-2)", fontSize: 11, padding: "0 6px" }}>
              {[80, 150, 300, 500].map(v => <option key={v} value={v} style={{ background: "#1a1d2a" }}>{v}</option>)}
            </select>
            <button className="btn ghost sm" onClick={resetView} title="重置视图"><RotateCcw size={12} /></button>
          </div>
        </div>

        {/* canvas */}
        <div ref={wrapRef} className="card" style={{ flex: 1, minHeight: 520, position: "relative", overflow: "hidden" }}>
          {loading && (
            <div style={{ position: "absolute", top: 12, left: 14, zIndex: 2, display: "flex", alignItems: "center", gap: 6, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--muted)" }}><Loader2 size={12} className="spin" />loading…</div>
          )}
          <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block", cursor: "grab", touchAction: "none" }}
            onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
            onPointerLeave={() => { setTooltip(null); hoverRef.current = null; panRef.current = null; dragRef.current = null; }} />
          <GraphTooltip node={tooltip} pos={mousePos} />
          {/* hint */}
          <div style={{ position: "absolute", top: 10, right: 14, fontFamily: "var(--font-mono)", fontSize: 9.5, color: "var(--muted-2)", letterSpacing: "0.04em", pointerEvents: "none", textAlign: "right", lineHeight: 1.5 }}>
            滚轮缩放 · 拖拽平移 · 拖动节点 · 点击查看
          </div>
          {/* legend */}
          <div style={{ position: "absolute", bottom: 10, right: 14, display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "flex-end", maxWidth: "70%", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--muted)", letterSpacing: "0.06em", pointerEvents: "none" }}>
            {types.map(t => <span key={t} style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: (ETYPE[t] || {}).hex }} />{t}</span>)}
          </div>
        </div>

        {/* summary bar */}
        <div style={{ display: "flex", gap: 10 }}>
          {types.map(t => {
            const cnt = entities.filter(e => e.type === t).length;
            return (
              <div key={t} className="stat-card" style={{ flex: 1, padding: "8px 12px" }}>
                <div className="mono" style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--muted)" }}>{t}</div>
                <div className="mono" style={{ marginTop: 4, fontSize: 18, fontWeight: 700, color: (ETYPE[t] || {}).hex }}>{cnt}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* right: detail panel */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {selected ? (
          <section className="card" style={{ flex: 1 }}>
            <div className="card-head">
              <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {selected.type && ETYPE_ICONS[selected.type] && (() => { const I = ETYPE_ICONS[selected.type]; return <I size={14} style={{ color: (ETYPE[selected.type] || {}).hex }} />; })()}
                <span style={{ color: (ETYPE[selected.type] || {}).hex }}>{selected.name}</span>
              </span>
              <button className="btn ghost sm" onClick={() => { setSelected(null); setSelRels([]); selectedRef.current = null; }}><X size={12} /></button>
            </div>
            <div className="card-body" style={{ overflowY: "auto", maxHeight: "calc(100vh - 300px)" }}>
              <div style={{ marginBottom: 10 }}>
                <span className="pill" data-tone="info" style={{ borderColor: `${(ETYPE[selected.type] || {}).hex}55`, color: (ETYPE[selected.type] || {}).hex }}>{selected.type}</span>
                {selected.evidence_block_id && <span className="mono" style={{ marginLeft: 8, fontSize: 10, color: "var(--muted-2)" }}>block: {selected.evidence_block_id}</span>}
              </div>
              <div className="section-head" style={{ marginBottom: 8 }}><span className="eyebrow">Relations ({selRels.length})</span></div>
              {selRels.length === 0 ? (
                <p style={{ fontSize: 12.5, color: "var(--muted)" }}>无关系数据</p>
              ) : (
                selRels.slice(0, 40).map((r, i) => {
                  const isSrc = r.source === selected.name;
                  const other = isSrc ? r.target : r.source;
                  const rcol = REL_COLORS[r.relation] || "var(--muted)";
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 0", borderBottom: "1px solid var(--line)", cursor: "pointer", transition: "background 0.15s ease" }}
                      onClick={() => clickEntity(other)} onMouseEnter={e => e.currentTarget.style.background = "oklch(1 0 0 / 0.03)"} onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <span style={{ fontSize: 10, color: rcol, fontWeight: 600, minWidth: 72, fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>{r.relation}</span>
                      <ArrowRight size={10} style={{ color: "var(--muted-2)", flexShrink: 0 }} />
                      <span style={{ fontSize: 12, color: "var(--ink-2)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{other}</span>
                    </div>
                  );
                })
              )}
            </div>
          </section>
        ) : (
          <>
            {/* graph overview — big numbers */}
            <section className="card">
              <div className="card-head"><span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}><Info size={14} style={{ color: "var(--accent)" }} />图谱概览</span></div>
              <div className="card-body" style={{ padding: "14px" }}>
                <div style={{ display: "flex", gap: 10 }}>
                  <div style={{ flex: 1, padding: "12px 14px", borderRadius: "var(--r-md)", background: "rgba(167,139,250,0.08)", border: "1px solid rgba(167,139,250,0.25)" }}>
                    <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--muted)" }}>实体</div>
                    <div className="mono" style={{ marginTop: 4, fontSize: 24, fontWeight: 700, color: "#a78bfa", letterSpacing: "-0.02em" }}>{(stats?.knowledge_graph?.entity_count || 0).toLocaleString()}</div>
                  </div>
                  <div style={{ flex: 1, padding: "12px 14px", borderRadius: "var(--r-md)", background: "rgba(45,212,191,0.08)", border: "1px solid rgba(45,212,191,0.25)" }}>
                    <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--muted)" }}>关系</div>
                    <div className="mono" style={{ marginTop: 4, fontSize: 24, fontWeight: 700, color: "#2dd4bf", letterSpacing: "-0.02em" }}>{(stats?.knowledge_graph?.relation_count || 0).toLocaleString()}</div>
                  </div>
                </div>
                <div className="mono" style={{ marginTop: 10, fontSize: 10.5, color: "var(--muted-2)" }}>当前视图: {entities.length} 节点 · {relations.length} 边</div>
              </div>
            </section>

            {/* entity type distribution */}
            <section className="card">
              <div className="card-head"><span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}><Hexagon size={14} style={{ color: "#a78bfa" }} />实体类型分布</span></div>
              <div className="card-body" style={{ padding: "10px 14px" }}>
                {(() => {
                  const counts = types.map(t => ({ t, cnt: entities.filter(e => e.type === t).length }));
                  const maxC = Math.max(...counts.map(c => c.cnt), 1);
                  return counts.map(({ t, cnt }) => {
                    const c = ETYPE[t] || {};
                    const Ic = ETYPE_ICONS[t] || Circle;
                    return (
                      <div key={t} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
                        <Ic size={11} style={{ color: c.hex, flexShrink: 0 }} />
                        <span style={{ width: 92, fontSize: 11, color: "var(--ink-2)", flexShrink: 0 }}>{t}</span>
                        <div style={{ flex: 1, height: 5, borderRadius: 3, background: "oklch(1 0 0 / 0.06)", overflow: "hidden" }}>
                          <div style={{ width: `${(cnt / maxC) * 100}%`, height: "100%", borderRadius: 3, background: `linear-gradient(90deg, ${c.hex}, ${c.hex}66)`, transition: "width 0.6s var(--ease)" }} />
                        </div>
                        <span className="mono" style={{ width: 36, textAlign: "right", fontSize: 10.5, color: "var(--muted)" }}>{cnt}</span>
                      </div>
                    );
                  });
                })()}
              </div>
            </section>

            {/* relation types */}
            <section className="card">
              <div className="card-head"><span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}><GitBranch size={14} style={{ color: "#2dd4bf" }} />关系类型</span></div>
              <div className="card-body" style={{ padding: "10px 14px" }}>
                {(() => {
                  const counts = Object.keys(REL_COLORS).map(type => ({ type, cnt: relations.filter(r => r.relation === type).length }));
                  const present = counts.filter(c => c.cnt > 0);
                  const rows = present.length ? present : counts;
                  const maxR = Math.max(...rows.map(c => c.cnt), 1);
                  return rows.map(({ type, cnt }) => (
                    <div key={type} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <span className="mono" style={{ width: 92, fontSize: 10.5, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{type}</span>
                      <div style={{ flex: 1, height: 4, borderRadius: 2, background: "oklch(1 0 0 / 0.06)", overflow: "hidden" }}>
                        <div style={{ width: `${(cnt / maxR) * 100}%`, height: "100%", borderRadius: 2, background: REL_COLORS[type], transition: "width 0.6s var(--ease)" }} />
                      </div>
                      <span className="mono" style={{ width: 44, textAlign: "right", fontSize: 10.5, color: "var(--ink-2)" }}>{cnt}</span>
                    </div>
                  ));
                })()}
              </div>
            </section>

            {/* interaction hints */}
            <section className="card">
              <div className="card-head"><span className="title">操作指南</span></div>
              <div className="card-body">
                <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 7 }}>
                  {[
                    "悬停节点：高亮其关联，其余淡出",
                    "点击节点：查看详情与关系列表",
                    "再次点击 / 点空白：取消高亮",
                    "滚轮：以光标为中心缩放",
                    "拖拽空白：平移视图",
                    "拖拽节点：调整布局",
                  ].map((t, i) => (
                    <li key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: "var(--ink-2)" }}>
                      <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--accent)", flexShrink: 0 }} />{t}
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════ DOCS TAB ═══════════════════════════════════ */
const DOC_STATUS = {
  indexed:  { hex: "var(--ok)", icon: CheckCircle2, label: "已索引" },
  indexing: { hex: "var(--accent)", icon: Loader2, label: "索引中" },
  failed:   { hex: "var(--danger, #f87171)", icon: AlertCircle, label: "失败" },
};
const PAGE_SIZE = 30;

function DocsTab() {
  const [docs, setDocs] = useState([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState({});
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploadState, setUploadState] = useState(null); // {status, msg}
  const [preview, setPreview] = useState(null); // {docId, filename}
  const fileRef = useRef(null);
  const debounceRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fetchRagDocs({ status: statusFilter, search, limit: PAGE_SIZE, offset });
      setDocs(d.docs || []);
      setTotal(d.total || 0);
      setCounts(d.status_counts || {});
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [statusFilter, search, offset]);

  useEffect(() => { load(); }, [load]);

  // debounce search → reset offset
  function onSearchChange(v) {
    setSearch(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setOffset(0), 350);
  }

  async function onUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadState({ status: "busy", msg: `正在解析 ${file.name}…` });
    try {
      const r = await uploadRagDoc(file);
      if (r.errors?.length) {
        setUploadState({ status: "warn", msg: `${file.name}: ${r.errors[0]}` });
      } else {
        setUploadState({ status: "ok", msg: `${file.name} 已入库 · ${r.block_count} 块 · ${r.entities_added || 0} 实体` });
        setOffset(0); load();
      }
    } catch (err) {
      setUploadState({ status: "err", msg: err.message });
    }
    if (fileRef.current) fileRef.current.value = "";
  }

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* status summary + upload */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        <span className="pill" data-tone="ok"><span className="dot" />已索引 {(counts.indexed || 0).toLocaleString()}</span>
        {counts.indexing > 0 && <span className="pill" data-tone="info"><span className="dot" />索引中 {counts.indexing}</span>}
        {counts.failed > 0 && <span className="pill" data-tone="warn"><span className="dot" />失败 {counts.failed}</span>}
        <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>共 {total.toLocaleString()} 篇</span>
        <div style={{ flex: 1 }} />
        <input ref={fileRef} type="file" accept=".pdf" onChange={onUpload} style={{ display: "none" }} />
        <button className="btn primary" onClick={() => fileRef.current?.click()} disabled={uploadState?.status === "busy"} style={{ height: 36 }}>
          {uploadState?.status === "busy" ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
          <span style={{ marginLeft: 4 }}>上传 PDF</span>
        </button>
      </div>

      {uploadState && uploadState.status !== "busy" && (
        <div style={{ padding: "8px 14px", borderRadius: "var(--r-md)", fontSize: 12.5,
          border: `1px solid ${uploadState.status === "ok" ? "oklch(0.80 0.15 155 / 0.4)" : "oklch(0.65 0.2 25 / 0.4)"}`,
          background: uploadState.status === "ok" ? "oklch(0.80 0.15 155 / 0.08)" : "oklch(0.65 0.2 25 / 0.08)",
          color: uploadState.status === "ok" ? "var(--ok)" : "var(--danger, #f87171)" }}>
          {uploadState.msg}
        </div>
      )}

      {/* filters */}
      <div className="card">
        <div className="card-body" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", flexWrap: "wrap" }}>
          {["", "indexed", "indexing", "failed"].map(s => {
            const active = statusFilter === s;
            const conf = DOC_STATUS[s];
            return (
              <button key={s || "all"} onClick={() => { setStatusFilter(s); setOffset(0); }}
                style={{ height: 26, padding: "0 12px", borderRadius: 999, border: `1px solid ${active ? "var(--accent)" : "var(--line-2)"}`, cursor: "pointer", background: active ? "var(--accent-soft)" : "transparent", color: active ? "var(--accent)" : "var(--muted)", fontSize: 11, fontWeight: 500 }}>
                {s ? (conf?.label || s) : "全部"}
              </button>
            );
          })}
          <div style={{ flex: 1, minWidth: 120 }} />
          <div className="comp-input" style={{ width: 220, height: 30 }}>
            <Search size={12} style={{ color: "var(--muted-2)" }} />
            <input placeholder="搜索文件名…" value={search} onChange={e => onSearchChange(e.target.value)} style={{ fontSize: 12 }} />
          </div>
        </div>
      </div>

      {/* doc list */}
      <section className="card" style={{ minHeight: 400 }}>
        <div className="card-body" style={{ padding: 0 }}>
          {loading ? (
            <div style={{ padding: 40, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, color: "var(--muted)" }}><Loader2 size={14} className="spin" />加载中…</div>
          ) : docs.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>无匹配文档</div>
          ) : (
            docs.map((d, i) => {
              const conf = DOC_STATUS[d.status] || { hex: "var(--muted)", icon: Circle, label: d.status };
              const SI = conf.icon;
              const openPreview = () => setPreview({ docId: d.doc_id, filename: d.filename || d.doc_id });
              return (
                <div key={d.doc_id || i} className="doc-row"
                  style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 16px", borderBottom: i < docs.length - 1 ? "1px solid var(--line)" : "none", cursor: "pointer", transition: "background 0.15s ease" }}
                  onClick={openPreview}
                  onMouseEnter={e => e.currentTarget.style.background = "oklch(1 0 0 / 0.03)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <FileText size={15} style={{ color: "var(--muted-2)", flexShrink: 0 }} />
                  <span style={{ flex: 1, fontSize: 13, color: "var(--ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.filename || d.doc_id}</span>
                  {d.parser && <span className="mono" style={{ fontSize: 10, color: "var(--muted-2)" }}>{d.parser}</span>}
                  <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: conf.hex, minWidth: 64 }}>
                    <SI size={12} className={d.status === "indexing" ? "spin" : ""} />{conf.label}
                  </span>
                  <button className="btn ghost sm" onClick={(e) => { e.stopPropagation(); openPreview(); }} style={{ padding: "0 8px", flexShrink: 0 }} title="预览 PDF">
                    <Eye size={13} />
                  </button>
                </div>
              );
            })
          )}
        </div>
      </section>

      {/* pagination */}
      {pages > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 12 }}>
          <button className="btn ghost sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</button>
          <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>{page} / {pages}</span>
          <button className="btn ghost sm" disabled={page >= pages} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</button>
        </div>
      )}

      {/* PDF preview modal */}
      <PdfPreviewModal preview={preview} onClose={() => setPreview(null)} />
    </div>
  );
}

/* ═══════════════════════════════════ MAIN PAGE ═══════════════════════════════════ */
export default function KnowledgePage() {
  const [tab, setTab] = useState("overview");
  const [stats, setStats] = useState(statsCache);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    const loadStats = () =>
      fetchKbStats({ timeout: STATS_TIMEOUT_MS })
        .then(d => { if (alive) { setErr(null); statsCache = d; setStats(d); } })
        .catch(e => {
          if (!alive) return;
          setErr(e.message === "" ? "请求超时" : e.message);
          setStats(prev => prev || statsCache || FALLBACK_STATS);
        });
    loadStats();
    // refresh periodically so live ingest progress shows up
    const iv = setInterval(loadStats, 15_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  if (err && !stats) {
    return (
      <div className="page">
        <div className="page-head compact">
          <div className="title-block">
            <span className="label">System · Knowledge Base</span>
            <h1>频谱知识库</h1>
            <p className="lede" style={{ color: "var(--warn)" }}>无法连接后端: {err}（请确认后端 uvicorn 已启动）</p>
          </div>
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="page">
        <div className="page-head compact">
          <div className="title-block">
            <span className="label">System · Knowledge Base</span>
            <h1>频谱知识库</h1>
            <p className="lede">正在连接后端...</p>
          </div>
        </div>
      </div>
    );
  }

  const ragReady = stats?.rag_pipeline?.status === "ready";
  const graphReady = stats?.knowledge_graph?.status === "ready";
  const tabs = [
    { id: "overview", label: "概览", en: "Overview", icon: Cpu },
    { id: "docs", label: "文档", en: "Documents", icon: FileText },
    { id: "graph", label: "知识图谱", en: "Graph", icon: Network },
  ];

  return (
    <div className="page">
      <div className="page-head compact">
        <div className="title-block">
          <span className="label">System · Knowledge Base</span>
          <h1>频谱知识库</h1>
          <p className="lede">
            {err
              ? `后端统计暂不可用：${err}。页面已进入降级展示，可继续查看结构并稍后刷新。`
              : ragReady
              ? `${stats?.total_pdfs} 份文档 · ${(stats?.rag_pipeline?.vector_count || 0).toLocaleString()} 向量 · ${(stats?.knowledge_graph?.entity_count || 0).toLocaleString()} 实体 · ${(stats?.knowledge_graph?.relation_count || 0).toLocaleString()} 关系`
              : "运行 python -m backend.rag.ingest 构建索引"}
          </p>
        </div>
        <div className="actions">
          <span className="pill" data-tone={err ? "warn" : ragReady ? "ok" : "warn"}><span className="dot" />{err ? "统计降级" : ragReady ? "RAG Pipeline 在线" : "TF-IDF 在线"}</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 18, borderBottom: "1px solid var(--line)" }}>
        {tabs.map(t => {
          const active = tab === t.id;
          const TIcon = t.icon;
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 16px", border: 0, borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent", background: "transparent", color: active ? "var(--ink)" : "var(--muted)", fontSize: 13.5, fontWeight: active ? 600 : 400, cursor: "pointer", transition: "color 0.15s ease, border-color 0.15s ease", marginBottom: -1 }}>
              <TIcon size={14} style={{ color: active ? "var(--accent)" : "var(--muted-2)" }} />
              <span>{t.label}</span>
              <span className="mono" style={{ fontSize: 10, color: "var(--muted-2)", letterSpacing: "0.06em" }}>{t.en}</span>
            </button>
          );
        })}
      </div>

      {tab === "overview" && <OverviewTab stats={stats} ragReady={ragReady} graphReady={graphReady} />}
      {tab === "docs" && <DocsTab />}
      {tab === "graph" && <GraphTab stats={stats} graphReady={graphReady} />}
    </div>
  );
}
