# SpectrumClaw Frontend

React + Vite 工作台，默认入口为 Console。

## 命令

```bash
npm --prefix frontend install
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
npm --prefix frontend run build
```

连接非默认后端：

```bash
VITE_API_BASE=http://127.0.0.1:8230 npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

## 页面

| 页面 | 文件 | 状态 |
| --- | --- | --- |
| Console | `src/pages/ConsolePage.jsx` | 流式对话、模型选择、thinking、日志、artifacts、反馈和本地持久化。 |
| Frequency Planning | `src/pages/FrequencyPlanningPage.jsx` | 频率规划 RAG profile，流式阶段、引用和结构化结果。 |
| Spectrum Construction | `src/pages/SituationBuildingPage.jsx` | Gudmundson/GenSpectra 与 UAV REM 结果展示。 |
| Spectrum Decision | `src/pages/SpectrumDecisionPage.jsx` | 参数化/自然语言资源分配，SSE agent 模式。 |
| Knowledge Base | `src/pages/KnowledgePage.jsx` | 统计、RAG 查询、文档列表、PDF 预览、图谱。 |
| Memory & Evolution | `src/pages/MemoryPage.jsx` | Memory API、skill stats、reports，支持缓存和后台刷新。 |
| System | `src/pages/SystemPage.jsx` | 系统状态展示，部分内容仍为 mockData。 |

## 状态保留

`App.jsx` 会保持页面节点挂载，通过 `display` 切换显示，避免切页时丢失长任务结果。Console、Knowledge、Memory、Decision 还使用 localStorage/module cache 保存关键状态。
