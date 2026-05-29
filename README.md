# SpectrumClaw

SpectrumClaw 是一个面向电磁频谱领域的智能体项目。项目目标是把大语言模型对话、skill 调用、频谱知识库、后续知识图谱、算法脚本和可视化结果组织成一个可部署到 4090 服务器的工作台。

## 项目进度快照

更新时间：2026-05-29

当前阶段：对话 + 工具调用 + 频谱知识库 RAG 已打通。频率规划 RAG 和态势构建算法接入暂未开始真实业务实现。

| 模块 | 当前状态 | 说明 |
| --- | --- | --- |
| 前端 Console | ✅ 完成 | 对话区、模型/技能/推理选择、Markdown 渲染、localStorage 持久化 |
| 基础 LLM 对话 | ✅ 已接入 | 后端 `/api/chat` 调用真实 LLM API，默认 DeepSeek（Pro/Flash 切换） |
| Provider 兼容 | ✅ 已建立 | 支持 `openai`、`deepseek`、`qwen`、`anthropic`、自定义代理 |
| Tool calling | ✅ 已修通 | get_time、get_weather、web_search(Tavily)、web_fetch、search_knowledge_base |
| 推理模式 | ✅ 已实现 | 思考开关 + low/high/xhigh/max 四档推理强度，合并到模型 popover |
| 频谱知识库 RAG | ✅ Phase 1 | 804 份 ITU PDF 文本提取 → TF-IDF 索引 → `search_knowledge_base` tool |
| 错误降级 | ✅ 已实现 | 不支持 tools 的模型 400 降级为普通对话，tool 错误时跳出循环 |
| 测试 | ✅ 已补充 | 后端测试覆盖 provider 配置、payload 构造、tool retry、降级逻辑 |

当前阶段优先完成：

| 优先级 | 内容 | 状态 |
| --- | --- | --- |
| P0 | 前端 Console v0 和基础对话体验 | 已实现并接入后端 `/api/chat` |
| P0 | 项目骨架、文档、环境复现文件 | 已规划并创建 |
| P0 | 真实 LLM API 和基础 tool calling | 已完成 DeepSeek 路径验证，其他 provider 保留兼容层 |
| P1 | 频率规划 RAG | 先用 `itu_documents.zip` 作为外挂资料库，下一阶段实现 |
| P2 | 态势构建 | 等用户准备好实验脚本后接入 |

## 页面规划

| 页面 | 作用 |
| --- | --- |
| Console | 与频谱智能体对话，选择频谱任务，查看任务日志和结果入口 |
| Knowledge Base | 展示 ITU 文档库、RAG 索引状态、后续知识图谱入口 |
| Memory & Evolution | 展示记忆层、能力清单、skill 演化总结 |
| System | 展示运行环境、API 状态、本地/服务器路径、依赖和服务健康状态 |

## 本地开发

### 前端

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

### 后端

```bash
bash scripts/local/start_backend.sh
```

后端默认监听 `127.0.0.1:8230`。前端 Console 页面会自动调用后端 `/api/chat`。

如需接入真实 LLM，在 `.env` 中设置。当前支持 `openai`、`deepseek`、`qwen`、`anthropic`，也支持自定义 `openai_compatible` 和 `anthropic_compatible` 代理。

```bash
# Anthropic-compatible / PackyAPI / Claude-compatible proxy
SPECTRUMCLAW_LLM_PROVIDER=anthropic_compatible
SPECTRUMCLAW_LLM_BASE_URL=https://your-provider.example
SPECTRUMCLAW_LLM_API_KEY=sk-xxx
SPECTRUMCLAW_LLM_MODEL=your-model

# OpenAI-compatible / OpenAI / DeepSeek / Qwen
SPECTRUMCLAW_LLM_PROVIDER=openai_compatible
SPECTRUMCLAW_LLM_BASE_URL=https://api.openai.com/v1
SPECTRUMCLAW_LLM_API_KEY=sk-xxx
SPECTRUMCLAW_LLM_MODEL=gpt-4o
```

未配置时，`/api/chat` 返回确定性降级回复，`metadata.configured=false`。

### Python 环境

```bash
conda create -n SpectrumClaw python=3.11 -y
conda run -n SpectrumClaw python -m pip install -r requirements.txt
conda run -n SpectrumClaw python -m pip check
```

### 测试

```bash
conda run -n SpectrumClaw pytest -q
```

当前已验证：

| 验证项 | 命令 | 当前结果 |
| --- | --- | --- |
| 后端测试 | `conda run -n SpectrumClaw pytest -q` | 通过，12 个测试 |
| 前端构建 | `cd frontend && npm run build` | 通过 |
| 后端健康检查 | `curl http://127.0.0.1:8230/health` | 通过，返回 DeepSeek provider 信息 |
| Tool calling 冒烟 | POST `/api/chat`，问题”现在是几点？” | 通过，`tool_rounds=1` |

## 知识库 & RAG

### 索引构建

```bash
PYTHONPATH=. conda run -n SpectrumClaw python -m backend.knowledge.ingest
```

从 `itu_documents.zip`（804 份 ITU-R PDF）提取文本 → 分块 → TF-IDF 索引。

### 存储后端

默认 `sqlite`（本地文件）。通过环境变量切换：

| 变量 | 说明 | 可选值 |
| --- | --- | --- |
| `SPECTRUMCLAW_KB_BACKEND` | 存储后端 | `sqlite`（默认）/ `postgres`（规划）/ `qdrant`（规划） |
| `SPECTRUMCLAW_KB_DSN` | Postgres 连接串 | `postgresql://user:pass@host:5432/db` |
| `SPECTRUMCLAW_QDRANT_URL` | Qdrant 地址 | `http://host:6333` |

所有后端实现统一接口（`backend/knowledge/store.py`）：
- `insert(chunks)` → 写入
- `search(query, top_k)` → 检索
- `count()` → 统计
- `clear()` → 清空

## 重要路径

| 路径 | 说明 |
| --- | --- |
| `itu_documents.zip` | 第一批频率规划资料库，当前不移动 |
| `frontend/` | React + Vite 前端 |
| `backend/` | 后端和 skill 目录占位，后续实现 |
| `docs/` | 架构、设计、部署和模块规划 |
| `data/knowledge_base/` | 后续 RAG 原始文件、索引和图谱目录 |
| `outputs/` | 后续任务输出 |
| `logs/` | 后续运行日志 |

## 当前限制

- 当前只实现了基础对话和通用工具调用，还没有真正的频谱业务 skill。
- 频率规划 RAG 尚未实现，只确定了第一批资料库 `itu_documents.zip`。
- 态势构建尚未接入真实算法，等待用户准备实验脚本和模型。
- 还没有实现知识图谱、调制方式识别、频谱决策和干扰分析。
- 还没有连接或部署到 4090 服务器。

## 下一阶段任务

这些任务适合交给 Claude Code 批量实现；Codex 负责架构把关、接口验收和卡点诊断。

| 优先级 | 任务 | 交付物 | 验收标准 |
| --- | --- | --- | --- |
| P0 | 整理 agent skill 注册机制 | `backend/agent/`、`backend/skills/` 中形成统一 skill registry 和执行入口 | Console 可以按 `tool_names` 或 skill id 触发对应能力 |
| P0 | 实现频率规划基础 RAG | 解压/读取 `itu_documents.zip`，建立最小文档索引和检索接口 | 用户可在 Console 中询问 ITU/频率规划问题，并返回带来源的回答 |
| P0 | 前端展示真实 agent 执行过程 | 对话气泡或任务日志展示 skill 选择、工具调用轮次、检索状态、结果摘要 | 用户能看清“智能体为什么调用了哪个能力” |
| P1 | 知识库页面接入真实状态 | Knowledge Base 页面展示文档数量、索引状态、检索样例和后续知识图谱入口 | 页面不再只展示 mock 数据 |
| P1 | 结果文件和日志目录联动 | 后端把任务日志写入 `logs/`，把结果写入 `outputs/`，前端可查看 | Console 结果区域能列出真实生成文件 |
| P1 | 频率规划报告生成 | 基于 RAG 回答生成 Markdown/JSON 报告 | `outputs/` 中产生可下载结果文件 |
| P2 | 接入记忆与进化总结 | 参考 AerialClaw 的 memory/evolution 思路，先做轻量记录 | Memory & Evolution 页面显示真实对话摘要和能力更新 |
| P2 | 服务器部署脚本 | 区分本地备份和 4090 主运行环境，准备 rsync/scp、启动脚本和日志路径 | 不在本地假装部署；等用户确认后再执行 |

## 给 Claude Code 的执行提示

| 约束 | 说明 |
| --- | --- |
| 先做频率规划 | 暂时不要接入态势构建，等待用户上传实验脚本 |
| 先小闭环 | RAG 先做最小可运行版本，不要一次引入复杂任务编排 |
| 保持兼容 | 后端 LLM client 已支持多 provider，新功能不要写死 DeepSeek |
| 保留审计信息 | 每次 skill 执行应返回 metadata，方便前端展示和后续排错 |
| 不泄露密钥 | 不要把 `.env` 内容写入日志、README、前端或测试输出 |
