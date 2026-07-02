import {
  Activity,
  AudioWaveform,
  BookMarked,
  BrainCircuit,
  Compass,
  Database,
  GitBranch,
  Layers,
  Network,
  Radar,
  Radio,
  Route,
  Settings2,
  ShieldAlert,
  Sparkles,
  Target,
  Waves
} from "lucide-react";

/* ─────────────── navigation ─────────────── */

export const navSections = [
  {
    id: "workspace",
    label: "工作台",
    items: [{ id: "console", label: "Console", chinese: "控制台", icon: Radio }]
  },
  {
    id: "skills",
    label: "技能能力",
    items: [
      {
        id: "frequency_planning",
        label: "频率规划",
        chinese: "Frequency Planning",
        icon: Compass,
        tier: "primary"
      },
      {
        id: "situation_building",
        label: "频谱构建",
        chinese: "Spectrum Construction",
        icon: Radar,
        tier: "primary"
      },
      {
        id: "spectrum_decision",
        label: "频谱决策",
        chinese: "Spectrum Decision",
        icon: Network,
        tier: "primary"
      }
    ]
  },
  {
    id: "knowledge",
    label: "知识与记忆",
    items: [
      { id: "knowledge", label: "知识库", chinese: "Knowledge Base", icon: Database },
      { id: "memory", label: "记忆与进化", chinese: "Memory & Evolution", icon: BrainCircuit }
    ]
  },
  {
    id: "system",
    label: "系统管理",
    items: [
      { id: "system", label: "系统状态", chinese: "System", icon: Settings2 }
    ]
  }
];

/* ─────────────── skills ─────────────── */

export const skills = [
  {
    id: "frequency_planning",
    label: "频率规划",
    english: "Frequency Planning",
    icon: Compass,
    tier: "primary",
    status: "运行中 · 高优先级",
    statusTone: "ok",
    accent: "cyan",
    summary: "基于 ITU 法规库与历史占用趋势，规划最优频段方案。",
    capabilities: [
      "ITU 频段法规检索",
      "干扰条件下的频段筛选",
      "带引用的规划建议生成"
    ]
  },
  {
    id: "situation_building",
    label: "频谱构建",
    english: "Spectrum Construction",
    icon: Radar,
    tier: "primary",
    status: "GenSpectra 已接入",
    statusTone: "ok",
    accent: "blue",
    summary: "基于 Gudmundson 生成多分辨率频谱覆盖，点击运行后调用 GenSpectra 返回重建图与 RMSE。",
    capabilities: [
      "Gudmundson 多分辨率生成",
      "75% ViT patch 掩码",
      "GenSpectra 重建图与 RMSE",
      "UAV REM 真实结果读取"
    ]
  },
  {
    id: "resource_allocation",
    label: "资源分配",
    english: "Resource Allocation",
    icon: Network,
    tier: "primary",
    status: "优化器已接入",
    statusTone: "info",
    accent: "violet",
    summary: "在合规、抗干扰、带宽等约束下，规划多用户资源分配方案。",
    capabilities: [
      "多目标约束求解",
      "动态频谱接入",
      "QoS 与公平性权衡"
    ]
  },
  {
    id: "interference_analysis",
    label: "干扰分析",
    english: "Interference Analysis",
    icon: ShieldAlert,
    tier: "primary",
    status: "预留",
    statusTone: "warn",
    accent: "teal",
    summary: "干扰检测、分类与识别定位，自动生成干扰报告。"
  },
  {
    id: "modulation_recognition",
    label: "调制识别",
    english: "Modulation Recognition",
    icon: AudioWaveform,
    tier: "primary",
    status: "预留",
    statusTone: "warn",
    accent: "amber",
    summary: "识别信号调制方式与特征，支持多模识别与置信度评估。"
  }
];

export const taskKeywordMap = [
  { id: "frequency_planning", words: ["频率", "规划", "ITU", "分配", "频段"] },
  { id: "situation_building", words: ["频谱", "构建", "Spectrum Construction", "覆盖", "地图", "重建"] },
  { id: "resource_allocation", words: ["资源", "调度", "功率", "时隙", "决策", "策略"] },
  { id: "modulation_recognition", words: ["调制", "识别", "信号"] },
  { id: "interference_analysis", words: ["干扰", "压制", "噪声"] }
];

/* ─────────────── console seed data ─────────────── */

export const initialMessages = [];

export const consolePrompts = [
  "帮我基于 ITU 材料做一个 2.4GHz 民用频段规划",
  "生成一组多分辨率 Spectrum Construction 预览",
  "在 8 个用户、3 段频谱下给我一个公平的资源分配方案"
];

export const systemSignals = [
  { label: "Runtime", value: "Online", tone: "ok" },
  { label: "API", value: "Connected", tone: "ok" },
  { label: "Memory", value: "已就绪", tone: "ok" },
  { label: "Model", value: "DeepSeek Pro", tone: "info", strong: true }
];

export const llmModels = [
  { id: "deepseek-v4-pro", label: "DeepSeek Pro" },
  { id: "deepseek-v4-flash", label: "DeepSeek Flash" }
];

export const reasoningEffortOptions = [
  { id: "off", label: "关闭推理 (Off)" },
  { id: "low", label: "低推理 (Low)" },
  { id: "medium", label: "中推理 (Medium)" },
  { id: "high", label: "高推理 (High)" },
  { id: "xhigh", label: "增强推理 (XHigh)" }
];

export const taskLogSeed = [
  { ts: "09:46:21", level: "info", msg: "RAG MinerU 预处理正在 3090 后台运行", tag: "运行中" },
  { ts: "09:45:11", level: "ok", msg: "Spectrum Construction GenSpectra 重建接口已验证", tag: "成功" },
  { ts: "09:44:22", level: "ok", msg: "Frequency Planning 规划为 P0 方案已保存", tag: "成功" }
];

export const artifacts = [
  { name: "干扰分析报告（详版）", type: "PDF", size: "2.4 MB", ts: "12:45:28" },
  { name: "频段规划建议（简版）", type: "PDF", size: "1.1 MB", ts: "12:45:18" },
  { name: "spectrum_plan.json", type: "JSON", size: "3.7 KB", ts: "12:44:38" }
];

/* ─────────────── ITU spectrum bands (mock) ─────────────── */

export const ituBands = [
  { name: "VLF", lo: 3, hi: 30, unit: "kHz", use: "导航 · 时间标准", load: 0.18 },
  { name: "LF", lo: 30, hi: 300, unit: "kHz", use: "广播 · AM", load: 0.32 },
  { name: "MF", lo: 0.3, hi: 3, unit: "MHz", use: "AM 广播", load: 0.41 },
  { name: "HF", lo: 3, hi: 30, unit: "MHz", use: "短波通信", load: 0.55 },
  { name: "VHF", lo: 30, hi: 300, unit: "MHz", use: "FM · 航空通信", load: 0.74 },
  { name: "UHF", lo: 0.3, hi: 3, unit: "GHz", use: "蜂窝 · WiFi", load: 0.92 },
  { name: "SHF", lo: 3, hi: 30, unit: "GHz", use: "卫星 · 雷达", load: 0.61 },
  { name: "EHF", lo: 30, hi: 300, unit: "GHz", use: "毫米波 · 5G", load: 0.43 }
];

/* ─────────────── knowledge base ─────────────── */

export const kbStats = [
  { label: "原始资料", value: "ITU · 804 PDFs", detail: "data/knowledge_base/raw" },
  { label: "旧索引", value: "20,871 chunks", detail: "TF-IDF knowledge base" },
  { label: "新 RAG", value: "MinerU 处理中", detail: "registry 尚未完成索引" },
  { label: "知识图谱", value: "初始可用", detail: "graph health: true" }
];

export const kbDocuments = [
  { id: "ITU-R M.1849", title: "Radiolocation services in the band 9–10 GHz", size: "3.2 MB", type: "PDF", tag: "Recommendation" },
  { id: "ITU-R SM.1138", title: "Determination of necessary bandwidths", size: "1.7 MB", type: "PDF", tag: "Recommendation" },
  { id: "ITU-R F.382", title: "Radio-frequency channel arrangements for fixed wireless systems", size: "2.4 MB", type: "PDF", tag: "Recommendation" },
  { id: "RR-2020", title: "Radio Regulations · Edition of 2020", size: "62.0 MB", type: "PDF", tag: "Regulation" },
  { id: "ITU-R P.452", title: "Prediction procedure for the evaluation of interference", size: "4.1 MB", type: "PDF", tag: "Recommendation" }
];

export const ragPipeline = [
  { step: "Raw PDFs", note: "804 ITU PDFs", status: "ready" },
  { step: "Document Parser", note: "MinerU shard 正在 3090 后台运行", status: "ready" },
  { step: "Chunk + Embed", note: "新 registry/chroma 尚未完成", status: "planned" },
  { step: "Retriever", note: "旧 TF-IDF 可用，新 RAG 待索引", status: "planned" },
  { step: "Cited Answer", note: "LangGraph RAG API 已接入", status: "ready" },
  { step: "Knowledge Graph", note: "初始 graph 可读，规模待扩展", status: "ready" }
];

/* ─────────────── memory & evolution ─────────────── */

export const memoryLayers = [
  { label: "Working Memory", chinese: "工作记忆", value: "当前任务上下文", icon: Activity, fill: 0.34 },
  { label: "Episodic", chinese: "事件记忆", value: "历史任务经历", icon: Sparkles, fill: 0.12 },
  { label: "Skill Memory", chinese: "能力记忆", value: "Skill 使用经验", icon: Route, fill: 0.21 },
  { label: "Domain", chinese: "领域知识", value: "频谱领域知识", icon: BookMarked, fill: 0.55 }
];

export const evolutionLog = [
  { ts: "2026-05-28", title: "Skill schema v0.2", note: "整合 spectrum_decision → resource_allocation", tone: "accent" },
  { ts: "2026-05-27", title: "Console v0 spec", note: "确定 chat-first + skill 二级页", tone: "info" },
  { ts: "2026-05-25", title: "Knowledge corpus pinned", note: "ITU 文档库定位为 P0", tone: "ok" },
  { ts: "2026-05-22", title: "Project scaffold", note: "前端 / 后端 / 文档骨架", tone: "muted" }
];

/* ─────────────── system page ─────────────── */

export const systemRows = [
  { name: "LLM API", value: "DeepSeek Pro · OpenAI-compatible", status: "Connected", tone: "ok", group: "External" },
  { name: "Local Conda", value: "SpectrumClaw · python 3.11", status: "Ready", tone: "ok", group: "Runtime" },
  { name: "3090 Backend", value: "127.0.0.1:8230 · uvicorn", status: "Running", tone: "ok", group: "Runtime" },
  { name: "GenSpectra Env", value: "Agent_UAV · torch CUDA", status: "Ready", tone: "ok", group: "Runtime" },
  { name: "Knowledge Path", value: "data/knowledge_base/raw", status: "Ready", tone: "ok", group: "Storage" },
  { name: "RAG Preparse", value: "backend.rag.preparse_mineru", status: "Running", tone: "info", group: "Storage" },
  { name: "Frontend", value: "Vite build · 127.0.0.1:5173", status: "Running", tone: "ok", group: "Service" },
  { name: "WebSocket", value: "SSE chat stream", status: "Available", tone: "ok", group: "Service" }
];

/* ─────────────── frequency planning page (mock) ─────────────── */

export const fpScenarios = [
  { id: "civil_2_4ghz", label: "民用 2.4 GHz 共用频段", region: "ITU 区域 1" },
  { id: "vhf_aero", label: "VHF 航空通信预留", region: "ITU 区域 2" },
  { id: "5g_mmwave", label: "5G 毫米波协调", region: "ITU 区域 3" }
];

export const fpCitations = [
  { id: "ITU-R M.1849-2", page: "p. 12 §3.4", excerpt: "Frequency bands above 9 GHz are subject to dual-allocation review where radiolocation services share with fixed services." },
  { id: "ITU-R SM.1138-2", page: "p. 5 §2.1", excerpt: "Necessary bandwidth shall be determined as the minimum bandwidth that ensures the transmission of information at the required rate and quality." },
  { id: "ITU-RR Article 5", page: "Vol. I §5.138", excerpt: "Allocations to services in the bands designated for industrial, scientific and medical applications are subject to special agreement." }
];

/* ─────────────── spectrum construction page (mock) ─────────────── */

export const sbScenarios = [
  { id: "urban", label: "城市电磁覆盖重建", area: "12 × 12 km" },
  { id: "borderline", label: "边境监测", area: "40 × 8 km" },
  { id: "harbor", label: "港口频谱态势", area: "6 × 4 km" }
];

/* ─────────────── resource allocation page (mock) ─────────────── */

export const raPolicies = [
  { id: "fairness", label: "公平优先", note: "Max-min 公平性，QoS 次之" },
  { id: "throughput", label: "吞吐优先", note: "总速率最大化" },
  { id: "balanced", label: "均衡策略", note: "公平 / 吞吐 / 干扰联合优化" }
];

export const raMockMatrix = (function build() {
  // 6 channels × 8 users mock heatmap; deterministic
  const rows = [];
  for (let c = 0; c < 6; c++) {
    const row = [];
    for (let u = 0; u < 8; u++) {
      const v = (Math.sin(c * 1.7 + u * 0.9) + 1) / 2;
      row.push(Number(v.toFixed(2)));
    }
    rows.push(row);
  }
  return rows;
})();
