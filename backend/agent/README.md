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

## 无人机任务智能体边界

无人机任务智能体位于 `backend/agents/uav_operations/`，与 Console 通用对话运行时分离。它只把自然语言编译成受限 `MissionPlan`，经过策略检查和人工批准后，才由 `UavMissionService` 驱动 PX4/Gazebo 仿真。

| 入口 | 调用方式 | 约束 |
| --- | --- | --- |
| 网页任务工作区 | 内置 Tool / HTTP API | 草案与批准分离；人工 WASD 可随时接管 |
| 外部 Agent | `backend.mcp.uav_server` | 默认本地 `stdio`；与内置 Tool 共用同一计划契约和策略 |

子智能体只能在每任务沙箱中产出已审阅的 JSON/Markdown 工件，不能调用 Shell、网络、原始 MAVLink 或任意速度接口。任务事件含 `run_id`、`trace_id`，并且必须以成功、失败、取消、中断或拒绝之一结束；详细操作流程见 `docs/uav-simulation/UAV_AGENT_OPERATIONS.md`。
