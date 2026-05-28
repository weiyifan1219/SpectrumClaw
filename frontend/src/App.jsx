import { useMemo, useState } from "react";
import {
  ArrowUpRight,
  Bot,
  Cable,
  CheckCircle2,
  CircleDashed,
  Download,
  FileText,
  Gauge,
  Menu,
  Send,
  Server,
  X
} from "lucide-react";
import {
  initialMessages,
  kbStats,
  memoryLayers,
  pages,
  spectrumTasks,
  systemSignals,
  taskLogSeed
} from "./data/mockData.js";

const taskKeywordMap = [
  { id: "frequency_planning", words: ["频率", "规划", "ITU", "分配", "频段"] },
  { id: "situation_building", words: ["态势", "REM", "覆盖", "地图"] },
  { id: "modulation_recognition", words: ["调制", "识别", "信号"] },
  { id: "spectrum_decision", words: ["决策", "策略", "优化"] },
  { id: "interference_analysis", words: ["干扰", "压制", "噪声"] }
];

function pickTaskId(text, fallback) {
  const hit = taskKeywordMap.find((entry) =>
    entry.words.some((word) => text.toLowerCase().includes(word.toLowerCase()))
  );
  return hit?.id ?? fallback;
}

function makeAssistantReply(text, task) {
  if (task.id === "frequency_planning") {
    return `已路由到「${task.label}」。当前 v0 会先展示交互闭环：后续真实流程会检索 itu_documents.zip 中的 ITU 标准材料，再通过 LLM API 生成带引用的频率规划建议。你的问题是：“${text}”。`;
  }
  if (task.id === "situation_building") {
    return `已识别为「${task.label}」请求。该模块当前等待用户准备最终实验脚本，后续会封装 Agent_UAV_REM 的推理和可视化能力。`;
  }
  return `已识别为「${task.label}」方向。该能力现在是预留入口，后续会作为独立 skill 接入后端调度。`;
}

function Sidebar({ activePage, setActivePage, sidebarOpen, setSidebarOpen }) {
  return (
    <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
      <div className="brand">
        <div className="brand-mark">SC</div>
        <div>
          <strong>SpectrumClaw</strong>
          <span>Electromagnetic Agent Console</span>
        </div>
      </div>

      <nav className="page-nav" aria-label="Main navigation">
        {pages.map((page) => {
          const Icon = page.icon;
          return (
            <button
              className={activePage === page.id ? "nav-item active" : "nav-item"}
              key={page.id}
              onClick={() => {
                setActivePage(page.id);
                setSidebarOpen(false);
              }}
            >
              <Icon size={18} />
              <span>{page.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="runtime-card">
        <span className="eyebrow">Run Mode</span>
        <strong>Local Preview</strong>
        <p>前端 v0，本地模拟对话。4090 服务器部署待后续确认。</p>
      </div>
    </aside>
  );
}

function TopBar({ activeTask, setSidebarOpen }) {
  return (
    <header className="topbar">
      <button className="icon-button mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
        <Menu size={20} />
      </button>
      <div className="topbar-title">
        <span className="eyebrow">Active Skill</span>
        <strong>{activeTask.label}</strong>
      </div>
      <div className="signal-row">
        {systemSignals.map((signal) => (
          <div className={`signal ${signal.tone}`} key={signal.label}>
            <span>{signal.label}</span>
            <strong>{signal.value}</strong>
          </div>
        ))}
      </div>
    </header>
  );
}

function TaskSelector({ activeTaskId, setActiveTaskId }) {
  return (
    <section className="task-strip" aria-label="Spectrum tasks">
      {spectrumTasks.map((task) => {
        const Icon = task.icon;
        const active = activeTaskId === task.id;
        return (
          <button
            key={task.id}
            className={`task-tile ${active ? "active" : ""} ${task.accent}`}
            onClick={() => setActiveTaskId(task.id)}
          >
            <span className="task-icon">
              <Icon size={19} />
            </span>
            <span>
              <strong>{task.label}</strong>
              <small>{task.status}</small>
            </span>
          </button>
        );
      })}
    </section>
  );
}

function ChatPanel({ activeTask, activeTaskId, setActiveTaskId, logs, setLogs }) {
  const [messages, setMessages] = useState(initialMessages);
  const [draft, setDraft] = useState("");

  function submitMessage(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;

    const routedTaskId = pickTaskId(text, activeTaskId);
    const routedTask = spectrumTasks.find((task) => task.id === routedTaskId) ?? activeTask;
    const reply = makeAssistantReply(text, routedTask);

    setActiveTaskId(routedTask.id);
    setMessages((current) => [
      ...current,
      { role: "user", content: text },
      { role: "assistant", content: reply }
    ]);
    setLogs((current) => [
      `User message received: ${text.slice(0, 42)}${text.length > 42 ? "..." : ""}`,
      `Skill routed to ${routedTask.label}.`,
      ...current
    ]);
    setDraft("");
  }

  return (
    <section className="chat-panel">
      <div className="panel-head">
        <div>
          <span className="eyebrow">Agent Dialogue</span>
          <h1>频谱智能体控制台</h1>
        </div>
        <div className="route-chip">
          <Cable size={16} />
          {activeTask.label}
        </div>
      </div>

      <div className="message-list">
        {messages.map((message, index) => (
          <div className={`message ${message.role}`} key={`${message.role}-${index}`}>
            <div className="message-avatar">
              {message.role === "assistant" ? <Bot size={17} /> : "你"}
            </div>
            <p>{message.content}</p>
          </div>
        ))}
      </div>

      <form className="composer" onSubmit={submitMessage}>
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="输入频谱任务需求，例如：帮我基于 ITU 材料做一个频率规划建议"
        />
        <button type="submit" aria-label="Send message">
          <Send size={18} />
        </button>
      </form>
    </section>
  );
}

function OperationsPanel({ activeTask, logs }) {
  return (
    <aside className="ops-panel">
      <section className="ops-card">
        <div className="section-title">
          <span className="eyebrow">Skill Route</span>
          <strong>{activeTask.label}</strong>
        </div>
        <p>{activeTask.description}</p>
        <div className="status-line">
          <CircleDashed size={16} />
          <span>{activeTask.readiness}</span>
        </div>
      </section>

      <section className="ops-card">
        <div className="section-title">
          <span className="eyebrow">Task Log</span>
          <strong>Latest Events</strong>
        </div>
        <div className="log-list">
          {logs.slice(0, 6).map((entry, index) => (
            <div className="log-row" key={`${entry}-${index}`}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <p>{entry}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="ops-card result-card">
        <div className="section-title">
          <span className="eyebrow">Artifacts</span>
          <strong>Result Files</strong>
        </div>
        <button className="ghost-action">
          <FileText size={17} />
          result.md
          <Download size={15} />
        </button>
        <button className="ghost-action">
          <FileText size={17} />
          metadata.json
          <Download size={15} />
        </button>
      </section>
    </aside>
  );
}

function ConsolePage() {
  const [activeTaskId, setActiveTaskId] = useState("frequency_planning");
  const [logs, setLogs] = useState(taskLogSeed);
  const activeTask = useMemo(
    () => spectrumTasks.find((task) => task.id === activeTaskId) ?? spectrumTasks[0],
    [activeTaskId]
  );

  return (
    <div className="console-grid">
      <main className="console-main">
        <TaskSelector activeTaskId={activeTaskId} setActiveTaskId={setActiveTaskId} />
        <ChatPanel
          activeTask={activeTask}
          activeTaskId={activeTaskId}
          setActiveTaskId={setActiveTaskId}
          logs={logs}
          setLogs={setLogs}
        />
      </main>
      <OperationsPanel activeTask={activeTask} logs={logs} />
    </div>
  );
}

function KnowledgePage() {
  return (
    <main className="page-surface knowledge-page">
      <div className="page-header">
        <span className="eyebrow">Knowledge Base</span>
        <h1>频谱知识库</h1>
        <p>第一批资料来自项目根目录的 ITU 文档压缩包。后续会参考 RAG-Anything 的多模态文档理解思路，逐步扩展为 RAG 和知识图谱。</p>
      </div>
      <div className="metric-grid">
        {kbStats.map((item) => (
          <div className="metric" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
      <section className="flow-board">
        {["Raw PDFs", "Document Parser", "Chunk Index", "RAG Answer", "Knowledge Graph"].map((step, index) => (
          <div className="flow-node" key={step}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{step}</strong>
          </div>
        ))}
      </section>
    </main>
  );
}

function MemoryPage() {
  return (
    <main className="page-surface">
      <div className="page-header">
        <span className="eyebrow">Memory & Evolution</span>
        <h1>记忆和进化总结</h1>
        <p>这里后续展示系统记忆、skill 使用反馈、能力版本变化和自动反思摘要。</p>
      </div>
      <div className="memory-grid">
        {memoryLayers.map((layer) => {
          const Icon = layer.icon;
          return (
            <article className="memory-card" key={layer.label}>
              <Icon size={22} />
              <strong>{layer.label}</strong>
              <p>{layer.value}</p>
            </article>
          );
        })}
      </div>
      <section className="evolution-strip">
        <div>
          <span className="eyebrow">Evolution Queue</span>
          <h2>下一步接入真实任务反馈</h2>
        </div>
        <button className="text-action">
          查看规划
          <ArrowUpRight size={16} />
        </button>
      </section>
    </main>
  );
}

function SystemPage() {
  const rows = [
    ["LLM API", "OpenAI-compatible config placeholder", "Planned"],
    ["Local Conda", "SpectrumClaw", "Provisioning"],
    ["Server Runtime", "4090 + conda activate Agent", "Pending"],
    ["Knowledge Path", "itu_documents.zip", "Ready"],
    ["Artifacts", "outputs/", "Reserved"],
    ["Logs", "logs/", "Reserved"]
  ];

  return (
    <main className="page-surface">
      <div className="page-header">
        <span className="eyebrow">System</span>
        <h1>运行系统状态</h1>
        <p>System 页面用于展示环境、API、路径、依赖和服务健康，帮助区分本地备份环境与 4090 主运行环境。</p>
      </div>
      <div className="system-table">
        {rows.map(([name, value, status]) => (
          <div className="system-row" key={name}>
            <div>
              <strong>{name}</strong>
              <span>{value}</span>
            </div>
            <em>{status}</em>
          </div>
        ))}
      </div>
      <section className="system-banner">
        <Server size={24} />
        <div>
          <strong>部署阶段尚未开始</strong>
          <p>后续会通过离线 wheelhouse 和 rsync/scp 将项目上传至 4090 服务器。</p>
        </div>
        <CheckCircle2 size={22} />
      </section>
    </main>
  );
}

function App() {
  const [activePage, setActivePage] = useState("console");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const activeTask = spectrumTasks[0];

  const pageContent = {
    console: <ConsolePage />,
    knowledge: <KnowledgePage />,
    memory: <MemoryPage />,
    system: <SystemPage />
  };

  return (
    <div className="app-shell">
      <Sidebar
        activePage={activePage}
        setActivePage={setActivePage}
        sidebarOpen={sidebarOpen}
        setSidebarOpen={setSidebarOpen}
      />
      {sidebarOpen && <button className="scrim" onClick={() => setSidebarOpen(false)} aria-label="Close menu" />}
      <div className="workspace">
        <TopBar activeTask={activeTask} setSidebarOpen={setSidebarOpen} />
        {pageContent[activePage]}
      </div>
      <button className="close-sidebar" onClick={() => setSidebarOpen(false)} aria-label="Close menu">
        <X size={18} />
      </button>
      <div className="spectral-grid" aria-hidden="true" />
      <Gauge className="corner-glyph" size={84} aria-hidden="true" />
    </div>
  );
}

export default App;
