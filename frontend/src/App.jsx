import { useMemo, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import TopBar from "./components/TopBar.jsx";
import ConsolePage from "./pages/ConsolePage.jsx";
import FrequencyPlanningPage from "./pages/FrequencyPlanningPage.jsx";
import SituationBuildingPage from "./pages/SituationBuildingPage.jsx";
import ResourceAllocationPage from "./pages/ResourceAllocationPage.jsx";
import KnowledgePage from "./pages/KnowledgePage.jsx";
import MemoryPage from "./pages/MemoryPage.jsx";
import SystemPage from "./pages/SystemPage.jsx";

const crumbMap = {
  console: ["SpectrumClaw", "Workspace", "Console"],
  frequency_planning: ["SpectrumClaw", "Skills", "Frequency Planning"],
  situation_building: ["SpectrumClaw", "Skills", "Situation Construction"],
  resource_allocation: ["SpectrumClaw", "Skills", "Resource Allocation"],
  knowledge: ["SpectrumClaw", "System", "Knowledge Base"],
  memory: ["SpectrumClaw", "System", "Memory & Evolution"],
  system: ["SpectrumClaw", "System", "Status"]
};

export default function App() {
  const [activeId, setActiveId] = useState("console");
  const [modelLabel, setModelLabel] = useState("DeepSeek Pro");

  const page = useMemo(() => {
    switch (activeId) {
      case "console":
        return (
          <ConsolePage
            onOpenSkill={(id) => setActiveId(id)}
            modelLabel={modelLabel}
            onModelChange={setModelLabel}
          />
        );
      case "frequency_planning":
        return <FrequencyPlanningPage onBack={() => setActiveId("console")} />;
      case "situation_building":
        return <SituationBuildingPage onBack={() => setActiveId("console")} />;
      case "resource_allocation":
        return <ResourceAllocationPage onBack={() => setActiveId("console")} />;
      case "knowledge":
        return <KnowledgePage />;
      case "memory":
        return <MemoryPage />;
      case "system":
        return <SystemPage />;
      default:
        return (
          <ConsolePage
            onOpenSkill={(id) => setActiveId(id)}
            modelLabel={modelLabel}
            onModelChange={setModelLabel}
          />
        );
    }
  }, [activeId, modelLabel]);

  const crumbs = crumbMap[activeId] ?? crumbMap.console;

  return (
    <div className="app-shell">
      <Sidebar activeId={activeId} onNavigate={setActiveId} />
      <div className="workspace">
        <TopBar crumbs={crumbs} modelLabel={modelLabel} />
        {page}
      </div>
    </div>
  );
}
