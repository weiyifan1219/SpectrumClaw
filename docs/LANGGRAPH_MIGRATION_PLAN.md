# LangGraph 运行时

本文原为迁移计划；当前迁移已经落地为双 runtime 结构。

## Runtime 选择

| 值 | 行为 |
| --- | --- |
| `SPECTRUMCLAW_AGENT_RUNTIME=legacy` | `/api/chat/stream` 直接调用 `backend.llm.client.stream_chat`。 |
| `SPECTRUMCLAW_AGENT_RUNTIME=langgraph` | 先执行路由和上下文节点，再调用 LLM 流式生成，并写入记忆。 |

无效值会回退到 `legacy`。

## 图拓扑

`backend/agent/graph.py` 定义标准 StateGraph：

```text
router
  -> rag_search / tool_executor / web_search / llm_answer
  -> llm_answer
  -> finalizer
  -> END
```

`backend/agent/runtime.py` 为了逐 token SSE，在 `stream_chat_langgraph()` 中手动按同一拓扑执行节点，而不是直接 `graph.astream()`。

## 节点职责

| 节点 | 文件 | 职责 |
| --- | --- | --- |
| `router_node` | `backend/agent/nodes.py` | 基于关键词判断 `rag/tool/web/chat`。 |
| `rag_search_node` | `backend/agent/nodes.py` | 优先 `MultimodalRetriever`，失败回退 TF-IDF。 |
| `tool_executor_node` | `backend/agent/nodes.py` | 调用 `get_time`、`get_system_status` 等 LangChain StructuredTool。 |
| `web_search_node` | `backend/agent/nodes.py` | 调用 Tavily web_search handler。 |
| `llm_answer_node` | `backend/agent/nodes.py` | 非流式图节点使用；流式路径直接调用 `stream_chat`。 |
| `finalizer_node` | `backend/agent/nodes.py` | 兜底回答、citations、feedback id 和记忆候选。 |

## 记忆流程

```text
phase 0: read thread/domain/skill memories
phase 1: route and gather context
phase 2: inject [系统记忆]
phase 3: stream LLM answer
phase 4: finalizer
phase 5: best-effort memory write
```

写入内容包括 user/assistant events、RAG events、memory_candidates 和 skill_run。

## SSE metadata

`done` 事件会携带：

| 字段 | 说明 |
| --- | --- |
| `graph_nodes` | 本轮执行节点序列。 |
| `citations` | RAG 引用。 |
| `rag_results` | 检索命中摘要。 |
| `runtime` | `langgraph` 或 legacy 元数据。 |
| `thread_id` | 前端持久化线程 id。 |
| `feedback_target_id` | 反馈锚点。 |

## 后续改进

| 方向 | 说明 |
| --- | --- |
| LLM router | 规则路由简单稳定，但复杂意图可加 LLM 分类。 |
| Skill subgraph | 频谱构建/决策可从独立 API 进一步接入 agent graph。 |
| 流式 Graph 原生化 | 如果 LangGraph streaming 足够稳定，可减少 runtime 手动编排。 |
| Tool coverage | `tool_executor_node` 当前只主动处理时间/系统状态，更多工具仍主要由 LLM tool loop 使用。 |
