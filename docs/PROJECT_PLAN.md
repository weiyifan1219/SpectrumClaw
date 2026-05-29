# SpectrumClaw 项目规划

## 总体定位

SpectrumClaw 是面向电磁频谱任务的智能体控制台。它以大语言模型对话为入口，通过 skill 调用频谱知识库、算法脚本、模型推理和可视化能力，逐步覆盖频率规划、态势构建、调制方式识别、频谱决策和干扰分析。

## 名称备选

| 名称 | 说明 |
| --- | --- |
| SpectrumClaw | 延续 AerialClaw 命名，突出频谱任务抓取和调度能力 |
| SpectrumGarden | 强调知识库、记忆和能力持续生长 |
| ElectraScope | 强调电磁领域和态势观察 |

推荐使用 `SpectrumClaw`，便于与当前目录和 AerialClaw 参考体系对齐。

## 当前阶段策略

| 项目 | 决策 |
| --- | --- |
| 第一优先级 | 前端 Console v0、本地模拟对话、项目文档和环境复现 |
| 频率规划 | 先以 `itu_documents.zip` 为外挂资料库，规划基础 RAG，后续实现 |
| 态势构建 | 等用户上传最终实验脚本后再接入 |
| LLM | 当前只使用 API；本地模型只保留接口说明，不实现 |
| 部署 | 本地先跑前端和环境验证；4090 服务器后续再部署 |

## AerialClaw 可借鉴部分

| 方向 | 借鉴点 | SpectrumClaw 采用方式 |
| --- | --- | --- |
| 前端控制台 | Console + 任务状态 + 日志 + 可视化 | 采用四页工作台结构，Console 为主页面 |
| Skill 机制 | skill registry、skill loader、能力说明 | 每个频谱模块作为独立 skill 单元 |
| Agent Loop | Observe -> Think -> Act -> Reflect | 后续后端 agent loop 参考该流程 |
| 记忆系统 | working / episodic / skill / world memory | Memory & Evolution 页面先展示规划，后续接入真实记忆 |
| 进化系统 | 任务反馈、反思、skill 参数漂移记录 | 后续记录 skill 成功率、失败原因和用户反馈 |
| 部署组织 | 启动脚本、日志目录、服务状态 | 保留本地和服务器双路径设计 |

## Agent_UAV_REM 可复用部分

| 方向 | 复用方式 | 当前状态 |
| --- | --- | --- |
| 态势构建算法 | 后续封装为 `situation_building` skill | 暂缓 |
| 模型文件 | 后续由配置指定 checkpoint 路径 | 暂缓 |
| 推理脚本 | 后续通过 subprocess 或 Python adapter 调用 | 暂缓 |
| 可视化结果 | 输出到 `outputs/situation_building/`，前端读取元数据展示 | 暂缓 |

## 目录结构

| 目录 | 职责 |
| --- | --- |
| `frontend/` | React + Vite 前端，当前第一优先级 |
| `backend/` | 后端服务、agent loop、API 和 skill 调度的占位目录 |
| `backend/skills/` | 频谱能力单元，每个模块独立目录 |
| `config/` | 路径、LLM、skill、运行模式配置 |
| `docs/` | 项目规划、架构、前后端设计、部署、依赖、模块设计 |
| `data/knowledge_base/` | RAG 原始文件、索引和知识图谱文件 |
| `outputs/` | 任务输出结果 |
| `logs/` | 服务日志和任务日志 |
| `scripts/` | 本地启动、部署、离线依赖管理脚本 |

## 规划文档清单

| 文件 | 内容 |
| --- | --- |
| `docs/PROJECT_PLAN.md` | 总体项目规划 |
| `docs/ARCHITECTURE.md` | 系统架构和模块边界 |
| `docs/FRONTEND_DESIGN.md` | 前端页面、布局、交互和视觉规范 |
| `docs/BACKEND_DESIGN.md` | 后端服务、API、任务和日志规划 |
| `docs/SKILL_SYSTEM.md` | skill 机制和模块注册规划 |
| `docs/FREQUENCY_PLANNING.md` | 频率规划 RAG 模块设计 |
| `docs/SITUATION_BUILDING.md` | 态势构建预留设计 |
| `docs/MEMORY_AND_EVOLUTION.md` | 记忆系统和进化机制规划 |
| `docs/DEPLOYMENT.md` | 本地备份和服务器主部署方案 |
| `docs/OFFLINE_DEPENDENCIES.md` | 离线依赖和 wheelhouse 管理 |

## 当前进度（2026-05-29 更新）

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| Console 对话 | ✅ 完成 | DeepSeek API，Pro/Flash 切换，Markdown 渲染，localStorage 持久化 |
| 流式输出 | ✅ 完成 | SSE streaming，逐 token 渲染 + 闪烁光标 |
| 思考过程展示 | ✅ 完成 | 紫色折叠框展示 reasoning，开始回答后收起 |
| 引用来源 | ✅ 完成 | 网页链接 ↗ 标记，知识库标注文档编号 |
| Thinking Mode | ✅ 完成 | Brain 开关 + low/high/xhigh/max 四档推理强度 |
| Tool Calling | ✅ 完成 | 7 工具：时间/天气/Tavily搜索/网页抓取/知识库检索/系统状态 |
| 布局 | ✅ 完成 | 技能面板右侧竖向，紧凑 Composer，100vh 单屏 |
| 知识库 RAG | ✅ Phase 1 | 804 ITU PDF → TF-IDF 索引 → search_knowledge_base tool |
| 可扩展存储 | ✅ 已设计 | SqliteStore / PostgresStore / QdrantStore 统一接口 |
| LangGraph/LangChain 技术路线 | ✅ 已确定 | 后续以 LangGraph 作为 agent runtime，LangChain Core 统一 tool/retriever |
| 知识库页面 | 🔶 占位 | UI 已有，待接入真实统计 |
| 技能详情页 | 🔶 占位 | 频率规划/态势构建/资源分配页面骨架 |
| 记忆与进化 | 🔶 占位 | UI 已有，待接入后端记忆系统 |
| 系统状态页 | 🔶 占位 | UI 已有，待接入真实健康检查 |
| 后端 agent loop | ❌ 未开始 | 下一阶段基于 LangGraph StateGraph 实现 |
| 服务器部署 | ❌ 未开始 | — |

## 阶段计划

| 阶段 | 目标 | 主要任务 |
| --- | --- | --- |
| MVP-0 | 前端和骨架可运行 | ✅ 已完成 |
| MVP-1 | ~~频率规划基础 RAG~~ → 频谱知识库 RAG | 🔨 进行中（见下方知识库方案） |
| MVP-2 | LangGraph agent runtime | legacy/langgraph runtime 开关、StateGraph、tool node、RAG node、事件流 |
| MVP-3 | 态势构建接入 | 对接用户准备好的 Agent_UAV_REM 脚本和可视化结果 |
| MVP-4 | 记忆和进化 | 任务反思、memory 浏览、skill 反馈和演化摘要 |
| MVP-5 | 服务器部署 | 4090 服务器离线依赖、服务脚本、日志和输出路径 |

---

## 频谱知识库 & RAG 方案

> **对标项目：** [RAG-Anything](https://github.com/HKUDS/RAG-Anything)（HKU · 20.7k stars）
> 多模态 RAG + 知识图谱框架。支持文本/图片/表格/公式统一处理，跨模态实体提取与关系图谱构建。
> **目标：** 最终建成与 RAG-Anything 同等水平的频谱领域知识库 + 知识图谱。
> **策略：** 先 MVP 跑通链路 → 逐层升级对齐 RAG-Anything 架构。

### 数据源

| 来源 | 内容 | 数量/大小 |
| --- | --- | --- |
| `itu_documents.zip` | ITU-R 建议书、报告、无线电规则 | 804 PDF · ~1GB |
| 后续扩展 | 频谱分配表、信号调制数据库、设备参数 | 待定 |

### Phase 1 · 文本 RAG MVP（✅ 当前）

**定位：** 最简链路，先让 Agent 能从文档库里查到东西。**故意从简**——后续对标 RAG-Anything 逐层替换。

**技术栈（MVP）：**
| 环节 | MVP 方案 | 对标 RAG-Anything |
| --- | --- | --- |
| 文档解析 | `pypdf` 纯文本 | → MinerU / Docling（保留表格/公式结构） |
| 内容分类 | 无（全部当文本） | → 自动识别文本/图片/表格/公式 |
| 向量化 | TF-IDF 稀疏向量 | → Embedding 模型（语义向量） |
| 存储 | SQLite 本地文件 | → Postgres + pgvector / Qdrant |
| 知识图谱 | 无 | → 频谱实体提取 + 关系图谱 |
| 检索 | 余弦相似度 Top-K | → 向量 + 图遍历混合检索 |
| 多模态 | 不支持 | → VLM 描述图片、LaTeX 公式解析 |

**流程：**
```
PDF → pypdf提取文本 → 按段落分chunk → TF-IDF向量化 → 存入SQLite
查询 → TF-IDF向量 → 余弦相似度Top-K → LLM综合 + 引用来源
```

### Phase 2 · Embedding + 结构化（下一阶段）

**目标：** 替换 TF-IDF 为语义 Embedding，大幅提升检索质量。

**升级点：**
- TF-IDF → DeepSeek Embedding API（或本地 BGE/bge-large-zh）
- sqlite → Postgres + pgvector（支持远端存储，数据量不受本地限制）
- 简单 chunk → 带元数据的结构化文档对象（标题、章节、页码）

### Phase 3 · 知识图谱

**目标：** 从文档中自动提取频谱实体和关系，构建可查询的知识网络。

- 实体类型：频段、业务类型、ITU 区域、建议书编号、干扰类型、调制方式
- 关系类型：分配关系、干扰关系、层级包含、引用关系
- 图存储：NetworkX（轻量 MVP）→ Neo4j（生产级）
- 检索增强：向量检索 + 图遍历（类似 RAG-Anything 的 modality-aware retrieval）

### Phase 4 · 多模态

**目标：** 处理频谱图、表格、公式等非文本内容，真正实现"anything"级 RAG。

- 图片 → VLM 生成描述文本后入库
- 表格 → 结构化提取 + 统计模式识别
- 公式 → LaTeX 解析保留数学语义
- 对标 RAG-Anything 的 MinerU + VLM 管线

## 风险点

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| ITU 文档体量大 | 索引慢、内存占用高 | 第一版采用增量索引和轻量检索 |
| 服务器无法联网 | 依赖安装复杂 | 本地构建 wheelhouse 后上传 |
| 态势构建脚本未定 | 接口不稳定 | 当前只预留 skill，等脚本稳定再接入 |
| LLM API 差异 | 调用失败或格式不一致 | 第一阶段保留现有 LLM adapter，不让 LangChain 直接吞掉 DeepSeek 特殊参数 |
| LangGraph 迁移过大 | 破坏现有对话、SSE 或工具调用 | 使用 `legacy/langgraph` runtime 开关，先并行验证再切默认 |
| LangChain 依赖膨胀 | 离线部署复杂 | 先引入 `langgraph` + `langchain-core`，谨慎引入完整生态包 |
| 前端过度复杂 | MVP 推进慢 | 当前先做 v0 静态/模拟体验 |

## LangGraph / LangChain 迁移要求

详见 `docs/LANGGRAPH_MIGRATION_PLAN.md`。执行时必须遵守：

| 要求 | 说明 |
| --- | --- |
| 不推倒重写 | 当前 LLM provider、tool calling、SSE、RAG 均已可用，先包装再替换 |
| 先 runtime 开关 | 新增 `SPECTRUMCLAW_AGENT_RUNTIME=legacy/langgraph`，默认可先保留 legacy |
| 先最小 graph | router -> tool/rag -> llm_answer -> finalizer，跑通后再做 memory/subgraph |
| 保留前端协议 | `/api/chat/stream` 的 `thinking/content/done/error` 事件格式不变 |
| 逐步完全接入 | 长期方向是 LangGraph 管所有 skill，LangChain Core 管工具和 retriever 抽象 |

## 需要确认

| 问题 | 默认假设 |
| --- | --- |
| LLM API 提供方和模型名 | 先使用 OpenAI-compatible 配置占位 |
| ITU 文档是否允许解压到 `data/knowledge_base/raw/itu/` | 后续实现 RAG 前再确认 |
| 服务器项目目录 | 暂定后续使用用户指定目录，不当前连接 |
| 频率规划输出格式 | 先规划为 Markdown + JSON metadata + 引用列表 |
