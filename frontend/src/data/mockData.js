import {
  Activity,
  BrainCircuit,
  Database,
  GitBranch,
  Radio,
  Radar,
  Route,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  Waves
} from "lucide-react";

export const pages = [
  { id: "console", label: "Console", icon: Radio },
  { id: "knowledge", label: "Knowledge Base", icon: Database },
  { id: "memory", label: "Memory & Evolution", icon: BrainCircuit },
  { id: "system", label: "System", icon: SlidersHorizontal }
];

export const spectrumTasks = [
  {
    id: "frequency_planning",
    label: "频率规划",
    status: "Priority",
    icon: Route,
    accent: "cyan",
    description: "基于 ITU 文档库的 RAG 检索和规划建议。",
    readiness: "前端入口就绪，后端 RAG 待实现。"
  },
  {
    id: "situation_building",
    label: "态势构建",
    status: "Waiting",
    icon: Radar,
    accent: "amber",
    description: "后续接入 Agent_UAV_REM 相关脚本和模型。",
    readiness: "等待用户准备最终实验脚本。"
  },
  {
    id: "modulation_recognition",
    label: "调制识别",
    status: "Reserved",
    icon: Waves,
    accent: "green",
    description: "预留调制方式识别模型接口。",
    readiness: "接口占位。"
  },
  {
    id: "spectrum_decision",
    label: "频谱决策",
    status: "Reserved",
    icon: GitBranch,
    accent: "violet",
    description: "预留频谱策略和优化决策接口。",
    readiness: "接口占位。"
  },
  {
    id: "interference_analysis",
    label: "干扰分析",
    status: "Reserved",
    icon: ShieldAlert,
    accent: "red",
    description: "预留干扰检测、定位和解释接口。",
    readiness: "接口占位。"
  }
];

export const initialMessages = [
  {
    role: "assistant",
    content:
      "我是 SpectrumClaw 前端 v0。现在可以先演示频谱智能体的对话、任务选择和 skill 路由流程；真实 LLM API 与 RAG 后端将在下一阶段接入。"
  }
];

export const systemSignals = [
  { label: "Runtime", value: "Local preview", tone: "green" },
  { label: "LLM", value: "API planned", tone: "amber" },
  { label: "Knowledge", value: "itu_documents.zip", tone: "cyan" },
  { label: "Server", value: "4090 pending", tone: "muted" }
];

export const taskLogSeed = [
  "Console initialized in local preview mode.",
  "Skill registry loaded from frontend mock data.",
  "Frequency planning marked as first implementation target.",
  "Situation building is blocked until scripts are ready."
];

export const kbStats = [
  { label: "资料包", value: "itu_documents.zip" },
  { label: "索引状态", value: "未构建" },
  { label: "RAG 策略", value: "MVP: PDF + chunk + retrieval" },
  { label: "图谱状态", value: "预留" }
];

export const memoryLayers = [
  { label: "Working", value: "当前任务上下文", icon: Activity },
  { label: "Episodic", value: "历史任务经历", icon: Sparkles },
  { label: "Skill", value: "能力使用经验", icon: Route },
  { label: "Domain", value: "频谱领域知识", icon: Database }
];
