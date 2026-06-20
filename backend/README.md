# Backend

SpectrumClaw 后端是 FastAPI 服务，入口为 `backend/app.py`。

## 模块

| 模块 | 路径 | 状态 |
| --- | --- | --- |
| App | `backend/app.py` | 注册 Chat、RAG、Memory、System、Spectrum Construction、Spectrum Decision、Eval 路由。 |
| Agent | `backend/agent/` | `legacy/langgraph` 双 runtime，langgraph 路径支持路由、记忆和 SSE。 |
| API | `backend/api/` | HTTP/SSE 接口层。 |
| LLM | `backend/llm/` | 多 provider client、thinking、tool loop、流式输出。 |
| RAG | `backend/rag/` | 解析、Chroma、关键词、图谱、重排、上下文打包、问答链。 |
| Memory | `backend/memory/` | SQLite threads/events/items/skill_runs/feedback/evolution reports。 |
| Skills | `backend/skills/` | 频率规划、频谱构建、频谱决策。 |
| Tools | `backend/tools/` | 内置工具注册和 LangChain StructuredTool 适配。 |

## 启动

```bash
scripts/local/start_backend.sh
```

或：

```bash
uvicorn backend.app:app --host 0.0.0.0 --port 8230 --reload
```

## 常用验证

```bash
curl http://127.0.0.1:8230/health
python -m py_compile backend/app.py backend/api/*.py backend/llm/client.py
pytest tests/test_chat_api.py tests/test_agent_runtime.py -q
```
