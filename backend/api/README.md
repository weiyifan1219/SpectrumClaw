# API Layer

FastAPI router 集中在 `backend/api/`，由 `backend/app.py` 统一挂载。

| 文件 | Prefix/端点 | 说明 |
| --- | --- | --- |
| `chat.py` | `/api/chat`, `/api/chat/stream`, `/api/kb/stats` | Console 对话、SSE 和知识库统计。 |
| `rag.py` | `/api/rag/*` | 上传、索引、问答、流式问答、频率规划、文档/PDF、图谱、状态。 |
| `memory.py` | `/api/memory/*` | 记忆概览、条目、线程、事件、反馈、反思、skill runs。 |
| `system.py` | `/api/system/*` | 日志、artifacts、预览和下载。 |
| `spectrum_construction.py` | `/api/spectrum-construction/*` | Gudmundson/GenSpectra 生成和 UAV REM 概览。 |
| `spectrum_decision.py` | `/api/spectrum-decision/*` | 资源分配与智能体流式分配。 |
| `eval_endpoints.py` | `/api/eval/*` | RAG 评测端点。 |

新增 router 后必须在 `backend/app.py` 中 `include_router()`。
