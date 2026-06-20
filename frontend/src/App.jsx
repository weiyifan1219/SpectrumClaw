import { useMemo, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import TopBar from "./components/TopBar.jsx";
import ConsolePage from "./pages/ConsolePage.jsx";
import FrequencyPlanningPage from "./pages/FrequencyPlanningPage.jsx";
import SituationBuildingPage from "./pages/SituationBuildingPage.jsx";
import ResourceAllocationPage from "./pages/ResourceAllocationPage.jsx";
import SpectrumDecisionPage from "./pages/SpectrumDecisionPage.jsx";
import KnowledgePage from "./pages/KnowledgePage.jsx";
import MemoryPage from "./pages/MemoryPage.jsx";
import SystemPage from "./pages/SystemPage.jsx";

const crumbMap = {
  console: ["SpectrumClaw", "Workspace", "Console"],
  frequency_planning: ["SpectrumClaw", "Skills", "Frequency Planning"],
  situation_building: ["SpectrumClaw", "Skills", "Spectrum Construction"],
  resource_allocation: ["SpectrumClaw", "Skills", "Resource Allocation"],
  spectrum_decision: ["SpectrumClaw", "Skills", "Spectrum Decision"],
  knowledge: ["SpectrumClaw", "System", "Knowledge Base"],
  memory: ["SpectrumClaw", "System", "Memory & Evolution"],
  system: ["SpectrumClaw", "System", "Status"]
};

const PAGE_IDS = [
  "console",
  "frequency_planning",
  "situation_building",
  "spectrum_decision",
  "resource_allocation",
  "knowledge",
  "memory",
  "system",
];

export default function App() {
  const [activeId, setActiveId] = useState("console");
  const [modelLabel, setModelLabel] = useState("DeepSeek Pro");

  const pageNodes = useMemo(() => ({
    console: (
      <ConsolePage
        onOpenSkill={(id) => setActiveId(id)}
        modelLabel={modelLabel}
        onModelChange={setModelLabel}
      />
    ),
    frequency_planning: <FrequencyPlanningPage onBack={() => setActiveId("console")} />,
    situation_building: <SituationBuildingPage onBack={() => setActiveId("console")} />,
    spectrum_decision: <SpectrumDecisionPage onBack={() => setActiveId("console")} />,
    resource_allocation: <SpectrumDecisionPage onBack={() => setActiveId("console")} />,
    knowledge: <KnowledgePage />,
    memory: <MemoryPage />,
    system: <SystemPage />,
  }), [modelLabel]);

  const crumbs = crumbMap[activeId] ?? crumbMap.console;

  return (
    <div className="app-shell">
      <Sidebar activeId={activeId} onNavigate={setActiveId} />
      <div className="workspace">
        <TopBar crumbs={crumbs} modelLabel={modelLabel} />
        {PAGE_IDS.map((id) => (
          <div
            key={id}
            style={{
              display: id === activeId ? "contents" : "none",
            }}
          >
            {pageNodes[id]}
          </div>
        ))}
      </div>
    </div>
  );
}
