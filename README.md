# SpectrumClaw

电磁频谱领域 AI 智能体工作台。以 Console 对话为入口，结合 LangGraph runtime、DeepSeek 模型、ITU-R 知识库检索、频谱构建模型和资源分配优化器，形成可交互的频谱任务控制台。

技术栈：React + Vite、FastAPI、LangGraph、DeepSeek OpenAI-compatible API、LangChain tools/retrievers、Chroma/TF-IDF 混合 RAG、MinerU 解析、GenSpectra、Agent_UAV_REM。

## 项目状态快照

更新时间：2026-06-09（第一个大版本）

| 模块 | 当前状态 | 说明 |
| --- | --- | --- |
| Console | 可用 | 支持流式对话、Markdown、工具/RAG 路由、模型选择和任务入口。 |
| LLM 接入 | 可用 | 3090 当前 `/health` 显示 DeepSeek Pro 已配置；服务器无外网，经本地反向隧道转发。 |
| LangGraph Agent | 可用 | 默认 runtime，包含 chat、tool、rag、web 路由路径。 |
| Tool Calling | 可用 | 时间、天气、网页抓取、Tavily 搜索、知识库检索、系统状态。 |
| 频率规划 | 可用 | 专用 RAG profile：FP 定制 prompt + 多跳检索（主频段→脚注/相邻频段）+ 流式思考过程；输出结构化卡片（分配状态/业务/脚注/相邻频段/共存约束/风险/建议）+ 中文分析正文；支持参数化与自然语言两种输入。 |
| Spectrum Construction | 已接入 | Gudmundson 生成多分辨率地图；点击运行调用 GenSpectra；显示真实地图、Patch Mask、重建图和 RMSE；UAV REM 读取 Agent_UAV_REM 结果。 |
| Spectrum Decision / 资源分配 | 已接入 | `/api/spectrum-decision/allocate` 支持直接优化器，保留 LLM agent 解释入口。 |
| Knowledge Base / RAG | 可用 | 流式 RAG pipeline（查询分析→混合检索→重排→打包→生成），带阶段事件、引用和思考过程。 |
| Knowledge Graph | 初始可用 | graph health 为 true，实体/关系仍是最小数据量。 |
| Memory & Evolution | 可用 MVP | SQLite memory service、API 和前端页面已接入；反思/演化为基础实现。 |
| 调制识别 / 干扰分析 | 预留 | UI 中保留方向，不宣称真实算法已接入。 |
| 3090 部署 | 可用 | 后端 `127.0.0.1:8230`，静态前端 `127.0.0.1:5173`。 |

## 3090 当前验证

| 检查项 | 结果 |
| --- | --- |
| 后端健康检查 | `GET /health` 返回 `status=ok`，DeepSeek Pro configured。 |
| GenSpectra 环境 | `/root/miniconda3/envs/Agent_UAV/bin/python`，torch 2.5.1 + CUDA 可用。 |
| GenSpectra 模型 | `/workspace/YiFan/GenSpectra/model/fixed_maskratio_0.75/pretrain/pretrain_GenSpectraLM_{32,64,128,224}.pth` 存在。 |
| GenSpectra 接口 | 64 x 64 调用返回 `reconstruction=true`，RMSE `0.4353`。 |
| UAV REM 接口 | scene 148 / Z2 返回 ground truth、reconstruction、error map，RMSE `1.3182`。 |
| 前端构建 | 当前静态包包含 `运行 GenSpectra`、重建图触发逻辑，已移除信号源黄色点。 |

## 启动方式

### 3090 后端

```bash
cd /workspace/YiFan/SpectrumClaw
/root/miniconda3/envs/SpectrumClaw/bin/python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8230
```

### 3090 静态前端

```bash
cd /workspace/YiFan/SpectrumClaw
/root/miniconda3/envs/SpectrumClaw/bin/python -m http.server 5173 --bind 127.0.0.1 --directory frontend/dist
```

### 本地访问 3090 服务

```bash
ssh -L 8230:127.0.0.1:8230 -L 5173:127.0.0.1:5173 weiyifan3090
```

浏览器打开 `http://127.0.0.1:5173/`。如果前端刚同步过，使用 `Ctrl + F5` 强制刷新。

### 本地开发前端，后端走 3090

```bash
cd /home/lenovo/workspace/SpectrumClaw
VITE_API_BASE=http://127.0.0.1:8230 npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

## API 端点

| 端点 | 说明 |
| --- | --- |
| `GET /health` | 后端健康检查和 LLM 配置。 |
| `POST /api/chat` | 标准对话。 |
| `POST /api/chat/stream` | SSE 流式对话。 |
| `GET /api/kb/stats` | 旧知识库索引统计。 |
| `POST /api/rag/query` | 新 RAG pipeline 问答（非流式）。 |
| `POST /api/rag/stream` | 流式 RAG 问答（SSE，知识库页面使用）。 |
| `POST /api/rag/frequency_plan/stream` | 频率规划专用流式接口：FP prompt + 多跳检索 + 思考过程 + 结构化 JSON。 |
| `GET /api/rag/status` | 新 RAG registry、Chroma、graph 和 ingest 状态。 |
| `POST /api/spectrum-construction/generate` | Gudmundson 生成；`enable_inference=true` 时调用 GenSpectra 返回重建图。 |
| `POST /api/spectrum-construction/uav-rem/overview` | 读取 Agent_UAV_REM 结果文件，返回 REM 场景和算法对比。 |
| `POST /api/spectrum-decision/allocate` | 多用户频谱资源分配。 |
| `GET /api/memory/overview` | 记忆系统概览。 |

## 项目结构

```text
frontend/                         React + Vite 前端
  src/pages/ConsolePage.jsx        主控制台
  src/pages/FrequencyPlanningPage.jsx
  src/pages/SituationBuildingPage.jsx  Spectrum Construction 工作区
  src/pages/SpectrumDecisionPage.jsx
  src/pages/KnowledgePage.jsx
  src/pages/MemoryPage.jsx
backend/
  app.py                           FastAPI 入口，注册 chat/memory/rag/skills API
  agent/                           LangGraph runtime
  api/                             HTTP API 层
  rag/                             RAG pipeline、MinerU/解析/图谱/检索、流式图（含频率规划 profile）
  knowledge/                       旧 TF-IDF 知识库
  memory/                          SQLite memory service
  skills/
    frequency_planning/            RAG 频率规划封装
    spectrum_construction/         Gudmundson + GenSpectra + Agent_UAV_REM
    spectrum_decision/             资源分配优化器和 agent 包装
data/knowledge_base/               ITU 原始文件和旧索引（不入库）
scripts/                           部署、离线依赖、服务器任务脚本
tests/                             Agent、Chat、Memory、RAG、Spectrum Construction 测试
  data/frequency_planning_probe.json  频率规划探测结果，作为性能/质量基线
```

## 验证命令

```bash
npm --prefix frontend run build
/home/lenovo/miniconda3/envs/SpectrumClaw/bin/python -m py_compile \
  backend/api/spectrum_construction.py \
  backend/skills/spectrum_construction/generator.py \
  backend/skills/spectrum_construction/genspectra_runner.py \
  backend/skills/spectrum_construction/uav_rem.py
```

3090 上已用真实服务验证：

```bash
POST http://127.0.0.1:8230/api/spectrum-construction/generate
POST http://127.0.0.1:8230/api/spectrum-construction/uav-rem/overview
```

## 下一步

| 优先级 | 任务 | 说明 |
| --- | --- | --- |
| P1 | 知识库覆盖扩展 | 部分业务（如卫星固定下行、业余 VHF）检索证据不足，需补充对应 ITU-R 文档的解析与索引。 |
| P1 | 频率规划结构化稳定性 | 个别场景业务名仍可能输出英文；持续优化 prompt 与字段后处理。 |
| P1 | Spectrum Construction 继续细化 | 支持更多分辨率模型逐个运行、错误提示和结果缓存。 |
| P1 | 资源分配结果验收 | 补齐页面验收、测试和 README 示例。 |
| P2 | 调制识别 / 干扰分析 | 等真实算法或数据上传后再接入。 |
