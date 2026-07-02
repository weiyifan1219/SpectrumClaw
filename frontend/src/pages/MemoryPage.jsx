import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Archive,
  BarChart3,
  BookMarked,
  BrainCircuit,
  CalendarDays,
  FileText,
  Gauge,
  Loader2,
  MessageSquare,
  RefreshCw,
  Search,
  Sparkles,
  Target,
  Trash2,
  X,
} from "lucide-react";
import { fetchMemoryItems, fetchMemoryOverview, fetchMemoryReports, triggerReflect, fetchThreads, deleteThread, fetchMemoryThread } from "../lib/api.js";

function formatShortTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch { return iso; }
}

const MEM_TABS = [
  { id: "threads", label: "历史记录", cn: "对话历史 · 查看 & 总结 & 删除", color: "var(--accent)", accent: "#3B82F6" },
  { id: "knowledge", label: "知识沉淀", cn: "技能经验 & 领域知识融合", color: "oklch(0.78 0.15 155)", accent: "#22C55E" },
  { id: "evolution", label: "进化报告", cn: "反馈分析 · 错误趋势 · 优化方向", color: "oklch(0.78 0.14 55)", accent: "#F59E0B" },
];

function tabAccent(tabId) { return MEM_TABS.find((t) => t.id === tabId) || MEM_TABS[0]; }

function threadMsgsKey(tid) { return `sc_msgs_${tid}`; }

function loadLocalThreadEvents(tid) {
  try {
    const raw = localStorage.getItem(threadMsgsKey(tid));
    if (!raw) return [];
    const msgs = JSON.parse(raw);
    if (!Array.isArray(msgs)) return [];
    return msgs
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m, idx) => ({
        event_id: `local-${tid}-${idx}`,
        role: m.role,
        content: m.content || "",
        created_at: m.meta?.ts || "",
        local: true,
      }));
  } catch {
    return [];
  }
}

function parseJsonish(value, fallback) {
  if (value == null || value === "") return fallback;
  if (typeof value !== "string") return value;
  try { return JSON.parse(value); } catch { return fallback; }
}

function normalizedReport(report) {
  return {
    ...report,
    metrics: parseJsonish(report.metrics ?? report.metrics_json, {}),
    suggestions: parseJsonish(report.suggestions ?? report.suggestions_json, []),
  };
}

export default function MemoryPage({ active = true }) {
  const [tab, setTab] = useState("threads");
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Threads
  const [threads, setThreads] = useState([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [threadDetail, setThreadDetail] = useState(null);
  const [threadDetailId, setThreadDetailId] = useState(null);
  const [threadDetailLoading, setThreadDetailLoading] = useState(false);
  const [threadDetailError, setThreadDetailError] = useState("");
  const [threadSearch, setThreadSearch] = useState("");
  const [summarizing, setSummarizing] = useState("");

  // Knowledge (merged skill + domain)
  const [knowledgeItems, setKnowledgeItems] = useState([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [knowledgeFilter, setKnowledgeFilter] = useState("all"); // all | skill | domain
  const [knowledgeSearch, setKnowledgeSearch] = useState("");
  const [selectedKnowledge, setSelectedKnowledge] = useState(null);

  // Evolution
  const [reports, setReports] = useState([]);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [reflecting, setReflecting] = useState(false);

  /* ── load overview ── */
  const loadOverview = useCallback(async () => {
    try {
      const ov = await fetchMemoryOverview();
      setOverview(ov);
      setError("");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (active) { loadOverview(); } }, [active]); // eslint-disable-line

  /* ── Threads ── */
  const loadThreads = useCallback(async () => {
    setThreadsLoading(true);
    try {
      const data = await fetchThreads({ limit: 100 });
      setThreads(data.threads || []);
    } catch { /* */ }
    finally { setThreadsLoading(false); }
  }, []);

  useEffect(() => { if (active) { loadThreads(); } }, [active]); // eslint-disable-line

  async function handleViewThread(e, tid) {
    e.preventDefault();
    e.stopPropagation();
    if (threadDetailId === tid) { setThreadDetail(null); setThreadDetailId(null); return; }
    const row = threads.find((t) => t.thread_id === tid);
    const localEvents = loadLocalThreadEvents(tid);
    setThreadDetailId(tid);
    setThreadDetailError("");
    setThreadDetail({
      thread: row || { thread_id: tid, title: "对话详情" },
      events: localEvents,
      items: [],
      localOnly: localEvents.length > 0,
    });
    setThreadDetailLoading(true);
    try {
      const data = await fetchMemoryThread(tid);
      const backendEvents = (data.events || []).filter((e) => e.role === "user" || e.role === "assistant");
      setThreadDetail({
        ...data,
        thread: data.thread || row || { thread_id: tid, title: "对话详情" },
        events: backendEvents.length > 0 ? data.events : localEvents,
        localOnly: backendEvents.length === 0 && localEvents.length > 0,
      });
    } catch (err) {
      setThreadDetailError(err.message || "加载失败");
    } finally {
      setThreadDetailLoading(false);
    }
  }

  async function handleDeleteThread(tid) {
    if (!confirm("确定删除此对话？相关记忆也会一并清除。")) return;
    try {
      await deleteThread(tid);
      setThreads((prev) => prev.filter((t) => t.thread_id !== tid));
      if (threadDetailId === tid) { setThreadDetail(null); setThreadDetailId(null); }
    } catch (e) { alert("删除失败: " + e.message); }
  }

  async function handleSummarizeThread(tid) {
    setSummarizing(tid);
    try {
      const apiBase = import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8230`;
      const resp = await fetch(`${apiBase}/api/memory/threads/${encodeURIComponent(tid)}/summarize`, { method: "POST" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setThreads((prev) => prev.map((t) => t.thread_id === tid ? { ...t, summary: data.summary } : t));
      if (threadDetailId === tid && threadDetail) {
        setThreadDetail({ ...threadDetail, thread: { ...threadDetail.thread, summary: data.summary } });
      }
    } catch (e) { alert("总结失败: " + e.message); }
    finally { setSummarizing(""); }
  }

  /* ── Knowledge ── */
  async function loadKnowledge() {
    setKnowledgeLoading(true);
    try {
      const [skillData, domainData] = await Promise.all([
        fetchMemoryItems({ kind: "skill", limit: 100 }),
        fetchMemoryItems({ kind: "domain", limit: 100 }),
      ]);
      const merged = [
        ...(skillData.items || []).map((i) => ({ ...i, _source: "skill" })),
        ...(domainData.items || []).map((i) => ({ ...i, _source: "domain" })),
      ].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
      setKnowledgeItems(merged);
    } catch { /* */ }
    finally { setKnowledgeLoading(false); }
  }

  useEffect(() => { if (active && tab === "knowledge") loadKnowledge(); }, [active, tab]);

  /* ── Evolution ── */
  async function loadReports() {
    setReportsLoading(true);
    try {
      const data = await fetchMemoryReports(20);
      setReports((data.reports || []).map(normalizedReport));
    } catch { /* */ }
    finally { setReportsLoading(false); }
  }

  useEffect(() => { if (active && tab === "evolution") loadReports(); }, [active, tab]);

  async function handleReflect() {
    setReflecting(true);
    try {
      await triggerReflect(168);
      await loadReports();
    } catch (e) { alert("反思失败: " + e.message); }
    finally { setReflecting(false); }
  }

  /* ── filtered ── */
  const filteredThreads = threads.filter((t) => {
    if (!threadSearch) return true;
    const q = threadSearch.toLowerCase();
    return (t.title || "").toLowerCase().includes(q) || (t.last_message || "").toLowerCase().includes(q);
  });

  const filteredKnowledge = knowledgeItems.filter((item) => {
    if (knowledgeFilter !== "all" && item._source !== knowledgeFilter) return false;
    if (knowledgeSearch) {
      const q = knowledgeSearch.toLowerCase();
      return (item.summary || item.text || "").toLowerCase().includes(q)
        || (item.tags || []).some((t) => t.toLowerCase().includes(q));
    }
    return true;
  });

  /* ── stats ── */
  const skillStats = overview?.skill_stats || [];
  const totalRuns = skillStats.reduce((s, r) => s + (r.total || 0), 0);
  const totalSuccess = skillStats.reduce((s, r) => s + (r.success || 0), 0);
  const latestReport = reports[0] || null;
  const latestMetrics = latestReport?.metrics || {};
  const latestSuggestions = Array.isArray(latestReport?.suggestions) ? latestReport.suggestions : [];

  return (
    <div className="page memory-page">
      <div className="page-head compact">
        <div className="title-block">
          <span className="label">System · Memory &amp; Evolution</span>
          <h1>记忆与进化</h1>
          <p className="lede">
            {overview
              ? `${overview.thread_count || 0} 个对话 · ${overview.item_count || 0} 条记忆 · ${reports.length} 份报告`
              : "对话历史、知识沉淀与进化反思"}
          </p>
        </div>
        <button className="btn ghost sm" onClick={loadOverview} disabled={loading}>
          <RefreshCw size={13} className={loading ? "spin" : ""} />
        </button>
      </div>

      {/* ── Tab bar ── */}
      <div className="mem-tab-bar">
        {MEM_TABS.map((t) => (
          <button key={t.id} className={`mem-tab ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
            style={tab === t.id ? { borderColor: t.color, background: `${t.accent}12` } : {}}>
            <span className="mem-tab-label" style={tab === t.id ? { color: t.color } : {}}>{t.label}</span>
            <span className="mem-tab-desc">{t.cn}</span>
          </button>
        ))}
      </div>

      <div className="mem-panel">
        {/* ═══════════ TAB 1: 历史记录 ═══════════ */}
        {tab === "threads" && (
          <div className="mem-thread-layout">
            <div className="mem-thread-list">
              <div className="mem-search-bar">
                <Search size={13} />
                <input placeholder="搜索对话…" value={threadSearch}
                  onChange={(e) => setThreadSearch(e.target.value)} />
                <span className="mem-search-count">{filteredThreads.length} 个对话</span>
              </div>
              {threadsLoading && <div className="mem-loading"><Loader2 size={16} className="spin" />加载中…</div>}
              {!threadsLoading && filteredThreads.length === 0 && (
                <div className="mem-empty"><Archive size={24} /><p>{threadSearch ? "无匹配对话" : "暂无对话，去 Console 开始吧"}</p></div>
              )}
              {filteredThreads.map((t) => (
                <div key={t.thread_id}
                  className={`mem-thread-row ${threadDetailId === t.thread_id ? "active" : ""}`}
                  onClick={(e) => handleViewThread(e, t.thread_id)}>
                  <div className="mtr-main">
                    <span className="mtr-title">{t.title || "未命名对话"}</span>
                    {t.summary && <span className="mtr-summary">{t.summary.slice(0, 80)}</span>}
                    <span className="mtr-preview">{t.last_message?.slice(0, 60) || "（空对话）"}</span>
                  </div>
                  <div className="mtr-actions">
                    <span className="mtr-meta">{formatShortTime(t.updated_at)}</span>
                    <button className="btn ghost sm" title="AI 总结" style={{ color: "var(--accent)" }}
                      onClick={(e) => { e.stopPropagation(); handleSummarizeThread(t.thread_id); }}
                      disabled={summarizing === t.thread_id}>
                      {summarizing === t.thread_id ? <Loader2 size={11} className="spin" /> : <Sparkles size={11} />}
                    </button>
                    <button className="btn ghost sm" title="删除" style={{ color: "oklch(0.70 0.18 25)" }}
                      onClick={(e) => { e.stopPropagation(); handleDeleteThread(t.thread_id); }}>
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <div className="mem-thread-detail">
              {threadDetail && (
                <>
                  <div className="mtd-head">
                    <button className="btn ghost sm" onClick={() => { setThreadDetail(null); setThreadDetailId(null); }}>
                      <X size={14} />
                    </button>
                    <span className="mtd-title">{threadDetail.thread?.title || "对话详情"}</span>
                    <button className="btn ghost sm" title="总结此对话"
                      onClick={() => handleSummarizeThread(threadDetailId)}
                      disabled={summarizing === threadDetailId}>
                      {summarizing === threadDetailId ? <Loader2 size={12} className="spin" /> : <Sparkles size={12} />}
                      总结
                    </button>
                  </div>
                  {(threadDetailLoading || threadDetailError || threadDetail.localOnly) && (
                    <div className={`mtd-state ${threadDetailError ? "error" : threadDetail.localOnly ? "local" : ""}`}>
                      {threadDetailLoading && <Loader2 size={13} className="spin" />}
                      {threadDetailError && <AlertTriangle size={13} />}
                      {!threadDetailError && threadDetail.localOnly && <MessageSquare size={13} />}
                      <span>
                        {threadDetailError
                          ? `后端详情暂不可用，已保留本地记录：${threadDetailError}`
                          : threadDetail.localOnly
                            ? "此对话来自本机缓存，后端 memory_events 暂无可展示消息"
                            : "正在同步后端详情…"}
                      </span>
                    </div>
                  )}
                  {threadDetail.thread?.summary && (
                    <div className="mtd-summary-box">
                      <span className="mtd-summary-label">AI 摘要</span>
                      <p>{threadDetail.thread.summary}</p>
                    </div>
                  )}
                  <div className="mtd-messages">
                    {(threadDetail.events || []).filter((e) => e.role === "user" || e.role === "assistant").map((e, idx) => (
                      <div key={e.event_id || `${e.role}-${idx}`} className={`mtd-msg ${e.role}`}>
                        <span className="mtd-msg-role">{e.role === "user" ? "USER" : "SPECTRUMCLAW"}</span>
                        <p>{e.content?.slice(0, 600)}</p>
                        <span className="mtd-msg-time">{formatShortTime(e.created_at)}</span>
                      </div>
                    ))}
                    {!threadDetailLoading && (threadDetail.events || []).filter((e) => e.role === "user" || e.role === "assistant").length === 0 && (
                      <div className="mem-empty compact"><MessageSquare size={22} /><p>这个线程暂时没有可展示的聊天消息</p></div>
                    )}
                  </div>
                </>
              )}
              {!threadDetail && (
                <div className="mem-empty"><FileText size={24} /><p>选择左侧对话查看详情</p></div>
              )}
            </div>
          </div>
        )}

        {/* ═══════════ TAB 2: 知识沉淀 ═══════════ */}
        {tab === "knowledge" && (
          <div className="mem-knowledge-panel">
            <div className="mem-search-bar">
              <Search size={13} />
              <input placeholder="搜索知识…" value={knowledgeSearch}
                onChange={(e) => setKnowledgeSearch(e.target.value)} />
              <div className="mem-knowledge-filters">
                <button className={`mem-kf-chip ${knowledgeFilter === "all" ? "active" : ""}`} onClick={() => setKnowledgeFilter("all")}>全部</button>
                <button className={`mem-kf-chip ${knowledgeFilter === "skill" ? "active" : ""}`} onClick={() => setKnowledgeFilter("skill")}>技能经验</button>
                <button className={`mem-kf-chip ${knowledgeFilter === "domain" ? "active" : ""}`} onClick={() => setKnowledgeFilter("domain")}>领域知识</button>
              </div>
              <span className="mem-search-count">{filteredKnowledge.length} 条</span>
            </div>
            {knowledgeLoading && <div className="mem-loading"><Loader2 size={16} className="spin" />加载中…</div>}
            <div className="mem-knowledge-grid">
              {filteredKnowledge.map((item) => (
                <div key={item.memory_id} className={`mem-kcard ${selectedKnowledge?.memory_id === item.memory_id ? "expanded" : ""}`}
                  onClick={() => setSelectedKnowledge(selectedKnowledge?.memory_id === item.memory_id ? null : item)}>
                  <div className="mem-kcard-head">
                    <span className={`mem-kcard-source ${item._source}`}>{item._source === "skill" ? "技能" : "领域"}</span>
                    {item.skill_name && <span className="mem-kcard-skill">{item.skill_name}</span>}
                    <span className="mem-kcard-time">{formatShortTime(item.created_at)}</span>
                  </div>
                  <p className="mem-kcard-text">{item.summary || item.text?.slice(0, 200)}</p>
                  {item.tags?.length > 0 && (
                    <div className="mem-kcard-tags">
                      {item.tags.slice(0, 5).map((tag) => <span key={tag} className="mem-kcard-tag">{tag}</span>)}
                    </div>
                  )}
                  {selectedKnowledge?.memory_id === item.memory_id && (
                    <div className="mem-kcard-detail">
                      <div className="mem-field">
                        <span className="mem-field-label">Memory ID</span>
                        <span className="mem-field-value mono">{item.memory_id}</span>
                      </div>
                      <div className="mem-field">
                        <span className="mem-field-label">来源会话</span>
                        <span className="mem-field-value mono">{item.thread_id || "（全局）"}</span>
                      </div>
                      {item.confidence != null && (
                        <div className="mem-field">
                          <span className="mem-field-label">置信度</span>
                          <span className="mem-field-value">{Math.round(item.confidence * 100)}%</span>
                        </div>
                      )}
                      {item.text && item.text !== item.summary && (
                        <div className="mem-field">
                          <span className="mem-field-label">完整内容</span>
                          <p className="mem-detail-text">{item.text}</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
              {!knowledgeLoading && filteredKnowledge.length === 0 && (
                <div className="mem-empty"><BookMarked size={24} /><p>暂无知识沉淀，多使用 Skill 后会自动积累</p></div>
              )}
            </div>
          </div>
        )}

        {/* ═══════════ TAB 3: 进化报告 ═══════════ */}
        {tab === "evolution" && (
          <div className="mem-evolution-panel">
            <div className="mem-evo-command">
              <div className="mem-evo-command-copy">
                <span className="mem-evo-kicker"><BrainCircuit size={13} /> Evolution Loop</span>
                <h2>把历史运行转成下一轮改进</h2>
                <p>聚合最近对话、技能调用、反馈与错误趋势，形成可执行的优化建议。</p>
              </div>
              <button className="btn ghost mem-evo-trigger" onClick={handleReflect} disabled={reflecting}>
                {reflecting ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />}
                {reflecting ? "反思中…" : "触发反思"}
              </button>
            </div>

            {reportsLoading && <div className="mem-loading"><Loader2 size={16} className="spin" />加载中…</div>}

            <div className="mem-evo-scoreboard">
              <div className="mem-evo-stat">
                <BarChart3 size={15} />
                <span className="mes-value">{reports.length}</span>
                <span className="mes-label">报告</span>
              </div>
              <div className="mem-evo-stat ok">
                <Target size={15} />
                <span className="mes-value">{totalRuns ? Math.round((totalSuccess / totalRuns) * 100) : 0}%</span>
                <span className="mes-label">成功率</span>
              </div>
              <div className="mem-evo-stat warn">
                <AlertTriangle size={15} />
                <span className="mes-value">{Math.max(totalRuns - totalSuccess, 0)}</span>
                <span className="mes-label">失败/错误</span>
              </div>
              <div className="mem-evo-stat">
                <Gauge size={15} />
                <span className="mes-value">{latestSuggestions.length}</span>
                <span className="mes-label">最新建议</span>
              </div>
            </div>

            <div className="mem-evo-grid">
              <section className="mem-evo-focus">
                <div className="mem-evo-section-head">
                  <span>最新进化报告</span>
                  {latestReport?.period && <span className="mono">{latestReport.period}</span>}
                </div>
                {latestReport ? (
                  <>
                    <p className="mem-evo-focus-summary">{latestReport.summary || "（无摘要）"}</p>
                    <div className="mem-evo-metric-grid">
                      {Object.entries(latestMetrics).slice(0, 6).map(([k, v]) => (
                        <div key={k} className="mem-evo-metric">
                          <span className="mem-evo-metric-val">{typeof v === "number" && v > 0 && v < 1 ? `${Math.round(v * 100)}%` : String(v)}</span>
                          <span className="mem-evo-metric-key">{k.replace(/_/g, " ")}</span>
                        </div>
                      ))}
                      {Object.keys(latestMetrics).length === 0 && (
                        <div className="mem-evo-muted">暂无结构化指标</div>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="mem-empty compact"><BrainCircuit size={24} /><p>暂无进化报告，点击触发反思生成第一份</p></div>
                )}
              </section>

              <section className="mem-evo-actions">
                <div className="mem-evo-section-head">
                  <span>优化建议队列</span>
                  <span className="mono">{latestSuggestions.length}</span>
                </div>
                {latestSuggestions.length > 0 ? latestSuggestions.slice(0, 5).map((s, idx) => {
                  const text = typeof s === "string" ? s : (s.action || s.text || s.summary || JSON.stringify(s));
                  const priority = typeof s === "object" ? (s.priority || "normal") : "normal";
                  return (
                    <div key={`${priority}-${idx}`} className="mem-evo-action">
                      <span className={`mem-evo-priority ${priority}`}>{priority}</span>
                      <p>{text}</p>
                    </div>
                  );
                }) : (
                  <div className="mem-evo-muted">最新报告中暂无建议</div>
                )}
              </section>
            </div>

            <div className="mem-evo-list">
              <div className="mem-evo-section-head full">
                <span>历史报告</span>
                <span className="mono">{reports.length}</span>
              </div>
              {reports.map((r) => (
                <div key={r.report_id} className="mem-evo-card">
                  <div className="mem-evo-card-head">
                    <span className="mem-evo-period"><CalendarDays size={12} />{r.period || "—"}</span>
                    <span className={`pill mem-evo-status ${r.status || "pending"}`}>{r.status || "pending"}</span>
                  </div>
                  <p className="mem-evo-summary">{r.summary || "（无摘要）"}</p>
                  {Array.isArray(r.suggestions) && r.suggestions.length > 0 && (
                    <div className="mem-evo-suggestions">
                      <span className="mem-evo-subtitle">优化建议</span>
                      <ul>{r.suggestions.slice(0, 3).map((s, i) => <li key={i}>{typeof s === "string" ? s : (s.action || s.text || JSON.stringify(s))}</li>)}</ul>
                    </div>
                  )}
                </div>
              ))}
              {!reportsLoading && reports.length === 0 && (
                <div className="mem-empty"><BrainCircuit size={24} /><p>暂无进化报告，点击"触发反思"生成第一份</p></div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
