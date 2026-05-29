# 系统架构

## 架构原则

| 原则 | 说明 |
| --- | --- |
| Console-first | 用户先进入可操作控制台，不做展示型 landing page |
| Skill-first | 每个频谱能力都是独立 skill，便于调用、替换和进化 |
| LangGraph-first | 后续 agent 编排以 LangGraph StateGraph 为核心，显式管理任务状态、节点和执行边 |
| LangChain-compatible | 工具、RAG、Document、Retriever 等接口逐步对齐 LangChain Core，便于长期演进 |
| API-first LLM | 当前只走外部 API，不部署本地大模型 |
| Server-primary | 最终以 4090 服务器为主运行环境，本地用于备份和中转 |
| MVP-first | 先跑通前端、RAG 和任务结果闭环，再做复杂调度 |

## 逻辑分层

| 层 | 目录 | 责任 |
| --- | --- | --- |
| Frontend | `frontend/` | 控制台、对话、任务选择、知识库、记忆、系统状态 |
| API Service | `backend/` | HTTP/WebSocket、任务创建、日志推送、结果文件索引 |
| Agent Core | `backend/agent/` | LangGraph runtime、意图识别、skill 选择、任务上下文、反思和事件输出 |
| Tools | `backend/tools/` | 后续统一工具注册、LangChain Tool 适配和工具执行 |
| Skills | `backend/skills/` | 频率规划、态势构建、调制识别、频谱决策、干扰分析，后续逐步变为 subgraph |
| Knowledge | `data/knowledge_base/` | 原始文档、RAG 索引、后续知识图谱 |
| Runtime | `outputs/`, `logs/` | 输出文件、任务日志、运行日志 |

## 当前已实现数据路径

```text
User -> Frontend Console -> Backend /api/chat or /api/chat/stream
     -> current llm.client tool loop
     -> DeepSeek / OpenAI-compatible API
     -> tools / knowledge search
     -> SSE or standard response
```

## LangGraph 目标数据路径

```text
User -> Frontend Console -> Backend API
     -> Agent Runtime
     -> LangGraph StateGraph
     -> router -> planner -> rag/tool/skill nodes -> finalizer
     -> Graph events -> existing SSE protocol
     -> Frontend reasoning/content/task log/artifacts
```

## 后续 Skill 调用路径

```text
Intent
  -> LangGraph Router
  -> Skill Registry / Subgraph
  -> Script / Model / Retriever / External API
  -> Structured Result
  -> GraphEvent + Log + Output Artifact
```

## Runtime 迁移边界

| Runtime | 状态 | 说明 |
| --- | --- | --- |
| `legacy` | 当前稳定路径 | 继续使用 `backend.llm.client.chat/stream_chat`，保证现有功能可回滚 |
| `langgraph` | 下一阶段目标 | 新增 LangGraph StateGraph，逐步接管 agent loop、tool、RAG、memory |

详见 `docs/LANGGRAPH_MIGRATION_PLAN.md`。

## 本地与服务器边界

| 环境 | 角色 | 数据 |
| --- | --- | --- |
| 本地 | 开发、备份、前端预览、依赖下载中转 | 源码、wheelhouse、轻量测试数据 |
| 4090 服务器 | 主运行、模型推理、长期服务 | 项目副本、Agent conda 环境、模型文件、输出结果 |

服务器部署阶段再执行上传、安装和启动。
