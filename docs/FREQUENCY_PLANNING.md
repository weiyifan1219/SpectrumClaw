# 频率规划模块设计

## 目标

第一阶段实现一个基础频率规划助手：用户通过对话提出频率规划问题，系统从 ITU 资料库中检索相关材料，再调用 LLM API 生成带引用的建议。

## 资料库

| 项目 | 路径 |
| --- | --- |
| 原始压缩包 | `/home/lenovo/workspace/SpectrumClaw/itu_documents.zip` |
| 后续解压目录 | `data/knowledge_base/raw/itu/` |
| 后续索引目录 | `data/knowledge_base/index/itu/` |
| 后续图谱目录 | `data/knowledge_base/graph/itu/` |

当前不解压、不索引，只规划。

## MVP 流程

```text
User question
  -> normalize query
  -> retrieve relevant chunks from ITU documents
  -> rerank or filter
  -> LLM API generates answer
  -> return answer + citations + result artifact
```

## RAG 策略

| 阶段 | 方案 |
| --- | --- |
| MVP-1 | PDF 文本抽取 + chunk + TF-IDF / embedding 可选 |
| MVP-2 | 增加 metadata、文档类别、标准编号过滤 |
| MVP-3 | 参考 RAG-Anything，引入多模态文档解析和结构化知识 |
| MVP-4 | 抽取实体关系，构建频谱知识图谱 |

## 输出格式

| 输出 | 内容 |
| --- | --- |
| `result.md` | 建议方案、依据、限制和下一步 |
| `metadata.json` | query、文档引用、模型、时间、参数 |
| `citations.json` | 文档名、页码、chunk id、得分 |

## API 预留

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/frequency-planning/query` | 提交频率规划问题 |
| `POST` | `/api/knowledge/index` | 后续构建知识库索引 |
| `POST` | `/api/knowledge/search` | 检索 ITU 文档 |

## 当前不做

- 不构建知识图谱。
- 不做复杂数据流编排。
- 不把频率规划和态势构建联动。
- 不在本轮连接服务器。
