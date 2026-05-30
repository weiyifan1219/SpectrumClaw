import { useEffect, useState, useRef, useCallback } from "react";
import {
  Database, FileText, HardDrive, Layers, Search, Zap,
  GitBranch, Network, Circle, Loader2, ArrowRight, Send,
  Workflow, Brain, Sparkles, Cpu, Hexagon, Link2,
  Filter, ZoomIn, ZoomOut, RotateCcw, Info, X,
} from "lucide-react";
import Markdown from "../components/Markdown.jsx";

const API = `http://${window.location.hostname}:8230`;

/* ── entity color palette (bright, high-contrast) ── */
const ETYPE = {
  FrequencyBand: { hex: "#a78bfa", bg: "rgba(167,139,250,0.15)", label: "FrequencyBand" },
  Standard:      { hex: "#22d3ee", bg: "rgba(34,211,238,0.15)", label: "Standard" },
  Footnote:      { hex: "#fbbf24", bg: "rgba(251,191,36,0.15)", label: "Footnote" },
  RadioService:  { hex: "#2dd4bf", bg: "rgba(45,212,191,0.15)", label: "RadioService" },
  Region:        { hex: "#60a5fa", bg: "rgba(96,165,250,0.15)", label: "Region" },
};
const ETYPE_ICONS = { FrequencyBand: Zap, Standard: FileText, Footnote: Link2, RadioService: Network, Region: GitBranch };
const REL_COLORS = { allocated_to: "#a78bfa", limited_by: "#fbbf24", applies_in: "#60a5fa" };

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
  const [query, setQuery] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showDbg, setShowDbg] = useState(false);
  const vc = stats?.rag_pipeline?.vector_count || 0;
  const ec = stats?.knowledge_graph?.entity_count || 0;
  const rc = stats?.knowledge_graph?.relation_count || 0;

  async function run() {
    if (!query.trim() || busy) return;
    setBusy(true); setRes(null);
    try {
      const r = await fetch(`${API}/api/rag/query`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: query }) });
      setRes(await r.json());
    } catch (e) { setRes({ answer: "查询失败: " + e.message, citations: [] }); }
    setBusy(false);
  }

  const steps = [
    { step: "Document Parsing",   icon: FileText,  note: "PyPDF + MinerU/Docling/PaddleOCR", status: ragReady ? "ready" : "planned" },
    { step: "Content Processing", icon: Brain,     note: "6 Modal Processors", status: ragReady ? "ready" : "planned" },
    { step: "Embedding + Store",  icon: Layers,    note: `${vc.toLocaleString()} vectors`, status: ragReady ? "ready" : "planned" },
    { step: "Hybrid Retrieval",   icon: Workflow,  note: "4-Channel RRF", status: ragReady ? "ready" : "planned" },
    { step: "Cited Answer",       icon: Sparkles,  note: "LangGraph → 带引用回答", status: ragReady ? "ready" : "planned" },
    { step: "Knowledge Graph",    icon: Network,   note: `${ec.toLocaleString()} entities`, status: graphReady ? "ready" : "planned" },
  ];

  const eb = stats?.knowledge_graph?.entity_breakdown || [
    { type: "FrequencyBand", count: 2382 }, { type: "Standard", count: 1848 },
    { type: "Footnote", count: 605 }, { type: "RadioService", count: 15 }, { type: "Region", count: 8 },
  ];
  const me = Math.max(...eb.map(e => e.count), 1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* stats row */}
      <div className="kb-stats">
        <StatCard icon={Zap} label="PDF 文档" value={stats?.total_pdfs || 0} detail="ITU-R 建议书 / 报告 / 规则" tone="167,139,250" />
        <StatCard icon={Layers} label="Chroma 向量" value={vc} detail="sentence-transformers · cosine" tone="34,211,238" />
        <StatCard icon={Network} label="图谱实体" value={ec} detail={`${rc.toLocaleString()} 条关系`} tone="167,139,250" />
        <StatCard icon={HardDrive} label="TF-IDF 块" value={stats?.total_chunks || 0} detail={`${(stats?.total_chars || 0 / 1_000_000).toFixed(1)}M chars`} tone="45,212,191" />
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

      {/* live query — visual center, largest */}
      <section className="card" style={{ borderColor: ragReady ? "oklch(0.80 0.15 155 / 0.25)" : "var(--line)", minHeight: 360 }}>
        <div className="card-head">
          <span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}><Search size={14} style={{ color: "var(--accent)" }} />实时查询</span>
          <span className="eyebrow">POST /api/rag/query</span>
        </div>
        <div className="card-body" style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 280 }}>
          {/* input area */}
          <div style={{ display: "flex", gap: 8, marginBottom: res ? 14 : 0 }}>
            <div className="comp-input" style={{ flex: 1, height: 44 }}>
              <input placeholder="输入频谱问题…  例: 2300-2400 MHz Region 3 业务分配？E-UTRA Band 40 频率范围？脚注 5.340 限制？"
                value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === "Enter" && run()} style={{ fontSize: 13.5 }} />
            </div>
            <button className="btn primary" onClick={run} disabled={busy} style={{ height: 44, padding: "0 18px" }}>
              {busy ? <Loader2 size={14} className="spin" /> : <Send size={14} />}
              <span style={{ marginLeft: 4 }}>查询</span>
            </button>
          </div>

          {/* results */}
          {res && (
            <div style={{ flex: 1, padding: 14, borderRadius: "var(--r-md)", border: "1px solid var(--line)", background: "oklch(0.20 0.025 252)", overflowY: "auto", minHeight: 200 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, fontFamily: "var(--font-mono)", fontSize: 10.5, letterSpacing: "0.08em", color: "var(--muted)", textTransform: "uppercase" }}>
                <Circle size={6} style={{ color: "var(--ok)", fill: "var(--ok)" }} />
                {res.citations?.length || 0} 引用来源
                {res.debug && <span style={{ marginLeft: "auto", color: "var(--muted-2)" }}>vec={res.debug.vector_count} kw={res.debug.keyword_count} graph={res.debug.graph_count} vlm={res.debug.vlm_multimodal_analyzed}</span>}
                {res.debug && <button className="btn ghost sm" onClick={() => setShowDbg(!showDbg)} style={{ fontSize: 10, padding: "0 6px" }}>{showDbg ? "隐藏" : "调试"}</button>}
              </div>
              <div style={{ fontSize: 13.5, lineHeight: 1.7, color: "var(--ink)", maxWidth: "100%" }}><Markdown>{res.answer}</Markdown></div>
              {showDbg && res.debug && (
                <pre className="mono" style={{ marginTop: 10, padding: 10, borderRadius: "var(--r-md)", border: "1px solid var(--line)", background: "oklch(0.16 0.02 252)", fontSize: 10.5, color: "var(--muted-2)", maxHeight: 180, overflowY: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{JSON.stringify(res.debug, null, 2)}</pre>
              )}
              {res.citations?.length > 0 && (
                <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
                  {res.citations.slice(0, 6).map((c, i) => (
                    <div key={i} className="mono" style={{ fontSize: 10.5, color: "var(--muted)", marginBottom: 2 }}>[{i + 1}] {c.source} p.{c.page || "?"} relevance={c.relevance}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

/* ═══════════════════════════════════ KNOWLEDGE GRAPH TAB ═══════════════════════════════════ */

/* ── tooltip component for canvas nodes ── */
function GraphTooltip({ node, pos, onClose }) {
  if (!node) return null;
  const c = ETYPE[node.type] || {};
  return (
    <div style={{ position: "absolute", left: pos.x + 14, top: pos.y - 10, zIndex: 20,
      padding: "10px 14px", borderRadius: "var(--r-md)", border: `1px solid ${c.hex}`,
      background: "oklch(0.22 0.03 252)", boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
      minWidth: 180, maxWidth: 280, pointerEvents: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: c.hex }}>{node.label}</span>
        <button onClick={onClose} style={{ background: "none", border: 0, color: "var(--muted)", cursor: "pointer", padding: 0 }}><X size={12} /></button>
      </div>
      <span className="pill" style={{ fontSize: 10, borderColor: `${c.hex}55`, color: c.hex }}>{node.type}</span>
      {node.relations !== undefined && <div className="mono" style={{ marginTop: 6, fontSize: 10, color: "var(--muted)" }}>{node.relations} relations</div>}
      <div className="mono" style={{ marginTop: 4, fontSize: 9.5, color: "var(--muted-2)" }}>click for details</div>
    </div>
  );
}

function GraphTab({ stats, graphReady }) {
  const canvasRef = useRef(null);
  const [entities, setEntities] = useState([]);
  const [relations, setRelations] = useState([]);
  const [filterType, setFilterType] = useState("");
  const [search, setSearch] = useState("");
  const [zoom, setZoom] = useState(60);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);
  const [selRels, setSelRels] = useState([]);
  const [tooltip, setTooltip] = useState(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  // node positions (persisted across renders)
  const nodesRef = useRef([]);
  const edgesRef = useRef([]);
  const animRef = useRef(null);

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (filterType) p.set("type", filterType);
      if (search) p.set("search", search);
      p.set("limit", String(Math.round(zoom * 2)));
      const r = await fetch(`${API}/api/rag/graph/entities?${p}`);
      const d = await r.json();
      setEntities(d.entities || []);
      setRelations(d.relations || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [filterType, search, zoom]);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  async function clickEntity(name) {
    try {
      const r = await fetch(`${API}/api/rag/graph/entity/${encodeURIComponent(name)}`);
      const d = await r.json();
      setSelected(d.entity);
      setSelRels(d.relations || []);
    } catch (e) { console.error(e); }
  }

  /* ── force simulation on canvas ── */
  const N = 10; // node radius
  useEffect(() => {
    if (entities.length === 0) { nodesRef.current = []; edgesRef.current = []; return; }
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const W = cvs.offsetWidth, H = cvs.offsetHeight;
    cvs.width = W * dpr; cvs.height = H * dpr;
    ctx.scale(dpr, dpr);

    // build node map
    const nMap = {};
    const nodes = entities.map((e, i) => {
      const n = { id: e.name, type: e.type, label: e.name, x: W / 2 + (Math.random() - 0.5) * 300, y: H / 2 + (Math.random() - 0.5) * 300, vx: 0, vy: 0, color: (ETYPE[e.type] || {}).hex || "#888" };
      nMap[e.name] = n;
      return n;
    });

    // build edges (dedup)
    const edgeSet = new Set();
    const edges = [];
    for (const r of relations) {
      const k = [r.source, r.target].sort().join("||");
      if (edgeSet.has(k) || !nMap[r.source] || !nMap[r.target]) continue;
      edgeSet.add(k);
      edges.push({ source: nMap[r.source], target: nMap[r.target], type: r.relation });
    }

    nodesRef.current = nodes; edgesRef.current = edges;

    let running = true;
    const cx = W / 2, cy = H / 2;
    const k = 0.04, damp = 0.82, rep = 500;

    function step() {
      if (!running) return;
      // center gravity
      for (const n of nodes) { n.vx += (cx - n.x) * 0.0008; n.vy += (cy - n.y) * 0.0008; }
      // repulsion
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[j].x - nodes[i].x, dy = nodes[j].y - nodes[i].y;
          const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const f = rep / (d * d);
          nodes[i].vx -= (dx / d) * f; nodes[i].vy -= (dy / d) * f;
          nodes[j].vx += (dx / d) * f; nodes[j].vy += (dy / d) * f;
        }
      }
      // springs
      for (const e of edges) {
        const dx = e.target.x - e.source.x, dy = e.target.y - e.source.y;
        const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const f = (d - 80) * k;
        e.source.vx += (dx / d) * f; e.source.vy += (dy / d) * f;
        e.target.vx -= (dx / d) * f; e.target.vy -= (dy / d) * f;
      }
      // apply + damp
      for (const n of nodes) { n.vx *= damp; n.vy *= damp; n.x = Math.max(N, Math.min(W - N, n.x + n.vx)); n.y = Math.max(N, Math.min(H - N, n.y + n.vy)); }
      // draw
      ctx.clearRect(0, 0, W, H);
      // edges
      for (const e of edges) {
        ctx.beginPath(); ctx.moveTo(e.source.x, e.source.y); ctx.lineTo(e.target.x, e.target.y);
        ctx.strokeStyle = "oklch(1 0 0 / 0.10)"; ctx.lineWidth = 0.6; ctx.stroke();
      }
      // nodes
      for (const n of nodes) {
        ctx.beginPath(); ctx.arc(n.x, n.y, N, 0, Math.PI * 2);
        ctx.fillStyle = n.color; ctx.fill();
        ctx.strokeStyle = "oklch(0.18 0.02 252)"; ctx.lineWidth = 1.5; ctx.stroke();
      }
      animRef.current = requestAnimationFrame(step);
    }
    step();
    return () => { running = false; if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, [entities, relations]);

  /* ── canvas mouse handlers ── */
  const handleMouseMove = useCallback((e) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    setMousePos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    const nodes = nodesRef.current;
    let found = null;
    for (const n of nodes) {
      const dx = mx - n.x, dy = my - n.y;
      if (dx * dx + dy * dy < (N + 4) * (N + 4)) {
        const edgeCount = edgesRef.current.filter(e => e.source.id === n.id || e.target.id === n.id).length;
        found = { ...n, relations: edgeCount };
        break;
      }
    }
    setTooltip(found);
    if (canvasRef.current) canvasRef.current.style.cursor = found ? "pointer" : "grab";
  }, []);

  const handleCanvasClick = useCallback((e) => {
    if (!tooltip) return;
    clickEntity(tooltip.id);
  }, [tooltip]);

  const types = ["FrequencyBand", "Standard", "Footnote", "RadioService", "Region"];

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
                <button key={t} onClick={() => { setFilterType(active ? "" : t); setSelected(null); }}
                  style={{ height: 26, padding: "0 10px", borderRadius: 999, border: `1px solid ${active ? c.hex : "var(--line-2)"}`, cursor: "pointer", background: active ? c.bg : "transparent", color: active ? c.hex : "var(--muted)", fontSize: 11, fontWeight: 500, transition: "all 0.15s ease" }}>{t}</button>
              );
            })}
            <div style={{ flex: 1, minWidth: 120 }} />
            <div className="comp-input" style={{ width: 160, height: 28 }}>
              <input placeholder="搜索实体…" value={search} onChange={e => setSearch(e.target.value)} style={{ fontSize: 11.5 }} />
            </div>
            <button className="btn ghost sm" onClick={() => setZoom(Math.max(10, zoom - 20))}><ZoomOut size={12} /></button>
            <span className="mono" style={{ fontSize: 10.5, color: "var(--muted)", width: 28, textAlign: "center" }}>{zoom}%</span>
            <button className="btn ghost sm" onClick={() => setZoom(Math.min(100, zoom + 20))}><ZoomIn size={12} /></button>
            <button className="btn ghost sm" onClick={() => { setFilterType(""); setSearch(""); setZoom(60); setSelected(null); }}><RotateCcw size={12} /></button>
          </div>
        </div>

        {/* canvas */}
        <div className="card" style={{ flex: 1, minHeight: 480, position: "relative", overflow: "hidden" }}>
          {loading && (
            <div style={{ position: "absolute", top: 12, left: 14, zIndex: 2, display: "flex", alignItems: "center", gap: 6, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--muted)" }}><Loader2 size={12} className="spin" />loading…</div>
          )}
          <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block", cursor: "grab" }}
            onMouseMove={handleMouseMove} onMouseLeave={() => setTooltip(null)} onClick={handleCanvasClick} />
          <GraphTooltip node={tooltip} pos={mousePos} onClose={() => setTooltip(null)} />
          {/* legend */}
          <div style={{ position: "absolute", bottom: 10, right: 14, display: "flex", gap: 12, fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--muted)", letterSpacing: "0.06em", pointerEvents: "none" }}>
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
              <button className="btn ghost sm" onClick={() => setSelected(null)}><X size={12} /></button>
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
            <section className="card">
              <div className="card-head"><span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}><Info size={14} style={{ color: "var(--accent)" }} />图谱概览</span></div>
              <div className="card-body">
                <p style={{ margin: 0, fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.7 }}>
                  共 <span className="mono" style={{ color: "#a78bfa", fontWeight: 600 }}>{(stats?.knowledge_graph?.entity_count || 0).toLocaleString()}</span> 实体，
                  <span className="mono" style={{ color: "#2dd4bf", fontWeight: 600 }}>{(stats?.knowledge_graph?.relation_count || 0).toLocaleString()}</span> 关系
                </p>
                <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--muted)", lineHeight: 1.6 }}>点击画布节点或类型筛选按钮浏览图谱。悬停查看实体信息，点击查看关系和证据。</p>
              </div>
            </section>

            {/* relation types */}
            <section className="card">
              <div className="card-head"><span className="title" style={{ display: "flex", alignItems: "center", gap: 8 }}><GitBranch size={14} style={{ color: "#2dd4bf" }} />关系类型</span></div>
              <div className="card-body" style={{ padding: "10px 14px" }}>
                {Object.entries(REL_COLORS).map(([type, color]) => {
                  const cnt = relations.filter(r => r.relation === type).length || 0;
                  const maxR = Math.max(...Object.values(REL_COLORS).map((_, i) => relations.filter(r => r.relation === Object.keys(REL_COLORS)[i]).length), 1);
                  const pct = maxR > 0 ? (cnt / maxR) * 100 : 0;
                  return (
                    <div key={type} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <span className="mono" style={{ width: 84, fontSize: 10.5, color: "var(--muted)" }}>{type}</span>
                      <div style={{ flex: 1, height: 4, borderRadius: 2, background: "oklch(1 0 0 / 0.06)", overflow: "hidden" }}>
                        <div style={{ width: `${pct}%`, height: "100%", borderRadius: 2, background: color, transition: "width 0.6s var(--ease)" }} />
                      </div>
                      <span className="mono" style={{ width: 44, textAlign: "right", fontSize: 10.5, color: "var(--ink-2)" }}>{cnt}</span>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* tips */}
            <section className="card">
              <div className="card-head"><span className="title">查询引导</span></div>
              <div className="card-body">
                <ul style={{ margin: 0, padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 6 }}>
                  {[{ I: Zap, c: "#a78bfa", t: "频段查询: 2300-2400 MHz" }, { I: GitBranch, c: "#60a5fa", t: "区域查询: Region 1/2/3" }, { I: Link2, c: "#fbbf24", t: "脚注查询: 5.340" }, { I: FileText, c: "#22d3ee", t: "标准查询: ITU-R M.1457" }].map((x, i) => (
                    <li key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--ink-2)" }}><x.I size={11} style={{ color: x.c, flexShrink: 0 }} />{x.t}</li>
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

/* ═══════════════════════════════════ MAIN PAGE ═══════════════════════════════════ */
export default function KnowledgePage() {
  const [tab, setTab] = useState("overview");
  const [stats, setStats] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    fetch(`${API}/api/kb/stats`)
      .then(r => r.json()).then(setStats)
      .catch(e => { setErr(e.message); setStats({ status: "error" }); });
  }, []);

  if (err) {
    return <div className="page"><div className="page-head compact"><div className="title-block"><span className="label">System · Knowledge Base</span><h1>频谱知识库</h1><p className="lede" style={{ color: "var(--warn)" }}>无法连接后端: {err}</p></div></div></div>;
  }

  if (!stats) {
    return <div className="page"><div className="page-head compact"><div className="title-block"><span className="label">System · Knowledge Base</span><h1>频谱知识库</h1><p className="lede">加载中...</p></div></div></div>;
  }

  const ragReady = stats?.rag_pipeline?.status === "ready";
  const graphReady = stats?.knowledge_graph?.status === "ready";
  const TabIcon1 = Cpu, TabIcon2 = Network;
  const tabs = [
    { id: "overview", label: "概览", en: "Overview", icon: TabIcon1 },
    { id: "graph", label: "知识图谱", en: "Graph", icon: TabIcon2 },
  ];

  return (
    <div className="page">
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
          <span className="pill" data-tone={ragReady ? "ok" : "warn"}><span className="dot" />{ragReady ? "RAG Pipeline 在线" : "TF-IDF 在线"}</span>
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
      {tab === "graph" && <GraphTab stats={stats} graphReady={graphReady} />}
    </div>
  );
}
