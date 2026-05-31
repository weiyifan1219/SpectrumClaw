import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Archive,
  BookMarked,
  BrainCircuit,
  Clock,
  FileText,
  Layers,
  Loader2,
  RefreshCw,
  Route,
  Search,
  Sparkles,
} from "lucide-react";
import { fetchMemoryItems, fetchMemoryOverview, fetchMemoryReports } from "../lib/api.js";

/* ── helpers ── */

const LAYER_DEFS = [
  { kind: "working", label: "Working", cn: "工作记忆", icon: Activity, desc: "当前请求上下文" },
  { kind: "thread", label: "Thread", cn: "会话记忆", icon: Layers, desc: "活跃会话" },
  { kind: "episodic", label: "Episodic", cn: "事件记忆", icon: Sparkles, desc: "历史任务经历" },
  { kind: "skill", label: "Skill", cn: "能力记忆", icon: Route, desc: "Skill 使用经验" },
  { kind: "domain", label: "Domain", cn: "领域知识", icon: BookMarked, desc: "频谱操作知识" },
];

const KIND_META = {
  episodic: { label: "事件记忆", icon: Sparkles, tint: "episodic" },
  skill: { label: "能力记忆", icon: Route, tint: "skill" },
  domain: { label: "领域知识", icon: BookMarked, tint: "domain" },
  evolution: { label: "进化记忆", icon: BrainCircuit, tint: "evolution" },
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
  } catch {
    return iso;
  }
}

function layerValue(kind, overview) {
  if (!overview) return "—";
  switch (kind) {
    case "working": return "当前请求";
    case "thread": return `${overview.thread_count || 0}`;
    case "episodic": return `${overview.episodic_count || 0}`;
    case "skill": return `${overview.skill_count || 0}`;
    case "domain": return `${overview.domain_count || 0}`;
    default: return "—";
  }
}

function layerFill(kind, overview) {
  if (!overview) return 0;
  const maxes = { thread: 20, episodic: 50, skill: 30, domain: 20, working: 1 };
  const vals = {
    working: 1,
    thread: overview.thread_count || 0,
    episodic: overview.episodic_count || 0,
    skill: overview.skill_count || 0,
    domain: overview.domain_count || 0,
  };
  return Math.min(1, (vals[kind] || 0) / (maxes[kind] || 20));
}

/* ── component ── */

export default function MemoryPage() {
  const [overview, setOverview] = useState(null);
  const [items, setItems] = useState([]);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterKind, setFilterKind] = useState("");
  const [filterTag, setFilterTag] = useState("");
  const [selectedItem, setSelectedItem] = useState(null);
  const [detailTab, setDetailTab] = useState("detail");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [ov, itemData, rptData] = await Promise.all([
        fetchMemoryOverview(),
        fetchMemoryItems({ kind: filterKind || undefined, tag: filterTag || undefined }),
        fetchMemoryReports(10),
      ]);
      setOverview(ov);
      setItems(itemData.items || []);
      setReports(rptData.reports || []);
    } catch (err) {
      setError(err.message || "无法连接到后端");
    } finally {
      setLoading(false);
    }
  }, [filterKind, filterTag]);

  useEffect(() => { load(); }, [load]);

  const activeTab = selectedItem ? "detail" : detailTab;

  return (
    <div className="page memory-page">
      {/* ── page header ── */}
      <div className="page-head compact">
        <div className="title-block">
          <span className="label">System · Memory &amp; Evolution</span>
          <h1>记忆与进化</h1>
          <p className="lede">
            {overview
              ? `${overview.item_count} 条记忆 · ${overview.thread_count} 个会话 · ${overview.skill_run_count} 次 skill 调用`
              : "系统记忆层级、skill 反馈与自动反思摘要"}
          </p>
        </div>
        <button className="btn ghost sm" onClick={load} disabled={loading}>
          <RefreshCw size={13} className={loading ? "spin" : ""} />
          <span>刷新</span>
        </button>
      </div>

      {/* ── error ── */}
      {error && (
        <div className="card" style={{ marginBottom: 12, borderColor: "var(--err)" }}>
          <div className="card-body" style={{ padding: "10px 14px", color: "var(--err)", fontSize: 12.5 }}>{error}</div>
        </div>
      )}

      {/* ── stat cards ── */}
      {!error && (
        <div className="mem-stats">
          {LAYER_DEFS.map((layer) => {
            const Icon = layer.icon;
            const val = layerValue(layer.kind, overview);
            const fill = layerFill(layer.kind, overview);
            return (
              <div className="mem-stat-card" data-kind={layer.kind} key={layer.kind}>
                <div className="ms-icon" data-kind={layer.kind}><Icon size={17} /></div>
                <span className="ms-label">{layer.label}</span>
                <div className="ms-value">{loading ? "…" : val}</div>
                <div className="ms-sub">{layer.cn} · {layer.desc}</div>
                <div className="ms-bar">
                  <div className="ms-bar-fill" style={{ width: `${fill * 100}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── filter bar ── */}
      <div className="mem-filter-bar">
        <button className={`mem-filter-chip ${filterKind === "" ? "active" : ""}`} onClick={() => setFilterKind("")}>
          全部
        </button>
        {Object.entries(KIND_META).map(([kind, meta]) => {
          const Icon = meta.icon;
          return (
            <button
              key={kind}
              className={`mem-filter-chip ${filterKind === kind ? "active" : ""}`}
              onClick={() => setFilterKind(filterKind === kind ? "" : kind)}
            >
              <span className="chip-dot" />
              {meta.label}
            </button>
          );
        })}
        <div style={{ position: "relative", marginLeft: 4 }}>
          <Search size={12} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--muted-2)", pointerEvents: "none" }} />
          <input
            className="mem-filter-search"
            placeholder="搜索标签…"
            value={filterTag}
            onChange={(e) => setFilterTag(e.target.value)}
            style={{ paddingLeft: 28 }}
          />
        </div>
        <span className="mem-filter-count">
          <span style={{ color: "var(--accent)", fontWeight: 600 }}>{items.length}</span> 条记忆
        </span>
      </div>

      {/* ── main content ── */}
      <div className={`mem-content ${selectedItem ? "" : "single-col"}`}>
        {/* items list */}
        <div className="mem-items-card">
          <div className="card-head">
            <span className="title">记忆条目</span>
            <span className="eyebrow muted">{overview?.item_count || 0} total</span>
          </div>
          <div className="mem-items-body">
            {loading && (
              <div className="mem-loading">
                <Loader2 size={18} className="spin" />
                加载中…
              </div>
            )}

            {!loading && items.length === 0 && (
              <div className="mem-empty">
                <div className="me-icon"><Archive size={22} /></div>
                <h3>暂无记忆</h3>
                <p>完成一次对话或 RAG 查询后，记忆系统会自动记录任务经历与检索结果。</p>
              </div>
            )}

            {!loading && items.map((item) => {
              const meta = KIND_META[item.kind] || { label: item.kind || "未知", icon: FileText, tint: "episodic" };
              const Icon = meta.icon;
              const isSel = selectedItem?.memory_id === item.memory_id;
              return (
                <div
                  key={item.memory_id}
                  className={`mem-item-row ${isSel ? "selected" : ""}`}
                  onClick={() => setSelectedItem(isSel ? null : item)}
                >
                  <div className="mi-kind-icon" data-kind={meta.tint}><Icon size={14} /></div>
                  <div className="mi-body">
                    <div className="mi-head">
                      <span className="mi-kind-label" data-kind={meta.tint}>{meta.label}</span>
                      {item.skill_name && <span className="mi-skill">{item.skill_name}</span>}
                    </div>
                    <p className="mi-summary">{item.summary || item.text?.slice(0, 120)}</p>
                    {item.tags?.length > 0 && (
                      <div className="mi-tags">
                        {item.tags.slice(0, 4).map((t) => <span className="mi-tag" key={t}>{t}</span>)}
                      </div>
                    )}
                  </div>
                  <span className="mi-time">{formatTime(item.created_at)}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* right panel: detail / evolution / reflection */}
        <div className="mem-detail-panel">
          <div className="mem-detail-tabs">
            {DETAIL_TABS.map((tab) => (
              <button
                key={tab.id}
                className={`mem-detail-tab ${activeTab === tab.id ? "active" : ""}`}
                onClick={() => { setDetailTab(tab.id); if (tab.id !== "detail") setSelectedItem(null); }}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="mem-detail-body">
            {activeTab === "detail" && selectedItem && (
              <DetailView item={selectedItem} />
            )}
            {activeTab === "detail" && !selectedItem && (
              <div className="mem-empty">
                <div className="me-icon"><FileText size={22} /></div>
                <h3>选择一条记忆</h3>
                <p>点击左侧列表中的记忆条目查看详细信息。</p>
              </div>
            )}
            {activeTab === "evolution" && (
              <EvolutionView reports={reports} loading={loading} />
            )}
            {activeTab === "reflect" && (
              <ReflectionView overview={overview} reports={reports} loading={loading} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── sub-views ── */

function DetailView({ item }) {
  const meta = KIND_META[item.kind] || { label: item.kind || "—", tint: "episodic" };
  return (
    <div>
      <div className="mem-field">
        <span className="mem-field-label">Memory ID</span>
        <span className="mem-field-value mono">{item.memory_id}</span>
      </div>
      <div className="mem-field">
        <span className="mem-field-label">类型</span>
        <span className="mem-field-value">{meta.label}</span>
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
        <span className="mem-field-value mono">{Math.round(item.confidence * 100)}%</span>
        <div className="mem-confidence-bar">
          <div className="mem-confidence-fill" style={{ width: `${item.confidence * 100}%` }} />
        </div>
      </div>
      <div className="mem-field">
        <span className="mem-field-label">创建时间</span>
        <span className="mem-field-value mono">{formatTime(item.created_at)}</span>
      </div>
      {item.valid_to && (
        <div className="mem-field">
          <span className="mem-field-label">有效期至</span>
          <span className="mem-field-value mono">{formatTime(item.valid_to)}</span>
        </div>
      )}
      {item.tags?.length > 0 && (
        <div className="mem-field">
          <span className="mem-field-label">标签</span>
          <div className="mi-tags" style={{ marginTop: 4 }}>
            {item.tags.map((t) => <span className="mi-tag" key={t}>{t}</span>)}
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

function EvolutionView({ reports, loading }) {
  if (loading) {
    return (
      <div className="mem-loading"><Loader2 size={18} className="spin" />加载中…</div>
    );
  }
  if (reports.length === 0) {
    return (
      <div className="mem-empty">
        <div className="me-icon"><BrainCircuit size={22} /></div>
        <h3>暂无进化报告</h3>
        <p>系统将在累积足够数据后自动生成周期反思摘要与改进建议。</p>
      </div>
    );
  }
  return (
    <div>
      {reports.map((r) => {
        const tone = r.status === "confirmed" ? "ok" : r.status === "pending" ? "info" : "accent";
        return (
          <div className="mem-evo-item" data-tone={tone} key={r.report_id}>
            <span className="ev-time">{formatTime(r.created_at)}</span>
            <span className="ev-period">{r.period || "周期报告"}</span>
            <p className="ev-summary">{r.summary || "(无摘要)"}</p>
          </div>
        );
      })}
    </div>
  );
}

function ReflectionView({ overview, reports, loading }) {
  if (loading) {
    return (
      <div className="mem-loading"><Loader2 size={18} className="spin" />加载中…</div>
    );
  }
  if (!overview) {
    return (
      <div className="mem-empty">
        <div className="me-icon"><Clock size={22} /></div>
        <h3>等待数据</h3>
        <p>后端连接后将自动展示反思队列与 skill 统计。</p>
      </div>
    );
  }

  const skillStats = overview.skill_stats || [];
  const failSkills = skillStats.filter((s) => s.total - s.success > 0);

  return (
    <div>
      {/* summary rows */}
      <div style={{ marginBottom: 20 }}>
        <span className="mem-field-label" style={{ marginBottom: 8, display: "block" }}>概览</span>
        <div className="mem-ref-row">
          <span className="rr-label">Skill 调用</span>
          <span className="rr-value">{overview.skill_run_count || 0} 次</span>
        </div>
        <div className="mem-ref-row">
          <span className="rr-label">失败 skill</span>
          <span className="rr-value">{failSkills.length} 个</span>
        </div>
        <div className="mem-ref-row">
          <span className="rr-label">用户反馈</span>
          <span className="rr-value">{overview.feedback_count || 0} 条</span>
        </div>
        <div className="mem-ref-row">
          <span className="rr-label">进化报告</span>
          <span className="rr-value">{reports.length} 份</span>
        </div>
      </div>

      {/* skill breakdown */}
      {skillStats.length > 0 && (
        <div>
          <span className="mem-field-label" style={{ marginBottom: 8, display: "block" }}>技能统计</span>
          {skillStats.slice(0, 8).map((s) => (
            <div className="mem-skill-mini" key={s.skill_name}>
              <span className="sm-name">{s.skill_name}</span>
              <span className="sm-stat">
                {s.success}/{s.total} 成功 · {Math.round(s.avg_latency_ms || 0)}ms
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
