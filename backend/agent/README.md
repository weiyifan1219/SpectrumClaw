# Agent Runtime

`backend/agent/` 负责 Console 对话的运行时编排。

## 文件

| 文件 | 说明 |
| --- | --- |
| `runtime.py` | 运行时选择；`legacy` 直接调 LLM，`langgraph` 执行路由、上下文聚合、流式回答和记忆写入。 |
| `graph.py` | LangGraph StateGraph 拓扑定义。 |
| `nodes.py` | router、RAG、tool、web、LLM、finalizer 节点实现。 |
| `state.py` | `AgentState` TypedDict。 |
| `events.py` | SSE 事件构造。 |

## Runtime

| 模式 | 配置 | 行为 |
| --- | --- | --- |
| legacy | `SPECTRUMCLAW_AGENT_RUNTIME=legacy` | 仅调用 `backend.llm.client.stream_chat`。 |
| langgraph | `SPECTRUMCLAW_AGENT_RUNTIME=langgraph` | 关键词路由到 `rag/tool/web/chat`，注入记忆与检索上下文后流式回答。 |

## langgraph 数据流

```text
messages
  -> read memory
  -> router_node
  -> rag_search_node / tool_executor_node / web_search_node
  -> stream_chat
  -> finalizer_node
  -> best-effort memory write
```

`done` 事件会携带 `graph_nodes`、`citations`、`rag_results`、`runtime`、`thread_id` 和 `feedback_target_id`。
