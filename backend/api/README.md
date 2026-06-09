# API Layer

FastAPI API 层当前包含可运行接口。

| 文件 | 端点 | 状态 |
| --- | --- | --- |
| `chat.py` | `/api/chat`, `/api/chat/stream`, `/api/kb/stats` | Console 对话、SSE 和旧 KB 统计。 |
| `memory.py` | `/api/memory/*` | Memory overview、items、threads、feedback、skill-runs、reports。 |
| `rag.py` | `/api/rag/*` | 新 RAG upload/index/query/status；索引流程仍在推进。 |
| `spectrum_construction.py` | `/api/spectrum-construction/*` | Gudmundson + GenSpectra + UAV REM。 |
| `spectrum_decision.py` | `/api/spectrum-decision/allocate` | 多用户资源分配优化器。 |

后端入口在 `backend/app.py`，新增 API 后需要在那里注册 router。
