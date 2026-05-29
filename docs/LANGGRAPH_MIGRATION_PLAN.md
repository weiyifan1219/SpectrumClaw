# LangGraph / LangChain 迁移计划

## 结论

SpectrumClaw 的智能体框架正式调整为 **LangGraph-first + LangChain-compatible** 路线。

| 决策 | 说明 |
| --- | --- |
| 编排核心 | 使用 LangGraph 管理 agent state、节点、条件边、工具循环、RAG 分支和记忆 checkpoint |
| 工具/RAG 接口 | 使用 LangChain Core 的 Tool / Retriever 抽象逐步统一 |
| 迁移方式 | 整体迁移方向确认，但分阶段落地，避免一次性推倒已验证功能 |
| 现有能力 | 保留当前 DeepSeek/OpenAI/Qwen/Anthropic 兼容层、SSE、7 个工具、TF-IDF 知识库 |
| 长期目标 | 逐步让业务 skill、RAG、memory、artifact、server runtime 都运行在 LangGraph agent runtime 上 |

## 为什么现在迁移

| 当前问题 | LangGraph / LangChain 价值 |
| --- | --- |
| Agent Loop 还停留在手写 tool loop | 用显式 StateGraph 表达 router、planner、tool、RAG、final answer |
| 后续 skill 越来越多 | 每个频谱能力可以作为 node 或 subgraph 接入 |
| 需要任务日志和执行轨迹 | graph event 可直接映射到前端任务日志 |
| 需要记忆与进化 | checkpoint、thread_id、store 适合作为记忆系统底座 |
| RAG 会从 TF-IDF 升级到 embedding / graph | LangChain retriever 接口便于替换底层实现 |
| 未来要接态势构建算法脚本 | situation building 可作为独立 subgraph，输入输出边界清晰 |

## 迁移原则

| 原则 | 要求 |
| --- | --- |
| 保留可用功能 | 不删除当前能工作的 `/api/chat`、`/api/chat/stream`、LLM provider 配置和工具 |
| LangGraph 管流程 | LangGraph 负责状态机、路由、节点和执行流，不直接吞掉 provider 细节 |
| LangChain 管接口 | LangChain Core 用于统一 Tool、Retriever、Document、Runnable 等接口 |
| 渐进替换 | 先把现有能力包成 node，再逐步替换底层实现 |
| 可回滚 | 保留 `legacy` runtime，新增 `langgraph` runtime 开关 |
| 先测试再切默认 | graph runtime 在测试和冒烟稳定后再设为默认 |

## 推荐运行时结构

```text
backend/
  agent/
    state.py              # SpectrumAgentState
    graph.py              # LangGraph StateGraph 定义
    nodes.py              # router / planner / rag / tool / llm / finalizer / memory
    runtime.py            # legacy/langgraph runtime 选择与执行入口
    events.py             # GraphEvent -> SSE event 转换

  tools/
    registry.py           # 现有 7 个工具的统一元数据和 handler
    langchain_tools.py    # registry -> LangChain StructuredTool
    executors.py          # 工具执行、错误包装、metadata

  rag/
    retriever.py          # 现有 TF-IDF 检索适配 LangChain retriever
    citations.py          # ITU 文档编号、URL、来源编号格式化

  memory/
    checkpoint.py         # LangGraph checkpoint adapter
    store.py              # 对话摘要、skill 运行记录、演化记录
```

## Agent State 草案

| 字段 | 说明 |
| --- | --- |
| `messages` | 对话历史，兼容 OpenAI/Anthropic 消息 |
| `user_intent` | 当前用户意图分类 |
| `selected_skill` | 用户显式选择或 agent 自动选择的 skill |
| `plan` | 当前任务步骤，可为空 |
| `tool_calls` | 本轮工具调用记录 |
| `rag_results` | 知识库检索结果和引用来源 |
| `artifacts` | 输出文件、报告、图片、JSON 等 |
| `logs` | 节点级运行日志 |
| `reasoning` | 可展示的思考摘要或 provider reasoning 内容 |
| `final_answer` | 最终返回给前端的回答 |
| `error` | 可恢复错误或失败原因 |

## Graph 节点设计

| 节点 | 职责 | 第一阶段实现 |
| --- | --- | --- |
| `router` | 判断普通对话、RAG、web、skill、系统查询 | 规则 + LLM 轻量判断 |
| `planner` | 对复杂任务生成步骤 | 第一版可只生成 metadata，不强制多步 |
| `rag_search` | 调用 ITU 知识库检索 | 包装现有 `backend.knowledge.retrieve.search` |
| `tool_executor` | 执行 web/time/weather/system 等工具 | 包装现有 7 个工具 |
| `llm_answer` | 调用模型生成最终回答 | 第一版继续调用现有 `backend/llm/client.py` |
| `artifact_writer` | 保存报告和结构化结果 | 第一版仅预留或写简单 markdown/json |
| `memory_writer` | 写入对话摘要和执行记录 | 第二阶段接入 |
| `finalizer` | 统一 citations、metadata、SSE done event | 第一阶段实现 |

## Runtime 开关

新增配置建议：

```bash
SPECTRUMCLAW_AGENT_RUNTIME=legacy     # 当前稳定路径
SPECTRUMCLAW_AGENT_RUNTIME=langgraph  # 新 LangGraph 路径
```

| 模式 | 行为 |
| --- | --- |
| `legacy` | 使用当前 `backend.llm.client.chat/stream_chat` |
| `langgraph` | 使用 `backend.agent.runtime` 驱动 LangGraph |

第一阶段建议默认仍为 `legacy`，本地测试通过后再切到 `langgraph`。

## 迁移阶段

| 阶段 | 目标 | 主要改动 | 验收标准 |
| --- | --- | --- | --- |
| Phase 0 | 建立迁移骨架 | 新增依赖、runtime 开关、agent 目录骨架 | 现有测试全部通过 |
| Phase 1 | 统一工具注册 | 从 `backend/llm/tools.py` 抽出 `backend/tools/registry.py` | 7 个工具仍可被模型调用 |
| Phase 2 | LangGraph 最小 Agent Loop | router -> tool/rag -> llm_answer -> finalizer | “现在几点？”和知识库查询均可走 graph |
| Phase 3 | SSE 事件迁移 | GraphEvent 映射为现有 `thinking/content/done/error` | 前端无需大改，流式体验保持 |
| Phase 4 | RAG retriever 化 | TF-IDF 检索包装成 LangChain retriever | 知识库问答带来源，Knowledge 页面可读统计 |
| Phase 5 | Memory checkpoint | 引入 checkpoint/thread_id/store | Memory 页面能展示真实摘要和执行轨迹 |
| Phase 6 | Skill subgraph | 频率规划、态势构建等作为 subgraph 接入 | 每个 skill 有独立输入输出和 artifact |
| Phase 7 | 深度 LangChain 化 | 根据稳定性逐步替换 model/tool/retriever 实现 | 保持 provider 兼容和离线部署可复现 |

## 依赖策略

| 依赖 | 建议 |
| --- | --- |
| `langgraph` | 必需，用于 StateGraph 和 checkpoint |
| `langchain-core` | 必需，用于 Tool、Document、Runnable 等基础抽象 |
| `langchain-community` | 谨慎引入，仅当需要成熟 loader/retriever 时使用 |
| `langchain-openai` | 可选，等 provider adapter 稳定后再评估 |

不要第一阶段直接把现有 DeepSeek provider 调用全部替换为 LangChain ChatModel。DeepSeek 的 `thinking`、`reasoning_content`、tool calling 格式已经踩过坑，应先保留当前 adapter。

## Claude Code 执行边界

| 可以做 | 暂时不要做 |
| --- | --- |
| 新增 `backend/agent/` LangGraph 骨架 | 不要删除当前 `backend/llm/client.py` |
| 新增 `backend/tools/` 并迁移工具定义 | 不要一次性重写所有工具实现 |
| 新增 runtime 开关 | 不要默认切到 LangGraph，先保留 legacy |
| 为 graph runtime 补测试 | 不要改动 `.env` 或输出 API key |
| 把 TF-IDF 包成 retriever | 不要立刻强制上 embedding/Qdrant |

## 第一批测试清单

| 测试 | 目标 |
| --- | --- |
| `test_graph_chat_plain` | 普通对话在 LangGraph runtime 下可返回 |
| `test_graph_get_time_tool` | “现在几点？”能通过 tool node 调用 `get_time` |
| `test_graph_kb_search` | 知识库查询能走 `rag_search` node 并返回 citations |
| `test_graph_runtime_fallback` | LangGraph 出错时可切回 legacy 或返回结构化 error |
| `test_stream_events_shape` | SSE 事件仍为 `thinking/content/done/error` |
| `test_provider_compatibility` | DeepSeek/OpenAI/Qwen/Anthropic 配置不被破坏 |

## 后续完全接入方向

| 阶段 | 完全接入目标 |
| --- | --- |
| 工具 | 所有工具都从 LangChain Tool schema 生成 provider-specific schema |
| RAG | TF-IDF、embedding、graph retrieval 都实现统一 retriever 接口 |
| Skill | 每个频谱 skill 都是 LangGraph subgraph |
| 记忆 | checkpoint + memory store 成为默认上下文来源 |
| 任务日志 | 前端日志完全来自 graph events |
| 部署 | 服务器 runtime 只启动统一 agent graph service |

## 当前结论

SpectrumClaw 应当向 LangGraph / LangChain 体系整体迁移，但第一阶段必须保护已验证的 LLM provider、SSE、工具和 RAG 链路。推荐先新增 graph runtime，与 legacy runtime 并行；当 graph runtime 覆盖普通对话、工具调用、知识库检索、流式输出后，再切为默认路径。
