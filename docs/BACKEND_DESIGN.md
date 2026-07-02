# 后端服务说明

后端已经是可运行服务，不再是占位规划。入口为 `backend/app.py`，应用创建函数为 `create_app()`。

## 服务组成

| 模块 | 文件/目录 | 当前职责 |
| --- | --- | --- |
| FastAPI App | `backend/app.py` | 关闭 LangSmith/匿名遥测，注册所有 router，启动时预热 embedding retriever。 |
| Chat API | `backend/api/chat.py` | `/api/chat` 非流式、`/api/chat/stream` SSE、`/api/kb/stats` 统计。 |
| RAG API | `backend/api/rag.py` | PDF 上传、索引、普通问答、流式问答、频率规划流、文档列表/PDF 预览、图谱查询、状态。 |
| Memory API | `backend/api/memory.py` | overview/items/threads/events/feedback/reflect/skill-runs/reports。 |
| System API | `backend/api/system.py` | 运行日志、artifacts 列表、预览和下载。 |
| Spectrum Construction API | `backend/api/spectrum_construction.py` | Gudmundson/GenSpectra 生成与 UAV REM 产物概览。 |
| Spectrum Decision API | `backend/api/spectrum_decision.py` | 手动/智能体资源分配，支持流式 agent 模式。 |
| Eval API | `backend/api/eval_endpoints.py` | RAG 评测相关端点。 |

## 主要 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康和 LLM provider 配置状态。 |
| `POST` | `/api/chat` | 非流式 LLM 对话。 |
| `POST` | `/api/chat/stream` | Console 使用的 SSE 对话入口。 |
| `GET` | `/api/kb/stats` | 知识库、Chroma 和 graph 统计。 |
| `POST` | `/api/rag/upload` | 上传 PDF 并解析。 |
| `POST` | `/api/rag/index` | 对上传目录或指定路径构建索引。 |
| `POST` | `/api/rag/query` | RAG 问答，返回 answer/citations/retrieved_blocks/debug。 |
| `POST` | `/api/rag/stream` | 阶段化 RAG SSE。 |
| `POST` | `/api/rag/frequency_plan/stream` | 频率规划 profile，含脚注/相邻频段多跳检索。 |
| `GET` | `/api/rag/docs` | 文档 registry 分页查询。 |
| `GET` | `/api/rag/docs/{doc_id}/pdf` | 已注册 PDF 内联预览。 |
| `GET` | `/api/rag/graph/entities` | 图谱实体/关系查询。 |
| `GET` | `/api/rag/status` | registry、Chroma、graph、ingest 事件状态。 |
| `POST` | `/api/spectrum-construction/generate` | 生成多分辨率频谱图和可选重建。 |
| `POST` | `/api/spectrum-construction/uav-rem/overview` | 读取 Agent_UAV_REM 实验产物。 |
| `POST` | `/api/spectrum-decision/allocate` | 参数化或智能体资源分配。 |
| `POST` | `/api/spectrum-decision/allocate/stream` | 智能体分配 SSE。 |

## LLM 配置

`backend/config.py` 从 `.env` 和环境变量读取配置。常用变量：

| 变量 | 说明 |
| --- | --- |
| `SPECTRUMCLAW_AGENT_RUNTIME` | `legacy` 或 `langgraph`。 |
| `SPECTRUMCLAW_LLM_PROVIDER` | `auto/deepseek/openai/qwen/anthropic/openai_compatible/anthropic_compatible`。 |
| `SPECTRUMCLAW_LLM_BASE_URL` | 自定义兼容端点。 |
| `SPECTRUMCLAW_LLM_API_KEY` | LLM API Key。 |
| `SPECTRUMCLAW_LLM_MODEL` | 模型名。 |
| `TAVILY_API_KEY` | 可选，启用 web_search。 |
| `QWEN_VL_API_KEY` | 可选，启用图像/图表描述。 |

## 运行命令

```bash
scripts/local/start_backend.sh
```

或直接运行：

```bash
uvicorn backend.app:app --host 0.0.0.0 --port 8230 --reload
```

## 验证

```bash
curl http://127.0.0.1:8230/health
python -m py_compile backend/app.py backend/api/*.py backend/llm/client.py
pytest tests/test_chat_api.py tests/test_agent_runtime.py -q
```

## 维护边界

| 规则 | 说明 |
| --- | --- |
| Router 注册 | 新增 `backend/api/*.py` 后必须在 `backend/app.py` 注册。 |
| 长任务 | MinerU 解析、全量入库、GenSpectra 推理应通过脚本/sidecar/子进程隔离。 |
| 记忆写入 | Memory 是 best-effort，不应让主任务因 SQLite 写入失败而失败。 |
| 数据路径 | RAG 目录统一从 `backend/rag/paths.py` 读取。 |
