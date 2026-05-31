# 频率规划子页面系统规划

## 1. 当前定位

频率规划页应从“静态 skill 展示页”升级为 **基于现有 RAG 流程的可审查规划工作区**。用户在这里输入频段、区域、业务、带宽和共存约束，系统调用当前 RAG pipeline 检索 ITU 文档，再输出带引用、带风险标记、可复制的频率规划建议。

| 项 | 当前状态 | 本阶段目标 |
| --- | --- | --- |
| 前端页面 | `frontend/src/pages/FrequencyPlanningPage.jsx` 使用 mock 数据 | 改成真实 RAG 任务工作区 |
| 后端 RAG | `/api/rag/query` 已可返回 `answer/citations/retrieved_blocks/debug` | 页面优先复用该接口 |
| Skill 封装 | `backend/skills/frequency_planning/planner.py` 已包装 `run_rag_query` | Phase 2 再暴露专用 API |
| 知识库 | ITU RAG 已远超原 MVP | 页面要把“证据链”展示出来 |
| Memory | 已有初版记忆系统 | 频率规划结果可后续写入 skill memory / episodic memory |

## 2. 设计原则

| 原则 | 要求 |
| --- | --- |
| 工作台优先 | 不做介绍页，不做营销式 hero，打开就是频率规划任务界面。 |
| 证据优先 | 结果必须和 citations、retrieved blocks、query analysis 放在同一屏可追溯。 |
| 参数可控 | 用户能调整区域、业务、检索模式、Top-K、是否启用图谱/关键词/向量检索。 |
| 渐进复杂度 | 默认提供“快速规划”，高级参数折叠，避免把用户困在表单里。 |
| 不伪造结论 | 如果 RAG 没有足够证据，页面必须显示“证据不足”，而不是强行给方案。 |
| 与 Console 联动 | 页面结果可复制为 Markdown，也可回到 Console 继续追问。 |

## 3. 可借鉴的优秀项目

| 项目 | 借鉴点 | SpectrumClaw 采用方式 |
| --- | --- | --- |
| RAGFlow | 深度文档解析、chunk 可视化、grounded citations、多路召回和 rerank。 | 采用“答案 + 证据块 + 检索流水线状态”的布局，不迁移完整平台。 |
| Kotaemon | 文档问答 UI 强调 citations、相关度和 PDF 高亮。 | 采用右侧 citation inspector，显示来源、页码、分数、片段。 |
| Open WebUI RAG | 支持 citations、hybrid search、reranking 和可配置阈值。 | 采用检索模式、Top-K、相关度阈值等可调控件。 |
| Onyx | 企业搜索场景强调 source list、权限、可审查回答和深度研究。 | 采用“规划结论”和“证据依据”分离展示，便于人工复核。 |

**结论：** 只参考交互和信息架构，不 clone 外部 repo。SpectrumClaw 已经有专用频谱 RAG pipeline，直接迁移通用 RAG 平台会增加重复架构。

## 4. 用户交互主流程

```text
用户进入 Frequency Planning
  -> 选择预设场景或手动输入需求
  -> 页面实时生成 RAG query preview
  -> 点击“运行规划”
  -> 前端调用 /api/rag/query
  -> 显示运行状态：query analysis -> retrieval -> rerank -> answer
  -> 展示规划答案、风险标记、引用来源、检索块
  -> 用户复制 Markdown / 返回 Console 继续追问 / 保存到 Memory
```

## 5. 页面信息架构

### 5.1 第一屏布局

建议采用三栏工作台，保持当前控制台风格，但替换 mock 内容。

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Header: 频率规划工作区 | RAG Ready | 返回 Console | 运行规划 | 复制结果       │
├───────────────────┬──────────────────────────────────────┬───────────────────┤
│ 左：任务输入       │ 中：规划结果 / 证据地图               │ 右：引用检查器      │
│ - 场景预设         │ - 运行状态 timeline                  │ - citations list   │
│ - 频段/区域/业务   │ - Answer markdown                    │ - retrieved blocks │
│ - 带宽/约束        │ - 风险与限制                         │ - query debug      │
│ - 检索模式/Top-K   │ - 推荐下一步                         │ - source metadata  │
└───────────────────┴──────────────────────────────────────┴───────────────────┘
```

### 5.2 区域职责

| 区域 | 组件 | 内容 |
| --- | --- | --- |
| Header | 状态 + 操作 | RAG 健康状态、当前模型、运行按钮、复制按钮、返回 Console。 |
| 左栏 | Request Builder | 场景预设、频段、ITU Region、国家/地区、业务类型、带宽、共存约束、自由文本。 |
| 左栏高级 | Retrieval Controls | 检索模式、Top-K、是否显示 debug、是否包含 graph retrieval、分数阈值。 |
| 中栏 | Plan Result | Markdown 规划答案、频段建议、约束、脚注、风险等级、下一步建议。 |
| 中栏 | Evidence Map | 向量/关键词/图谱/频率匹配的召回情况，用紧凑 timeline 展示。 |
| 右栏 | Citation Inspector | 来源文档、页码、block 类型、相关度、摘录、点击后展开全文片段。 |

## 6. 输入设计

| 字段 | 类型 | 默认/示例 | 说明 |
| --- | --- | --- | --- |
| `scenario` | select | 民用 2.4 GHz 共用频段 | 快速填充常用参数。 |
| `frequency_band` | text | `2300-2400 MHz` | 必填；支持 MHz/GHz/kHz。 |
| `region` | segmented/select | Region 1 / 2 / 3 | 可由国家自动推断，但用户可覆盖。 |
| `country` | text/select | 中国 | 可选；用于补充区域和本地约束。 |
| `service` | select/multiselect | Fixed, Mobile, Radiolocation | 支持多业务共存。 |
| `bandwidth_mhz` | number | 20 | 可选；用于规划建议而非 RAG 必填。 |
| `coexistence` | tags | WiFi, Bluetooth, radar | 用户输入干扰或共存对象。 |
| `mission_context` | textarea | 无人机短距数据链 | 自由描述任务背景。 |
| `retrieval_mode` | segmented | Hybrid | `vector/keyword/graph/hybrid`；初期只影响 query 文案和 UI 状态。 |
| `top_k` | number/slider | 8 | Phase 1 如后端不支持，可先固定显示。 |

## 7. Query 生成规则

前端不直接把整张表单丢给 LLM，应生成明确的 RAG query。

| 输入 | Query 片段 |
| --- | --- |
| frequency_band | `2300-2400 MHz 频段` |
| region | `ITU Region 3` |
| country | `中国` |
| service | `Fixed Mobile 业务分配` |
| coexistence | `共存 干扰 保护条件 WiFi Bluetooth` |
| mission_context | 保留用户原文 |
| 固定增强 | `frequency allocation footnote limitation protection criteria Radio Regulations` |

示例：

```text
2300-2400 MHz 频段 ITU Region 3 中国 Fixed Mobile 业务分配 共存 干扰 保护条件 无人机短距数据链 frequency allocation footnote limitation protection criteria Radio Regulations
```

## 8. 结果展示格式

### 8.1 中栏答案结构

LLM 返回的 Markdown 要在前端按以下结构渲染；如果后端暂时只返回普通 `answer`，前端先直接显示，不强拆。

| 区块 | 展示内容 |
| --- | --- |
| 结论摘要 | 是否建议使用、推荐频段、风险等级。 |
| 频段适用性 | Region / country / service 的适用判断。 |
| 约束条件 | primary/secondary、保护标准、脚注、邻频限制。 |
| 共存建议 | 带宽、功率、避让、监测、协调建议。 |
| 证据依据 | 引用编号，与右侧 citation 对齐。 |
| 下一步 | 需要补充的参数或进一步检索的问题。 |

### 8.2 风险等级

| 等级 | UI | 判定规则 |
| --- | --- | --- |
| `ok` | 绿色 | 引用充足且结论明确。 |
| `warn` | 琥珀 | 有引用但存在脚注、区域差异、二级业务或共存限制。 |
| `danger` | 红色 | 明确冲突、证据不足、未找到分配依据。 |
| `unknown` | 灰色 | RAG 返回为空或后端报错。 |

Phase 1 可以用简单规则：`citations.length === 0 -> unknown`；answer 含 `not allocated/prohibited/禁止/不得` -> danger；含 `secondary/coordination/protection/脚注` -> warn。

## 9. Citation Inspector

| 字段 | 来源 | UI |
| --- | --- | --- |
| `source` | `citations[].source` 或 retrieved block metadata | 文档名，单行截断。 |
| `page` | `citations[].page` | `p.12` badge。 |
| `relevance` | `citations[].relevance` / score | 0-100% 条形条。 |
| `block_type` | retrieved block metadata | text/table/image/equation badge。 |
| `excerpt` | retrieved block text | 默认 2-4 行，点击展开。 |
| `debug` | `debug.query_analysis` | 折叠显示 frequency、region、service、intent。 |

右栏必须避免只列文档名；用户需要能判断“这条引用为什么支撑结论”。

## 10. API 规划

### 10.1 Phase 1：复用现有 RAG API

先不新增后端接口，前端调用：

```http
POST /api/rag/query
Content-Type: application/json

{
  "question": "2300-2400 MHz 频段 ITU Region 3 中国 Fixed Mobile 业务分配 ..."
}
```

响应已存在：

```json
{
  "answer": "...",
  "citations": [
    {"source": "...", "page": 12, "block_id": "...", "relevance": 0.82}
  ],
  "retrieved_blocks": [
    {"text": "...", "metadata": {"source_path": "...", "page_idx": 12}}
  ],
  "debug": {
    "query_analysis": {
      "frequency_range": "2300-2400 MHz",
      "region": "Region 3",
      "radio_service": "Mobile",
      "intent": "allocation_check"
    }
  }
}
```

### 10.2 Phase 2：专用 Frequency Planning API

如果 Phase 1 页面稳定，再加专用接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/frequency-planning/query` | 接收结构化参数，内部调用 `FrequencyPlanner.analyze()`。 |
| `GET` | `/api/frequency-planning/presets` | 返回场景预设。 |
| `POST` | `/api/frequency-planning/export` | 导出 Markdown/JSON artifact。 |

专用请求：

```json
{
  "frequency_band": "2300-2400 MHz",
  "region": "Region 3",
  "country": "中国",
  "services": ["Fixed", "Mobile"],
  "bandwidth_mhz": 20,
  "coexistence": ["WiFi", "Bluetooth"],
  "mission_context": "无人机短距数据链",
  "retrieval_mode": "hybrid",
  "top_k": 8
}
```

## 11. 前端状态机

| 状态 | 触发 | UI |
| --- | --- | --- |
| `idle` | 初始进入页面 | 显示预设和空结果区。 |
| `ready` | 必填字段满足 | “运行规划”按钮可用。 |
| `running` | 点击运行 | 禁用输入，显示 pipeline steps。 |
| `success` | RAG 返回 | 显示答案、引用、debug、复制按钮。 |
| `empty` | 无引用/无答案 | 显示证据不足和建议补充字段。 |
| `error` | API 失败 | 显示错误、重试、回到 Console。 |

## 12. 前端实现任务

| 任务 | 文件 | 要求 |
| --- | --- | --- |
| 1. 增加 RAG query API helper | `frontend/src/lib/api.js` | 新增 `runRagQuery(question)`，调用 `/api/rag/query`。 |
| 2. 重写频率规划页面状态 | `frontend/src/pages/FrequencyPlanningPage.jsx` | 用 React state 管理 form、query preview、loading、result、error、selected citation。 |
| 3. 替换 mock 结果 | `frontend/src/pages/FrequencyPlanningPage.jsx` | 删除 `fpCitations/ituBands` 依赖，改用真实 response。 |
| 4. 增加输入构建器 | 同上 | 场景预设、必填校验、query preview、高级参数。 |
| 5. 增加结果视图 | 同上 | Markdown answer、risk badge、pipeline steps、copy markdown。 |
| 6. 增加引用检查器 | 同上 | citations + retrieved_blocks 合并展示，支持选择和展开。 |
| 7. 增加样式 | `frontend/src/styles/app.css` | 新增 `.fp-*` 命名空间，保持控制台风格，不影响其他页面。 |
| 8. 增加测试/构建验证 | 现有测试 + build | 至少跑 `npm run build`；如新增后端 API 再补 pytest。 |

## 13. 建议组件拆分

为了避免 `FrequencyPlanningPage.jsx` 变成一个超大文件，建议在 Phase 1 就拆小组件。

| 组件 | 职责 |
| --- | --- |
| `FrequencyPlanningPage` | 页面状态、API 调用、三栏布局。 |
| `FrequencyRequestForm` | 参数输入和 query preview。 |
| `FrequencyResultPanel` | Markdown 答案、风险、复制。 |
| `FrequencyCitationPanel` | citations / retrieved blocks / debug。 |
| `RetrievalStepRail` | query analysis、retrieval、rerank、answer 状态。 |

如果不想新增太多文件，Phase 1 可以先在同一文件内写内部函数组件，稳定后再拆。

## 14. 视觉设计

| 项 | 设计 |
| --- | --- |
| 整体 | 保持 SpectrumClaw 深色控制台，信息密度高，少装饰。 |
| 主色 | 频谱青用于检索链路，琥珀用于风险和约束，绿色用于可用建议，红色用于冲突。 |
| 图形 | 不做大面积装饰图；用紧凑频段条、证据条、score bar 表达状态。 |
| 布局 | 左窄中宽右窄；中栏结果区可滚动，右栏引用固定高度滚动。 |
| 空态 | 显示“等待运行规划”，提供 2-3 个预设按钮。 |
| 加载 | 显示四步 pipeline：Query Analysis / Hybrid Retrieval / Rerank / Answer。 |
| 响应式 | 窄屏改为单列：输入 -> 结果 -> 引用。 |

## 15. 用户体验细节

| 场景 | 行为 |
| --- | --- |
| 用户只输入频段 | 自动补 query：`频率划分 限制条件 脚注`。 |
| 用户选择国家但没选 Region | 根据现有 `SpectrumQueryAnalyzer` 逻辑提示推断 Region。 |
| RAG 无引用 | 不显示“推荐使用”，而是提示证据不足。 |
| 点击 citation | 右栏展开片段，相关度条高亮；中栏答案引用编号不需要本阶段跳转。 |
| 复制结果 | 复制 Markdown：结论、参数、引用列表、生成时间。 |
| 再问 Console | 预留按钮：把当前参数和结论作为一条消息打开 Console；本阶段可只复制到剪贴板。 |
| 保存 Memory | 等 Memory v0.2 后接入；本阶段不强行实现。 |

## 16. 不做事项

| 不做 | 原因 |
| --- | --- |
| 不重写 RAG pipeline | 现有 `/api/rag/query` 已足够支撑页面。 |
| 不引入 RAGFlow/Kotaemon/Open WebUI 代码 | 项目已有专用架构，迁移成本高。 |
| 不做 PDF 原文查看器 | 可在引用卡片显示片段，PDF 高亮留到后续。 |
| 不做真实频谱仿真 | 当前是法规/RAG 规划页，不接态势构建脚本。 |
| 不自动生成最终工程配置 | 输出是决策建议，不是无线电参数下发。 |

## 17. 验收标准

| 验收项 | 命令/操作 | 期望 |
| --- | --- | --- |
| 前端构建 | `cd frontend && npm run build` | 构建通过。 |
| 页面可运行 | 打开 Frequency Planning，输入 `2300-2400 MHz Region 3` 后运行 | 显示 answer、citations、retrieved blocks。 |
| 空态合理 | 不输入频段时 | 运行按钮禁用或提示必填。 |
| 错误态合理 | 后端未启动 | 显示可读错误，不白屏。 |
| 回归 | Console / Knowledge / Memory 页面切换 | 不受频率规划页改动影响。 |
| RAG 回归 | `conda run -n SpectrumClaw python -m pytest tests/test_rag_pipeline.py -q` | 通过。 |

## 18. 后续路线

| 阶段 | 内容 |
| --- | --- |
| Phase 1 | 前端复用 `/api/rag/query`，实现真实 RAG 规划页。 |
| Phase 2 | 新增 `/api/frequency-planning/query`，返回结构化 planning result。 |
| Phase 3 | 输出 artifacts：`outputs/frequency_planning/<run_id>/result.md|metadata.json|citations.json`。 |
| Phase 4 | 接 Memory：记录 `skill_run`、RAG 引用、用户反馈和规划摘要。 |
| Phase 5 | Citation PDF preview：跳转或预览原文页片段。 |

## 19. Claude Code 实现顺序

| 顺序 | 做什么 | 验证 |
| --- | --- | --- |
| 1 | 只改前端 API helper 和 FrequencyPlanningPage 状态 | `npm run build` |
| 2 | 接 `/api/rag/query` 并显示真实 answer/citations | 手动输入频段运行 |
| 3 | 做 citation inspector 和 retrieved blocks 合并 | 手动点击 citation |
| 4 | 加 loading/error/empty 状态 | 断开后端、空输入分别检查 |
| 5 | 补样式和响应式 | 桌面/窄屏浏览 |
| 6 | 如需要再做专用后端 API | `pytest tests/test_rag_pipeline.py -q` |

## 20. 参考资料

| 资料 | 用途 |
| --- | --- |
| [RAGFlow](https://github.com/infiniflow/ragflow) | 深度文档理解、chunk 可视化、grounded citations、多路召回和 rerank。 |
| [Kotaemon](https://github.com/Cinnamon/kotaemon) | 文档 QA、citation score、PDF 高亮式证据审查。 |
| [Open WebUI RAG](https://docs.openwebui.com/features/rag/) | citations、hybrid search、reranking、RAG 配置项交互。 |
| [Onyx](https://github.com/onyx-dot-app/onyx) | 企业搜索、source list、审查式 RAG 回答体验。 |
