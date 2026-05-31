# Memory & Evolution 系统规划

## 1. 定位和当前结论

SpectrumClaw 的 RAG MVP-1 已经具备可用的频谱知识库检索、引用和多模态/图谱化扩展基础。MVP-4 的目标不是再做一个知识库，而是把 **Agent 对话、RAG 检索结果、skill 执行轨迹、用户反馈和失败复盘** 沉淀成可检索、可审计、可用于下一轮推理的记忆系统。

| 项 | 结论 |
| --- | --- |
| 当前优先级 | 先做本地可用的 Memory MVP，再考虑复杂外部框架 |
| 推荐主线 | `LangGraph checkpoint + 本地 SQLite memory store + 后台总结器 + 前端 Memory 页面` |
| 不推荐当前做 | 不直接引入 Mem0/Zep/Letta 全量平台，不上云，不接服务器部署，不写真实态势构建业务记忆 |
| 与 RAG 的关系 | RAG 负责“领域文档证据”，Memory 负责“系统经历、用户反馈、任务偏好和可复盘执行轨迹” |
| 与 Evolution 的关系 | Evolution 是基于 memory 的二次加工：统计、反思、skill 参数建议、版本摘要 |

## 2. 主流方案调研摘要

| 方案 | 可借鉴点 | 当前取舍 |
| --- | --- | --- |
| LangGraph memory | 官方推荐把短期记忆放入 graph state/checkpointer，长期记忆放入 store；store 以 namespace/key 存 JSON 文档，节点可通过 runtime.store 读取和写入。 | SpectrumClaw 已有 LangGraph runtime，应优先沿这条路线做最小闭环。 |
| LangMem | 在 LangGraph store 上提供 memory manager、memory search/manage tools、后台抽取和 prompt 优化能力。 | 可作为 Phase 3 可选依赖；MVP 先实现轻量本地 manager，避免 API 和依赖膨胀。 |
| Mem0 | 强调 user/session/agent 多层记忆、ADD-only 抽取、实体链接、semantic + BM25 + entity 融合检索、时间感知检索。 | 借鉴算法形态，不直接依赖服务；后续可做 `MemoryProvider` 适配。 |
| Zep / Graphiti | temporal context graph，保留事实有效期、provenance、增量图更新和语义 + 关键词 + 图遍历混合检索。 | 与 SpectrumClaw 后续知识图谱方向一致；MVP 不上 Neo4j/FalkorDB，Phase 4 再评估。 |
| Letta / MemGPT | 核心记忆、档案记忆、回忆记忆三层模型，agent 主动管理自己的记忆。 | 不切换 agent runtime；只借鉴“三层记忆”和可审计 memory 操作思想。 |

**当前判断：** 不需要为了 MVP-4 clone 并迁移外部 repo。外部 repo 的价值主要在模式参考；直接迁移会引入新的运行时、数据库、认证和部署复杂度，和当前“本地优先、服务器后置”的边界冲突。

## 3. 设计目标

| 目标 | 验收标准 |
| --- | --- |
| 让对话可跨轮次复用 | 同一个 `thread_id` 下，Agent 能读取最近对话摘要和关键事实。 |
| 让 RAG 结果可沉淀 | 每次知识库检索的 query、top sources、引用、最终答案摘要可进入 episodic memory。 |
| 让 skill 执行可复盘 | skill 名称、输入、输出摘要、成功/失败、耗时、错误原因可查询。 |
| 让 Memory 页面显示真实数据 | 前端不再只读 mockData，可显示层级统计、最近记忆、反思队列和 skill 统计。 |
| 让进化可控 | 只生成“建议”和“摘要”，不自动改 prompt、参数或代码；需要用户/开发者确认后才应用。 |
| 让实现可回滚 | 通过配置开关启停 memory，不破坏现有 chat/RAG/SSE 链路。 |

## 4. 非目标

| 非目标 | 原因 |
| --- | --- |
| 不把 ITU 文档全文塞进 memory | 领域资料仍归 RAG/knowledge base 管理，避免重复存储和检索污染。 |
| 不把所有消息原文永久注入 prompt | 成本高，且容易被旧上下文干扰；只注入摘要和检索命中的短片段。 |
| 不自动改写 skill 代码或系统 prompt | MVP-4 先做可审计建议，Evolution 不直接执行自修改。 |
| 不接外部 SaaS memory | 当前服务器离线部署约束明显，本地方案更可控。 |
| 不做多用户权限系统 | 先按 local single-user / default workspace 设计，保留 user_id 字段即可。 |

## 5. 记忆分层

| 层 | 范围 | 存什么 | 检索方式 | 进入 prompt 方式 |
| --- | --- | --- | --- | --- |
| Working Memory | 单次请求和当前 thread | 当前用户问题、路由意图、选中 skill、RAG 上下文、临时参数 | 直接在 `AgentState` 中传递 | 当前请求内直接使用 |
| Short-term / Thread Memory | 单个 `thread_id` | 最近 N 轮消息、滚动摘要、未完成任务状态 | LangGraph checkpoint 或 SQLite thread state | 注入“本轮会话摘要” |
| Episodic Memory | 跨 thread 的任务经历 | RAG 查询、skill run、最终答案摘要、引用、错误、反馈 | SQLite 结构化过滤 + FTS/BM25 | 命中后注入 3-5 条 |
| Skill Memory | 跨 thread 的能力经验 | skill 成功率、常用参数、失败模式、用户修正 | 按 skill_name 聚合 | 作为 planner/router 提示 |
| Domain Memory | 领域操作性知识 | 用户确认过的频谱规则解释、术语映射、项目决策 | 先结构化过滤，后续可接向量/图 | 只注入高置信条目 |
| Evolution Memory | 系统自我总结 | 周期总结、版本摘要、改进建议、待确认项 | 按状态/时间查询 | 默认不进 prompt，仅展示和审查 |

## 6. 数据目录和文件边界

建议所有本地记忆落在项目数据目录，避免混入 `docs/` 或源码。

| 路径 | 类型 | 用途 |
| --- | --- | --- |
| `data/memory/spectrum_memory.sqlite3` | SQLite | MVP 主存储，保存 threads、events、memories、feedback、summaries。 |
| `data/memory/exports/` | JSONL/Markdown | 人工导出、审计和备份。 |
| `data/memory/reflections/` | Markdown/JSON | 周期反思和 evolution 版本摘要。 |
| `logs/agent_events/` | JSONL | 可选运行事件流，保留更细粒度调试证据。 |

`config/paths.yaml` 后续建议增加：

```yaml
memory_db: data/memory/spectrum_memory.sqlite3
memory_exports: data/memory/exports
memory_reflections: data/memory/reflections
```

`config/app.yaml` 或环境变量后续建议增加：

```yaml
memory:
  enabled: true
  write_mode: background
  inject_top_k: 5
  summarize_every_turns: 6
  require_user_confirmation_for_procedural: true
```

## 7. 最小数据模型

### 7.1 SQLite 表

| 表 | 主字段 | 说明 |
| --- | --- | --- |
| `memory_threads` | `thread_id`, `title`, `created_at`, `updated_at`, `summary`, `turn_count` | 会话级状态和滚动摘要。 |
| `memory_events` | `event_id`, `thread_id`, `event_type`, `role`, `content`, `metadata_json`, `created_at` | 原始事件日志：user/assistant/tool/rag/error/feedback。 |
| `memory_items` | `memory_id`, `scope`, `kind`, `text`, `summary`, `confidence`, `source_event_id`, `thread_id`, `skill_name`, `tags_json`, `valid_from`, `valid_to`, `created_at`, `updated_at` | 可检索长期记忆，尽量保持事实粒度。 |
| `skill_runs` | `run_id`, `thread_id`, `skill_name`, `input_json`, `output_summary`, `status`, `latency_ms`, `error`, `rag_refs_json`, `created_at` | skill 执行轨迹和统计来源。 |
| `memory_feedback` | `feedback_id`, `target_type`, `target_id`, `rating`, `comment`, `created_at` | 用户反馈、开发者标注和纠错。 |
| `evolution_reports` | `report_id`, `period`, `summary`, `metrics_json`, `suggestions_json`, `status`, `created_at` | 系统反思报告和待确认建议。 |

### 7.2 统一 Memory Item JSON

```json
{
  "memory_id": "mem_20260530_000001",
  "scope": "workspace",
  "kind": "episodic",
  "text": "用户询问 Region 3 中 2.4 GHz 频段共用条件，系统使用 RAG 返回 ITU 引用并建议优先检查干扰约束。",
  "summary": "Region 3 / 2.4 GHz 频段规划问答记录",
  "confidence": 0.82,
  "source_event_id": "evt_20260530_000003",
  "thread_id": "thread_default",
  "skill_name": "frequency_planning",
  "tags": ["rag", "frequency_planning", "itu", "region_3"],
  "valid_from": "2026-05-30T00:00:00+08:00",
  "valid_to": null
}
```

## 8. Agent 运行链路

### 8.1 请求链路

| 步骤 | 节点/模块 | 动作 |
| --- | --- | --- |
| 1 | `backend/api/chat.py` | 接收 `messages`，补充/生成 `thread_id`，传给 runtime。 |
| 2 | `memory_reader` | 基于最后一条用户消息检索 thread summary、skill memory、episodic memory。 |
| 3 | `router` | 在现有规则路由基础上读取 memory hints，但 memory 不应覆盖明确用户意图。 |
| 4 | `rag_search` / `tool_executor` / `web_search` | 执行现有能力，并把关键结果写入 state 的 `memory_candidates`。 |
| 5 | `llm_answer` | 使用 RAG context + 命中 memory 生成回答。 |
| 6 | `finalizer` | 生成 answer metadata、sources、skill stats。 |
| 7 | `memory_writer` | 后台写入 event、memory item、skill_run、thread summary。失败只记录日志，不影响用户回答。 |

### 8.2 建议新增 state 字段

| 字段 | 类型 | 来源 | 用途 |
| --- | --- | --- | --- |
| `thread_id` | `str` | API 或前端生成 | checkpoint、thread summary、events 归档。 |
| `user_id` | `str` | 默认 `local_user` | 未来多用户隔离。 |
| `memory_hits` | `list[dict]` | `memory_reader` | 注入 LLM 的检索记忆。 |
| `memory_candidates` | `list[dict]` | RAG/tool/finalizer | 本轮可能写入的记忆候选。 |
| `skill_run` | `dict | None` | skill/tool 节点 | 统计和复盘。 |
| `feedback_target_id` | `str | None` | finalizer | 前端反馈绑定目标。 |

## 9. API 规划

| 方法 | 路径 | 用途 | MVP 是否需要 |
| --- | --- | --- | --- |
| `GET` | `/api/memory/overview` | Memory 页面总览：条目数、层级统计、最近更新时间、队列状态。 | 是 |
| `GET` | `/api/memory/items` | 按 `kind/thread_id/skill_name/tag/q` 查询记忆条目。 | 是 |
| `GET` | `/api/memory/threads/{thread_id}` | 查看某个会话摘要和事件流。 | 是 |
| `POST` | `/api/memory/feedback` | 用户对答案、RAG 结果或 memory item 进行标注。 | 是 |
| `POST` | `/api/memory/reflect` | 手动触发反思总结，默认只生成报告。 | 可选 |
| `POST` | `/api/memory/export` | 导出 JSONL/Markdown。 | 可选 |
| `DELETE` | `/api/memory/items/{memory_id}` | 删除或失效错误记忆。 | Phase 2 |

## 10. 前端页面规划

| 区域 | 当前状态 | MVP-4 改造 |
| --- | --- | --- |
| 顶部指标 | mockData | 接 `/api/memory/overview`，展示 working/thread/episodic/skill/domain 数量。 |
| 记忆列表 | 无 | 新增可筛选列表：类型、标签、来源 thread、置信度、时间。 |
| 进化日志 | mockData | 接 `evolution_reports`，显示报告摘要和建议状态。 |
| 反思队列 | 静态说明 | 展示待确认建议：参数调整、prompt 建议、失败模式。 |
| Console 反馈 | 无 | 在 assistant 消息旁加轻量反馈入口，写入 `/api/memory/feedback`。 |

## 11. Evolution 规则

| 类别 | 输入 | 产出 | 是否自动应用 |
| --- | --- | --- | --- |
| 任务复盘 | `memory_events`, `skill_runs`, `rag_refs` | 单次任务摘要、失败原因、可复用经验 | 自动写摘要，不改系统 |
| Skill 统计 | `skill_runs` | 成功率、平均耗时、常见失败、常用 query 类型 | 自动统计 |
| RAG 质量 | RAG 命中、引用、用户反馈 | 低分 query、缺失资料、检索参数建议 | 只生成建议 |
| Prompt/策略进化 | 用户纠错、失败复盘 | procedural memory 候选 | 必须人工确认 |
| 版本摘要 | 周期报告 | `evolution_reports` | 自动生成，人工采纳 |

## 12. 实施阶段

| 阶段 | 目标 | 主要改动 | 验收 |
| --- | --- | --- | --- |
| Phase 0 | 文档和开关 | 完成本文件；增加 memory 配置规划。 | Claude Code 能按文档拆任务。 |
| Phase 1 | 本地存储 MVP | 新增 `backend/memory/`、SQLite schema、Repository、service；不接 LLM 总结。 | 单元测试能创建 thread/event/item/skill_run 并查询。 |
| Phase 2 | 接入 Agent runtime | API 传递 `thread_id`；新增 `memory_reader` / `memory_writer`；RAG/tool/finalizer 写候选。 | 对话后数据库出现 event 和 episodic memory；关闭 memory 不影响 chat。 |
| Phase 3 | 摘要和反思 | 新增 thread rolling summary、skill statistics、manual reflect endpoint。 | Memory 页面展示真实摘要、skill 统计和反思报告。 |
| Phase 4 | 检索增强 | SQLite FTS5/BM25；可选接现有 embedding provider；对 memory item 做多信号排序。 | `q=频率规划` 能检索相关历史任务。 |
| Phase 5 | 图谱化/外部适配 | 评估 Graphiti、Mem0 或自研 temporal graph；抽象 `MemoryProvider`。 | 不改上层 API 即可替换底层 provider。 |

## 13. Claude Code 实现任务拆分

| 任务 | 文件 | 要求 |
| --- | --- | --- |
| 1. 建立 memory 包 | `backend/memory/__init__.py`, `backend/memory/models.py`, `backend/memory/store.py`, `backend/memory/service.py` | 只用标准库 `sqlite3` + `pydantic`，先不加外部依赖。 |
| 2. 增加配置 | `backend/config.py`, `config/paths.yaml`, `.env.example` | 支持 `SPECTRUMCLAW_MEMORY_ENABLED` 和 memory db path。 |
| 3. 写存储测试 | `tests/test_memory_store.py` | 覆盖 init schema、insert event、insert item、query by kind/tag/thread。 |
| 4. 接 chat thread_id | `backend/api/chat.py`, `frontend/src/lib/api.js`, `frontend/src/pages/ConsolePage.jsx` | API payload 支持 `thread_id`；前端本地保存当前 thread id。 |
| 5. 接 runtime state | `backend/agent/state.py`, `backend/agent/runtime.py`, `backend/agent/nodes.py` | 读取 memory hits，写入 event/item/skill_run；writer 失败不阻断 SSE。 |
| 6. 增加 memory API | `backend/api/memory.py`, `backend/app.py` | 提供 overview/items/thread/feedback。 |
| 7. 改前端 Memory 页面 | `frontend/src/pages/MemoryPage.jsx`, `frontend/src/lib/api.js`, `frontend/src/styles/app.css` | 从 API 读真实数据，失败时显示空状态而非 mock。 |
| 8. 增加集成测试 | `tests/test_chat_api.py`, `tests/test_agent_runtime.py`, `tests/test_memory_api.py` | 覆盖 memory enabled/disabled、RAG 后写入、API 查询。 |

## 14. 测试和验收命令

| 验收项 | 命令 | 期望 |
| --- | --- | --- |
| Python 单测 | `pytest tests/test_memory_store.py tests/test_memory_api.py -q` | 全部通过。 |
| Agent 回归 | `pytest tests/test_agent_runtime.py tests/test_chat_api.py -q` | 现有 chat/RAG/SSE 行为不回退。 |
| RAG 回归 | `pytest tests/test_rag_pipeline.py -q` | RAG pipeline 不受 memory 改动影响。 |
| 前端构建 | `cd frontend && npm run build` | 构建通过。 |
| 手动冒烟 | 启动后端和前端，完成一次 RAG 对话，再打开 Memory 页面 | 能看到真实 thread/event/item 记录。 |

## 15. 风险和约束

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| 记忆污染 | 错误事实被反复注入回答 | 每条 memory 带 `confidence/source_event_id/tags`，低置信不自动注入；支持失效。 |
| prompt 变长 | 响应变慢、成本上升 | 注入 top-k 短摘要，不注入原始全文。 |
| RAG 和 memory 混淆 | 文档事实与历史经验互相污染 | Domain 文档仍走 RAG；Memory 只存任务经历和用户确认事实。 |
| SQLite 并发 | 多请求写入冲突 | MVP 本地低并发可接受；写入使用短事务，后续服务器可迁移 Postgres。 |
| 服务器离线 | 外部依赖不可安装 | MVP 不新增重型依赖；LangMem/Mem0/Graphiti 只作为后续适配。 |
| 自进化失控 | 自动改 prompt/参数导致不可解释 | Evolution 只生成建议，人工确认后再改配置。 |

## 16. 后续可选迁移路线

| 路线 | 触发条件 | 迁移方式 |
| --- | --- | --- |
| LangMem | 需要更强的后台抽取、procedural memory 和 memory tools | 在 `backend/memory/provider.py` 下增加 `LangMemProvider`，保留现有 API。 |
| Mem0 | 需要跨应用、跨 agent 的通用 memory service | 增加 `Mem0Provider`，只把已确认 memory item 同步出去。 |
| Graphiti/Zep | 需要 temporal graph、事实有效期和关系推理 | 将 `memory_items`/`memory_events` 作为 episodes，同步到 Graphiti。 |
| Postgres/pgvector | 服务器部署后需要更强并发和向量检索 | SQLite schema 映射到 Postgres，保持 Repository 接口不变。 |

## 17. 参考资料

| 资料 | 用途 |
| --- | --- |
| [LangGraph Memory](https://docs.langchain.com/oss/python/langgraph/add-memory) | 短期 checkpointer、长期 store、Runtime 注入模式。 |
| [LangChain Short-term Memory](https://docs.langchain.com/oss/python/langchain/short-term-memory) | thread 级对话状态、消息裁剪和总结动机。 |
| [LangChain Long-term Memory](https://docs.langchain.com/oss/python/langchain/long-term-memory) | namespace/key JSON store、跨 thread 长期记忆。 |
| [LangMem](https://langchain-ai.github.io/langmem/) | memory manager、hot path/background memory、LangGraph store 集成。 |
| [mem0](https://github.com/mem0ai/mem0) | ADD-only 抽取、多信号检索、实体链接和时间感知检索。 |
| [Graphiti](https://github.com/getzep/graphiti) | temporal context graph、provenance、语义 + 关键词 + 图遍历。 |
| [Letta](https://github.com/letta-ai/letta) | memory-native/stateful agent 的层级记忆思想。 |
