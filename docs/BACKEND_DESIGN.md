# 后端服务规划

## 当前边界

当前阶段不实现后端业务逻辑。后端目录只保留结构、接口规划和后续实现边界。

## 服务职责

| 模块 | 职责 |
| --- | --- |
| API | 提供 chat、task、skill、knowledge、memory、system 状态接口 |
| Agent Core | 理解用户意图、选择 skill、组织上下文、调用 LLM |
| Skill Runtime | 执行频谱任务、管理输入输出、记录日志 |
| Artifact Manager | 管理 Markdown、JSON、图表、模型输出等结果文件 |
| Runtime Monitor | 汇总依赖、路径、服务和服务器环境状态 |

## API 规划

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康 |
| `POST` | `/api/chat` | 对话入口 |
| `POST` | `/api/tasks` | 创建频谱任务 |
| `GET` | `/api/tasks/{id}` | 查询任务状态 |
| `GET` | `/api/tasks/{id}/logs` | 查询任务日志 |
| `GET` | `/api/artifacts` | 查询结果文件 |
| `GET` | `/api/skills` | 查询 skill registry |
| `POST` | `/api/knowledge/search` | RAG 检索 |
| `GET` | `/api/system/runtime` | 系统运行状态 |

## LLM API 接入

| 层 | 设计 |
| --- | --- |
| Client | `backend/llm/client.py` 后续统一封装 |
| Provider | 默认 OpenAI-compatible API |
| Config | `.env` + `config/llm.yaml` |
| Output | 优先要求 JSON schema 或结构化 Markdown |
| Local Model | 只保留接口，不实现本地模型部署 |

## 任务执行方式

第一版可以直接同步执行轻量任务；RAG 索引、态势构建和模型推理等长任务后续改为异步任务。

```text
API request -> Task Manager -> Skill Runtime -> logs/artifacts -> API response
```

## Claude Code 后续实现边界

后端具体实现由 Claude Code MCP 执行，但 Codex 需要先确认：

| 项目 | 需要 Codex 把关 |
| --- | --- |
| API schema | 是 |
| LLM client 抽象 | 是 |
| Skill registry 接口 | 是 |
| RAG 检索结果格式 | 是 |
| 部署脚本 | 是 |
| 普通 CRUD 和日志接口 | 可由 Claude Code 直接实现后再摘要验收 |
