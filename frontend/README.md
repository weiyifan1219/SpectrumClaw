# SpectrumClaw Frontend

React + Vite 工作台，默认入口为 Console。

## 命令

```bash
npm --prefix frontend install
bash scripts/local/start_frontend.sh
npm --prefix frontend run build
```

网络环境切换后：

```bash
bash scripts/local/reconnect_network.sh
```

本地开发时前端监听 `0.0.0.0:5173`，API 通过 `/backend` 同源代理转发。稳定运行时执行 `bash scripts/local/deploy_server_frontend.sh`，生产构建会部署到服务器并由后端 `8230` 同源托管，浏览器直接访问 `http://<服务器IP>:8230/`。

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
