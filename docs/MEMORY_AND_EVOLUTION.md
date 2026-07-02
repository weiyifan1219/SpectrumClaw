# Memory & Evolution

Memory 系统已经落地为 SQLite 存储和 API，不再只是页面规划。目标是把对话、RAG、技能调用、反馈和反思报告沉淀为可审计、可注入下一轮推理的经验。

## 当前实现

| 层 | 文件 | 说明 |
| --- | --- | --- |
| Store | `backend/memory/store.py` | sqlite3 + WAL，创建和读写所有表。 |
| Models | `backend/memory/models.py` | Pydantic/dataclass 数据结构。 |
| Service | `backend/memory/service.py` | 高层读写接口，失败时返回空/None，不抛出阻塞主流程。 |
| Hooks | `backend/memory/hooks.py` | `track_skill_run()` 审计 skill 调用。 |
| Reflector | `backend/memory/reflector.py` | 聚合近期数据并生成 evolution report。 |
| API | `backend/api/memory.py` | 前端 Memory 页面使用的 HTTP 接口。 |
| Frontend | `frontend/src/pages/MemoryPage.jsx` | 概览、条目、报告和 skill stats 展示，带缓存与后台刷新。 |

## SQLite 表

| 表 | 内容 |
| --- | --- |
| `memory_threads` | 会话线程、标题、摘要、turn_count。 |
| `memory_events` | user/assistant/rag/system 事件。 |
| `memory_items` | episodic/domain/skill/evolution 等可检索记忆条目。 |
| `skill_runs` | skill 调用输入、输出摘要、状态、耗时、错误和引用。 |
| `memory_feedback` | 前端赞/踩/评论。 |
| `evolution_reports` | 反思报告、指标和建议。 |

## Agent 读写流程

```text
stream_chat_langgraph
  -> read thread-scoped memories
  -> read cross-thread domain/skill memories
  -> inject [系统记忆] system message
  -> run route/RAG/tool/web/LLM
  -> finalizer creates memory candidates
  -> _write_memory best-effort
```

写入失败会被捕获，不影响用户回答。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/memory/overview` | 记忆系统总览和 skill stats。 |
| `GET` | `/api/memory/items` | 记忆条目查询，支持 kind/tag/thread 等过滤。 |
| `GET` | `/api/memory/threads` | 会话线程列表。 |
| `GET` | `/api/memory/threads/{thread_id}/events` | 单线程事件。 |
| `POST` | `/api/memory/feedback` | 前端回答反馈。 |
| `POST` | `/api/memory/reflect` | 触发反思报告。 |
| `GET` | `/api/memory/reports` | evolution reports。 |
| `GET` | `/api/memory/skill-runs` | skill run 审计记录。 |

## 记忆类型

| kind | 用途 |
| --- | --- |
| `episodic` | 对话、RAG 查询、最终回答摘要等事件经验。 |
| `skill` | 工具/技能调用摘要、成功/失败信息。 |
| `domain` | 可跨会话复用的领域知识或项目决策。 |
| `evolution` | 反思报告和改进建议。 |

## 前端行为

`MemoryPage.jsx` 使用模块级缓存 `memCache`，避免切页后重新加载时闪空；同时每 30 秒 silent refresh，保持数据新鲜但不打断阅读。

## 后续增强

| 方向 | 说明 |
| --- | --- |
| 更强检索 | SQLite FTS5/BM25 或 embedding 排序。 |
| 自动摘要 | 长线程自动压缩为 thread summary。 |
| 建议闭环 | evolution suggestions 变成可确认/忽略/执行的任务。 |
| 去重与过期 | memory item 相似去重、valid_to 和置信度衰减。 |
