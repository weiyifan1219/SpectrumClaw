# SpectrumClaw 技术实现文档

本文聚焦后端核心技术细节，覆盖四条主线：**智能体工作流**、**技能系统**、**知识库（RAG）**、**记忆与进化**。前端仅作为展示层，不在本文展开。

> 阅读对象：需要理解系统如何运转、各子模块如何协作、关键算法如何落地的工程同学。

---

## 0. 系统总览

### 0.1 分层

| 层 | 目录 | 职责 |
| --- | --- | --- |
| API Service | `backend/app.py`, `backend/api/` | FastAPI 应用，挂载 chat / rag / memory / spectrum-construction / spectrum-decision 五组路由 |
| Agent Core | `backend/agent/` | LangGraph StateGraph，意图路由、RAG/工具/Web 节点、最终回答与记忆写入 |
| LLM Client | `backend/llm/` | 统一的多 provider 适配（OpenAI 兼容 / Anthropic 兼容）+ 工具循环 |
| Skills | `backend/skills/` | 频率规划、频谱构建、频谱决策三个能力单元 |
| Knowledge / RAG | `backend/rag/` | 文档解析、向量库、知识图谱、混合检索、流式问答 |
| Memory | `backend/memory/` | SQLite 记忆存储、技能审计、用户反馈、进化反思 |
| Tools | `backend/tools/` | 工具注册表 + LangChain Tool 适配 |

### 0.2 运行时模型

- 后端跑在 **3090 服务器**（`uvicorn backend.app:create_app --factory --port 8230`），前端本地 `vite dev`，通过 SSH 隧道（本地 8230 → 服务器 8230）连接。服务器**无外网**，模型与依赖均本地下载后上传。
- LLM 一律走**外部 API**（默认 DeepSeek，可切 OpenAI / Qwen / Anthropic 兼容端点），不部署本地大模型。
- 所有 LLM 调用收敛到 `backend/llm/client.py` 的 `chat()`（非流式，返回 `(reply, meta)`）和 `stream_chat()`（流式，yield SSE 事件）。

### 0.3 两套 Agent 运行时

`backend/agent/runtime.py` 用 `SPECTRUMCLAW_AGENT_RUNTIME` 环境变量在两条路径间切换：

- `legacy`：直接调 `llm.client.stream_chat`，保留可回滚的稳定路径。
- `langgraph`：走 `StateGraph`，接管意图路由、上下文聚合、记忆读写。

统一入口 `runtime.stream_chat()` 根据 `get_runtime()` 分发，对上层 API 透明。

### 0.4 端到端数据流（langgraph + RAG 问答为例）

```text
前端 → POST /api/chat/stream
     → runtime.stream_chat_langgraph
        → 读记忆（thread + domain/skill 跨线程）
        → router_node 判定 intent
        → rag_search_node 检索（Chroma+KW+Graph+Freq）
        → 注入记忆 + RAG 上下文到 system message
        → llm.client.stream_chat 流式生成（SSE token）
        → finalizer_node 汇总
        → _write_memory 落库（best-effort）
     → SSE: thinking / content / done
```

---

## 1. 智能体工作流（Agent Workflow）

### 1.1 LangGraph 图结构

定义在 `backend/agent/graph.py`，节点与边：

```text
router ──┬─(rag)──→ rag_search ──┐
         ├─(tool)─→ tool_executor┤
         ├─(web)──→ web_search ──┼─→ llm_answer ─→ finalizer ─→ END
         └─(chat)────────────────┘
```

- **入口**：`router`
- **条件边**：`route_after_router` 把 `user_intent` 映射到四个分支之一。
- **汇聚**：RAG / tool / web 三个节点统一回到 `llm_answer`，再到 `finalizer` 结束。
- 图用模块级单例 `get_graph()` 编译一次复用。

> 注意：`graph.py` 是标准的 StateGraph 定义；而 `runtime.py` 里的 `stream_chat_langgraph` 出于**流式输出**需要，手动按相同拓扑顺序驱动各节点（router → 分支节点 → 流式 llm → finalizer），以便在 `llm_answer` 阶段逐 token yield。两者拓扑一致，前者用于非流式编排，后者用于流式。

### 1.2 状态对象

`backend/agent/state.py` 的 `AgentState`（TypedDict）贯穿全流程，关键字段：

- `messages`：对话历史（OpenAI 消息格式）
- `user_intent`：router 判定结果（rag/tool/web/chat）
- `rag_results` / `citations`：检索命中与引用
- `memory_hits`：注入的记忆条目
- `memory_candidates`：本轮待写入的记忆（各节点累积）
- `skill_run`：本轮技能调用审计记录
- `final_answer` / `feedback_target_id`：最终回答 + 可供前端反馈的目标 id

`runtime._merge_state_update` 在手动驱动节点时合并状态：`logs` 和 `memory_candidates` 是**追加**语义，其余字段**覆盖**。

### 1.3 节点实现（`backend/agent/nodes.py`）

**router_node** — 基于关键词的轻量意图分类（无 LLM 开销）：
- `KB_KEYWORDS`（itu / 建议书 / 频谱 / mhz / 干扰…）→ `rag`
- `WEB_KEYWORDS`（天气 / 新闻 / 最新…）→ `web`
- `TOOL_KEYWORDS`（几点 / 时间 / 系统状态…）→ `tool`
- 都不命中 → `chat`

**rag_search_node** — 优先用 `MultimodalRetriever`（Chroma + 关键词 + 图 + 频率，包装成 LangChain `BaseRetriever`，`ainvoke`），失败回退到 TF-IDF retriever。命中后：
- 拼引用串、把检索上下文以 system message 追加到 `messages`
- 产出一条 `episodic` 记忆候选（记录查询和 top source）

**tool_executor_node** — 通过 `tools.registry` + LangChain `StructuredTool` 调内置工具（`get_time` / `get_system_status`），记录 `skill_run`（含 latency）和 `skill` 类记忆候选。

**web_search_node** — 走 Tavily（`web_search` handler），结果以 system message 注入。

**llm_answer_node** — 调 `llm.client.chat`，支持 thinking / reasoning_effort 透传。

**finalizer_node** — 兜底取回答、生成 `feedback_target_id`、追加"最终回答摘要"记忆候选。

### 1.4 记忆注入与回写（runtime 层）

`stream_chat_langgraph` 在节点之外做了两件记忆相关的事：

**读（phase 0）**：开局即查记忆——
- 当前线程的 thread-scoped 记忆（top_k 由 `memory_inject_top_k` 控制）
- 跨线程的 workspace 记忆（`domain` 2 条 + `skill` 2 条）
- 线程摘要（若有）
合并去重后存入 `memory_hits`，在 phase 2 拼成 `[系统记忆]` system message 插到消息最前。

**写（phase 4）**：回答流结束后调 `_write_memory`（best-effort，try/except 包裹，绝不阻塞响应）——
- 写 user/assistant 原始事件（对话历史审计）
- 把各节点产生的 `memory_candidates` 落成 `memory_items`
- RAG 结果落成 `rag` 事件
- 若有 `skill_run` 则记录技能调用

### 1.5 SSE 事件协议

`backend/agent/events.py` 定义事件类型，流式回答按序 yield：
- `thinking`：路由决策摘要（如 `路由决策: rag → router → rag_search`）
- `content`：逐 token 回答
- `done`：终局元数据（graph_nodes / citations / rag_results / runtime / thread_id / feedback_target_id）
- `error`：异常信息

前端按 `data: {json}\n\n` 解析。`done` 事件里的 `feedback_target_id` 是记忆反馈闭环的锚点。

---

## 2. 技能系统（Skills）

技能是 SpectrumClaw 的频谱能力单元，位于 `backend/skills/`。每个技能独立封装算法/模型调用，通过 `backend/api/` 下的路由对外暴露，并统一接入记忆审计（见 §4.2.3）。

当前三个技能：

| 技能 | 目录 | API 路由 | 引擎 |
| --- | --- | --- | --- |
| 频率规划 | `frequency_planning/` | （经 RAG）`/api/rag/*` | RAG 流水线 + 规则抽取 |
| 频谱构建 | `spectrum_construction/` | `/api/spectrum-construction/*` | Gudmundson 物理模型 + GenSpectra 外部推理 + UAV-REM 适配 |
| 频谱决策 | `spectrum_decision/` | `/api/spectrum-decision/allocate` | SLSQP 比例公平优化 + LLM Agent |

### 2.1 频率规划（Frequency Planning）

`skills/frequency_planning/planner.py` 是 RAG 的薄封装：把频段/区域/业务/国家拼成查询串，调 `rag.graph.workflow.run_rag_query`，再从回答里**规则抽取**结构化字段：

- `services`：关键词映射（mobile→Mobile Service 等 13 类业务）
- `constraints`：primary / secondary / not allocated / restricted…
- `footnotes`：正则 `5\.\d{3}[A-Z]?` 抽 ITU 脚注号

输出 `FrequencyPlanResult`（频段、区域、业务列表、分配状态、约束、脚注、相邻频段、引用、原始回答）。本质是"RAG 问答 + 后处理成结构化频谱规划卡片"。

### 2.2 频谱构建（Spectrum Construction）

两个独立子能力，对应 API `/generate` 与 `/uav-rem/overview`。

#### 2.2.1 Gudmundson 多分辨率预览（`generator.py`）

`build_multi_resolution_preview` 生成多分辨率（32/64/128/224）的频谱功率图预览：

1. **物理建模**：`GudmundsonMapGenerator` 用确定性随机数（`np.random.default_rng(seed)`）在 100×100 区域随机布放 `n_tx` 个发射机，按路径损耗模型计算每个网格点功率：
   - 自由空间因子 `k = (λ/4π)²`，`λ = c/freq`
   - 接收功率 `P_rx = Σ (P_tx·k) / d^path_loss_exp`（默认 `path_loss_exp=3.0`）
   - 输入功率单位 dBm，内部转自然单位（mW）计算，输出再转回 dB
2. **ViT patch 掩码**：`_fixed_patch_mask` 按分辨率对应的 patch 尺寸（32→2, 64→4, 128→8, 224→14）划格，按 `mask_ratio`（默认 0.75）随机遮挡 patch，模拟稀疏观测。
3. **可选推理**：`enable_inference=True` 时，把原始图通过 `subprocess` 交给外部 GenSpectra 运行器（`genspectra_runner.py`，用独立 conda 环境 `Agent_UAV` 的 python，避免主进程依赖 torch/timm），加载 `pretrain_GenSpectraLM_{res}.pth` checkpoint 做掩码重建，返回重建图 + RMSE。
4. **checkpoint 状态聚合**：`ready` / `partial` / `failed` / `pending_checkpoint` / `inference_disabled`，前端据此显示。

返回结构含每个分辨率的 `original` / `masked` / `observed_mask` / `reconstruction` / `rmse` / `source_positions` / `metrics`。

> 设计要点：物理模型在主进程跑（轻量、无 GPU 依赖），深度学习推理隔离到子进程（重依赖、需 checkpoint），二者解耦。checkpoint 缺失时优雅降级为"仅物理预览"。

#### 2.2.2 UAV-REM 适配器（`uav_rem.py`）

**只读适配** `/workspace/YiFan/Agent_UAV_REM` 的既有实验产物，不训练、不改动该项目。`build_uav_rem_overview`：

- 读 `final_comparison.csv` → 各方法（ABR / Radio_UNet / ViT / KNN / IDW / Kriging / DRUE / SBL_GP…）在不同采样率下的 RMSE 曲线，按 mean RMSE 排序
- 读 `abr/results.csv` → 主动采样策略效率
- 加载指定场景的 `.npz`（128×128×5 的 REM），取指定高度层，输出：真值图 / 稀疏采样图 / 重建图 / 误差图 / 观测掩码 / 建筑图 + RMSE、采样点数、覆盖率、无人机路径点
- 算法卡片：GeoBelief ABR（主动采样）、UAVSwinUNet2D（重建）、Coverage planner、传统基线

源目录不存在时返回 `available:false` 的占位结构，前端显示"等待产物"。

### 2.3 频谱决策（Spectrum Decision）

`/api/spectrum-decision/allocate` 支持两种模式（`use_agent` 区分）。

#### 2.3.1 核心优化器（`resource_allocator.py`）

**比例公平（Proportional Fairness）资源分配**，源自 WirelessAgent R1：

- **目标**：最大化 `Σ log(rate_i)`（等价于比例公平）
- **速率模型**：`rate = α·B·log10(1 + 10^(CQI/10))`（Shannon 式，α 为业务相关缩放因子）
- **约束**：
  - 总带宽 `Σ B_i = B`（等式约束）
  - 每用户速率 `rate_i ≥ R_min`（不等式约束）
  - 带宽边界 `B_min ≤ B_i ≤ B_max`（业务相关）
- **求解**：`scipy.optimize.minimize(method="SLSQP")`，最小化 `-Σ log(rate)`，maxiter=500
- **可行性检查**：先判断 `B_max` 下能否满足 `R_min`、总带宽是否够最小需求；不可行则走 `_fallback_allocation`（按 CQI 优先级贪心分配）
- **公平性度量**：Jain's fairness index `(Σr)² / (n·Σr²)`，范围 `[1/n, 1]`

**多业务混合**（`allocate_multi_service`）：把用户按业务（eMBB / URLLC / mMTC）分组，按用户数比例切分总带宽，各组独立跑 SLSQP，最后汇总吞吐与全局公平性。三类业务有不同的带宽/速率档位（eMBB 高吞吐、URLLC 低延迟小带宽、mMTC 海量小速率）。

#### 2.3.2 LLM Agent 模式（`agent.py`）

优化器是引擎，Agent 是智能助手，三步：

1. **意图解析** `parse_intent`：LLM 把自然语言（"给 20 个自动驾驶车辆分配 200MHz"）解析成结构化参数（num_users / total_bandwidth_mhz / environment / service_mix_desc / seed），输出 JSON。解析失败回退默认参数。
2. **运行优化器**：`generate_users` 按环境（urban/suburban/rural）和业务比例生成用户（含 CQI、SNR、距离、LOS、谱效率），跑 `allocate_multi_service`。
3. **结果解释** `explain_result`：LLM 用中文解释分配质量（公平性、吞吐效率、带宽分配模式、给运营商的建议）。

`service_mix_desc` 映射：embb_heavy（80/15/5）、urllc_heavy（20/70/10）、balanced（40/30/30）、default（60/30/10）。

### 2.4 技能的统一审计接入

每个领域技能 handler 都用 `backend/memory/hooks.py` 的 `track_skill_run` 上下文管理器包裹（详见 §4.2.3），自动记录技能名、入参、输出摘要、成败、耗时。例如 `/generate` 记 `spectrum_construction`、`/allocate` 记 `spectrum_decision` 或 `spectrum_decision_agent`（Agent 模式）。

---

## 3. 知识库（RAG）

知识库对标 [RAG-Anything](https://github.com/HKUDS/RAG-Anything)，覆盖**解析 → 向量化 + 知识图谱 → 混合检索 → 流式问答**全流程。语料是 ITU-R 系列文档（无线电规则、建议书、报告），约 5000+ PDF。

### 3.1 数据目录

`backend/rag/paths.py` 统一管理路径（`data/` 下）：

| 目录 | 内容 |
| --- | --- |
| `knowledge_base/raw/` | 原始 PDF |
| `mineru_cache/` | MinerU 解析缓存（`content_list.json` + `metadata.json`，按 doc_id 分目录） |
| `parsed/` | 结构化文档输出 + 资产 |
| `chroma/` | ChromaDB 向量库 |
| `graph/spectrum_graph.json` | 知识图谱（实体 + 关系） |
| `index/doc_registry.json` | 文档索引状态登记 |

### 3.2 解析层

#### 3.2.1 GPU 加速 MinerU 预解析（`preparse_gpu.py`）

原方案是 CLI subprocess-per-file，每个 PDF 都要重载 ~100s 模型。改造后用 **MinerU Python API + ModelSingleton**：模型加载一次进 GPU 显存，所有 PDF 复用，**约 8× 提速**。

流程（`_process_single_pdf`）：
1. `read_local_pdfs` 读入 → `dataset.classify()` 判断扫描件还是文本型
2. `doc_analyze(dataset, ocr=use_ocr)` 做版面分析（文本型走 txt 模式，扫描件走 OCR）
3. `pipe_txt_mode` / `pipe_ocr_mode` → `get_content_list` 输出结构化内容块

**离线适配**（服务器无外网）：设 `TRANSFORMERS_OFFLINE=1` / `HF_HUB_OFFLINE=1`，layoutreader 模型路径写进 `magic-pdf.json`，HF_HOME 指向本地缓存，避免运行时从 HuggingFace 下载。

**缓存机制**：doc_id = `md5(resolved_path)[:12]`，缓存校验比对文件 `size` + `mtime_ns`，命中则跳过。支持 `--shards`/`--shard-index` 多 worker 分片并行。原子写（`.tmp` → `replace`）防止半写。

#### 3.2.2 内容块模型（`schemas/block.py`）

`SpectrumContentBlock` 是多模态内容块，关键设计：
- **三层内容**：`raw_content`（原始）→ `content`（清洗）→ `enhanced_content`（语义增强，用于嵌入）
- **多模态资产**：`asset_path`（图）、`latex`（公式）、`table_markdown` / `table_rows`（表格）
- **溯源**：`content_hash`、`parser_name/version`、`processing_status`（raw→processed→enhanced→indexed）
- **图谱字段**：解析时抽取的 `entities` / `relations`
- 块类型：text / title / table / image / equation / footnote / chart / code 等

### 3.3 入库层（`ingest_from_cache.py`）

从 MinerU 缓存直接灌库，**不重新解析 PDF**：

1. `_discover_cached_docs` 扫描 `mineru_cache/`，加载 `content_list.json`
2. `_content_to_blocks` 转成 `SpectrumContentBlock`（过滤页码块）
3. `_separate_content` 拆分文本块 / 多模态块
4. **向量化入 Chroma**：`store.add_blocks` 用 bge-m3 嵌入，批量 200 条插入
5. **知识图谱抽取**（`_extract_entities_batch`，正则为主，省 LLM 成本）：
   - 频段：`(\d+)-(\d+)\s*(MHz|GHz|kHz|THz)` → `FrequencyBand` 实体
   - 标准：`ITU-R [A-Z].\d+` → `Standard` 实体
   - 脚注：`5.\d{3}[A-Z]?` → `Footnote` 实体
   - 文档实体 + `mentioned_in` 关系
6. `_merge_graph` 去重合并（实体按 (name,type)，关系按 (source,relation,target)）写 `spectrum_graph.json`
7. `doc_registry` 登记状态，支持断点续传（已 indexed 的跳过）

> 注：完整 LLM 实体抽取走 `pipeline.py` 的 `DocumentProcessor`（含多模态 VLM 分析），ingest_from_cache 是快速批量路径。

### 3.4 向量库（`vectorstores/chroma_store.py`）

ChromaDB 持久化，collection `spectrum_blocks`，HNSW + cosine 距离：
- `add_blocks`：嵌入 `enhanced_content or content`，metadata 含 doc_id/page_idx/block_type/source_path/section_path（Chroma 只支持标量，list 展平为逗号串）
- `search`：query 嵌入后取 top_k，距离转相似度 `score = 1 - min(dist, 1.0)`
- 禁用 PostHog 遥测（离线环境噪音）

### 3.5 嵌入（`embeddings/sentence_transformer.py`）

- 默认 **bge-m3**（本地 `models/embeddings/` 下，多语言、ITU 中英混合语料友好），找不到本地模型则尝试 `bge-small-en-v1.5`
- **离线兜底** `HashingEmbeddingProvider`：当 sentence-transformers 权重不可用时，用 md5 哈希投影到 384 维做确定性嵌入，保证 ingest/search 链路在无模型环境下仍能跑通（非生产级，仅验证用）
- 设备由 `SPECTRUMCLAW_EMBEDDING_DEVICE` 控制（ingest 默认 cuda）

### 3.6 检索层

#### 3.6.1 查询分析（`retrievers/query_analyzer.py`）

`SpectrumQueryAnalyzer` 规则抽取（中英双语，无 LLM 开销），从问题中提取：
- **频率范围**：正则匹配 `2300-2400 MHz` / `2300 MHz`
- **区域**：`Region 1/2/3`，或从国家名映射（中国→Region 3、USA→Region 2 等，含中英对照表）
- **业务**：Mobile / Fixed / Broadcasting / Satellite 等 13 类（关键词映射）
- **标准 / 脚注**：`ITU-R M.1036` / `5.388`
- **意图**：allocation_check / footnote_lookup / standard_lookup / interference_check / band_plan

输出 `QueryInfo`，驱动后续检索和重排的领域加权。

#### 3.6.2 三路混合检索

| 检索器 | 实现 | 命中 |
| --- | --- | --- |
| 向量 | `VectorRetriever` + ChromaStore | 语义相似块 |
| 关键词 | `KeywordRetriever`（BM25/TF-IDF） | 精确术语匹配 |
| 图 | `GraphRetriever` | 从图谱实体出发的关联块 |

`GraphRetriever`（`retrievers/graph_retriever.py`）：加载 `spectrum_graph.json`，用 QueryInfo 的频段/区域/业务/标准/脚注作为 search_terms，匹配实体名，返回这些实体相关的 `(entity, relation, target, evidence_block_id)` 三元组（上限 20）。

#### 3.6.3 重排（`retrievers/reranker.py`）

**规则加权重排**（领域知识驱动，非神经重排），在向量分基础上叠加：

| 加分项 | 权重 |
| --- | --- |
| 频率范围精确匹配 | +0.30 |
| 区域匹配 | +0.20 |
| 业务匹配 | +0.20 |
| 图谱实体命中 | +0.15 |
| 标准/脚注精确匹配 | +0.15 |
| footnote 块类型 | +0.15 |
| table 块类型 | +0.10 |
| 来源权威性（R-REC/Rec.） | +0.05 |

分数 clamp 到 1.0，按 rerank_score 降序取 top_k。设计意图：ITU 频谱查询里"频段/区域/业务三要素精确命中"远比语义相似重要，所以给重权。

#### 3.6.4 上下文打包（`retrievers/context_packer.py`）

`ContextPacker.pack`：
- 按 block_id 去重 → 同 doc+page 的块合并（`\n---\n` 连接）
- 限制 max_blocks=15、max_tokens≈4000（1 token≈4 字符粗估）
- 每块加 `[n] source (p.X, type, score)` 标号，生成 LLM-ready context + 去重引用列表

### 3.7 流式问答（`graph/stream.py`）

`stream_rag_query` 是 async generator，按阶段 yield SSE 事件：

```text
stage query_analysis → stage_done
stage retrieval (vec+kw+graph 并行) → stage_done {counts}
stage rerank → stage_done {count}
pack context
stage answer → content (逐 token) → stage_done
[记忆写入 best-effort]
done {citations, debug}
```

- 检索三路各自 try/except，单路失败不影响其他
- 答案生成调 `stream_chat` 逐 token 流出；无 context 时返回友好提示
- **结尾写记忆**（§4.2.2）：成功/失败/异常三个出口都调 `_record_rag_memory`，best-effort

#### 3.7.1 非流式入口

`graph/workflow.py` 的 `run_rag_query` 用真正的 LangGraph StateGraph（节点见 `graph/nodes.py`：analyze_query → retrieve_vector/keyword/graph → rerank → pack_context → generate_answer，可选 multimodal VLM 分析）。流式版（stream.py）为逐 token 输出手动展开同一拓扑。

### 3.8 知识图谱 API（`api/rag.py`）

- `GET /api/rag/graph/entities`：按类型/搜索词过滤实体 + 相关关系
- `GET /api/rag/graph/entity/{name}`：单实体及其全部关系（含关联实体类型解析）
- `GET /api/rag/status`：doc_registry 统计 + Chroma/Graph 健康 + 入库进度事件

> 知识图谱的交互式可视化（前端）规划对标 RAG-Anything，当前为后续迭代项。

---

## 4. 记忆与进化（Memory & Evolution）

这是系统"真正在进化"的核心：智能体在实际运行中**自动积累记忆和技能成败**，累积用户反馈，再通过**手动触发反思**让 LLM 回看近期数据，产出进化报告 + 改进建议。不是 seed 占位数据，而是从真实经验里学习。

### 4.1 存储设计

**双层存储分离**：

| 数据 | 位置 | 说明 |
| --- | --- | --- |
| 记忆库 | `data/memory/spectrum_memory.sqlite3` | 全部记忆、事件、技能审计、反馈、报告 |
| 进化报告（额外导出） | `data/evolution/<report_id>.json` | 每份报告的可读 JSON 副本（含完整聚合 metrics + 原始数据） |

记忆留在 SQLite 便于查询统计，进化报告额外落 JSON 便于人工查阅和归档。

#### 4.1.1 数据模型（`memory/models.py`，Pydantic）

| 模型 | 表 | 关键字段 |
| --- | --- | --- |
| `MemoryThread` | memory_threads | thread_id, summary, turn_count |
| `MemoryEvent` | memory_events | event_type(user/assistant/tool/rag/error/feedback/system), content |
| `MemoryItem` | memory_items | **kind**(episodic/skill/domain/evolution), text, confidence, tags |
| `SkillRun` | skill_runs | skill_name, status, latency_ms, error, rag_refs |
| `MemoryFeedback` | memory_feedback | target_type, target_id, rating(-1~5), comment |
| `EvolutionReport` | evolution_reports | period, summary, metrics_json, suggestions_json, status |

四种记忆 kind：
- `episodic`：情景记忆（某次查询/对话发生了什么）
- `skill`：技能相关记忆
- `domain`：领域知识沉淀（跨线程复用）
- `evolution`：进化相关

#### 4.1.2 存储层（`memory/store.py`）

纯 sqlite3（无 ORM），线程安全（`threading.Lock` + WAL 模式）。提供 CRUD + 聚合：
- `query_items`：按 kind/thread/skill/tag 过滤
- `list_skill_runs` / `skill_run_stats`：技能审计与按技能聚合（total/success/avg_latency）
- `list_feedback` / `list_reports` / `insert_report`
- `overview`：全库统计快照

`memory/service.py` 是薄服务层，**所有写方法 try/except 返回，绝不抛异常**——记忆失败永不阻塞主流程。

### 4.2 运行时自动写记忆

记忆系统接入了三条真实工作链路（这是本次实现把"孤岛存储"变成"活数据"的关键）：

#### 4.2.1 LangGraph 聊天路径（`agent/runtime.py`，已有）

`_write_memory`（phase 4，回答流结束后）：写对话事件、memory_candidates、RAG 结果事件、skill_run。读侧在开局注入 thread + domain/skill 记忆（§1.4）。

#### 4.2.2 RAG 查询路径（`rag/graph/stream.py`，本次新增）

`_record_rag_memory` 在 stream 的 done / except 出口调用，写两条：
- **episodic 记忆**：`RAG查询: {问题} → 命中{N}块, 主来源{source}`，tags=`["rag", radio_service]`，成功 confidence=0.7 / 失败 0.3
- **skill_run**：`skill_name="rag_query"`，output_summary=`命中{N}块, vec/kw/graph={a}/{b}/{c}`，记 latency、citations 作为 rag_refs、成败状态

全程 best-effort try/except，不影响回答流。

> **验证结果**：真实发起一次 RAG 查询后，`/api/memory/skill-runs?skill_name=rag_query` 立即出现新记录（input=真实问题、output=命中块数与三路计数、latency 真实），episodic 记忆同步写入。闭环已跑通。

#### 4.2.3 领域技能路径（`memory/hooks.py`，本次新增）

`track_skill_run` 上下文管理器，给 API handler 统一计时 + 成败捕获：

```python
with track_skill_run("spectrum_construction", input_data=req.model_dump()) as run:
    result = build_multi_resolution_preview(...)
    run["output_summary"] = f"variant=..., resolutions=..."
    return result
```

- 进入时记起始时间，退出时记 `SkillRun`（成功/异常都记，异常会标 failed 并重抛）
- 持久化失败被吞掉，不影响 API 响应

已接入：`/generate`（spectrum_construction）、`/uav-rem/overview`（uav_rem_overview）、`/allocate`（spectrum_decision，Agent 模式记 spectrum_decision_agent）。

> **验证结果**：调用后 `skill_run_stats` 真实累积——spectrum_construction total=8/success=7、uav_rem_overview total=4/success=4、rag_query total=4 等，每条带真实平均延迟。

### 4.3 进化反思（`memory/reflector.py`，本次新增）

核心 `async def generate_evolution_report(hours=168)`，四步：

**1. 聚合**（`_aggregate`）：拉最近 N 小时的 skill_runs / feedback / episodic，计算：
- 全局：技能调用数、成功率、平均评分、反馈数、情景记忆数
- **per_skill 拆分**：每个技能的 total/success/failed/success_rate/avg_latency_ms + 失败错误样本
- 原始数据：低分反馈评论、失败案例、近期查询主题

**2. LLM 合成**（`_llm_synthesize`）：把聚合数据塞进中文 prompt，要求 LLM 严格输出 JSON：
```json
{"summary": "一段话总结本周期表现与问题",
 "suggestions": [{"priority": "high|medium|low", "action": "具体改进建议"}]}
```
`_extract_json` 容错解析（裸 JSON / markdown fence / 前后散文都能抠出）。

**3. 规则兜底**（`_fallback_report`）：LLM 不可用或 JSON 解析失败时，直接用聚合 metrics 拼基础报告——对失败技能、低评分自动生成改进建议。**保证反思永远产出报告**。

**4. 持久化 + 导出**：构造 `EvolutionReport`（report_id=`rpt_{uuid12}`，status=pending），写 SQLite，并 `_export_json` 导出到 `data/evolution/<id>.json`（含完整 metrics + 原始聚合）。

> **验证结果**：`POST /api/memory/reflect?hours=168` 返回真实 report_id，summary 基于真实数据（"10 次技能调用，成功率 80%…"），per_skill 准确拆出 rag_query 失败原因（"No vectors in collection"）、spectrum_construction 失败原因（"checkpoint not found"）。JSON 文件成功导出，报告入列 `/api/memory/reports`。这正是"从真实运行经验里反思"。

### 4.4 反馈闭环

- `POST /api/memory/feedback`：对回答打分（target_id 即回答的 `feedback_target_id`，由 finalizer 生成）
- 反馈进 `memory_feedback` 表 → 下次反思时 `avg_rating` + 低分评论被纳入分析 → LLM 据此提改进建议

### 4.5 记忆 API（`api/memory.py`）

| 端点 | 用途 |
| --- | --- |
| `GET /api/memory/overview` | 全库统计 + skill_stats + 报告列表 |
| `GET /api/memory/items` | 按 kind/thread/skill/tag 查记忆 |
| `GET /api/memory/threads/{id}` | 线程详情（事件 + 记忆） |
| `GET /api/memory/skill-runs` | 技能审计记录 |
| `GET /api/memory/reports` | 进化报告列表 |
| `POST /api/memory/feedback` | 提交反馈 |
| `POST /api/memory/reflect?hours=N` | **手动触发反思**（本次新增） |

### 4.6 进化闭环全景

```text
真实运行
  ├─ RAG 查询      → episodic 记忆 + rag_query skill_run
  ├─ 领域技能调用  → skill_run（成败/延迟/错误）
  ├─ 对话          → 事件 + 记忆候选 + 线程摘要
  └─ 用户反馈      → feedback（评分 + 评论）
        ↓ 积累进 SQLite
  手动触发 POST /api/memory/reflect
        ↓ 聚合最近 N 小时
  _aggregate（per_skill 成败/延迟/错误 + 反馈 + 查询主题）
        ↓
  LLM 合成报告（JSON）  ──失败──→ 规则兜底报告
        ↓
  写 SQLite + 导出 data/evolution/<id>.json
        ↓
  前端「触发反思」按钮展示新报告 + 改进建议
```

系统据此形成"积累 → 反思 → 改进建议"的进化回路：跑得越多，反思的数据基础越扎实，建议越有针对性。

---

## 5. 部署与环境要点

- 后端在 3090 跑：`uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8230`
- 前端本地 vite，经 SSH 隧道（本地 8230 → 3090 8230）连后端
- **服务器无外网**：依赖通过本地下载 cp310 wheel 后上传离线安装（如 langchain_core 1.4.0 链路所需的 uuid_utils / xxhash / jiter / zstandard / mmh3 / ormsgpack / langgraph-checkpoint / langgraph-prebuilt）
- LLM 走外部 API（默认 deepseek-v4-pro），不部署本地大模型
- 记忆/进化、技能审计全部 best-effort，失败不阻塞主响应

### 5.1 离线 LLM 接入（反向隧道方案）

服务器无外网，**无法直连 `api.deepseek.com`**（DNS FAIL、curl http=000），且无内网代理出口。RAG 回答生成、进化反思的 LLM 合成都依赖外部 API。解决方案是**本地反向隧道转发**：

```text
服务器 backend (DEEPSEEK_BASE_URL=http://127.0.0.1:8240/v1)
   → SSH 反向隧道 (ssh -R 8240:127.0.0.1:8240)
      → 本地转发代理 (scripts/llm_forward_proxy.py, 监听 127.0.0.1:8240)
         → https://api.deepseek.com  （本地可联网）
```

三个组件：

1. **本地转发代理** `scripts/llm_forward_proxy.py`：Starlette + httpx 透明转发，监听 `127.0.0.1:8240`，把任意路径原样转发到 `UPSTREAM`（默认 deepseek），保留 method/body/Authorization，**流式回传**（SSE-friendly，支持逐 token）。
2. **SSH 反向隧道**：`ssh -N -R 8240:127.0.0.1:8240 -o ServerAliveInterval=30 <server>`，把本地 8240 暴露到服务器 `127.0.0.1:8240`。
3. **服务器 `.env`**：加 `DEEPSEEK_BASE_URL=http://127.0.0.1:8240/v1`，让 deepseek profile 指向隧道（仅服务器侧，本地 `.env` 不变）。

> 验证：服务器 `curl 127.0.0.1:8240/v1/models` 返回 200 + 真实模型列表；RAG stream 逐 token 输出中文回答；reflect 返回 LLM 合成的 summary + 带优先级的改进建议（不再走规则兜底）。
>
> 注意：本地代理 + 隧道需常驻；本地断网或进程退出则服务器 LLM 调用失败（但 best-effort 设计保证不会 crash，RAG/reflect 会回落到友好提示 / 规则兜底）。
