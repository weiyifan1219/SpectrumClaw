# Frequency Planning Skill

该目录提供频率规划的后端封装。核心文件为 `planner.py`。

## 当前实现

| 项 | 说明 |
| --- | --- |
| 输入 | `frequency_band`、`region`、`service`、`country`、`constraints`。 |
| 核心 | 拼接频谱规划 query，调用 `backend.rag.graph.workflow.run_rag_query()`。 |
| 后处理 | 从回答中规则抽取业务类型、primary/secondary/not allocated 等约束和 ITU 脚注号。 |
| 输出 | `FrequencyPlanResult`，包含 answer、citations、services、constraints、footnotes 等。 |

前端主路径目前使用 `/api/rag/frequency_plan/stream`，该 skill 可用于非流式或后续结构化 API。
