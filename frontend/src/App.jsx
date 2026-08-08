import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import TopBar from "./components/TopBar.jsx";
import ConsolePage from "./pages/ConsolePage.jsx";

const FrequencyPlanningPage = lazy(() => import("./pages/FrequencyPlanningPage.jsx"));
const SituationBuildingPage = lazy(() => import("./pages/SituationBuildingPage.jsx"));
const SpectrumDecisionPage = lazy(() => import("./pages/SpectrumDecisionPage.jsx"));
const KnowledgePage = lazy(() => import("./pages/KnowledgePage.jsx"));
const MemoryPage = lazy(() => import("./pages/MemoryPage.jsx"));
const SystemPage = lazy(() => import("./pages/SystemPage.jsx"));
const UavSpectrumSimPage = lazy(() => import("./pages/UavSpectrumSimPage.jsx"));

const crumbMap = {
  console: ["SpectrumClaw", "Workspace", "Console"],
  uav_spectrum_sim: ["SpectrumClaw", "Workspace", "UAV Spectrum Simulation"],
  frequency_planning: ["SpectrumClaw", "Skills", "Frequency Planning"],
  situation_building: ["SpectrumClaw", "Skills", "Spectrum Construction"],
  resource_allocation: ["SpectrumClaw", "Skills", "Resource Allocation"],
  spectrum_decision: ["SpectrumClaw", "Skills", "Spectrum Decision"],
  knowledge: ["SpectrumClaw", "System", "Knowledge Base"],
  memory: ["SpectrumClaw", "System", "Memory & Evolution"],
  system: ["SpectrumClaw", "System", "Status"]
};

const pageMetaMap = {
  console: { kicker: "Workspace · Agent Console", title: "智能控制台", description: "对话、技能调用与运行产出集中工作区" },
  uav_spectrum_sim: { kicker: "Simulation · UAV Spectrum", title: "无人机仿真与智能体控制", description: "飞控任务、电磁频谱态势与系统诊断" },
  frequency_planning: { kicker: "Skill · Frequency Planning", title: "频率规划工作区", description: "ITU 知识检索与可引用频段方案" },
  situation_building: { kicker: "Skill · Spectrum Construction", title: "频谱构建工作区", description: "多分辨率构建、UAV REM 与算法对比" },
  spectrum_decision: { kicker: "Skill · Spectrum Decision", title: "频谱决策 · 资源分配", description: "多用户业务切片与约束优化" },
  knowledge: { kicker: "System · Knowledge Base", title: "频谱知识库", description: "文档、混合检索与知识图谱" },
  memory: { kicker: "System · Memory & Evolution", title: "记忆与进化", description: "对话历史、知识沉淀与进化报告" },
  system: { kicker: "System · Runtime Status", title: "运行系统状态", description: "后端、模型、RAG 与技能健康检查" },
};

export const PAGE_IDS = [
  "console",
  "uav_spectrum_sim",
  "frequency_planning",
  "situation_building",
  "spectrum_decision",
  "resource_allocation",
  "knowledge",
  "memory",
  "system",
];

const PAGE_ALIASES = {
  resource_allocation: "spectrum_decision",
};

const ACTIVE_PAGE_STORAGE_KEY = "spectrumclaw:active-page";

function initialActivePage() {
  const rawHashPage = window.location.hash.replace(/^#/, "");
  const hashPage = PAGE_ALIASES[rawHashPage] || rawHashPage;
  if (PAGE_IDS.includes(hashPage)) return hashPage;
  try {
    const saved = window.sessionStorage.getItem(ACTIVE_PAGE_STORAGE_KEY);
    if (PAGE_IDS.includes(saved)) return saved;
  } catch {
    // Storage may be disabled; the console remains a safe default.
  }
  return "console";
}

function PageLoadFallback() {
  return (
    <div className="page-load-fallback" role="status" aria-live="polite">
      <span className="page-load-mark" />
      <div><strong>正在打开工作区</strong><small>加载页面资源与上次工作状态…</small></div>
    </div>
  );
}

export default function App() {
  const [activeId, setActiveId] = useState(initialActivePage);
  const [modelLabel, setModelLabel] = useState("DeepSeek Pro");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [visitedIds, setVisitedIds] = useState(() => new Set([initialActivePage()]));
  const pageRefs = useRef({});

  const navigate = useCallback((requestedId, { replace = false } = {}) => {
    const nextId = PAGE_ALIASES[requestedId] || requestedId;
    if (!PAGE_IDS.includes(nextId)) return;
    setActiveId(nextId);
    setSidebarOpen(false);
    const nextHash = `#${nextId}`;
    if (window.location.hash !== nextHash) {
      window.history[replace ? "replaceState" : "pushState"](null, "", nextHash);
    }
  }, []);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(ACTIVE_PAGE_STORAGE_KEY, activeId);
    } catch {
      // Navigation must not depend on browser storage availability.
    }
    const activePage = pageRefs.current[activeId];
    window.requestAnimationFrame(() => activePage?.focus({ preventScroll: true }));
    setVisitedIds((visited) => {
      if (visited.has(activeId)) return visited;
      const next = new Set(visited);
      next.add(activeId);
      return next;
    });
  }, [activeId]);

  useEffect(() => {
    const restoreFromHash = () => {
      const requestedPage = window.location.hash.replace(/^#/, "");
      const page = PAGE_ALIASES[requestedPage] || requestedPage;
      if (PAGE_IDS.includes(page)) {
        setActiveId(page);
        setSidebarOpen(false);
      }
    };
    window.addEventListener("hashchange", restoreFromHash);
    return () => window.removeEventListener("hashchange", restoreFromHash);
  }, []);

  useEffect(() => {
    if (!window.location.hash || !PAGE_IDS.includes(PAGE_ALIASES[window.location.hash.slice(1)] || window.location.hash.slice(1))) {
      navigate(activeId, { replace: true });
    }
  }, [activeId, navigate]);

  const pageNodes = useMemo(() => ({
    console: (
      <ConsolePage
        active={activeId === "console"}
        onOpenSkill={navigate}
        modelLabel={modelLabel}
        onModelChange={setModelLabel}
      />
    ),
    uav_spectrum_sim: <UavSpectrumSimPage active={activeId === "uav_spectrum_sim"} onBack={() => navigate("console")} onOpenSystem={() => navigate("system")} />,
    frequency_planning: <FrequencyPlanningPage active={activeId === "frequency_planning"} onBack={() => navigate("console")} />,
    situation_building: <SituationBuildingPage active={activeId === "situation_building"} onBack={() => navigate("console")} />,
    spectrum_decision: <SpectrumDecisionPage active={activeId === "spectrum_decision"} onBack={() => navigate("console")} />,
    knowledge: <KnowledgePage active={activeId === "knowledge"} />,
    memory: <MemoryPage active={activeId === "memory"} />,
    system: <SystemPage active={activeId === "system"} />,
  }), [activeId, modelLabel, navigate]);

  const crumbs = crumbMap[activeId] ?? crumbMap.console;

  return (
    <div className={`app-shell page-${activeId} ${sidebarOpen ? "sidebar-is-open" : ""}`}>
      <a className="skip-link" href="#main-content">跳到主内容</a>
      <Sidebar activeId={activeId} open={sidebarOpen} onNavigate={navigate} onClose={() => setSidebarOpen(false)} />
      <button className="sidebar-scrim" type="button" aria-label="关闭导航" onClick={() => setSidebarOpen(false)} />
      <div className="workspace">
        <TopBar
          activeId={activeId}
          crumbs={crumbs}
          pageMeta={pageMetaMap[activeId]}
          modelLabel={modelLabel}
          onNavigate={navigate}
          onToggleSidebar={() => setSidebarOpen((open) => !open)}
        />
        <main className="workspace-content" id="main-content">
          {PAGE_IDS.map((id) => (
            <div
              key={id}
              ref={(node) => { pageRefs.current[id] = node; }}
              className={`page-stage ${id === activeId ? "is-active" : ""}`}
              hidden={id !== activeId}
              tabIndex={-1}
              aria-label={crumbMap[id]?.at(-1) || id}
            >
              {visitedIds.has(id) ? <Suspense fallback={<PageLoadFallback />}>{pageNodes[id]}</Suspense> : null}
            </div>
          ))}
        </main>
      </div>
    </div>
  );
}
