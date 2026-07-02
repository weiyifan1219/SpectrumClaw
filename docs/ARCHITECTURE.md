# 系统架构

本文描述当前代码仓库的真实运行架构。早期“后续接入/占位”的描述已不再适用：SpectrumClaw 现在是一个可运行的 FastAPI + React + LangGraph/RAG + 频谱技能工作台。

## 架构原则

| 原则 | 当前落地 |
| --- | --- |
| Console-first | 前端默认进入 Console，对话、技能入口、日志和 artifacts 都围绕工作台组织。 |
| API-first | 后端能力全部通过 FastAPI 暴露，前端通过 REST/SSE 调用。 |
| LangGraph-compatible | `backend/agent/graph.py` 定义 StateGraph，流式路径在 `runtime.py` 手动按同一拓扑驱动。 |
| RAG-first | 频谱知识问答和频率规划优先走 ITU 知识库混合检索。 |
| Skill-isolated | 频率规划、频谱构建、频谱决策按 `backend/skills/` 隔离实现。 |
| Memory best-effort | 记忆、反馈和 skill run 审计失败时不阻塞主任务。 |
| External model | LLM 通过 DeepSeek/OpenAI/Qwen/Anthropic 或兼容端点调用，不在本仓库部署本地大模型。 |

## 逻辑分层

| 层 | 目录 | 职责 |
| --- | --- | --- |
| Frontend | `frontend/` | React + Vite 工作台，包含 Console、Knowledge、Memory、System 和技能页面。 |
| API Service | `backend/app.py`, `backend/api/` | FastAPI 应用，挂载 Chat、RAG、Memory、System、频谱构建和频谱决策路由。 |
| Agent Runtime | `backend/agent/` | 运行时选择、意图路由、RAG/tool/web 上下文聚合、流式回答和记忆写入。 |
| LLM Client | `backend/llm/` | OpenAI-compatible / Anthropic-compatible 统一请求、thinking、工具循环和流式事件。 |
| RAG Pipeline | `backend/rag/` | MinerU/PyPDF 等解析、Chroma 向量库、关键词检索、知识图谱、重排、引用打包和答案生成。 |
| Skills | `backend/skills/` | 频率规划、Gudmundson/GenSpectra/UAV REM、SLSQP 资源分配等领域能力。 |
| Memory | `backend/memory/` | SQLite threads/events/items/skill_runs/feedback/evolution_reports。 |
| Runtime Data | `data/`, `outputs/`, `logs/` | 原文、parsed 内容、Chroma、graph、memory、输出产物和日志。 |
| Scripts | `scripts/` | 本地启动、SSH/LLM 链路、MinerU 批处理、parsed 入库、服务器部署和离线依赖。 |

## 端到端路径

### Console 对话

```text
User
  -> frontend ConsolePage
  -> POST /api/chat/stream
  -> backend.agent.runtime
     -> legacy 或 langgraph
     -> router: chat / rag / tool / web
     -> RAG/tool/web context
     -> backend.llm.client.stream_chat
     -> finalizer + memory writer
  -> SSE thinking/content/done
```

### RAG / 频率规划

```text
User query
  -> /api/rag/stream 或 /api/rag/frequency_plan/stream
  -> query analysis
  -> vector + keyword + graph retrieval
  -> rule rerank
  -> context pack + citations
  -> LLM answer stream
  -> best-effort RAG memory
```

`frequency_plan` profile 额外做一次脚注/相邻频段多跳检索，并使用频率规划专用 prompt。

### 频谱构建

```text
/api/spectrum-construction/generate
  -> GudmundsonMapGenerator
  -> ViT patch mask
  -> optional GenSpectra sidecar/subprocess inference
  -> maps + metrics + checkpoint status

/api/spectrum-construction/uav-rem/overview
  -> read Agent_UAV_REM artifacts
  -> comparison + active sampling + scene reconstruction
```

### 频谱决策

```text
/api/spectrum-decision/allocate
  -> manual: generate users -> allocate_multi_service
  -> agent: parse intent -> optimize -> LLM explanation

/api/spectrum-decision/allocate/stream
  -> SSE: intent -> optimize -> explanation tokens -> done
```

## Runtime 模式

| Runtime | 配置 | 说明 |
| --- | --- | --- |
| `legacy` | `SPECTRUMCLAW_AGENT_RUNTIME=legacy` | 直接调用 `backend.llm.client.stream_chat`，保留回退路径。 |
| `langgraph` | `SPECTRUMCLAW_AGENT_RUNTIME=langgraph` | 当前推荐路径，包含路由、上下文聚合、记忆注入和写回。 |

## 本地与服务器边界

| 环境 | 角色 | 典型端口/路径 |
| --- | --- | --- |
| 本地开发机 | 前端预览、代码编辑、Git、SSH/代理中转 | Vite `5173`，本地转发后端 `8230`，LLM forward proxy `8240` |
| GPU 服务器 | 后端、RAG 数据、MinerU/GenSpectra/UAV REM 产物 | 后端 `8230`，可选 GenSpectra sidecar `8231` |

当前仓库内已有大量运行数据路径约定，但大型数据、模型权重和私有服务器目录不应作为源码分发的一部分。
