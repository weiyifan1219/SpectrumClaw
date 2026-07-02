# SpectrumClaw 项目状态与路线

本文是当前项目状态快照，不再作为早期 MVP 规划文档使用。

## 当前定位

SpectrumClaw 是面向电磁频谱工程任务的 AI 智能体工作台。系统以 Console 对话为入口，结合本地 ITU 知识库 RAG、LangGraph 风格运行时、频谱构建模型适配、频谱资源分配优化和记忆进化机制，形成可运行、可审查、可扩展的任务平台。

## 已落地能力

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Console 对话 | 可用 | SSE 流式、模型选择、thinking、工具/RAG、日志、artifacts 和反馈。 |
| Agent runtime | 可用 | `legacy/langgraph` 双路径；langgraph 负责路由、上下文聚合、记忆注入和写回。 |
| RAG 知识库 | 可用 | MinerU 3.3.0 解析 4,656 个 PDF，Chroma 1.4M vectors，图谱 9K entities。 |
| 频率规划 | 可用 | 专用 RAG profile，脚注/相邻频段多跳检索，带引用回答。 |
| 频谱构建 | 可用 | Gudmundson 物理预览、可选 GenSpectra 重建、UAV REM 结果读取。 |
| 频谱决策 | 可用 | 多业务 CQI-Shannon + SLSQP 比例公平优化，LLM agent 可解析自然语言。 |
| Memory & Evolution | 可用 | SQLite 记录 threads/events/items/skill_runs/feedback/reports。 |
| System artifacts | 可用 | 后端可列出日志、输出产物并提供预览/下载。 |

## 当前代码目录

| 目录 | 说明 |
| --- | --- |
| `frontend/` | React + Vite 工作台。 |
| `backend/api/` | FastAPI 路由。 |
| `backend/agent/` | Console agent runtime。 |
| `backend/llm/` | 多 provider LLM client 和工具循环。 |
| `backend/rag/` | 解析、检索、图谱、重排、问答链。 |
| `backend/skills/` | 频率规划、频谱构建、频谱决策等领域能力。 |
| `backend/memory/` | SQLite 记忆系统。 |
| `scripts/` | 启动、链路、部署、解析和入库脚本。 |
| `data/` | 知识库、parsed、Chroma、graph、memory、eval 数据。 |

## 近期优先级

| 优先级 | 事项 | 原因 |
| --- | --- | --- |
| P0 | 修复 GitHub 推送凭据 | 当前 HTTPS/SSH 都无 GitHub 认证，无法从本环境 push。 |
| P0 | 稳定 LLM/代理/SSH 链路 | RAG answer、Judge、agent 解析和解释都依赖可用 provider。 |
| P1 | SystemPage 动态化 | 前端 System 仍有部分 mockData，应该接 `/api/system/*`。 |
| P1 | RAG 增量入库去重 | `ingest_parsed.py` 补入库场景仍需更强 block_id 去重。 |
| P1 | 频率规划结构化 API | 当前主路径是流式 RAG；可增加专用 JSON schema 输出。 |
| P2 | VLM 图表/图片描述补录 | 现有 image/chart blocks 仍可进一步多模态增强。 |
| P2 | 干扰分析/调制识别真实模型 | 两个 skill 目录仍为预留模块。 |

## 风险与边界

| 风险 | 当前处理 |
| --- | --- |
| 大型数据体积 | 原始 PDF、parsed、Chroma、graph 不应无策略提交到源码仓库。 |
| 外部模型依赖 | GenSpectra、UAV REM 通过路径配置和降级状态隔离。 |
| LLM 不稳定 | API 层返回明确错误，Memory 写入 best-effort。 |
| 文档漂移 | README/docs 需要随实现变化同步，尤其是旧“占位/后续规划”措辞。 |

## 验收命令

```bash
npm --prefix frontend run build
python -m py_compile backend/app.py backend/api/*.py backend/llm/client.py
pytest tests/test_chat_api.py tests/test_agent_runtime.py tests/test_memory_store.py -q
```
