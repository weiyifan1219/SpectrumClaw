# Backend

当前阶段后端只保留结构和设计边界，不实现真实业务逻辑。

后续由 Claude Code MCP 在 Codex 确认接口后实现：

| 模块 | 目录 |
| --- | --- |
| API 服务 | `backend/api/` |
| Agent 核心 | `backend/agent/` |
| Skill 调度 | `backend/skills/` |
| LLM API client | `backend/llm/` |
| 运行时工具 | `backend/runtime/` |

第一阶段后端优先级：

1. `/health`
2. `/api/chat`
3. `/api/skills`
4. `/api/knowledge/search`
5. `/api/tasks`
