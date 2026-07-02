# 频率规划

频率规划当前基于 RAG pipeline 实现，不再是静态展示页或纯规划文档。主要入口是前端 `FrequencyPlanningPage.jsx` 和后端 `/api/rag/frequency_plan/stream`。

## 当前能力

| 能力 | 状态 | 入口 |
| --- | --- | --- |
| 参数化规划 | 可用 | 前端频率规划页将频段、区域、国家、业务和约束组合成 query。 |
| 自然语言规划 | 可用 | 用户直接描述任务，后端 profile 做检索和回答。 |
| 流式阶段展示 | 可用 | `query_analysis -> retrieval -> rerank -> multihop -> answer`。 |
| 多跳补检 | 可用 | `frequency_plan` profile 会根据脚注和区域提示补检脚注/相邻频段/共存约束。 |
| 引用与 PDF | 可用 | citations 关联文档名、页码和 PDF 预览。 |
| 结构化结果 | 部分可用 | `backend/skills/frequency_planning/planner.py` 可从 RAG 回答中抽取业务、脚注和约束。 |

## 后端路径

```text
POST /api/rag/frequency_plan/stream
  -> backend.rag.graph.stream.stream_rag_query(profile="frequency_plan")
  -> SpectrumQueryAnalyzer
  -> VectorRetriever + KeywordRetriever + GraphRetriever
  -> Reranker
  -> footnote/adjacent multi-hop retrieval
  -> ContextPacker
  -> LLM stream with frequency-planning prompt
  -> citations/debug/done
```

## 请求

```json
{
  "question": "2300-2400 MHz 在 ITU Region 3 是否适合移动业务？请说明脚注和相邻频段共存约束。",
  "thinking_enabled": true
}
```

## SSE 事件

| 类型 | 说明 |
| --- | --- |
| `stage` | 一个阶段开始，包含 `stage` 和 `label`。 |
| `stage_done` | 阶段结束，检索阶段会带 counts，rerank 会带 count。 |
| `thinking` | LLM thinking token，需模型/provider 支持。 |
| `content` | 回答 token。 |
| `done` | 终局 citations/debug。 |
| `error` | 异常信息。 |

## 检索增强

| 步骤 | 说明 |
| --- | --- |
| Query analysis | 抽取频段、区域、业务、标准号、脚注和意图。 |
| Vector retrieval | ChromaDB + BGE-M3 embedding。 |
| Keyword retrieval | 关键词/TF-IDF 辅助召回。 |
| Graph retrieval | 基于 `data/graph/spectrum_graph.json` 的 Document/FrequencyBand/Standard/Footnote 关系。 |
| Rerank | 按频段、区域、业务、标准号、脚注、block type 和来源权威度加权。 |
| Multi-hop | 从 pass-1 上下文抽取 `5.xxx` 脚注，再补检脚注、相邻频段、共存、保护和协调限制。 |

## 前端展示

| 区域 | 说明 |
| --- | --- |
| 左栏 | 参数输入、场景预设、自然语言输入和运行按钮。 |
| 中栏 | 阶段进度、Markdown 回答、结构化规划摘要。 |
| 右栏 | citations、来源文档、页码、相关度、原文 PDF 入口和 debug。 |

## 质量边界

| 边界 | 说明 |
| --- | --- |
| 结论必须带证据 | 没有 citations 时应提示证据不足。 |
| 区域/脚注需谨慎 | 频率规划必须明确 ITU Region、脚注、primary/secondary 和共存协调。 |
| LLM 不应替代法规原文 | 回答是工程建议，最终判断应回查原始 ITU 文档。 |
| 数据依赖 | 答案质量依赖 Chroma、Graph、doc registry 和 PDF 原文是否完整。 |

## 相关文件

| 文件 | 说明 |
| --- | --- |
| `frontend/src/pages/FrequencyPlanningPage.jsx` | 前端工作区。 |
| `backend/api/rag.py` | `/frequency_plan/stream` 路由。 |
| `backend/rag/graph/stream.py` | 流式 RAG 与多跳逻辑。 |
| `backend/rag/chains/prompts.py` | 频率规划 prompt。 |
| `backend/skills/frequency_planning/planner.py` | RAG 频率规划薄封装和规则抽取。 |
