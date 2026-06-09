# 计划：统一增量数据入库接口（Universal Ingestion Interface）

> 状态：**待实现**（本文档只描述技术路线与接口设计，不含实现）
> 创建：2026-06-09
> 关联：`backend/rag/ingest_from_cache.py`、`backend/rag/ingest.py`、`backend/api/rag.py`、技术文档 §3（知识库 RAG）

---

## 1. 背景与动机

当前知识库的所有入库路径都**假设输入是 PDF**：

| 现有入口 | 路径 | 引擎 | 局限 |
| --- | --- | --- | --- |
| `POST /api/rag/upload` | 单 PDF 上传 | DocumentProcessor（LLM/VLM 抽取） | 仅 PDF |
| `POST /api/rag/index` | 一批 PDF 路径 | DocumentProcessor | 仅 PDF |
| `ingest_from_cache.py` (CLI) | MinerU 缓存批量 | 正则抽取（快） | 仅 PDF→MinerU 缓存 |

但项目后续要持续添加**各类数据**——不只是 ITU-R PDF，还可能有：
- 结构化频谱分配表（CSV / Excel / 数据库导出）
- 网页 / HTML 抓取内容
- 其他格式文档（Word、Markdown、纯文本）
- 外部 API 返回的结构化数据（如 ITU 在线数据库）
- 人工录入的领域知识条目

这些数据若都要先转成 PDF 再走解析链路，既浪费又有损信息。需要一个**与来源/格式解耦的统一增量入库接口**：任何数据源只要能转成标准内容块，就能直接向量化 + 建图谱入库。

---

## 2. 设计目标

1. **来源无关**：输入是已结构化的内容块列表，不关心它从 PDF / CSV / 网页 / API 哪来。
2. **增量友好**：复用现有 `doc_registry` 去重续传机制，重复入库自动跳过，新增数据只处理增量。
3. **复用现有组件**：不重造轮子，直接用 `SpectrumContentBlock`、`ChromaStore.add_blocks`、`_extract_entities_batch` + `_merge_graph`。
4. **双引擎可选**：实体抽取支持「正则（快）」和「LLM（准）」两种模式，由调用方按数据重要性选择。
5. **API + CLI 双入口**：既能被前端/外部系统通过 HTTP 调用，也能在服务器批处理。
6. **不破坏现有链路**：PDF 的 upload/index 路径保持不变，新接口与之并存。

---

## 3. 技术路线

### 3.1 核心抽象：来源适配器 → 标准块 → 入库核

```text
各类数据源                  适配器(Source Adapter)         入库核(Ingest Core)
─────────                  ────────────────────          ──────────────────
PDF/MinerU缓存   ┐
CSV/Excel        │
HTML/网页        ├──→  to_blocks() ──→ list[SpectrumContentBlock] ──→ ingest_blocks()
Word/Markdown    │         （每种源一个适配器）                  │
外部API/DB       │                                              ├─ doc_registry 去重
人工条目         ┘                                              ├─ ChromaStore.add_blocks（向量化）
                                                                ├─ 实体抽取（regex | llm）
                                                                └─ _merge_graph（建图）
```

**关键：把 `ingest_from_cache.py` 里 per-doc 的入库逻辑（第 296-330 行）抽出来**，成为一个不依赖 MinerU 缓存的纯函数 `ingest_blocks()`。现有 `ingest_from_cache` 改为「MinerU 缓存适配器 + 调用 ingest_blocks」。

### 3.2 入库核函数（新增 `backend/rag/ingest_core.py`）

```python
async def ingest_blocks(
    blocks: list[SpectrumContentBlock],
    *,
    doc_id: str,
    source_path: str,           # 逻辑来源标识（URL / 文件名 / "manual:xxx"）
    source_type: str = "generic",  # pdf | csv | html | manual | api | ...
    entity_mode: str = "regex",  # regex（快） | llm（准） | none
    clear: bool = False,
    store=None, emb=None,        # 可注入，便于复用已加载的模型
) -> IngestResult:
    """来源无关的增量入库核：向量化 + 建图，带 doc_registry 去重。"""
```

- 复用 `register_doc` / `is_cached` / `update_status`（doc_registry）做增量去重
- 复用 `store.add_blocks`（向量化入 Chroma）
- `entity_mode=regex` → 复用 `_extract_entities_batch`；`=llm` → 走 DocumentProcessor 的 LLM 抽取；`=none` → 跳过建图
- 复用 `_merge_graph` 写图谱
- 返回 `IngestResult(doc_id, blocks, vectors, entities, relations, skipped, errors)`

### 3.3 来源适配器（新增 `backend/rag/adapters/`）

每种数据源一个适配器，职责单一：**把原始数据转成 `list[SpectrumContentBlock]`**。

| 适配器 | 文件 | 输入 | 块类型映射 |
| --- | --- | --- | --- |
| MinerU 缓存 | `adapters/mineru.py`（迁移现有逻辑） | content_list.json | 现有 _content_to_blocks |
| 表格 | `adapters/tabular.py` | CSV/Excel/DataFrame | 每行→table_row，表头→table |
| HTML | `adapters/html.py` | URL/HTML 字符串 | 段落→text，表格→table |
| 纯文本/MD | `adapters/text.py` | txt/md | 按标题分段→text/title |
| 人工条目 | `adapters/manual.py` | dict/JSON | 直接构造 block |

`SpectrumContentBlock.create()` 已是通用工厂，适配器只需填 doc_id/source_path/block_type/content 等字段。

### 3.4 API 接口（扩展 `backend/api/rag.py`）

```python
class IngestBlocksRequest(BaseModel):
    source_type: str = "generic"
    source_id: str                      # 逻辑来源标识
    blocks: list[dict]                  # 已结构化的块（含 content/block_type/page_idx 等）
    entity_mode: str = "regex"          # regex | llm | none

@router.post("/ingest")                 # 通用增量入库（来源无关）
async def handle_ingest_blocks(req: IngestBlocksRequest): ...

@router.post("/ingest/tabular")          # 便捷：上传 CSV/Excel 直接入库
async def handle_ingest_tabular(file: UploadFile, source_id: str): ...

@router.post("/ingest/url")              # 便捷：抓取 URL 入库
async def handle_ingest_url(url: str): ...
```

- `/ingest` 是底层通用入口：调用方自己把数据转成 blocks dict 传入
- `/ingest/tabular`、`/ingest/url` 是便捷封装：服务端用对应适配器转换后调 `ingest_blocks`
- 全部复用 §3.2 的入库核，返回统一 `IngestResult`

### 3.5 CLI（扩展，便于批量）

```bash
# 现有（保持）
python -m backend.rag.ingest_from_cache --clear

# 新增：通用批量入库
python -m backend.rag.ingest_batch --source-type csv --input data/tables/*.csv --entity-mode regex
python -m backend.rag.ingest_batch --source-type html --input urls.txt
```

---

## 4. 实施步骤（后续实现时按序）

1. **抽核**：从 `ingest_from_cache.py` 提取 `ingest_blocks()` 到 `backend/rag/ingest_core.py`，现有脚本改为调用它（保证行为不变，跑回归）。
2. **建适配器目录**：`backend/rag/adapters/`，先迁移 MinerU 适配器（`_content_to_blocks` → `adapters/mineru.py`）。
3. **加表格适配器**：`adapters/tabular.py`（CSV/Excel→blocks），这是最高频的「各类数据」需求。
4. **加 API `/ingest`**：通用块入库端点 + `IngestResult` schema。
5. **加便捷端点**：`/ingest/tabular`、`/ingest/url`，按需。
6. **加 CLI `ingest_batch`**：通用批量入口。
7. **文档**：更新技术文档 §3，把统一入库写入知识库章节。

---

## 5. 复用清单（已有，无需重写）

| 能力 | 现有实现 | 位置 |
| --- | --- | --- |
| 通用内容块模型 | `SpectrumContentBlock` | `rag/schemas/block.py` |
| 向量化入库 | `ChromaStore.add_blocks` | `rag/vectorstores/chroma_store.py` |
| 嵌入（bge-m3） | `_build_embedding_provider` | `rag/embeddings/` |
| 正则实体抽取 | `_extract_entities_batch` | `rag/ingest_from_cache.py` |
| LLM 实体抽取 | `DocumentProcessor` | `rag/pipeline.py` |
| 图谱合并去重 | `_merge_graph` | `rag/ingest_from_cache.py` |
| 增量去重续传 | `register_doc` / `is_cached` / `update_status` | `rag/doc_registry.py` |

> 核心工作量在「抽核 + 适配器」，入库/向量/图谱/去重全部复用现有组件。预估实现成本中等。

---

## 6. 风险与注意

- **嵌入一致性**：新数据必须用与现有库相同的嵌入模型（bge-m3），否则向量空间不一致。入库核应共享 `_build_embedding_provider`。
- **block_id / doc_id 唯一性**：非 PDF 来源需保证 doc_id 稳定可复现（如 `md5(source_id)`），供 doc_registry 去重。
- **图谱实体抽取的领域性**：现有正则是为 ITU 频谱定制（频段/标准/脚注）。非频谱数据可能需要不同抽取规则，`entity_mode` 留出扩展点。
- **不阻塞主链路**：入库是后台/异步操作，API 端点对大批量应支持异步任务（参考现有 ingest 后台跑 + 日志模式）。
