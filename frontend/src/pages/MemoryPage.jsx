import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Archive,
  ArrowDown,
  ArrowUp,
  BookMarked,
  BrainCircuit,
  Clock,
  FileText,
  Layers,
  Loader2,
  Minus,
  RefreshCw,
  Route,
  Search,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { fetchMemoryItems, fetchMemoryOverview, fetchMemoryReports, triggerReflect } from "../lib/api.js";

const LAYER_DEFS = [
  { kind: "working", label: "Working", cn: "工作记忆", icon: Activity, desc: "当前请求上下文" },
  { kind: "thread", label: "Thread", cn: "会话记忆", icon: Layers, desc: "活跃会话" },
  { kind: "episodic", label: "Episodic", cn: "事件记忆", icon: Sparkles, desc: "历史任务经历" },
  { kind: "skill", label: "Skill", cn: "能力记忆", icon: Route, desc: "Skill 使用经验" },
  { kind: "domain", label: "Domain", cn: "领域知识", icon: BookMarked, desc: "频谱操作知识" },
];

const KIND_META = {
  episodic: { label: "事件记忆", icon: Sparkles, color: "oklch(0.78 0.15 280)" },
  skill: { label: "能力记忆", icon: Route, color: "oklch(0.78 0.14 195)" },
  domain: { label: "领域知识", icon: BookMarked, color: "oklch(0.78 0.14 145)" },
  evolution: { label: "进化记忆", icon: BrainCircuit, color: "oklch(0.78 0.14 55)" },
};

const DETAIL_TABS = [
  { id: "detail", label: "记忆详情" },
  { id: "evolution", label: "进化日志" },
  { id: "reflect", label: "反思队列" },
];

function formatTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch { return iso; }
}

function formatShortTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch { return iso; }
}

function layerValue(kind, overview) {
  if (!overview) return "—";
  switch (kind) {
    case "working": return "Active";
    case "thread": return `${overview.thread_count || 0}`;
    case "episodic": return `${overview.episodic_count || 0}`;
    case "skill": return `${overview.skill_count || 0}`;
    case "domain": return `${overview.domain_count || 0}`;
    default: return "—";
  }
}

function MiniDonut({ success, total, size = 32 }) {
  if (!total) return null;
  const ratio = total > 0 ? success / total : 0;
  const r = (size - 4) / 2;
  const circumference = 2 * Math.PI * r;
  const filled = circumference * ratio;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flexShrink: 0 }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="oklch(1 0 0 / 0.08)" strokeWidth={3} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="oklch(0.78 0.14 155)" strokeWidth={3}
        strokeDasharray={`${filled} ${circumference - filled}`}
        strokeDashoffset={circumference / 4} strokeLinecap="round"
        style={{ transition: "stroke-dasharray 600ms ease" }} />
      <text x={size / 2} y={size / 2} textAnchor="middle" dominantBaseline="central"
        fill="var(--ink)" fontSize={size * 0.28} fontFamily="var(--font-mono)" fontWeight="600">
        {Math.round(ratio * 100)}
      </text>
    </svg>
  );
}

// module-level cache: survives unmount, shared across remounts
const memCache = { overview: null, items: null, reports: null, lastFilterKey: "" };

export default function MemoryPage() {
  const [overview, setOverview] = useState(memCache.overview);
  const [items, setItems] = useState(memCache.items || []);
  const [reports, setReports] = useState(memCache.reports || []);
  const [loading, setLoading] = useState(memCache.overview == null);
  const [error, setError] = useState("");
  const [filterKind, setFilterKind] = useState("");
  const [filterTag, setFilterTag] = useState("");
  const [selectedItem, setSelectedItem] = useState(null);
  const [detailTab, setDetailTab] = useState("detail");

  const load = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    if (!silent) setError("");
    try {
      const [ov, itemData, rptData] = await Promise.all([
        fetchMemoryOverview(),
        fetchMemoryItems({ kind: filterKind || undefined, tag: filterTag || undefined }),
        fetchMemoryReports(10),
      ]);
      memCache.overview = ov;
      memCache.items = itemData.items || [];
      memCache.reports = rptData.reports || [];
      memCache.lastFilterKey = `${filterKind}|${filterTag}`;
      setOverview(ov);
      setItems(memCache.items);
      setReports(memCache.reports);
      if (!silent) setError("");
    } catch (err) {
      if (!silent) setError(err.message || "无法连接到后端");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [filterKind, filterTag]);

  // initial load (skip if cache is fresh and filters unchanged)
  useEffect(() => {
    const key = `${filterKind}|${filterTag}`;
    if (memCache.overview != null && memCache.lastFilterKey === key) {
      // already loaded — just refresh silently in background
      load({ silent: true });
    } else {
      load();
    }
  }, [load, filterKind, filterTag]);

  // background polling — keep data fresh without flashing loading state
  useEffect(() => {
    const id = setInterval(() => { load({ silent: true }); }, 30_000);
    return () => clearInterval(id);
  }, [load]);

  const skillStats = overview?.skill_stats || [];
  const totalRuns = skillStats.reduce((s, r) => s + (r.total || 0), 0);
  const totalSuccess = skillStats.reduce((s, r) => s + (r.success || 0), 0);

  return (
    <div className="page memory-page">
      <div className="page-head compact">
        <div className="title-block">
          <span className="label">System · Memory &amp; Evolution</span>
          <h1>记忆与进化</h1>
          <p className="lede">
            {overview
              ? `${overview.item_count} 条记忆 · ${overview.thread_count} 个会话 · ${totalRuns} 次 skill 调用 · 成功率 ${totalRuns > 0 ? Math.round(totalSuccess / totalRuns * 100) : 0}%`
              : "系统记忆层级、skill 反馈与自动反思摘要"}
          </p>
        </div>
        <button className="btn ghost sm" onClick={load} disabled={loading}>
          <RefreshCw size={13} className={loading ? "spin" : ""} />
          <span>刷新</span>
        </button>
      </div>

      {error && (
        <div className="card" style={{ marginBottom: 12, borderColor: "oklch(0.70 0.18 25 / 0.5)" }}>
          <div className="card-body" style={{ padding: "10px 14px", color: "oklch(0.80 0.16 25)", fontSize: 12.5 }}>{error}</div>
        </div>
      )}

      <div className="mem-stats-strip">
        {LAYER_DEFS.map((layer) => {
          const Icon = layer.icon;
          const val = layerValue(layer.kind, overview);
          return (
            <div className="mem-stat-chip" key={layer.kind}>
              <Icon size={13} style={{ color: "var(--accent)", opacity: 0.8 }} />
              <span className="msc-label">{layer.cn}</span>
              <span className="msc-value">{loading ? "…" : val}</span>
            </div>
          );
        })}
        {totalRuns > 0 && (
          <div className="mem-stat-chip" style={{ marginLeft: "auto", gap: 8 }}>
            <MiniDonut success={totalSuccess} total={totalRuns} size={28} />
            <span className="msc-label">Skill 成功率</span>
          </div>
        )}
      </div>

      <div className="mem-filter-bar">
        <button className={`mem-filter-chip ${filterKind === "" ? "active" : ""}`} onClick={() => setFilterKind("")}>全部</button>
        {Object.entries(KIND_META).map(([kind, meta]) => (
          <button key={kind}
            className={`mem-filter-chip ${filterKind === kind ? "active" : ""}`}
            onClick={() => setFilterKind(filterKind === kind ? "" : kind)}
            style={filterKind === kind ? { borderColor: meta.color, color: meta.color } : undefined}
          >
            <span className="chip-dot" style={filterKind === kind ? { background: meta.color } : undefined} />
            {meta.label}
          </button>
        ))}
        <div style={{ position: "relative", marginLeft: 4 }}>
          <Search size={12} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--muted-2)", pointerEvents: "none" }} />
          <input className="mem-filter-search" placeholder="搜索标签…" value={filterTag}
            onChange={(e) => setFilterTag(e.target.value)} style={{ paddingLeft: 28 }} />
        </div>
        <span className="mem-filter-count">
          <span style={{ color: "var(--accent)", fontWeight: 600 }}>{items.length}</span> 条
        </span>
      </div>

      <div className="mem-content">
        <div className="mem-timeline-card">
          <div className="card-head">
            <span className="title">记忆时间线</span>
            <span className="eyebrow muted">{overview?.item_count || 0} total</span>
          </div>
          <div className="mem-timeline-body">
            {loading && <div className="mem-loading"><Loader2 size={18} className="spin" />加载中…</div>}
            {!loading && items.length === 0 && (
              <div className="mem-empty">
                <div className="me-icon"><Archive size={28} /></div>
                <h3>记忆系统就绪</h3>
                <p>完成 Console 对话、RAG 查询或 Skill 调用后，系统自动写入记忆。运行 seed 脚本可填充演示数据。</p>
                <span className="mono" style={{ fontSize: 10, color: "var(--muted-2)", marginTop: 4 }}>python -m backend.memory.seed</span>
              </div>
            )}
            {!loading && items.map((item, idx) => (
              <TimelineItem key={item.memory_id} item={item} isLast={idx === items.length - 1}
                selected={selectedItem?.memory_id === item.memory_id}
                onClick={() => { setSelectedItem(selectedItem?.memory_id === item.memory_id ? null : item); setDetailTab("detail"); }} />
            ))}
          </div>
        </div>

        <div className="mem-detail-panel">
          <div className="mem-detail-tabs">
            {DETAIL_TABS.map((tab) => (
              <button key={tab.id}
                className={`mem-detail-tab ${detailTab === tab.id ? "active" : ""}`}
                onClick={() => { setDetailTab(tab.id); if (tab.id !== "detail") setSelectedItem(null); }}
              >{tab.label}</button>
            ))}
          </div>
          <div className="mem-detail-body">
            {detailTab === "detail" && selectedItem && <DetailView item={selectedItem} />}
            {detailTab === "detail" && !selectedItem && (
              <div className="mem-empty">
                <div className="me-icon"><FileText size={22} /></div>
                <h3>选择一条记忆</h3>
                <p>点击左侧时间线中的条目查看详情。</p>
              </div>
            )}
            {detailTab === "evolution" && <EvolutionView reports={reports} loading={loading} onReflect={load} />}
            {detailTab === "reflect" && <ReflectionView overview={overview} reports={reports} loading={loading} skillStats={skillStats} />}
          </div>
        </div>
      </div>
    </div>
  );
}

function TimelineItem({ item, isLast, selected, onClick }) {
  const meta = KIND_META[item.kind] || { label: item.kind || "未知", icon: FileText, color: "var(--muted)" };
  const Icon = meta.icon;
  return (
    <div className={`mem-tl-item ${selected ? "selected" : ""}`} onClick={onClick}>
      <div className="mem-tl-rail">
        <div className="mem-tl-dot" style={{ borderColor: meta.color, background: selected ? meta.color : "transparent" }} />
        {!isLast && <div className="mem-tl-line" />}
      </div>
      <div className="mem-tl-content">
        <div className="mem-tl-head">
          <Icon size={12} style={{ color: meta.color, flexShrink: 0 }} />
          <span className="mem-tl-kind" style={{ color: meta.color }}>{meta.label}</span>
          {item.skill_name && <span className="mem-tl-skill">{item.skill_name}</span>}
          <span className="mem-tl-time">{formatShortTime(item.created_at)}</span>
        </div>
        <p className="mem-tl-text">{item.summary || item.text?.slice(0, 140)}</p>
        {item.tags?.length > 0 && (
          <div className="mem-tl-tags">
            {item.tags.slice(0, 3).map((t) => <span key={t} className="mem-tl-tag">{t}</span>)}
          </div>
        )}
      </div>
    </div>
  );
}

function DetailView({ item }) {
  const meta = KIND_META[item.kind] || { label: item.kind || "—", color: "var(--muted)" };
  return (
    <div className="mem-detail-content">
      <div className="mem-field">
        <span className="mem-field-label">Memory ID</span>
        <span className="mem-field-value mono">{item.memory_id}</span>
      </div>
      <div className="mem-field">
        <span className="mem-field-label">类型</span>
        <span className="mem-field-value" style={{ color: meta.color }}>{meta.label}</span>
      </div>
      <div className="mem-field">
        <span className="mem-field-label">来源会话</span>
        <span className="mem-field-value mono">{item.thread_id || "(全局)"}</span>
      </div>
      {item.skill_name && (
        <div className="mem-field">
          <span className="mem-field-label">关联技能</span>
          <span className="mem-field-value mono">{item.skill_name}</span>
        </div>
      )}
      <div className="mem-field">
        <span className="mem-field-label">置信度</span>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="mem-confidence-bar">
            <div className="mem-confidence-fill" style={{ width: `${item.confidence * 100}%` }} />
          </div>
          <span className="mono" style={{ fontSize: 11, color: "var(--ink-2)" }}>{Math.round(item.confidence * 100)}%</span>
        </div>
      </div>
      <div className="mem-field">
        <span className="mem-field-label">创建时间</span>
        <span className="mem-field-value mono">{formatTime(item.created_at)}</span>
      </div>
      {item.tags?.length > 0 && (
        <div className="mem-field">
          <span className="mem-field-label">标签</span>
          <div className="mem-tl-tags" style={{ marginTop: 4 }}>
            {item.tags.map((t) => <span className="mem-tl-tag" key={t}>{t}</span>)}
          </div>
        </div>
      )}
      <div className="mem-field">
        <span className="mem-field-label">全文</span>
        <div className="mem-detail-text">{item.text}</div>
      </div>
    </div>
  );
}

function EvolutionView({ reports, loading, onReflect }) {
  const [reflecting, setReflecting] = useState(false);
  const [reflectError, setReflectError] = useState("");

  const handleReflect = async () => {
    setReflecting(true);
    setReflectError("");
    try {
      await triggerReflect(168);
      if (onReflect) await onReflect();
    } catch (e) {
      setReflectError(e.message || "反思生成失败");
    } finally {
      setReflecting(false);
    }
  };

  const reflectBar = (
    <div className="mem-evo-toolbar">
      <div className="mem-evo-toolbar-info">
        <BrainCircuit size={13} style={{ color: "var(--accent)" }} />
        <span>回看最近 7 天的技能调用、反馈与查询，生成进化报告</span>
      </div>
      <button className="btn primary sm" onClick={handleReflect} disabled={reflecting}>
        {reflecting ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />}
        <span>{reflecting ? "反思中…" : "触发反思"}</span>
      </button>
    </div>
  );

  if (loading) {
    return (
      <>
        {reflectBar}
        <div className="mem-loading"><Loader2 size={18} className="spin" />加载中…</div>
      </>
    );
  }

  return (
    <>
      {reflectBar}
      {reflectError && (
        <div className="mem-evo-error">{reflectError}</div>
      )}
      {reflecting && reports.length === 0 && (
        <div className="mem-loading"><Loader2 size={18} className="spin" />正在分析近期数据…</div>
      )}
      {reports.length === 0 && !reflecting ? (
        <div className="mem-empty">
          <div className="me-icon"><BrainCircuit size={22} /></div>
          <h3>暂无进化报告</h3>
          <p>点击上方「触发反思」，让系统回看近期数据并生成周期反思摘要与改进建议。</p>
        </div>
      ) : (
        <div className="mem-evo-list">
          {reports.map((r) => {
            let metrics = {};
            try { metrics = typeof r.metrics_json === "string" ? JSON.parse(r.metrics_json) : r.metrics_json || {}; } catch {}
            let suggestions = [];
            try { suggestions = typeof r.suggestions_json === "string" ? JSON.parse(r.suggestions_json) : r.suggestions_json || []; } catch {}
            const successRate = metrics.success_rate;
            const trend = successRate != null ? (successRate >= 0.8 ? "up" : successRate >= 0.5 ? "flat" : "down") : null;
            const TrendIcon = trend === "up" ? ArrowUp : trend === "down" ? ArrowDown : Minus;
            const trendColor = trend === "up" ? "oklch(0.78 0.14 155)" : trend === "down" ? "oklch(0.78 0.16 25)" : "var(--muted)";
            const numericMetrics = Object.entries(metrics).filter(([, v]) => typeof v === "number");

            return (
              <div className="mem-evo-card" key={r.report_id}>
                <div className="mem-evo-header">
                  <div className="mem-evo-period">
                    <Clock size={11} style={{ color: "var(--muted)" }} />
                    <span>{r.period || "周期报告"}</span>
                  </div>
                  {trend && (
                    <div className="mem-evo-trend" style={{ color: trendColor }}>
                      <TrendIcon size={12} />
                      <span>{successRate != null ? `${Math.round(successRate * 100)}%` : ""}</span>
                    </div>
                  )}
                </div>
                <p className="mem-evo-summary">{r.summary || "(无摘要)"}</p>
                {numericMetrics.length > 0 && (
                  <div className="mem-evo-metrics">
                    {numericMetrics.slice(0, 4).map(([k, v]) => (
                      <div key={k} className="mem-evo-metric">
                        <span className="mem-evo-mk">{k.replace(/_/g, " ")}</span>
                        <span className="mem-evo-mv">{v < 1 && v > 0 ? `${Math.round(v * 100)}%` : v}</span>
                      </div>
                    ))}
                  </div>
                )}
                {suggestions.length > 0 && (
                  <div className="mem-evo-suggestions">
                    {suggestions.slice(0, 3).map((s, i) => (
                      <div key={i} className="mem-evo-sug">
                        <span className={`mem-evo-pri ${s.priority || "low"}`}>{s.priority || "—"}</span>
                        <span>{s.action}</span>
                      </div>
                    ))}
                  </div>
                )}
                <span className="mem-evo-time">{formatShortTime(r.created_at)}</span>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

function ReflectionView({ overview, reports, loading, skillStats }) {
  if (loading) return <div className="mem-loading"><Loader2 size={18} className="spin" />加载中…</div>;
  if (!overview) {
    return (
      <div className="mem-empty">
        <div className="me-icon"><Clock size={22} /></div>
        <h3>等待数据</h3>
        <p>后端连接后将自动展示反思队列与 skill 统计。</p>
      </div>
    );
  }

  const failSkills = (skillStats || []).filter((s) => s.total - s.success > 0);

  return (
    <div className="mem-reflect-content">
      <div className="mem-reflect-grid">
        <div className="mem-reflect-stat">
          <span className="mrs-value">{overview.skill_run_count || 0}</span>
          <span className="mrs-label">Skill 调用</span>
        </div>
        <div className="mem-reflect-stat">
          <span className="mrs-value">{failSkills.length}</span>
          <span className="mrs-label">失败技能</span>
        </div>
        <div className="mem-reflect-stat">
          <span className="mrs-value">{overview.feedback_count || 0}</span>
          <span className="mrs-label">用户反馈</span>
        </div>
        <div className="mem-reflect-stat">
          <span className="mrs-value">{reports.length}</span>
          <span className="mrs-label">进化报告</span>
        </div>
      </div>

      {(skillStats || []).length > 0 && (
        <div className="mem-reflect-skills">
          <span className="mem-field-label" style={{ marginBottom: 10, display: "block" }}>技能表现</span>
          {skillStats.slice(0, 6).map((s) => {
            const rate = s.total > 0 ? s.success / s.total : 0;
            return (
              <div className="mem-skill-row" key={s.skill_name}>
                <span className="msr-name">{s.skill_name}</span>
                <div className="msr-bar-wrap">
                  <div className="msr-bar" style={{ width: `${rate * 100}%` }} />
                </div>
                <span className="msr-stat">{s.success}/{s.total}</span>
                <span className="msr-latency">{Math.round(s.avg_latency_ms || 0)}ms</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
