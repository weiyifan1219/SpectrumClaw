import { useEffect, useState, useRef, useCallback } from "react";
import {
  Database, FileText, HardDrive, Layers, Search, Zap,
  GitBranch, Network, Circle, Loader2, ArrowRight,
  BarChart3, Workflow, Brain, Sparkles, Cpu, Send,
  Hexagon, Link2, ExternalLink, X, Maximize2, Minimize2,
  Filter, ChevronRight, ZoomIn, ZoomOut, RotateCcw, Info,
} from "lucide-react";
import Markdown from "../components/Markdown.jsx";

const API_BASE = `http://${window.location.hostname}:8230`;

/* ── color tokens ── */
const ENTITY_COLORS = {
  FrequencyBand:  "var(--acc-violet)",
  Standard:       "var(--acc-blue)",
  Footnote:       "var(--acc-amber)",
  RadioService:   "var(--acc-teal)",
  Region:         "var(--acc-cyan)",
};
const ENTITY_ICONS = {
  FrequencyBand: Zap,
  Standard: FileText,
  Footnote: Link2,
  RadioService: Network,
  Region: GitBranch,
};
const RELATION_COLORS = {
  allocated_to: "var(--acc-violet)",
  limited_by:   "var(--acc-amber)",
  applies_in:   "var(--acc-cyan)",
};

/* ── helpers ── */
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

/* ── StatCard ── */
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
      <div style={{ marginTop: 4, fontSize: 11.5, color: "var(--muted-2)" }}>{detail}</div>
    </div>
  );
}

/* ── BarRow ── */
function BarRow({ label, value, max, color, icon: Icon }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
      <span style={{ width: 130, display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--ink-2)", flexShrink: 0 }}>
        {Icon && <Icon size={12} style={{ color }} />}{label}
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

/* ══════════════════════════════════════════════════════════════
   OVERVIEW TAB
   ══════════════════════════════════════════════════════════════ */
function OverviewTab({ stats, ragReady, graphReady }) {
  const [query, setQuery] = useState("");
  const [queryResult, setQueryResult] = useState(null);
  const [queryBusy, setQueryBusy] = useState(false);
  const [showDebug, setShowDebug] = useState(false);
  const vecCount = stats?.rag_pipeline?.vector_count || 0;
  const entCount = stats?.knowledge_graph?.entity_count || 0;
  const relCount = stats?.knowledge_graph?.relation_count || 0;

  async function runQuery() {
    if (!query.trim() || queryBusy) return;
    setQueryBusy(true); setQueryResult(null);
    try {
      const r = await fetch(`${API_BASE}/api/rag/query`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: query }),
      });
      setQueryResult(await r.json());
    } catch (e) {
      setQueryResult({ answer: "查询失败: " + e.message, citations: [] });
    }
    setQueryBusy(false);
  }

  const pipelineSteps = [
    { step: "Document Parsing",   icon: FileText,  note: "PyPDF + MinerU/Docling/PaddleOCR 可插拔",  status: ragReady ? "ready" : "planned" },
    { step: "Content Processing", icon: Brain,     note: "Modal Processors + ContextBuilder", status: ragReady ? "ready" : "planned" },
    { step: "Embedding + Store",  icon: Layers,    note: `${vecCount.toLocaleString()} vectors · BGE/ Qwen / OpenAI`, status: ragReady ? "ready" : "planned" },
    { step: "Hybrid Retrieval",   icon: Workflow,  note: "Multi-Channel RRF: Vec + KW + Freq + Graph", status: ragReady ? "ready" : "planned" },
    { step: "Cited Answer",       icon: Sparkles,  note: "LangGraph → 结论/依据/限制/来源/不确定性", status: ragReady ? "ready" : "planned" },
    { step: "Knowledge Graph",    icon: Network,   note: `${entCount.toLocaleString()} entities · ${relCount.toLocaleString()} relations`, status: graphReady ? "ready" : "planned" },
  ];

  const entityBreakdown = stats?.knowledge_graph?.entity_breakdown || [];
  const maxEntity = Math.max(...entityBreakdown.map(e => e.count), 1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* stats row */}
      <div className="kb-stats">
        <StatCard icon={Zap}      label="PDF 文档"       value={stats?.total_pdfs || 0}  detail="ITU-R 建议书 / 报告 / 规则" tone={null} />
        <StatCard icon={Layers}   label="Chroma 向量"    value={vecCount}                detail="sentence-transformers · cosine" tone="var(--acc-blue)" />
        <StatCard icon={Network}  label="知识图谱实体"    value={entCount}                detail={`${relCount.toLocaleString()} 条关系`} tone="var(--acc-violet)" />
        <StatCard icon={HardDrive} label="TF-IDF 文本块" value={stats?.total_chunks || 0} detail={`${(stats?.total_chars || 0 / 1_000_000).toFixed(1)}M 字符`} tone="var(--acc-teal)" />
      </div>

      {/* pipeline + entity bars side by side */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <section className="card">
          <div className="card-head">
            <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Cpu size={14} style={{ color: "var(--accent)" }} />RAG 流水线
            </span>
            <span className="eyebrow">{ragReady ? "全部就绪" : "Partially Ready"}</span>
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
                      <div style={{ position: "absolute", top: -1, left: 0, right: 0, height: 1,
                        background: "linear-gradient(90deg, transparent, var(--ok), transparent)", opacity: 0.35 }} />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Hexagon size={14} style={{ color: "var(--acc-violet)" }} />图谱实体分布
            </span>
            <span className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>{entCount.toLocaleString()} total</span>
          </div>
          <div className="card-body" style={{ padding: "12px 14px" }}>
            {entityBreakdown.map((e) => {
              const cfg = ENTITY_COLORS[e.type] || "var(--muted)";
              const Ic = ENTITY_ICONS[e.type] || Circle;
              return <BarRow key={e.type} label={e.type} value={e.count} max={maxEntity} color={cfg} icon={Ic} />;
            })}
          </div>
        </section>
      </div>

      {/* live query */}
      <section className="card" style={{ borderColor: ragReady ? "oklch(0.80 0.15 155 / 0.25)" : "var(--line)" }}>
        <div className="card-head">
          <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Search size={14} style={{ color: "var(--accent)" }} />实时查询
          </span>
          <span className="eyebrow">POST /api/rag/query</span>
        </div>
        <div className="card-body">
          <div style={{ display: "flex", gap: 8 }}>
            <div className="comp-input" style={{ flex: 1 }}>
              <input
                placeholder="输入频谱问题…  例: 2300-2400 MHz Region 3 业务分配？E-UTRA Band 40 频率范围？"
                value={query} onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runQuery()}
              />
            </div>
            <button className="btn primary" onClick={runQuery} disabled={queryBusy} style={{ height: 36 }}>
              {queryBusy ? <Loader2 size={14} className="spin" /> : <Send size={14} />}查询
            </button>
          </div>
          {queryResult && (
            <div style={{ marginTop: 14, padding: 14, borderRadius: "var(--r-md)",
              border: "1px solid var(--line)", background: "oklch(0.20 0.025 252)", maxHeight: 420, overflowY: "auto" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10,
                fontFamily: "var(--font-mono)", fontSize: 10.5, letterSpacing: "0.08em", color: "var(--muted)", textTransform: "uppercase" }}>
                <Circle size={6} style={{ color: "var(--ok)", fill: "var(--ok)" }} />
                检索完成 · {queryResult.citations?.length || 0} 引用来源
                {queryResult.debug && (
                  <span style={{ marginLeft: "auto", color: "var(--muted-2)" }}>
                    vec={queryResult.debug.vector_count} kw={queryResult.debug.keyword_count} graph={queryResult.debug.graph_count}
                  </span>
                )}
              </div>
              <Markdown>{queryResult.answer}</Markdown>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12 }}>
                {queryResult.citations?.length > 0 && (
                  <div style={{ flex: 1, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
                    {queryResult.citations.slice(0, 5).map((c, i) => (
                      <div key={i} className="mono" style={{ fontSize: 10.5, color: "var(--muted)", marginBottom: 2 }}>
                        [{i + 1}] {c.source} p.{c.page || "?"} relevance={c.relevance}
                      </div>
                    ))}
                  </div>
                )}
                {queryResult.debug && (
                  <button className="btn ghost sm" onClick={() => setShowDebug(!showDebug)}
                    style={{ flexShrink: 0, alignSelf: "flex-start", marginTop: 10 }}>
                    {showDebug ? "隐藏调试" : "调试详情"}
                  </button>
                )}
              </div>
              {showDebug && queryResult.debug && (
                <pre className="mono" style={{
                  marginTop: 8, padding: 10, borderRadius: "var(--r-md)",
                  border: "1px solid var(--line)", background: "oklch(0.16 0.02 252)",
                  fontSize: 10.5, color: "var(--muted-2)", maxHeight: 200, overflowY: "auto",
                  whiteSpace: "pre-wrap", wordBreak: "break-all",
                }}>
                  {JSON.stringify(queryResult.debug, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════
   KNOWLEDGE GRAPH TAB
   ══════════════════════════════════════════════════════════════ */
function GraphTab({ stats, graphReady }) {
  const [entities, setEntities] = useState([]);
  const [relations, setRelations] = useState([]);
  const [filterType, setFilterType] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedEntity, setSelectedEntity] = useState(null);
  const [selectedRelations, setSelectedRelations] = useState([]);
  const [zoom, setZoom] = useState(60); // 0-100, controls how many entities shown
  const canvasRef = useRef(null);
  const animRef = useRef(null);

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterType) params.set("type", filterType);
      if (searchTerm) params.set("search", searchTerm);
      params.set("limit", String(Math.round(zoom * 2)));
      const r = await fetch(`${API_BASE}/api/rag/graph/entities?${params}`);
      const data = await r.json();
      setEntities(data.entities || []);
      setRelations(data.relations || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [filterType, searchTerm, zoom]);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  async function selectEntity(name) {
    try {
      const r = await fetch(`${API_BASE}/api/rag/graph/entity/${encodeURIComponent(name)}`);
      const data = await r.json();
      setSelectedEntity(data.entity);
      setSelectedRelations(data.relations || []);
    } catch (e) { console.error(e); }
  }

  /* ── force graph on canvas ── */
  const NODE_R = 5;
  useEffect(() => {
    if (entities.length === 0) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width = canvas.offsetWidth * 2;
    const H = canvas.height = canvas.offsetHeight * 2;
    ctx.scale(2, 2);
    const cw = canvas.offsetWidth, ch = canvas.offsetHeight;

    // build nodes
    const nodeMap = {};
    const nodes = entities.map((e, i) => {
      const n = { id: e.name, type: e.type, x: cw / 2 + (Math.random() - 0.5) * 200, y: ch / 2 + (Math.random() - 0.5) * 200, vx: 0, vy: 0, color: ENTITY_COLORS[e.type] || "var(--muted)" };
      nodeMap[e.name] = n;
      return n;
    });

    const relSet = new Set();
    const edges = [];
    for (const r of relations) {
      const key = [r.source, r.target].sort().join("||");
      if (relSet.has(key)) continue;
      relSet.add(key);
      if (nodeMap[r.source] && nodeMap[r.target]) {
        edges.push({ source: nodeMap[r.source], target: nodeMap[r.target], type: r.relation });
      }
    }

    let running = true;
    function step() {
      if (!running) return;
      const cx = cw / 2, cy = ch / 2;
      const k = 0.03; // spring
      const damp = 0.85;
      const repulsion = 400;

      for (const n of nodes) {
        n.vx += (cx - n.x) * 0.001;
        n.vy += (cy - n.y) * 0.001;
      }
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[j].x - nodes[i].x;
          const dy = nodes[j].y - nodes[i].y;
          const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const f = repulsion / (d * d);
          nodes[i].vx -= (dx / d) * f;
          nodes[i].vy -= (dy / d) * f;
          nodes[j].vx += (dx / d) * f;
          nodes[j].vy += (dy / d) * f;
        }
      }
      for (const e of edges) {
        const dx = e.target.x - e.source.x;
        const dy = e.target.y - e.source.y;
        const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const f = (d - 60) * k;
        e.source.vx += (dx / d) * f;
        e.source.vy += (dy / d) * f;
        e.target.vx -= (dx / d) * f;
        e.target.vy -= (dy / d) * f;
      }
      for (const n of nodes) {
        n.vx *= damp; n.vy *= damp;
        n.x += n.vx; n.y += n.vy;
        n.x = Math.max(NODE_R, Math.min(cw - NODE_R, n.x));
        n.y = Math.max(NODE_R, Math.min(ch - NODE_R, n.y));
      }

      // draw
      ctx.clearRect(0, 0, cw, ch);
      for (const e of edges) {
        ctx.beginPath();
        ctx.moveTo(e.source.x, e.source.y);
        ctx.lineTo(e.target.x, e.target.y);
        ctx.strokeStyle = "oklch(1 0 0 / 0.06)";
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }
      for (const n of nodes) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, NODE_R, 0, Math.PI * 2);
        ctx.fillStyle = n.color;
        ctx.fill();
      }
      animRef.current = requestAnimationFrame(step);
    }
    step();
    return () => { running = false; cancelAnimationFrame(animRef.current); };
  }, [entities, relations]);

  const entityTypes = ["FrequencyBand", "Standard", "Footnote", "RadioService", "Region"];
  const totalEnt = stats?.knowledge_graph?.entity_count || 0;
  const totalRel = stats?.knowledge_graph?.relation_count || 0;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16 }}>
      {/* left: graph canvas + controls */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {/* controls */}
        <div className="card">
          <div className="card-body" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", flexWrap: "wrap" }}>
            <span className="mono" style={{ fontSize: 10, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--muted)", marginRight: 4 }}>Filter</span>
            {entityTypes.map(t => (
              <button key={t} onClick={() => { setFilterType(filterType === t ? "" : t); setSelectedEntity(null); }}
                style={{
                  height: 26, padding: "0 10px", borderRadius: 999, border: `1px solid ${ENTITY_COLORS[t] || "var(--line-2)"}`, cursor: "pointer",
                  background: filterType === t ? `oklch(from ${ENTITY_COLORS[t]} l c h / 0.15)` : "transparent",
                  color: filterType === t ? "var(--ink)" : "var(--muted)", fontSize: 11, fontWeight: 500,
                  transition: "background var(--dur-1) var(--ease), color var(--dur-1) var(--ease)",
                }}>
                {t} ({entities.filter(e => e.type === t).length})
              </button>
            ))}
            <div className="comp-input" style={{ flex: 1, minWidth: 140, height: 28 }}>
              <input placeholder="搜索实体…" value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{ fontSize: 11.5 }} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
              <button className="btn ghost sm" onClick={() => { setZoom(Math.max(10, zoom - 20)); setSelectedEntity(null); }}><ZoomOut size={12} /></button>
              <span className="mono" style={{ fontSize: 10, color: "var(--muted)", width: 32, textAlign: "center" }}>{zoom}%</span>
              <button className="btn ghost sm" onClick={() => { setZoom(Math.min(100, zoom + 20)); setSelectedEntity(null); }}><ZoomIn size={12} /></button>
              <button className="btn ghost sm" onClick={() => { setFilterType(""); setSearchTerm(""); setZoom(60); setSelectedEntity(null); }}><RotateCcw size={12} /></button>
            </div>
          </div>
        </div>

        {/* canvas */}
        <div className="card" style={{ flex: 1, minHeight: 500, position: "relative", overflow: "hidden" }}>
          {loading && (
            <div style={{ position: "absolute", top: 12, left: 12, zIndex: 2, display: "flex", alignItems: "center", gap: 6,
              fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--muted)" }}>
              <Loader2 size={12} className="spin" />加载中…
            </div>
          )}
          <canvas ref={canvasRef}
            style={{ width: "100%", height: "100%", display: "block", cursor: "grab" }} />
          {/* legend */}
          <div style={{ position: "absolute", bottom: 10, right: 14, display: "flex", gap: 12,
            fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--muted)", letterSpacing: "0.06em", pointerEvents: "none" }}>
            {entityTypes.map(t => (
              <span key={t} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: ENTITY_COLORS[t] }} />{t}
              </span>
            ))}
          </div>
        </div>

        {/* summary bar */}
        <div style={{ display: "flex", gap: 12 }}>
          {entityTypes.map(t => {
            const count = entities.filter(e => e.type === t).length;
            return (
              <div key={t} className="stat-card" style={{ flex: 1, padding: "10px 14px" }}>
                <div className="mono" style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--muted)" }}>{t}</div>
                <div className="mono" style={{ marginTop: 4, fontSize: 18, fontWeight: 700, color: ENTITY_COLORS[t] }}>{count}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* right: detail panel */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {/* entity detail */}
        {selectedEntity ? (
          <section className="card">
            <div className="card-head">
              <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {selectedEntity.type && ENTITY_ICONS[selectedEntity.type] &&
                  React.createElement(ENTITY_ICONS[selectedEntity.type], { size: 14, style: { color: ENTITY_COLORS[selectedEntity.type] } })}
                {selectedEntity.name}
              </span>
              <button className="btn ghost sm" onClick={() => setSelectedEntity(null)}><X size={12} /></button>
            </div>
            <div className="card-body" style={{ maxHeight: 300, overflowY: "auto" }}>
              <div style={{ marginBottom: 10 }}>
                <span className="pill" data-tone="info">{selectedEntity.type}</span>
                {selectedEntity.evidence_block_id && (
                  <span className="mono" style={{ marginLeft: 8, fontSize: 10, color: "var(--muted-2)" }}>
                    block: {selectedEntity.evidence_block_id}
                  </span>
                )}
              </div>
              <div className="section-head" style={{ marginBottom: 6 }}>
                <span className="eyebrow">Relations ({selectedRelations.length})</span>
              </div>
              {selectedRelations.length === 0 ? (
                <p style={{ fontSize: 12.5, color: "var(--muted)" }}>无关系数据</p>
              ) : (
                selectedRelations.slice(0, 30).map((r, i) => {
                  const isSource = r.source === selectedEntity.name;
                  const other = isSource ? r.target : r.source;
                  const otherType = isSource ? r.target_type : r.source_type;
                  const relColor = RELATION_COLORS[r.relation] || "var(--muted)";
                  return (
                    <div key={i} style={{
                      display: "flex", alignItems: "center", gap: 6, padding: "6px 0", borderBottom: "1px solid var(--line)",
                      cursor: "pointer", transition: "background var(--dur-1) var(--ease)",
                    }} onClick={() => selectEntity(other)}>
                      <span style={{ fontSize: 10, color: relColor, fontWeight: 600, minWidth: 72, fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>
                        {r.relation}
                      </span>
                      <ArrowRight size={10} style={{ color: "var(--muted-2)", flexShrink: 0 }} />
                      <span style={{ fontSize: 12, color: "var(--ink-2)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {other}
                      </span>
                      {otherType && (
                        <span style={{ fontSize: 9.5, color: ENTITY_COLORS[otherType] || "var(--muted)", fontFamily: "var(--font-mono)", letterSpacing: "0.04em", flexShrink: 0 }}>
                          {otherType}
                        </span>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </section>
        ) : (
          <section className="card">
            <div className="card-head">
              <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Info size={14} style={{ color: "var(--accent)" }} />图谱概览
              </span>
            </div>
            <div className="card-body">
              <p style={{ margin: 0, fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.7 }}>
                共 <span className="mono" style={{ color: "var(--acc-violet)", fontWeight: 600 }}>{totalEnt.toLocaleString()}</span> 个实体，
                <span className="mono" style={{ color: "var(--acc-teal)", fontWeight: 600 }}>{totalRel.toLocaleString()}</span> 条关系。
              </p>
              <p style={{ margin: "10px 0 0", fontSize: 12, color: "var(--muted)", lineHeight: 1.6 }}>
                使用顶部的类型筛选按钮浏览实体，调整缩放滑块控制显示数量。点击关系列表中的实体名称或画布节点可查看详情。
              </p>
            </div>
          </section>
        )}

        {/* relation types breakdown */}
        <section className="card">
          <div className="card-head">
            <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <GitBranch size={14} style={{ color: "var(--acc-teal)" }} />关系类型
            </span>
          </div>
          <div className="card-body" style={{ padding: "10px 14px" }}>
            {Object.entries(RELATION_COLORS).map(([type, color]) => {
              const count = relations.filter(r => r.relation === type).length || 0;
              const maxRel = Math.max(...Object.values(RELATION_COLORS).map((_, i) =>
                relations.filter(r => r.relation === Object.keys(RELATION_COLORS)[i]).length
              ), 1);
              const pct = maxRel > 0 ? (count / maxRel) * 100 : 0;
              return (
                <div key={type} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <span className="mono" style={{ width: 84, fontSize: 10.5, color: "var(--muted)", flexShrink: 0 }}>{type}</span>
                  <div style={{ flex: 1, height: 4, borderRadius: 2, background: "oklch(1 0 0 / 0.06)", overflow: "hidden" }}>
                    <div style={{ width: `${pct}%`, height: "100%", borderRadius: 2, background: color, transition: "width 600ms var(--ease)" }} />
                  </div>
                  <span className="mono" style={{ width: 44, textAlign: "right", fontSize: 10.5, color: "var(--ink-2)", flexShrink: 0 }}>{count}</span>
                </div>
              );
            })}
          </div>
        </section>

        {/* search tips */}
        <section className="card">
          <div className="card-head"><span className="title">查询引导</span></div>
          <div className="card-body">
            <ul style={{ margin: 0, padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 6 }}>
              {[
                { icon: Zap, color: "var(--acc-violet)", text: "用具体频段提问: 2300-2400 MHz" },
                { icon: GitBranch, color: "var(--acc-cyan)", text: "指定区域: Region 1/2/3 或国家名" },
                { icon: Link2, color: "var(--acc-amber)", text: "查脚注: 5.340, 5.432A" },
                { icon: FileText, color: "var(--acc-blue)", text: "查标准: ITU-R M.1457" },
              ].map((t, i) => (
                <li key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--ink-2)" }}>
                  <t.icon size={11} style={{ color: t.color, flexShrink: 0 }} />{t.text}
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════
   MAIN PAGE — with tabs
   ══════════════════════════════════════════════════════════════ */
export default function KnowledgePage() {
  const [tab, setTab] = useState("overview");
  const [stats, setStats] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/kb/stats`)
      .then((r) => r.json()).then(setStats)
      .catch(() => setStats({ status: "无法连接后端" }));
  }, []);

  const isReady = stats?.status === "ready";
  const ragReady = stats?.rag_pipeline?.status === "ready";
  const graphReady = stats?.knowledge_graph?.status === "ready";

  const tabs = [
    { id: "overview", label: "概览", en: "Overview", icon: BarChart3 },
    { id: "graph",    label: "知识图谱", en: "Knowledge Graph", icon: Network },
  ];

  return (
    <div className="page">
      {/* header */}
      <div className="page-head compact">
        <div className="title-block">
          <span className="label">System · Knowledge Base</span>
          <h1>频谱知识库</h1>
          <p className="lede">
            {ragReady
              ? `${stats?.total_pdfs} 份文档 · ${(stats?.rag_pipeline?.vector_count || 0).toLocaleString()} 向量 · ${(stats?.knowledge_graph?.entity_count || 0).toLocaleString()} 实体 · ${(stats?.knowledge_graph?.relation_count || 0).toLocaleString()} 关系`
              : "运行 python -m backend.rag.ingest 构建索引"}
          </p>
        </div>
        <div className="actions">
          <span className="pill" data-tone={ragReady ? "ok" : "warn"}>
            <span className="dot" />{ragReady ? "RAG Pipeline 在线" : isReady ? "TF-IDF 在线" : "离线"}
          </span>
        </div>
      </div>

      {/* tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 20, borderBottom: "1px solid var(--line)", paddingBottom: 0 }}>
        {tabs.map(t => {
          const active = tab === t.id;
          return (
            <button key={t.id} onClick={() => setTab(t.id)}
              style={{
                display: "flex", alignItems: "center", gap: 8, padding: "10px 16px",
                border: 0, borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
                background: "transparent", color: active ? "var(--ink)" : "var(--muted)",
                fontSize: 13.5, fontWeight: active ? 600 : 400, cursor: "pointer",
                transition: "color var(--dur-1) var(--ease), border-color var(--dur-1) var(--ease)",
                marginBottom: -1, letterSpacing: 0,
              }}>
              <t.icon size={14} style={{ color: active ? "var(--accent)" : "var(--muted-2)" }} />
              <span>{t.label}</span>
              <span className="mono" style={{ fontSize: 10, color: "var(--muted-2)", letterSpacing: "0.06em" }}>{t.en}</span>
            </button>
          );
        })}
      </div>

      {/* tab content */}
      {tab === "overview" && <OverviewTab stats={stats} ragReady={ragReady} graphReady={graphReady} />}
      {tab === "graph" && <GraphTab stats={stats} graphReady={graphReady} />}
    </div>
  );
}
