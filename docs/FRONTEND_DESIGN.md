# 前端设计与实现

前端是一个频谱任务工作台，不是 landing page。入口为 `frontend/src/App.jsx`，默认页面是 Console。

## 技术栈

| 项 | 当前值 |
| --- | --- |
| 框架 | React 18 + Vite 5 |
| 图标 | `lucide-react` |
| Markdown | `react-markdown` + `remark-gfm` |
| 状态持久化 | localStorage + `usePersistentState` |
| API client | `frontend/src/lib/api.js` |
| 样式 | `frontend/src/styles/tokens.css`, `frontend/src/styles/app.css` |

## 页面结构

| 页面 | 文件 | 当前能力 |
| --- | --- | --- |
| Console | `ConsolePage.jsx` | 流式对话、模型选择、thinking、工具/RAG 默认工具、线程持久化、反馈、日志和 artifacts 预览。 |
| Frequency Planning | `FrequencyPlanningPage.jsx` | 频率规划专用 RAG 流、参数化/自然语言输入、结构化规划结果和引用。 |
| Spectrum Construction | `SituationBuildingPage.jsx` | Gudmundson/GenSpectra 频谱图、UAV REM 结果读取。 |
| Spectrum Decision | `SpectrumDecisionPage.jsx` | 参数化资源分配、自然语言 agent 模式、SSE 阶段进度和结果解读。 |
| Knowledge Base | `KnowledgePage.jsx` | 知识库统计、RAG 流式问答、文档管理、PDF 预览、图谱实体/关系浏览。 |
| Memory & Evolution | `MemoryPage.jsx` | Memory overview/items/reports/skill stats，带缓存和后台刷新。 |
| System | `SystemPage.jsx` | 系统状态页面，目前仍有部分静态 mock 行，后续可接 `/api/system/*` 做动态化。 |

## App 状态保留

`App.jsx` 不再用 switch 直接卸载页面，而是把所有页面节点挂载后用 `display: contents/none` 切换。这样 Console、Knowledge、Memory、Decision 等页面在导航切换时能保留本地状态。

## Console 数据流

```text
用户输入
  -> ConsolePage submit
  -> POST /api/chat/stream
  -> SSE thinking/content/done/error
  -> messages + task log + feedback target
  -> localStorage 持久化
```

默认工具：

```js
["get_time", "get_system_status", "get_weather", "web_search", "web_fetch", "search_knowledge_base"]
```

## Knowledge 数据流

| UI 区域 | API |
| --- | --- |
| 统计卡片 | `GET /api/kb/stats` |
| RAG 状态 | `GET /api/rag/status`，30 秒刷新 |
| 实时查询 | `POST /api/rag/stream` |
| 文档管理 | `GET /api/rag/docs` |
| PDF 预览 | `GET /api/rag/docs/{doc_id}/pdf` |
| 图谱 | `GET /api/rag/graph/entities`, `GET /api/rag/graph/entity/{name}` |

## 交互约束

| 约束 | 说明 |
| --- | --- |
| 第一屏工作台 | 不新增营销 hero。 |
| 信息密度 | 控制台/技能页以可扫描信息为主，避免空泛说明卡。 |
| 状态可恢复 | 长页面尽量使用缓存或 localStorage，避免切页后丢上下文。 |
| SSE 友好 | 所有流式结果必须能处理中间阶段、token、done 和 error。 |
| 引用可审查 | RAG 回答必须展示 citations，并尽量允许打开原文 PDF。 |

## 命令

```bash
npm --prefix frontend install
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
npm --prefix frontend run build
```
