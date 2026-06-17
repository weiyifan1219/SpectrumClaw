import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Brain,
  Check,
  ChevronDown,
  Download,
  Eye,
  FileCode,
  FileText,
  Loader2,
  MessageSquare,
  Mic,
  Plus,
  RefreshCw,
  Send,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  User,
  X,
  FolderOpen,
  File
} from "lucide-react";
import {
  artifacts as _unusedArtifacts,
  initialMessages,
  llmModels,
  reasoningEffortOptions,
  skills,
  taskLogSeed as _unusedTaskLog
} from "../data/mockData.js";
import { sendChat, sendChatStream, submitFeedback, fetchSystemLogs, fetchSystemLog, fetchSystemArtifacts, fetchArtifactPreview, artifactDownloadUrl } from "../lib/api.js";
import Markdown from "../components/Markdown.jsx";

/* ── localStorage helpers ── */
const CHAT_KEY = "sc_chat";
const MODEL_KEY = "sc_model";
const THREAD_KEY = "sc_thread_id";
const TASKLOG_KEY = "sc_tasklog";
const ARTIFACTS_CACHE_KEY = "sc_artifacts";
const MAX_TASK_LOG = 50;
const DEFAULT_TOOL_NAMES = ["get_time", "get_system_status", "get_weather", "web_search", "web_fetch", "search_knowledge_base"];

function uid() { return "thread_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8); }
function formatSize(bytes) {
  if (!bytes || bytes < 0) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0, v = bytes;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(i === 0 ? 0 : 1) + " " + u[i];
}
function timeAgo(ts) {
  if (!ts) return "";
  const diff = (Date.now() - ts * 1000) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return Math.floor(diff / 60) + "分钟前";
  if (diff < 86400) return Math.floor(diff / 3600) + "小时前";
  return Math.floor(diff / 86400) + "天前";
}
function loadThreadId() {
  try { const v = localStorage.getItem(THREAD_KEY); if (v) return v; } catch { /* */ }
  const id = uid();
  try { localStorage.setItem(THREAD_KEY, id); } catch { /* */ }
  return id;
}
function saveThreadId(v) { try { localStorage.setItem(THREAD_KEY, v); } catch { /* */ } }

function loadMsgs() {
  try {
    const raw = localStorage.getItem(CHAT_KEY);
    if (raw) { const p = JSON.parse(raw); if (Array.isArray(p) && p.length) return p; }
  } catch { /* ignore */ }
  return null;
}
function saveMsgs(m) { try { localStorage.setItem(CHAT_KEY, JSON.stringify(m)); } catch { /* */ } }
function loadModel() { try { return localStorage.getItem(MODEL_KEY); } catch { return null; } }
function saveModel(v) { try { localStorage.setItem(MODEL_KEY, v); } catch { /* */ } }

function loadTaskLog() {
  try {
    const raw = localStorage.getItem(TASKLOG_KEY);
    if (raw) { const p = JSON.parse(raw); if (Array.isArray(p)) return p; }
  } catch { /* */ }
  return [];
}
function saveTaskLog(log) {
  try { localStorage.setItem(TASKLOG_KEY, JSON.stringify(log.slice(0, MAX_TASK_LOG))); } catch { /* */ }
}

function FileTypeIcon({ type }) {
  if (type === "JSON") return <FileCode size={14} color="var(--accent)" />;
  return <FileText size={14} color="var(--accent-2)" />;
}

export default function ConsolePage({ onOpenSkill, onModelChange }) {
  const [skillSel, setSkillSel] = useState("chat");
  const [messages, setMessages] = useState(() => loadMsgs() ?? initialMessages);
  const [logs, setLogs] = useState(() => loadTaskLog());
  const [logDetail, setLogDetail] = useState(null);  // { name, content } when viewing
  const [logList, setLogList] = useState([]);        // list of log file names
  const [artifacts, setArtifacts] = useState(() => {
    try {
      const cached = localStorage.getItem(ARTIFACTS_CACHE_KEY);
      if (cached) return JSON.parse(cached);
    } catch { /* */ }
    return [];
  });
  const [preview, setPreview] = useState(null);       // { name, content } modal
  const [artLoading, setArtLoading] = useState(false);
  const [showLogFiles, setShowLogFiles] = useState(false);
  const logDropdownRef = useRef(null);
  const [draft, setDraft] = useState("");
  const [threadId, setThreadId] = useState(() => loadThreadId());
  const [model, setModel] = useState(() => {
    const saved = loadModel();
    return saved && llmModels.some((m) => m.id === saved) ? saved : "deepseek-v4-pro";
  });
  const [thinkingEnabled, setThinkingEnabled] = useState(false);
  const [reasoningEffort, setReasoningEffort] = useState("high");
  const [modelOpen, setModelOpen] = useState(false);
  const [skillOpen, setSkillOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const bodyRef = useRef(null);

  const activeSkill = useMemo(
    () => (skillSel === "chat" ? null : skills.find((s) => s.id === skillSel) ?? null),
    [skillSel]
  );

  /* persist messages */
  useEffect(() => { saveMsgs(messages); }, [messages]);

  /* auto-scroll */
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [messages]);

  /* close popovers on outside click */
  useEffect(() => {
    function onDoc() { setModelOpen(false); setSkillOpen(false); }
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, []);

  /* ── fetch system log file list (for "查看完整日志" click) ── */
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const data = await fetchSystemLogs();
        if (!active) return;
        setLogList(data.logs || []);
      } catch { /* best-effort */ }
    }
    load();
    const interval = setInterval(load, 30000);
    return () => { active = false; clearInterval(interval); };
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      setArtLoading(true);
      try {
        const data = await fetchSystemArtifacts({ limit: 30 });
        if (!active) return;
        const list = data.artifacts || [];
        setArtifacts(list);
        try { localStorage.setItem(ARTIFACTS_CACHE_KEY, JSON.stringify(list)); } catch { /* */ }
      } catch { /* best-effort */ }
      finally { if (active) setArtLoading(false); }
    }
    load();
    const interval = setInterval(load, 30000);
    return () => { active = false; clearInterval(interval); };
  }, []);

  async function viewLog(name) {
    if (logDetail?.name === name) { setLogDetail(null); return; }
    try {
      const data = await fetchSystemLog(name, { tail: 200 });
      setLogDetail({ name, content: data.content });
    } catch { /* best-effort */ }
  }

function artifactViewUrl(path) {
  return artifactDownloadUrl(path) + "?inline=true";
}

  async function openPreview(art) {
    if (art.preview_type === "image") {
      setPreview({ name: art.name, imageUrl: artifactViewUrl(art.path), isImage: true });
      return;
    }
    if (art.preview_type === "pdf") {
      setPreview({ name: art.name, pdfUrl: artifactViewUrl(art.path), isPdf: true });
      return;
    }
    try {
      const data = await fetchArtifactPreview(art.path);
      setPreview({ name: art.name, content: data.content, isImage: false, isPdf: false });
    } catch (e) {
      setPreview({ name: art.name, content: `预览失败: ${e.message}`, error: true, isImage: false, isPdf: false });
    }
  }

  const handleModelChange = useCallback((id) => {
    setModel(id);
    saveModel(id);
    const m = llmModels.find((x) => x.id === id);
    onModelChange?.(m?.label ?? id);
  }, [onModelChange]);

  const addTaskLog = useCallback((level, msg, tag) => {
    const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    setLogs((curr) => {
      const next = [{ ts, level, msg, tag }, ...curr];
      saveTaskLog(next);
      return next;
    });
  }, []);

  async function submit(e) {
    e?.preventDefault?.();
    const text = draft.trim();
    if (!text || sending) return;

    const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    const userMsg = { role: "user", content: text, meta: { ts } };
    setDraft("");
    setSending(true);

    // task log: user action
    if (activeSkill) {
      addTaskLog("info", `「${activeSkill.label}」任务发起 · ${text.slice(0, 40)}${text.length > 40 ? "…" : ""}`, activeSkill.label);
    } else {
      addTaskLog("info", `对话 · ${text.slice(0, 50)}${text.length > 50 ? "…" : ""}`, "Chat");
    }

    const history = [...messages, userMsg];
    const placeholderId = Date.now();
    setMessages([...history, {
      role: "assistant",
      content: "",
      meta: { skill: activeSkill?.label ?? null, ts, streaming: true, id: placeholderId },
      reasoning: "",
    }]);

    const apiMessages = history
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, content: m.content }));

    await sendChatStream(apiMessages, {
      model,
      thinking_enabled: thinkingEnabled,
      reasoning_effort: thinkingEnabled ? reasoningEffort : null,
      tool_names: DEFAULT_TOOL_NAMES,
      thread_id: threadId,
    }, (event) => {
      if (event.type === "thinking") {
        setMessages((curr) => {
          const next = [...curr];
          const idx = next.findIndex((m) => m.meta?.id === placeholderId);
          if (idx >= 0) {
            next[idx] = { ...next[idx], reasoning: (next[idx].reasoning || "") + event.data };
          }
          return next;
        });
      } else if (event.type === "content") {
        setMessages((curr) => {
          const next = [...curr];
          const idx = next.findIndex((m) => m.meta?.id === placeholderId);
          if (idx >= 0) {
            next[idx] = { ...next[idx], content: next[idx].content + event.data };
          }
          return next;
        });
      } else if (event.type === "done") {
        setMessages((curr) => {
          const next = [...curr];
          const idx = next.findIndex((m) => m.meta?.id === placeholderId);
          if (idx >= 0) {
            next[idx] = { ...next[idx], meta: { ...next[idx].meta, streaming: false, done: true, feedbackId: event.data?.feedback_target_id || null } };
          }
          return next;
        });
        if (activeSkill) {
          addTaskLog("ok", `「${activeSkill.label}」任务完成`, activeSkill.label);
        } else {
          addTaskLog("ok", "对话完成", "Chat");
        }
      } else if (event.type === "error") {
        addTaskLog("error", `请求失败 · ${(event.data || "未知错误").slice(0, 60)}`, "Error");
        setMessages((curr) => {
          const next = [...curr];
          const idx = next.findIndex((m) => m.meta?.id === placeholderId);
          if (idx >= 0) {
            next[idx] = { ...next[idx], content: event.data || "请求失败", meta: { ...next[idx].meta, error: true, streaming: false, userMsgIndex: history.length - 1 } };
          }
          return next;
        });
      }
    });

    setSending(false);
  }

  async function retry(errorIndex) {
    const errMsg = messages[errorIndex];
    if (!errMsg?.meta?.error || sending) return;
    const ui = errMsg.meta.userMsgIndex;
    if (ui == null || !messages[ui] || messages[ui].role !== "user") return;

    setSending(true);
    addTaskLog("info", "重试上一次请求", "Retry");

    // remove the error bubble, keep the user message
    const clean = [...messages];
    clean.splice(errorIndex, 1);
    setMessages(clean);

    try {
      const apiMessages = clean
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role, content: m.content }));

      const result = await sendChat(apiMessages, {
        model,
        thinking_enabled: thinkingEnabled,
        reasoning_effort: thinkingEnabled ? reasoningEffort : null,
        tool_names: DEFAULT_TOOL_NAMES,
      });
      const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });

      setMessages((curr) => [
        ...curr,
        {
          role: "assistant",
          content: result.reply,
          meta: { skill: activeSkill?.label ?? null, ts }
        }
      ]);
    } catch (err2) {
      setMessages((curr) => [
        ...curr,
        {
          role: "assistant",
          content: err2.message || "重试失败",
          meta: { skill: null, ts: new Date().toLocaleTimeString("zh-CN", { hour12: false }), error: true, userMsgIndex: ui }
        }
      ]);
    } finally {
      setSending(false);
    }
  }

  async function handleFeedback(msgIndex, rating) {
    const msg = messages[msgIndex];
    if (!msg?.meta?.feedbackId) return;
    try {
      await submitFeedback({ targetType: "answer", targetId: msg.meta.feedbackId, rating });
      setMessages((curr) => {
        const next = [...curr];
        next[msgIndex] = { ...next[msgIndex], meta: { ...next[msgIndex].meta, feedbackRating: rating } };
        return next;
      });
    } catch { /* best-effort */ }
  }

  function clearChat() {
    setMessages([initialMessages[0]]);
    saveMsgs([initialMessages[0]]);
    const newId = uid();
    setThreadId(newId);
    saveThreadId(newId);
  }

  const skillSelLabel = skillSel === "chat" ? "普通对话" : activeSkill?.label;
  const modeLabel = skillSel === "chat" ? "普通对话模式" : `技能模式 · ${activeSkill?.label}`;
  const currentModelLabel = llmModels.find((m) => m.id === model)?.label ?? model;

  return (
    <div className="page console-page">
      <div className="console-main">
        {/* ───────── Hero: Agent Dialogue ───────── */}
        <section className="chat hero">
        <header className="chat-head">
          <div className="left">
            <span className="eyebrow">AGENT DIALOGUE</span>
            <span className="dot-sep">·</span>
            <span className="cn-title">实时对话</span>
            <span className={`mode-pill ${skillSel === "chat" ? "mode-chat" : `mode-skill acc-${activeSkill?.accent}`}`}>
              {skillSel === "chat" ? <MessageSquare size={11} /> : <span className="ms-dot" />}
              {modeLabel}
            </span>
          </div>
          <div className="right">
            <button className="btn ghost sm" onClick={clearChat}>
              <Trash2 size={13} /> 清空对话
            </button>
          </div>
        </header>

        <div className="chat-body" ref={bodyRef}>
          {messages.map((m, i) => (
            <div className={`message ${m.role} ${m.meta?.error ? "error" : ""}`} key={`${m.role}-${i}`}>
              <div className="avatar">
                {m.meta?.error ? <AlertTriangle size={15} /> : m.role === "assistant" ? <Bot size={16} /> : <User size={16} />}
              </div>
              <div className="bubble">
                <div className="who">
                  <strong>{m.meta?.error ? "错误" : m.role === "assistant" ? "SPECTRUMCLAW" : "USER"}</strong>
                  {m.meta?.ts && <span className="ts mono">· {m.meta.ts}</span>}
                  {m.meta?.streaming && !m.content && <span className="streaming-dot" />}
                </div>
                {m.reasoning && (
                  <details className="reasoning-box" open={!m.content}>
                    <summary>思考过程{m.meta?.streaming && !m.content ? "…" : ""}</summary>
                    <p>{m.reasoning}</p>
                  </details>
                )}
                {m.content ? <Markdown>{m.content}</Markdown> : m.meta?.streaming && <span className="cursor-blink" />}
                {m.meta?.error && (
                  <button className="retry-btn" onClick={() => retry(i)} title="重新发送">
                    <RefreshCw size={13} /> 重试
                  </button>
                )}
                {m.pipeline && (
                  <div className="pipeline-bubble">
                    {m.pipeline.map((step, idx) => (
                      <span className="step" key={step.name}>
                        <span className="check"><Check size={11} /></span>
                        <span className="sn">{step.name}</span>
                        {idx < m.pipeline.length - 1 && <span className="arr">→</span>}
                      </span>
                    ))}
                  </div>
                )}
                {m.role === "assistant" && m.meta?.done && !m.meta?.error && (
                  <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
                    <button
                      className={`feedback-btn ${m.meta?.feedbackRating === 1 ? "on" : ""}`}
                      onClick={() => handleFeedback(i, 1)}
                      title="有用"
                      disabled={m.meta?.feedbackRating != null}
                    >
                      <ThumbsUp size={12} />
                    </button>
                    <button
                      className={`feedback-btn ${m.meta?.feedbackRating === -1 ? "on" : ""}`}
                      onClick={() => handleFeedback(i, -1)}
                      title="没用"
                      disabled={m.meta?.feedbackRating != null}
                    >
                      <ThumbsDown size={12} />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Composer */}
        <form className="composer-v2" onSubmit={submit}>
          <button type="button" className="comp-btn plus" aria-label="附件" title="上传文件 / 添加附件">
            <Plus size={18} />
          </button>

          <div className="comp-input">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={
                skillSel === "chat"
                  ? "和 SpectrumClaw 对话，问问题或下达指令…"
                  : `调用「${activeSkill?.label}」技能 — 输入任务描述…`
              }
              aria-label="Message"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
              }}
            />
          </div>

          <div className="comp-divider" />

          {/* Model + Thinking combined popover */}
          <div className="comp-select" onClick={(e) => e.stopPropagation()}>
            <span className="sel-label">模型</span>
            <button
              type="button"
              className={`sel-btn ${thinkingEnabled ? "active" : ""}`}
              onClick={() => { setModelOpen((v) => !v); setSkillOpen(false); }}
            >
              <span>{currentModelLabel}</span>
              <ChevronDown size={13} />
            </button>
            {modelOpen && (
              <div className="sel-pop model-pop">
                <div className="pop-label">选择模型</div>
                {llmModels.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    className={`pop-item ${m.id === model ? "on" : ""}`}
                    onClick={() => { handleModelChange(m.id); setModelOpen(false); }}
                  >
                    <span className="pi-dot" />
                    <span className="pi-label">{m.label}</span>
                    <span className="pi-check">{m.id === model && <Check size={12} />}</span>
                  </button>
                ))}
                <div className="pop-sep" />
                <div className="pop-label">深度思考</div>
                <button
                  type="button"
                  className={`pop-item ${thinkingEnabled ? "on" : ""}`}
                  onClick={() => setThinkingEnabled((v) => !v)}
                >
                  <span className={`pi-dot ${thinkingEnabled ? "pi-think-on" : ""}`}><Brain size={10} /></span>
                  <span className="pi-label">{thinkingEnabled ? "已开启" : "关闭"}</span>
                  <span className="pi-check">{thinkingEnabled && <Check size={12} />}</span>
                </button>
                {thinkingEnabled && (
                  <>
                    <div className="pop-sep" />
                    <div className="pop-label">推理强度</div>
                    {reasoningEffortOptions.map((r) => (
                      <button
                        key={r.id}
                        type="button"
                        className={`pop-item ${r.id === reasoningEffort ? "on" : ""}`}
                        onClick={() => setReasoningEffort(r.id)}
                      >
                        <span className="pi-dot" />
                        <span className="pi-label">{r.label}</span>
                        <span className="pi-check">{r.id === reasoningEffort && <Check size={12} />}</span>
                      </button>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>

          {/* Skill select */}
          <div className="comp-select" onClick={(e) => e.stopPropagation()}>
            <span className="sel-label">技能</span>
            <button
              type="button"
              className={`sel-btn ${skillSel !== "chat" ? "active" : ""}`}
              onClick={() => { setSkillOpen((v) => !v); setModelOpen(false); }}
            >
              <span>{skillSelLabel}</span>
              <ChevronDown size={13} />
            </button>
            {skillOpen && (
              <div className="sel-pop wide">
                <button
                  type="button"
                  className={`pop-item ${skillSel === "chat" ? "on" : ""}`}
                  onClick={() => { setSkillSel("chat"); setSkillOpen(false); }}
                >
                  <span className="pi-dot pi-chat"><MessageSquare size={10} /></span>
                  <span className="pi-label">普通对话</span>
                  <span className="pi-check">{skillSel === "chat" && <Check size={12} />}</span>
                </button>
                <div className="pop-sep" />
                {skills.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`pop-item ${skillSel === s.id ? "on" : ""}`}
                    onClick={() => { setSkillSel(s.id); setSkillOpen(false); }}
                  >
                    <span className={`pi-dot acc-${s.accent}`} />
                    <span className="pi-label">{s.label}</span>
                    <span className="pi-check">{skillSel === s.id && <Check size={12} />}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <button type="button" className="comp-btn mic" aria-label="语音输入">
            <Mic size={16} />
          </button>

          <button type="submit" className="comp-btn send" aria-label="发送" disabled={sending}>
            {sending ? <Loader2 size={17} className="spin" /> : <ArrowRight size={17} />}
          </button>
        </form>
      </section>

      {/* ───────── Skill panel (right sidebar) ───────── */}
      <aside className="skill-panel">
        <header className="section-head">
          <span className="cn-title">可用技能</span>
          <span className="eyebrow">SKILLS · {skills.length}</span>
        </header>
        <div className="skill-rail-v">
          {skills.map((s) => {
            const Icon = s.icon;
            const isActive = skillSel === s.id;
            return (
              <article
                key={s.id}
                className={`skill-card acc-${s.accent} ${isActive ? "active" : ""}`}
                onClick={() => setSkillSel(s.id)}
              >
                <div className="sc-glow" aria-hidden="true" />
                <header className="sc-head">
                  <span className="sc-icon"><Icon size={16} /></span>
                  <div className="sc-title">
                    <strong>{s.label}</strong>
                    <small>{s.english}</small>
                  </div>
                </header>
                <p className="sc-desc">{s.summary}</p>
                <footer className="sc-foot">
                  <span className="pill" data-tone={s.statusTone}>
                    <span className="dot" /> {s.status}
                  </span>
                  <button
                    className="sc-open"
                    onClick={(e) => { e.stopPropagation(); onOpenSkill?.(s.id); }}
                  >
                    打开 <ArrowRight size={11} />
                  </button>
                </footer>
              </article>
            );
          })}
          {/* + placeholder card */}
          <article className="skill-card skill-card-add">
            <div className="sc-glow-add" aria-hidden="true" />
            <div className="add-inner">
              <Plus size={24} />
              <span>添加技能</span>
            </div>
          </article>
        </div>
      </aside>
    </div>

      {/* ───────── Bottom: Task Log + Artifacts ───────── */}
      <section className="bottom-grid">
        {/* ── Task Log ── */}
        <div className="card panel-card" style={{ display: "flex", flexDirection: "column" }}>
          <header className="card-head">
            <span className="title">
              <span className="eyebrow">TASK LOG</span>
              <span className="dot-sep">·</span>
              <span className="cn-title sm">任务日志</span>
            </span>
            <span className="eyebrow muted">
              {logs.length ? `活动 · ${logs.length} 条` : "暂无记录"}
            </span>
          </header>
          <div className="log-list-v2" style={{ maxHeight: 142, overflowY: "auto" }}>
            {logs.length === 0 && (
              <div className="log-row-v2" data-lvl="info" style={{ gridTemplateColumns: "1fr" }}>
                <p className="msg" style={{ opacity: 0.6, gridColumn: "1 / -1" }}>暂无任务日志，开始对话或使用技能后将自动记录</p>
              </div>
            )}
            {logs.slice(0, 10).map((l, i) => (
              <div className="log-row-v2" key={i} data-lvl={l.level}>
                <span className="ts mono">{l.ts}</span>
                <span className="lvl" />
                <p className="msg log-msg-truncate">{l.msg}</p>
                {l.tag && <span className={`tag tag-${l.level}`}>{l.tag}</span>}
              </div>
            ))}
          </div>
          {/* system log files dropdown — at very bottom, opens upward */}
          {logList.length > 0 && (
            <div ref={logDropdownRef} style={{ borderTop: "1px solid var(--border)", marginTop: "auto" }}>
              <button
                className="btn ghost sm"
                style={{ width: "100%", textAlign: "left", fontSize: 11, fontFamily: "var(--mono)", padding: "5px 16px", opacity: 0.5 }}
                onClick={() => setShowLogFiles((v) => !v)}
              >
                <FolderOpen size={10} style={{ marginRight: 4 }} />
                系统日志文件 ({logList.length})
                <ChevronDown size={10} style={{ marginLeft: "auto", transform: showLogFiles ? "rotate(180deg)" : "", transition: "transform .15s" }} />
              </button>
              {showLogFiles && (() => {
                const rect = logDropdownRef.current?.getBoundingClientRect?.();
                const bottom = rect ? window.innerHeight - rect.top : 0;
                const left = rect?.left ?? 0;
                const width = rect?.width ?? 300;
                return (
                  <>
                    <div style={{ position: "fixed", inset: 0, zIndex: 99 }} onClick={() => setShowLogFiles(false)} />
                    <div style={{
                      position: "fixed", left, bottom,
                      width, maxHeight: 220, overflowY: "auto",
                      background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "var(--radius)",
                      boxShadow: "0 -4px 16px oklch(0 0 0 / 0.22)", zIndex: 100,
                    }}>
                      {logList.map((f) => (
                        <button
                          key={f.name}
                          className="btn ghost sm"
                          style={{ display: "block", width: "100%", textAlign: "left", fontSize: 11, fontFamily: "var(--mono)", padding: "4px 10px" }}
                          onClick={() => { viewLog(f.name); setShowLogFiles(false); }}
                        >
                          <File size={10} style={{ marginRight: 6 }} />
                          {f.name}
                          <span style={{ opacity: 0.4, marginLeft: 6 }}>{formatSize(f.size)}</span>
                        </button>
                      ))}
                    </div>
                  </>
                );
              })()}
            </div>
          )}
          {/* log detail popup */}
          {logDetail && (
            <div className="modal-overlay" onClick={() => setLogDetail(null)}>
              <div className="modal-content preview-modal" onClick={(e) => e.stopPropagation()}>
                <header className="modal-head">
                  <span><FileText size={14} /> {logDetail.name}</span>
                  <button className="btn ghost sm" onClick={() => setLogDetail(null)}><X size={14} /></button>
                </header>
                <pre className="preview-body">{logDetail.content}</pre>
              </div>
            </div>
          )}
        </div>

        {/* ── Artifacts ── */}
        <div className="card panel-card">
          <header className="card-head">
            <span className="title">
              <span className="eyebrow">ARTIFACTS</span>
              <span className="dot-sep">·</span>
              <span className="cn-title sm">产出物</span>
            </span>
            <span className="eyebrow muted">
              {artLoading ? "加载中…" : `LATEST · ${artifacts.length}`}
            </span>
          </header>
          <div className="art-list" style={{ maxHeight: 142, overflowY: "auto" }}>
            {artifacts.length === 0 && !artLoading && (
              <div className="art-row" style={{ opacity: 0.5 }}>加载产出物列表…</div>
            )}
            {artifacts.map((a) => (
              <div className="art-row" key={a.path} title={a.path}>
                <FileTypeIcon type={a.type} />
                <span className="name">{a.name}</span>
                <span className="ext mono">{a.type}</span>
                <span className="size mono" style={{ display: "flex", flexDirection: "column", lineHeight: 1.3 }}>
                  <span>{formatSize(a.size)}</span>
                  <span style={{ fontSize: 10, opacity: 0.45 }}>{timeAgo(a.modified)}</span>
                </span>
                <span style={{ display: "flex", gap: 2, flexShrink: 0 }}>
                  {a.previewable && (
                    <button className="btn ghost sm" title={a.preview_type === "image" ? "预览图片" : a.preview_type === "pdf" ? "预览PDF" : "预览"} onClick={() => openPreview(a)}>
                      <Eye size={12} />
                    </button>
                  )}
                  <a className="btn ghost sm" title="下载" href={artifactDownloadUrl(a.path)} download>
                    <Download size={12} />
                  </a>
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Preview Modal ── */}
      {preview && (
        <div className="modal-overlay" onClick={() => setPreview(null)}>
          <div className="modal-content preview-modal" onClick={(e) => e.stopPropagation()}>
            <header className="modal-head">
              <span><Eye size={14} /> {preview.name}</span>
              <button className="btn ghost sm" onClick={() => setPreview(null)}><X size={14} /></button>
            </header>
            {preview.isPdf ? (
              <iframe src={preview.pdfUrl} style={{ width: "100%", height: "70vh", border: "none" }} title={preview.name} />
            ) : preview.isImage ? (
              <div className="preview-body" style={{ display: "flex", alignItems: "center", justifyContent: "center", background: "oklch(0 0 0 / 0.06)" }}>
                <img src={preview.imageUrl} alt={preview.name} style={{ maxWidth: "100%", maxHeight: "70vh", objectFit: "contain" }} />
              </div>
            ) : (
              <pre className={`preview-body ${preview.error ? "preview-err" : ""}`}>{preview.content}</pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
