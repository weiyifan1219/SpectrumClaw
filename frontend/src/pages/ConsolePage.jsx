import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Brain,
  Check,
  ChevronDown,
  FileCode,
  FileText,
  Loader2,
  MessageSquare,
  Mic,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  User
} from "lucide-react";
import {
  artifacts,
  initialMessages,
  llmModels,
  reasoningEffortOptions,
  skills,
  taskLogSeed
} from "../data/mockData.js";
import { sendChat } from "../lib/api.js";
import Markdown from "../components/Markdown.jsx";

/* ── localStorage helpers ── */
const CHAT_KEY = "sc_chat";
const MODEL_KEY = "sc_model";
const DEFAULT_TOOL_NAMES = ["get_time", "get_system_status", "get_weather", "web_search", "web_fetch", "search_knowledge_base"];

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

function FileTypeIcon({ type }) {
  if (type === "JSON") return <FileCode size={14} color="var(--accent)" />;
  return <FileText size={14} color="var(--accent-2)" />;
}

export default function ConsolePage({ onOpenSkill, onModelChange }) {
  const [skillSel, setSkillSel] = useState("chat");
  const [messages, setMessages] = useState(() => loadMsgs() ?? initialMessages);
  const [logs, setLogs] = useState(taskLogSeed);
  const [draft, setDraft] = useState("");
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

  const handleModelChange = useCallback((id) => {
    setModel(id);
    saveModel(id);
    const m = llmModels.find((x) => x.id === id);
    onModelChange?.(m?.label ?? id);
  }, [onModelChange]);

  async function submit(e) {
    e?.preventDefault?.();
    const text = draft.trim();
    if (!text || sending) return;

    const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    const userMsg = { role: "user", content: text, meta: { ts } };
    setDraft("");
    setSending(true);

    const history = [...messages, userMsg];
    setMessages(history);

    try {
      const apiMessages = history
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role, content: m.content }));

      const result = await sendChat(apiMessages, {
        model,
        thinking_enabled: thinkingEnabled,
        reasoning_effort: thinkingEnabled ? reasoningEffort : null,
        tool_names: DEFAULT_TOOL_NAMES,
      });

      const assistantMsg = {
        role: "assistant",
        content: result.reply,
        meta: { skill: activeSkill?.label ?? null, ts }
      };

      if (activeSkill) {
        assistantMsg.pipeline = [
          { name: "接收请求", done: true },
          { name: "加载模型", done: true },
          { name: activeSkill.label, done: true },
          { name: "影响评估", done: true },
          { name: "策略建议", done: true }
        ];
      }

      setMessages((curr) => [...curr, assistantMsg]);

      if (activeSkill) {
        setLogs((curr) => [
          { ts, level: "info", msg: `${activeSkill.label} 任务已启动`, tag: "运行中" },
          ...curr
        ]);
      }
    } catch (err) {
      const userMsgIndex = history.length - 1;
      setMessages((curr) => [
        ...curr,
        {
          role: "assistant",
          content: err.message || "请求失败，请稍后重试",
          meta: { skill: null, ts, error: true, userMsgIndex }
        }
      ]);
    } finally {
      setSending(false);
    }
  }

  async function retry(errorIndex) {
    const errMsg = messages[errorIndex];
    if (!errMsg?.meta?.error || sending) return;
    const ui = errMsg.meta.userMsgIndex;
    if (ui == null || !messages[ui] || messages[ui].role !== "user") return;

    setSending(true);

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

  function clearChat() {
    setMessages([initialMessages[0]]);
    saveMsgs([initialMessages[0]]);
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
                </div>
                <Markdown>{m.content}</Markdown>
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
        <div className="card panel-card">
          <header className="card-head">
            <span className="title">
              <span className="eyebrow">TASK LOG</span>
              <span className="dot-sep">·</span>
              <span className="cn-title sm">任务日志</span>
            </span>
            <span className="eyebrow muted">LATEST · {logs.length}</span>
          </header>
          <div className="log-list-v2">
            {logs.slice(0, 3).map((l, i) => (
              <div className="log-row-v2" key={i} data-lvl={l.level}>
                <span className="ts mono">{l.ts}</span>
                <span className="lvl" />
                <p className="msg">{l.msg}</p>
                <span className={`tag tag-${l.level}`}>{l.tag}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card panel-card">
          <header className="card-head">
            <span className="title">
              <span className="eyebrow">ARTIFACTS</span>
              <span className="dot-sep">·</span>
              <span className="cn-title sm">产出物</span>
            </span>
            <span className="eyebrow muted">LATEST · {artifacts.length}</span>
          </header>
          <div className="art-list">
            {artifacts.map((a) => (
              <div className="art-row" key={a.name}>
                <FileTypeIcon type={a.type} />
                <span className="name">{a.name}</span>
                <span className="ext mono">{a.type}</span>
                <span className="ts mono">{a.ts}</span>
                <span className="size mono">{a.size}</span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
