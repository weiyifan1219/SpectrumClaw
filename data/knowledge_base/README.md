# Knowledge Base Data

`data/knowledge_base/` 是知识库源文件与轻量索引占位目录。当前主 RAG 数据路径已经统一到 `backend/rag/paths.py`：

| 路径 | 说明 |
| --- | --- |
| `data/knowledge_base/raw/` | 原始 PDF 放置目录，也可通过 `/api/rag/upload` 上传到 uploads。 |
| `data/parsed/` | MinerU/PyPDF 等解析输出。 |
| `data/chroma/` | ChromaDB 向量库。 |
| `data/graph/spectrum_graph.json` | 频谱知识图谱。 |
| `data/index/doc_registry.json` | 文档 registry。 |

## 当前规模

| 指标 | 数值 |
| --- | --- |
| 去重后 PDF | 4,656 个成功解析，2 个超大文件失败/待单独处理。 |
| Chroma vectors | 1,399,856 |
| 图谱实体 | 9,239 |
| 图谱关系 | 16,259 |
| 解析引擎 | MinerU 3.3.0 pipeline |

大型原始资料、向量库、图谱和 parsed 缓存体积较大，开源分发时应按 `.gitignore` 和数据发布策略处理。
