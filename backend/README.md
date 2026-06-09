# Backend

FastAPI 后端已经进入可运行状态，不再是纯占位骨架。

## 当前模块

| 模块 | 路径 | 状态 |
| --- | --- | --- |
| FastAPI 入口 | `backend/app.py` | 注册 chat、memory、rag、spectrum_construction、spectrum_decision。 |
| Agent runtime | `backend/agent/` | LangGraph 默认路径，legacy 保留回退。 |
| API 层 | `backend/api/` | 对话、记忆、RAG、频谱构建、频谱决策接口。 |
| RAG | `backend/rag/` | 新解析/检索 pipeline 进行中，3090 正在跑 MinerU 预处理。 |
| 旧知识库 | `backend/knowledge/` | 804 PDF / 20,871 chunk 的 TF-IDF 检索统计仍可用。 |
| Memory | `backend/memory/` | SQLite MVP、overview/items/feedback/reports API。 |
| Skills | `backend/skills/` | Frequency Planning、Spectrum Construction、Spectrum Decision 已有真实代码。 |

## 启动

```bash
cd /workspace/YiFan/SpectrumClaw
/root/miniconda3/envs/SpectrumClaw/bin/python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8230
```

本地环境可用 `/home/lenovo/miniconda3/envs/SpectrumClaw/bin/python` 做语法检查和轻量测试。
