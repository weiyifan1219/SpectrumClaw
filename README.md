# SpectrumClaw

电磁频谱领域 AI 智能体工作台。以对话为入口，通过 skill 调用频谱知识库、算法脚本、大模型推理和可视化能力，逐步覆盖频率规划、态势构建、资源分配、干扰分析和调制识别。

## 项目进度快照

更新时间：2026-05-29

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 前端 Console | ✅ 完成 | 对话区、Markdown 渲染、流式输出、localStorage 持久化 |
| 模型接入 | ✅ 完成 | DeepSeek（Pro/Flash），OpenAI/Qwen/Anthropic 兼容层 |
| Tool Calling | ✅ 完成 | 7 个工具：时间、天气、网页抓取、Tavily 搜索、ITU 知识库检索 |
| 流式输出 | ✅ 完成 | SSE streaming，逐 token 渲染 + 闪烁光标 |
| 思考过程 | ✅ 完成 | 紫色折叠框展示 reasoning，开始回答后收起 |
| 推理模式 | ✅ 完成 | Brain 开关 + low/high/xhigh/max 四档（合并到模型 popover）|
| 知识库 RAG | ✅ Phase 1 | 804 份 ITU PDF 文本提取 → TF-IDF 索引 → `search_knowledge_base` tool |
| 知识库页面 | 🔶 占位 | UI 已有，待接入真实统计 |
| 技能详情页 | 🔶 占位 | 频率规划 / 态势构建 / 资源分配页面骨架 |
| 记忆与进化 | 🔶 占位 | UI 已有，待接入后端记忆系统 |
| LangGraph Agent 迁移 | ✅ 完成 | 默认 runtime，router → tool/rag/web → llm → finalizer 四路径 |
| 知识图谱 | ❌ 未开始 | Phase 3 规划，对标 RAG-Anything 架构 |
| 服务器部署 | ❌ 未开始 | 4090 离线环境待后续 |

## Agent 工作流：Legacy vs LangGraph

当前默认 runtime 已切换为 **LangGraph**。两种模式可通过环境变量切换：

```bash
SPECTRUMCLAW_AGENT_RUNTIME=langgraph  # 默认
SPECTRUMCLAW_AGENT_RUNTIME=legacy     # 回退到旧版
```

### 架构对比

| 维度 | Legacy（旧） | LangGraph（新·默认） |
| --- | --- | --- |
| 编排方式 | 手写 while 循环 + tool loop | 显式 StateGraph 节点路由 |
| 意图路由 | 模型自己决定调哪些 tool | router 节点先分类（chat/rag/tool/web） |
| 工具调用 | 混在 chat() 函数里 tool_calls 循环 | 独立 tool_executor / rag_search / web_search 节点 |
| 可观测性 | 只有 metadata 里的 tool_rounds | graph_nodes 记录完整执行路径 |
| 可扩展性 | 加新能力要改 client.py | 加新能力 = 加新 node + 边 |
| 工具注册 | backend/llm/tools.py 自维护 | backend/tools/registry.py 统一注册（LangChain 兼容） |
| SSE 事件 | 直接透传 DeepSeek reasoning + content | thinking → content → done 三段式 |

### LangGraph 执行路径

```
用户输入 → router（意图分类）
            ├─ chat  → llm_answer → finalizer   （普通对话）
            ├─ tool  → tool_executor → ...        （时间/状态工具）
            ├─ rag   → rag_search → ...           （ITU 知识库检索）
            └─ web   → web_search → ...           （Tavily 联网搜索）
```

所有路径最终汇聚到 llm_answer（调用 LLM）→ finalizer（组装输出）。开发新功能时只需加新 node 和路由规则。

### 开发主线

LangGraph 是当前开发主线，所有新功能（skill、memory、RAG 升级）都应在 LangGraph 节点层实现。Legacy 保留用于回退和兼容性验证。

## 本地开发

### 前端

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

### 后端

```bash
bash scripts/local/start_backend.sh
```

后端监听 `0.0.0.0:8230`。前端 Console 自动调用后端 API。

### LLM 配置

在 `.env` 中配置（默认 DeepSeek）：

```bash
SPECTRUMCLAW_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-v4-pro

# 可选：OpenAI / Qwen / Anthropic / 自定义代理
# SPECTRUMCLAW_LLM_PROVIDER=openai_compatible
# SPECTRUMCLAW_LLM_BASE_URL=https://api.openai.com/v1
# SPECTRUMCLAW_LLM_API_KEY=sk-xxx
# SPECTRUMCLAW_LLM_MODEL=gpt-4o
```

### Python 环境

```bash
conda create -n SpectrumClaw python=3.11 -y
conda run -n SpectrumClaw python -m pip install -r requirements.txt
```

### 知识库索引

```bash
PYTHONPATH=. conda run -n SpectrumClaw python -m backend.knowledge.ingest
```

从 `itu_documents.zip`（804 份 ITU-R PDF）提取文本 → 分块 → TF-IDF 索引 → 存入 SQLite。

### Web 搜索

在 `.env` 中配置 Tavily API key（免费 100 次/月：https://tavily.com）：

```bash
TAVILY_API_KEY=tvly-xxx
```

## API 端点

| 端点 | 说明 |
| --- | --- |
| `GET /health` | 健康检查 + LLM 配置状态 |
| `POST /api/chat` | 标准对话（一次性返回） |
| `POST /api/chat/stream` | 流式对话（SSE，逐 token 推送） |

### 流式事件格式

```
data: {"type":"thinking","data":"思考内容..."}
data: {"type":"content","data":"回答内容..."}
data: {"type":"done","data":{元数据}}
```

## 工具列表

| 工具 | 说明 | 需要配置 |
| --- | --- | --- |
| `get_time` | UTC + 北京时间 | 无 |
| `get_weather` | 实时天气（wttr.in） | 无 |
| `web_fetch` | 抓取 URL 网页内容 | 无 |
| `web_search` | 互联网搜索 | Tavily API key |
| `search_knowledge_base` | ITU 频谱知识库检索 | 运行过 ingest |
| `get_system_status` | 系统组件状态 | 无 |

## 项目结构

```
frontend/          React + Vite 前端
backend/
  agent/           LangGraph agent runtime ★ 主开发线
    state.py       AgentState TypedDict
    graph.py       StateGraph 定义（router → nodes → finalizer）
    nodes.py       节点实现（router/tool/rag/web/llm/finalizer）
    runtime.py     legacy/langgraph 分发 + stream_chat
    events.py      SSE 事件格式
  tools/
    registry.py    统一工具注册（单点真源）
    langchain_tools.py  LangChain StructuredTool 转换
    executors.py   async 工具执行
  api/chat.py      /api/chat + /api/chat/stream 端点
  config.py        Provider + runtime 配置
  llm/
    client.py      LLM 客户端（legacy，保留）
    tools.py       Tool registry（legacy，保留）
  knowledge/
    ingest.py      PDF 提取 → chunk → TF-IDF 索引（804 ITU PDF）
    retrieve.py    检索接口
    store.py       存储后端（sqlite/postgres/qdrant）
data/knowledge_base/  RAG 索引和原始文件
docs/             项目规划、架构、设计文档
scripts/local/    本地启动脚本
```

## Agent 框架演进路线

SpectrumClaw 后续智能体框架采用 **LangGraph-first + LangChain-compatible** 路线：

| 层级 | 目标方案 | 迁移策略 |
| --- | --- | --- |
| Agent 编排 | LangGraph StateGraph | 逐步替换当前手写 tool loop |
| 工具接口 | LangChain Core Tool / StructuredTool | 先把现有 7 个工具迁移到统一 registry |
| RAG 接口 | LangChain Retriever 风格 | 先包装现有 TF-IDF 检索，后续升级 embedding/graph |
| 模型调用 | 保留现有 provider adapter，逐步兼容 LangChain ChatModel | 避免破坏 DeepSeek thinking / reasoning_content / tool calling |
| 记忆系统 | LangGraph checkpoint + 自定义 memory store | 后续接入 Memory & Evolution 页面 |
| 前端事件 | 保持现有 SSE 事件协议 | Graph events 映射为 `thinking/content/done/error` |

迁移计划详见 [`docs/LANGGRAPH_MIGRATION_PLAN.md`](docs/LANGGRAPH_MIGRATION_PLAN.md)。

## 知识库演进路线

参考 [RAG-Anything](https://github.com/HKUDS/RAG-Anything)（HKU · 20.7k stars）架构：

| Phase | 目标 | 状态 |
| --- | --- | --- |
| 1 | 文本 RAG（pypdf + TF-IDF + SQLite） | ✅ 当前 |
| 2 | Embedding 语义检索 + Postgres/pgvector | 规划 |
| 3 | 频谱知识图谱（实体/关系提取 + 图遍历） | 规划 |
| 4 | 多模态（表格/公式/图片 VLM 描述） | 远期 |

## 当前限制

- 知识库检索为 TF-IDF 词频匹配，非语义检索
- 技能详情页（频率规划/态势构建/资源分配）为占位 UI
- 记忆与进化系统尚未接入后端
- 尚未部署到 4090 服务器
- 知识图谱、多模态 RAG 尚未开始

## 下一步任务

| 优先级 | 任务 | 说明 |
| --- | --- | --- |
| P0 | 知识库页面接入真实状态 | 展示索引统计、文档数、检索样例 |
| P0 | LangGraph Agent Runtime | 建立 `legacy/langgraph` runtime 开关、StateGraph 骨架和基础节点 |
| P0 | 统一 Tool Registry | 将 7 个工具迁移为 LangChain-compatible tool registry |
| P0 | 实现 Agent Loop | 用 LangGraph 接管 router、tool、RAG、final answer 多步执行 |
| P1 | 技能详情页开发 | 频率规划/态势构建/资源分配完整交互 |
| P1 | 记忆与进化后端 | 对话摘要、skill 成功率记录 |
| P2 | Embedding 升级 | TF-IDF → 语义向量 |
| P2 | 知识图谱 | 频谱实体/关系提取 |

## 参考项目

- [RAG-Anything](https://github.com/HKUDS/RAG-Anything) — 多模态 RAG + 知识图谱框架
- [AerialClaw](https://github.com/weiyifan1219/AerialClaw) — 同系列无人机智能体项目
- [DeepSeek API Docs](https://api-docs.deepseek.com/) — 当前主力模型
