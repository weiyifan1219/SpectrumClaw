# Runtime

历史占位目录。当前运行时实现主要位于：

| 路径 | 说明 |
| --- | --- |
| `backend/agent/runtime.py` | Chat runtime 选择和流式编排。 |
| `backend/api/system.py` | 日志、artifacts 和运行文件预览。 |
| `backend/memory/` | 运行记忆和 skill 审计。 |

后续如需要独立任务队列、后台 job 状态机或 artifact indexer，可在此目录扩展。
