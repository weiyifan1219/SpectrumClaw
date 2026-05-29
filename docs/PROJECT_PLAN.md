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
| Console 对话 | ✅ 完成 | DeepSeek API 接入，Pro/Flash 切换，Markdown 渲染，持久化 |
| Thinking Mode | ✅ 完成 | 深度思考开关 + 推理强度可选 |
| Tool Calling | ✅ 完成 | get_time, get_weather, web_search(Tavily), web_fetch |
| 布局 | ✅ 完成 | 技能面板右侧竖向，紧凑 Composer，100vh 单屏 |
| 知识库页面 | 🔶 占位 | UI 已有，数据为 mock，等待 RAG 接入 |
| 技能详情页 | 🔶 占位 | 频率规划/态势构建/资源分配页面骨架已有 |
| 记忆与进化 | 🔶 占位 | UI 已有，等待后端记忆系统 |
| 系统状态页 | 🔶 占位 | UI 已有，等待后端健康检查接入 |
| 后端 agent loop | ❌ 未开始 | — |
| 服务器部署 | ❌ 未开始 | — |

## 阶段计划

| 阶段 | 目标 | 主要任务 |
| --- | --- | --- |
| MVP-0 | 前端和骨架可运行 | ✅ 已完成 |
| MVP-1 | ~~频率规划基础 RAG~~ → 频谱知识库 RAG | 🔨 进行中（见下方知识库方案） |
| MVP-2 | 后端 agent loop | API、任务队列、skill registry、日志、结果文件 |
| MVP-3 | 态势构建接入 | 对接用户准备好的 Agent_UAV_REM 脚本和可视化结果 |
| MVP-4 | 记忆和进化 | 任务反思、memory 浏览、skill 反馈和演化摘要 |
| MVP-5 | 服务器部署 | 4090 服务器离线依赖、服务脚本、日志和输出路径 |

---

## 频谱知识库 & RAG 方案

> 参考项目：[RAG-Anything](https://github.com/HKUDS/RAG-Anything) — 多模态 RAG + 知识图谱框架

### 数据源

| 来源 | 内容 | 数量/大小 |
| --- | --- | --- |
| `itu_documents.zip` | ITU-R 建议书、报告、无线电规则 | 804 PDF · ~1GB |
| 后续扩展 | 频谱分配表、信号调制数据库、设备参数 | 待定 |

### Phase 1 · 文本 RAG（当前）

**目标：** Agent 能从 ITU 文档库中检索相关内容并给出带引用回答。

**技术栈：**
- `pypdf` 提取 PDF 文本
- `scikit-learn` TfidfVectorizer 构建稀疏向量索引
- `sqlite3` 存储文档元数据和 chunk
- 注册为 `search_knowledge_base` tool

**流程：**
```
PDF → pypdf提取文本 → 按段落分chunk → TF-IDF向量化 → 存入sqlite
查询 → TF-IDF向量 → 余弦相似度Top-K → LLM综合 + 引用来源
```

### Phase 2 · 知识图谱（规划中）

**目标：** 提取频谱实体和关系，构建结构化知识网络。

**实体类型：** 频段、业务类型、ITU 区域、建议书编号、干扰类型、调制方式
**关系类型：** 分配关系、干扰关系、层级包含、引用关系

**技术栈：** NetworkX（轻量）+ 可视化前端

### Phase 3 · 多模态（远期）

**目标：** 处理频谱图、表格、公式等非文本内容。

**技术栈：** VLM 图像描述、LaTeX 公式解析、结构化表格提取

## 风险点

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| ITU 文档体量大 | 索引慢、内存占用高 | 第一版采用增量索引和轻量检索 |
| 服务器无法联网 | 依赖安装复杂 | 本地构建 wheelhouse 后上传 |
| 态势构建脚本未定 | 接口不稳定 | 当前只预留 skill，等脚本稳定再接入 |
| LLM API 差异 | 调用失败或格式不一致 | 统一 LLM client 抽象 |
| 前端过度复杂 | MVP 推进慢 | 当前先做 v0 静态/模拟体验 |

## 需要确认

| 问题 | 默认假设 |
| --- | --- |
| LLM API 提供方和模型名 | 先使用 OpenAI-compatible 配置占位 |
| ITU 文档是否允许解压到 `data/knowledge_base/raw/itu/` | 后续实现 RAG 前再确认 |
| 服务器项目目录 | 暂定后续使用用户指定目录，不当前连接 |
| 频率规划输出格式 | 先规划为 Markdown + JSON metadata + 引用列表 |
