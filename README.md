# SpectrumClaw

电磁频谱领域 AI 智能体工作台。以对话为入口，通过 Skill 调用频谱知识库、算法脚本、大模型推理和可视化能力，逐步覆盖频率规划、态势构建、资源分配、干扰分析和调制识别。

**技术栈：** LangGraph Agent Runtime + DeepSeek LLM + LangChain Tools/Retrievers + ITU 知识库 RAG

## 项目进度快照

更新时间：2026-05-29

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 前端 Console | ✅ 完成 | 流式输出、Markdown 渲染、localStorage 持久化、居中布局 |
| 模型接入 | ✅ 完成 | DeepSeek Pro/Flash，OpenAI/Qwen/Anthropic 兼容 |
| Tool Calling | ✅ 完成 | 7 工具：时间/天气/Tavily搜索/网页抓取/知识库/系统状态 |
| 流式输出 + 思考 | ✅ 完成 | SSE 实时 token 推送 + 真推理过程 + 闪烁光标 |
| 推理模式 | ✅ 完成 | Brain 开关 + 4 档强度，合并在模型 popover 中 |
| 引用来源 | ✅ 完成 | 网页 ↗ 标记，知识库 📄 文档编号 |
| LangGraph Agent | ✅ 完成 | 默认 runtime，router → tool/rag/web → llm stream 四路径 |
| LangChain 集成 | ✅ 完成 | BaseRetriever 包装 RAG，StructuredTool 包装 Tools |
| 知识库 RAG | ✅ Phase 1 | 804 ITU PDF → 20,871 chunks → TF-IDF → search_knowledge_base |
| 知识库页面 | ✅ 完成 | 真实索引统计（PDF 数、chunk 数、字符量）|
| 可扩展存储 | ✅ 设计 | SqliteStore / PostgresStore / QdrantStore 统一接口 |
| 技能详情页 | 🔶 占位 | 频率规划/态势构建/资源分配页面骨架 |
| 记忆与进化 | 🔶 占位 | UI 已有，待 LangGraph checkpoint + memory store |
| 知识图谱 | ❌ 未开始 | RAG Phase 3，对标 RAG-Anything |
| 服务器部署 | ❌ 未开始 | 4090 离线环境 |

## 本地开发

### 启动

```bash
# 后端（默认 LangGraph runtime）
bash scripts/local/start_backend.sh

# 前端
cd frontend && npm run dev -- --host 0.0.0.0
```

后端 `0.0.0.0:8230`，前端自动连接。

### LLM 配置

```bash
# .env（默认 DeepSeek）
SPECTRUMCLAW_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-v4-pro

# 切换 runtime
SPECTRUMCLAW_AGENT_RUNTIME=langgraph  # 默认
SPECTRUMCLAW_AGENT_RUNTIME=legacy     # 回退
```

### 知识库索引

```bash
PYTHONPATH=. conda run -n SpectrumClaw python -m backend.knowledge.ingest
```

### Web 搜索

```bash
TAVILY_API_KEY=tvly-xxx  # 免费 100 次/月: https://tavily.com
```

## API 端点

| 端点 | 说明 |
| --- | --- |
| `GET /health` | 健康检查 + LLM 状态 |
| `GET /api/kb/stats` | 知识库索引统计 |
| `POST /api/chat` | 标准对话 |
| `POST /api/chat/stream` | SSE 流式对话 |

流式事件格式：`thinking` → `content` → `done`

## Agent 架构

### 工作流对比

| | Legacy（旧） | LangGraph（新·默认） |
| --- | --- | --- |
| 编排 | 手写 while + tool loop | StateGraph 节点路由 |
| 路由 | 模型自行决定 | router 先分类（chat/rag/tool/web） |
| 工具 | 混在 chat() 函数 | 独立节点 + LangChain StructuredTool |
| RAG | 直接调 retrieve | LangChain BaseRetriever 包装 |
| 可观测 | tool_rounds 数字 | graph_nodes 完整路径 |
| 流式 | ✅ 真逐 token | ✅ 真逐 token + 真实推理链 |

### 执行路径

```
用户输入 → router
            ├─ chat → [stream LLM answer]
            ├─ tool → tool_executor → [stream]
            ├─ rag  → rag_search → [stream]
            └─ web  → web_search → [stream]
```

### 开发主线

LangGraph `backend/agent/` 是当前开发主路径。加新能力 = 加 node + 路由规则。Legacy 保留回退。

## 工具列表

| 工具 | 说明 | 配置 |
| --- | --- | --- |
| `get_time` | UTC + 北京时间 | 无 |
| `get_weather` | 实时天气（wttr.in） | 无 |
| `web_fetch` | 抓取 URL | 无 |
| `web_search` | 互联网搜索（Tavily） | `TAVILY_API_KEY` |
| `search_knowledge_base` | ITU 知识库检索 | 运行过 `ingest` |
| `get_system_status` | 系统状态 | 无 |

## 项目结构

```
frontend/            React + Vite
backend/
  agent/             LangGraph runtime ★ 主开发
    state.py           AgentState
    graph.py           StateGraph（router → nodes）
    nodes.py           节点实现
    runtime.py         legacy/langgraph 分发 + stream_chat
    events.py          SSE 事件格式
  tools/
    registry.py        统一工具注册（单点真源）
    langchain_tools.py StructuredTool 转换
    executors.py       async 执行
  rag/
    retriever.py       LangChain BaseRetriever
    citations.py       引用格式化 + RAG context
  knowledge/
    ingest.py          PDF → chunk → TF-IDF（804 ITU PDF）
    retrieve.py        检索
    store.py           SqliteStore / PostgresStore / QdrantStore
  api/chat.py          /api/chat + /api/chat/stream + /api/kb/stats
  config.py            Provider + Runtime 配置
  llm/
    client.py          LLM client（legacy，保留）
    tools.py           Tool registry（legacy，保留）
data/knowledge_base/  RAG 索引和原始文件
docs/                 项目规划、架构文档
scripts/local/        启动脚本
tests/                16 个测试
```

## 知识库演进

对标 [RAG-Anything](https://github.com/HKUDS/RAG-Anything)（HKU · 20.7k stars）：

| Phase | 目标 | 技术 | 状态 |
| --- | --- | --- | --- |
| 1 | 文本 RAG | pypdf + TF-IDF + SQLite | ✅ 当前 |
| 2 | Embedding 语义检索 | DeepSeek Embedding / BGE + Postgres/pgvector | 规划 |
| 3 | 知识图谱 | 频谱实体/关系提取 + 图遍历 | 规划 |
| 4 | 多模态 | 表格/公式/图片 VLM 描述 | 远期 |

## 下一步任务

| 优先级 | 任务 | 说明 |
| --- | --- | --- |
| P0 | RAG Phase 2 — Embedding 升级 | TF-IDF → 语义向量，大幅提升检索质量 |
| P1 | 技能详情页 | 频率规划/态势构建/资源分配真实交互 |
| P1 | 记忆与进化 | LangGraph checkpoint + memory store |
| P1 | Agent Skill Subgraph | 每个 skill 作为 LangGraph subgraph |
| P2 | 知识图谱 | 频谱实体/关系提取 |
| P2 | 服务器部署 | 4090 离线环境 |

## 测试

```bash
PYTHONPATH=. conda run -n SpectrumClaw pytest -q  # 16 passed
cd frontend && npm run build                        # 通过
```

## 参考

- [RAG-Anything](https://github.com/HKUDS/RAG-Anything) — 多模态 RAG + 知识图谱
- [LangGraph](https://langchain-ai.github.io/langgraph/) — Agent 编排框架
- [DeepSeek API](https://api-docs.deepseek.com/) — 主力模型
