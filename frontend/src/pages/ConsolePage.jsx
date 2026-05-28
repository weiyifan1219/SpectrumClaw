import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Bot,
  Check,
  ChevronDown,
  FileCode,
  FileText,
  MessageSquare,
  Mic,
  Plus,
  Send,
  Trash2,
  User
} from "lucide-react";
import {
  artifacts,
  initialMessages,
  llmModels,
  skills,
  taskLogSeed
} from "../data/mockData.js";

function makeReply(text, skill) {
  if (!skill) {
    return `收到：「${text}」。当前为普通对话模式（未选中技能），我会直接以助手身份回应。如需调用具体能力，请在下方「技能」中选择对应 skill。`;
  }
  if (skill.id === "frequency_planning") {
    return `已路由到 ${skill.label}。预览阶段会先返回结构化建议；接入 RAG 后会基于 ITU 文档库给出可引用的频段方案。`;
  }
  if (skill.id === "situation_building") {
    return `已识别为 ${skill.label} 任务。当前等待用户上传 REM 推理脚本到 4090 服务器；接入后会输出覆盖热力图与异常源定位。`;
  }
  if (skill.id === "resource_allocation") {
    return `已识别为 ${skill.label} 任务。该 skill 会在频段、功率、时隙的多维约束下求解多目标分配。`;
  }
  if (skill.id === "interference_analysis") {
    return `已识别为 ${skill.label} 任务。将自动检测并定位干扰源，生成干扰报告与处置建议。`;
  }
  return `已识别为 ${skill.label} 任务。该 skill 当前为预留接口，后续会作为独立 skill 接入后端调度。`;
}

function FileTypeIcon({ type }) {
  if (type === "JSON") return <FileCode size={14} color="var(--accent)" />;
  return <FileText size={14} color="var(--accent-2)" />;
}

export default function ConsolePage({ onOpenSkill }) {
  const [skillSel, setSkillSel] = useState("chat");
  const [messages, setMessages] = useState(initialMessages);
  const [logs, setLogs] = useState(taskLogSeed);
  const [draft, setDraft] = useState("");
  const [model, setModel] = useState("gpt-4o");
  const [modelOpen, setModelOpen] = useState(false);
  const [skillOpen, setSkillOpen] = useState(false);
  const bodyRef = useRef(null);

  const activeSkill = useMemo(
    () => (skillSel === "chat" ? null : skills.find((s) => s.id === skillSel) ?? null),
    [skillSel]
  );

  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    function onDoc() { setModelOpen(false); setSkillOpen(false); }
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, []);

  function submit(e) {
    e?.preventDefault?.();
    const text = draft.trim();
    if (!text) return;

    const reply = makeReply(text, activeSkill);
    const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });

    const assistantMsg = {
      role: "assistant",
      content: reply,
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

    setMessages((curr) => [
      ...curr,
      { role: "user", content: text, meta: { ts } },
      assistantMsg
    ]);

    if (activeSkill) {
      setLogs((curr) => [
        { ts, level: "info", msg: `${activeSkill.label} 任务已启动`, tag: "运行中" },
        ...curr
      ]);
    }
    setDraft("");
  }

  function clearChat() {
    setMessages([initialMessages[0]]);
  }

  const skillSelLabel = skillSel === "chat" ? "普通对话" : activeSkill?.label;
  const modeLabel = skillSel === "chat" ? "普通对话模式" : `技能模式 · ${activeSkill?.label}`;

  return (
    <div className="page console-page">
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
            <div className={`message ${m.role}`} key={`${m.role}-${i}`}>
              <div className="avatar">
                {m.role === "assistant" ? <Bot size={16} /> : <User size={16} />}
              </div>
              <div className="bubble">
                <div className="who">
                  <strong>{m.role === "assistant" ? "SPECTRUMCLAW" : "USER"}</strong>
                  {m.meta?.ts && <span className="ts mono">· {m.meta.ts}</span>}
                </div>
                <p>{m.content}</p>
                {m.pipeline && (
                  <div className="pipeline-bubble">
                    {m.pipeline.map((step, idx) => (
                      <span className="step" key={step.name}>
                        <span className="check">
                          <Check size={11} />
                        </span>
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
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
          </div>

          <div className="comp-divider" />

          {/* Model select */}
          <div className="comp-select" onClick={(e) => e.stopPropagation()}>
            <span className="sel-label">模型</span>
            <button
              type="button"
              className="sel-btn"
              onClick={() => { setModelOpen((v) => !v); setSkillOpen(false); }}
            >
              <span>{model}</span>
              <ChevronDown size={13} />
            </button>
            {modelOpen && (
              <div className="sel-pop">
                {llmModels.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    className={`pop-item ${m.id === model ? "on" : ""}`}
                    onClick={() => { setModel(m.id); setModelOpen(false); }}
                  >
                    <span className="pi-dot" />
                    <span className="pi-label">{m.label}</span>
                    <span className="pi-check">{m.id === model && <Check size={12} />}</span>
                  </button>
                ))}
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

          <button type="submit" className="comp-btn send" aria-label="发送">
            <ArrowRight size={17} />
          </button>
        </form>
      </section>

      {/* ───────── Skill cards ───────── */}
      <section className="skill-section">
        <header className="section-head">
          <span className="cn-title">可用技能</span>
          <span className="eyebrow">AVAILABLE SKILLS · {skills.length}</span>
          <span className="head-hint">
            {skillSel === "chat" ? "选择一项进入技能模式" : "已选中 — 当前对话将走此 skill 流程"}
          </span>
        </header>
        <div className="skill-rail-h">
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
                  <span className="sc-icon">
                    <Icon size={16} />
                  </span>
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
        </div>
      </section>

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
