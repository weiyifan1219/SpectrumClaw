<div align="center">

# SpectrumClaw

电磁频谱领域 AI 智能体工作台

面向频率规划、频谱构建、频谱决策和知识库问答的开源智能体系统。SpectrumClaw 以可交互 Console 为入口，将大语言模型、频谱领域 RAG、LangGraph 工作流、频谱构建模型、资源分配优化器和记忆进化机制组织为一个可运行、可审查、可扩展的频谱任务平台。

</div>

---

## 项目简介

SpectrumClaw 不是一个通用聊天机器人，而是一个面向电磁频谱工程任务的智能体工作台。系统围绕“用户需求 -> 智能体路由 -> 领域工具/知识库/算法技能 -> 结构化结果 -> 记忆沉淀”的流程设计，支持从自然语言问题进入频谱知识检索、法规依据分析、频率规划、频谱态势构建和频谱资源分配。

项目的核心设计目标是让频谱任务的执行过程可见、证据可查、模块可替换：RAG 回答需要带引用，技能调用会写入审计记录，模型和外部算法通过 API 与适配器解耦，前端以控制台和工作区形式展示任务状态、结果、引用和系统记忆。

## 核心能力

| 能力 | 说明 | 主要入口 |
| --- | --- | --- |
| 智能体 Console | 支持流式对话、模型选择、思考过程展示、工具调用、知识库检索和任务入口跳转 | `frontend/src/pages/ConsolePage.jsx`, `/api/chat/stream` |
| 频率规划 | 基于 ITU-R 文档 RAG，输出频段划分、业务状态、脚注限制、相邻频段、共存约束和带引用规划建议 | `frontend/src/pages/FrequencyPlanningPage.jsx`, `/api/rag/frequency_plan/stream` |
| 频谱知识库 | 支持 PDF 上传、解析、索引、混合检索、知识图谱查询、流式问答和 PDF 来源查看 | `frontend/src/pages/KnowledgePage.jsx`, `/api/rag/*` |
| 频谱构建 | 使用 Gudmundson 物理模型生成多分辨率频谱图，可选调用 GenSpectra 做掩码重建，并读取 Agent_UAV_REM 实验产物 | `/api/spectrum-construction/generate`, `/api/spectrum-construction/uav-rem/overview` |
| 频谱决策 | 基于 CQI-Shannon 速率模型和 SLSQP 比例公平优化进行多用户、多业务资源分配，给出贪心吞吐基线对比，支持 LLM 解析自然语言需求并流式解读 | `frontend/src/pages/SpectrumDecisionPage.jsx`, `/api/spectrum-decision/allocate` |
| 记忆与进化 | 记录会话、RAG 查询、技能调用、用户反馈和进化报告，支持后续反思与能力改进 | `frontend/src/pages/MemoryPage.jsx`, `/api/memory/*` |
| 工具系统 | 内置时间、系统状态、天气、网页搜索、网页抓取、知识库检索和频率规划工具，可接入 LangChain Tool | `backend/tools/`, `backend/llm/tools.py` |

## 系统架构

```text
User
  -> React Console / Skill Workspace
  -> FastAPI API Service
  -> LangGraph Agent Runtime
     -> Router
     -> RAG / Tool / Web / Skill Nodes
     -> LLM Client
     -> Finalizer
  -> SSE Events + Structured Results
  -> Memory & Evolution Store
```

| 层级 | 目录 | 职责 |
| --- | --- | --- |
| Frontend | `frontend/` | React + Vite 控制台、技能工作区、知识库、记忆与系统状态页面 |
| API Service | `backend/app.py`, `backend/api/` | FastAPI 应用，统一挂载 Chat、RAG、Memory、Spectrum Construction、Spectrum Decision 路由 |
| Agent Runtime | `backend/agent/` | LangGraph 状态图、意图路由、上下文聚合、工具/RAG/Web 路径和记忆读写 |
| LLM Client | `backend/llm/` | OpenAI-compatible 与 Anthropic-compatible 统一适配，支持工具循环、thinking 和流式输出 |
| RAG Pipeline | `backend/rag/` | 文档解析、内容处理、向量库、知识图谱、查询分析、混合检索、重排和带引用回答 |
| Skills | `backend/skills/` | 频率规划、频谱构建、频谱决策等领域技能封装 |
| Memory | `backend/memory/` | SQLite 记忆存储、技能审计、反馈记录和进化报告 |
| Data | `data/` | 知识库原文、Chroma 向量库、图谱、解析缓存、评测数据和运行记忆 |

## 技术栈

| 类型 | 技术 |
| --- | --- |
| 前端 | React, Vite, lucide-react, react-markdown, remark-gfm |
| 后端 | FastAPI, Uvicorn, Pydantic, httpx |
| Agent | LangGraph, LangChain Core tools |
| LLM 接入 | DeepSeek / OpenAI / Qwen / Anthropic / OpenAI-compatible / Anthropic-compatible |
| RAG | ChromaDB, sentence-transformers, PyPDF, MinerU/Docling/PaddleOCR 预留解析路径 |
| 检索 | 向量检索、关键词检索、频段规则匹配、知识图谱检索、规则重排 |
| 数值计算 | NumPy, SciPy, scikit-learn |
| 存储 | SQLite memory store, JSON doc registry, Chroma persistent store |

## 快速开始

### 1. 克隆并进入项目

```bash
git clone https://github.com/weiyifan1219/SpectrumClaw.git
cd SpectrumClaw
```

### 2. 创建 Python 环境

```bash
conda env create -f environment.yml
conda activate SpectrumClaw
```

也可以直接使用 pip：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 3. 安装前端依赖

```bash
npm --prefix frontend install
```

### 4. 配置环境变量

```bash
cp .env.example .env
```

至少配置一个可用的 LLM provider。默认可以使用 DeepSeek，也可以切换 OpenAI、Qwen、Anthropic 或兼容端点。

```env
SPECTRUMCLAW_AGENT_RUNTIME=langgraph
SPECTRUMCLAW_LLM_PROVIDER=deepseek
SPECTRUMCLAW_LLM_BASE_URL=
SPECTRUMCLAW_LLM_API_KEY=
SPECTRUMCLAW_LLM_MODEL=
```

常用配置：

| 变量 | 说明 |
| --- | --- |
| `SPECTRUMCLAW_AGENT_RUNTIME` | `langgraph` 或 `legacy` |
| `SPECTRUMCLAW_LLM_PROVIDER` | `auto`, `deepseek`, `openai`, `qwen`, `anthropic`, `openai_compatible`, `anthropic_compatible` |
| `SPECTRUMCLAW_LLM_BASE_URL` | 自定义兼容端点 |
| `SPECTRUMCLAW_LLM_API_KEY` | LLM API Key |
| `SPECTRUMCLAW_LLM_MODEL` | 模型名称 |
| `TAVILY_API_KEY` | 可选，启用 Web 搜索工具 |
| `QWEN_VL_API_KEY` | 可选，启用图像内容理解 |
| `SPECTRUMCLAW_PARSER` | `pypdf` 或 `mineru` |

### 5. 启动后端

```bash
scripts/local/start_backend.sh
```

或直接运行：

```bash
uvicorn backend.app:app --host 0.0.0.0 --port 8230 --reload
```

健康检查：

```bash
curl http://127.0.0.1:8230/health
```

### 6. 启动前端

```bash
scripts/local/start_frontend.sh
```

默认访问：

```text
http://127.0.0.1:5173/
```

如果前端与后端不在同一主机，可显式设置 API 地址：

```bash
VITE_API_BASE=http://127.0.0.1:8230 npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

## 知识库使用

SpectrumClaw 的知识库面向 ITU-R 建议书、报告、无线电规则和其他频谱工程资料。大型原始资料、向量库、图谱和模型权重通常不直接随源码发布。

### 放置文档

```text
data/knowledge_base/raw/
```

也可以通过前端 Knowledge Base 页面或 `/api/rag/upload` 上传 PDF。

### 构建索引

```bash
python -m backend.rag.ingest --clear
```

常用参数：

```bash
python -m backend.rag.ingest --file path/to/document.pdf
python -m backend.rag.ingest --dir data/knowledge_base/raw
python -m backend.rag.ingest --limit 20
```

索引后可使用：

| 功能 | 入口 |
| --- | --- |
| RAG 状态 | `GET /api/rag/status` |
| 知识库统计 | `GET /api/kb/stats` |
| 普通问答 | `POST /api/rag/query` |
| 流式问答 | `POST /api/rag/stream` |
| 频率规划 | `POST /api/rag/frequency_plan/stream` |
| 图谱实体 | `GET /api/rag/graph/entities` |

## 领域模块

### 频率规划

频率规划模块使用专用 RAG profile。系统先做查询分析，再进行向量、关键词和图谱检索，重排后打包上下文。频率规划路径额外执行一次脚注与相邻频段检索，用于补充 ITU 区域差异、脚注限制、共存协调和风险判断。

输出包含两部分：

| 输出 | 说明 |
| --- | --- |
| 中文规划分析 | 结论、频段划分、脚注与限制、相邻频段与共存、规划建议、来源和不确定性 |
| 结构化 JSON | `frequency_band`, `region`, `allocation_status`, `services`, `footnotes`, `adjacent_bands`, `risk_level`, `recommendation` |

### 频谱构建

频谱构建模块由两条能力组成：

| 子能力 | 说明 |
| --- | --- |
| Gudmundson 预览 | 生成 32/64/128/224 多分辨率功率地图，使用 ViT patch 掩码模拟稀疏观测 |
| GenSpectra 推理 | 当外部 GenSpectra 根目录、Python 环境和 checkpoint 可用时，通过 sidecar 或子进程执行掩码重建 |
| UAV REM 读取 | 只读适配 Agent_UAV_REM 结果，展示真值图、稀疏采样、重建图、误差图、主动采样路径和算法对比 |

GenSpectra 相关路径通过环境变量或服务器目录约定配置。缺少模型或 checkpoint 时，系统会降级为物理预览，不阻塞主流程。

### 频谱决策

频谱决策模块面向多用户资源分配。系统根据环境和服务配比生成用户信道数据，将 SNR 映射为 CQI，再使用比例公平目标进行带宽分配。跨业务的频谱按各业务的带宽需求加权切分，避免按人头平分时高吞吐业务被饿死。

| 部分 | 说明 |
| --- | --- |
| 信道建模 | FSPL + COST231-Hata，支持 urban/suburban/rural 环境 |
| 业务类型 | eMBB、URLLC、mMTC |
| 优化目标 | 最大化 `sum(log(rate_i))` |
| 求解器 | SciPy SLSQP，失败时使用 CQI 优先 fallback；结果区透出真实可行性与求解方法 |
| 评价指标 | 总吞吐量、Jain 公平指数、服务分组结果、贪心吞吐基线对比（量化"以吞吐换公平"的增益） |
| 参数化模式 | 直接配置用户数、带宽、环境、载波频率、随机种子与业务配比 |
| 自然语言模式 | LLM 将需求解析为结构化参数，分"意图识别 → 优化 → 结果解读"三阶段 SSE 流式展示，并用中文解读结果；内置可点击的部署场景示例 |

### 记忆与进化

系统会以 best-effort 方式记录运行过程，不让记忆失败影响主任务：

| 数据 | 说明 |
| --- | --- |
| Thread | 会话级信息和摘要 |
| Events | 用户、助手、RAG、系统事件 |
| Memory Items | episodic、skill、domain、evolution 等记忆条目 |
| Skill Runs | 技能调用输入、输出摘要、状态、耗时和错误 |
| Feedback | 前端回答反馈 |
| Evolution Reports | 聚合近期运行指标和反馈生成的进化报告 |

## API 概览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 后端和 LLM 配置健康检查 |
| `POST` | `/api/chat` | 非流式对话 |
| `POST` | `/api/chat/stream` | SSE 流式智能体对话 |
| `GET` | `/api/kb/stats` | 知识库统计 |
| `POST` | `/api/rag/upload` | 上传 PDF 并解析入库 |
| `POST` | `/api/rag/index` | 对指定文件或上传目录构建索引 |
| `POST` | `/api/rag/query` | RAG 问答 |
| `POST` | `/api/rag/stream` | 流式 RAG 问答 |
| `POST` | `/api/rag/frequency_plan/stream` | 频率规划专用流式问答 |
| `GET` | `/api/rag/status` | RAG registry、Chroma、Graph 和 ingest 状态 |
| `GET` | `/api/rag/graph/entities` | 查询知识图谱实体 |
| `GET` | `/api/rag/graph/entity/{name}` | 查询单个实体及其关系 |
| `POST` | `/api/spectrum-construction/generate` | 生成频谱构建预览，可选 GenSpectra 推理 |
| `POST` | `/api/spectrum-construction/uav-rem/overview` | 读取 UAV REM 场景与算法对比 |
| `POST` | `/api/spectrum-decision/allocate` | 频谱资源分配（手动 / 智能体，非流式） |
| `POST` | `/api/spectrum-decision/allocate/stream` | 智能体模式流式分配：意图识别 → 优化 → 结果解读 |
| `GET` | `/api/memory/overview` | 记忆系统概览 |
| `GET` | `/api/memory/items` | 记忆条目查询 |
| `POST` | `/api/memory/feedback` | 提交用户反馈 |
| `POST` | `/api/memory/reflect` | 生成进化反思报告 |

## 项目结构

```text
SpectrumClaw/
  backend/
    app.py                         FastAPI 应用入口
    agent/                         LangGraph agent runtime
    api/                           HTTP API 路由
    llm/                           多 provider LLM client 与工具循环
    rag/                           文档解析、索引、检索、图谱和 RAG 问答
    skills/
      frequency_planning/          频率规划 RAG 封装
      spectrum_construction/       Gudmundson、GenSpectra、UAV REM 适配
      spectrum_decision/           资源分配优化器和 LLM agent
    memory/                        SQLite 记忆、反馈和进化报告
    tools/                         统一工具注册与 LangChain 适配
  frontend/
    src/pages/                     Console、Knowledge、Memory、System 和技能页面
    src/components/                通用 UI 组件
    src/lib/api.js                 前端 API client
    src/styles/                    设计变量和页面样式
  config/                          应用、LLM、RAG、skills 配置
  data/                            知识库、索引、图谱、记忆、评测数据
  docs/                            架构、部署、RAG、技能和前端设计文档
  scripts/                         本地启动、服务器部署、离线依赖和索引脚本
  tests/                           Chat、Agent、RAG、Memory、Spectrum Construction 测试
```

## 测试与构建

```bash
pytest -q
npm --prefix frontend run build
```

也可以按模块运行：

```bash
pytest tests/test_chat_api.py -q
pytest tests/test_agent_runtime.py -q
pytest tests/test_rag_pipeline.py -q
pytest tests/test_memory_store.py tests/test_memory_api.py -q
pytest tests/test_spectrum_construction.py -q
```

## 部署说明

SpectrumClaw 支持本地轻量开发，也支持部署到无公网服务器。推荐模式是本地负责代码开发、前端预览和依赖中转，GPU 服务器负责长期运行、模型推理、RAG 预处理和外部实验产物读取。

| 场景 | 说明 |
| --- | --- |
| 本地开发 | 使用 conda 或 venv 安装依赖，运行 FastAPI + Vite |
| 服务器部署 | 使用 `scripts/server_deploy.sh` 和离线 wheelhouse 安装依赖 |
| 无公网服务器 | 通过本地下载依赖和模型后上传，或使用 SSH 隧道转发 API |
| GenSpectra | 建议在独立环境中运行，SpectrumClaw 通过 sidecar 或子进程调用 |
| Agent_UAV_REM | SpectrumClaw 只读既有实验产物，不训练、不修改外部项目 |

更多细节见 `docs/DEPLOYMENT.md` 和 `docs/OFFLINE_DEPENDENCIES.md`。

## 开发路线

| 方向 | 内容 |
| --- | --- |
| 知识库增强 | 扩展更多频谱文档、提升解析质量、增强图谱关系和引用定位 |
| 多模态 RAG | 接入更完整的图像、表格、公式理解与跨模态检索 |
| Skill 扩展 | 继续接入调制识别、干扰分析和更多频谱任务技能 |
| 评测体系 | 建立频率规划、RAG 引用质量、资源分配结果和前端交互的评测基线 |
| 部署工程 | 完善离线依赖、服务器守护、日志观测和模型/数据路径配置 |
| 记忆进化 | 将反馈、失败案例和领域经验沉淀为可持续改进的 agent memory |

## 参考文档

| 文档 | 说明 |
| --- | --- |
| `docs/TECHNICAL_OVERVIEW.md` | 后端核心实现、Agent、RAG、Skills、Memory 技术细节 |
| `docs/ARCHITECTURE.md` | 系统分层、运行路径和本地/服务器边界 |
| `docs/FREQUENCY_PLANNING.md` | 频率规划页面和 RAG 工作区设计 |
| `docs/FRONTEND_DESIGN.md` | 前端信息架构和视觉方向 |
| `docs/MEMORY_AND_EVOLUTION.md` | 记忆与进化机制设计 |
| `docs/OFFLINE_DEPENDENCIES.md` | 离线依赖管理 |

## 说明

大型数据、模型权重、向量库、服务器私有路径和 API Key 不应提交到源码仓库。开源分发时建议同时补充 `LICENSE`、示例数据说明和截图资源。
