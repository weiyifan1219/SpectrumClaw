# Frequency Planning Skill

该目录提供频率规划的兼容 RAG 封装与领域智能体编排。

## 当前实现

| 路径 | 说明 |
| --- | --- |
| `agent.py` | 主路径：理解自然语言或结构化参数，调用干扰分析工具，检索 ITU 证据，调用当前真实模型综合结论，并由系统计算可信度。 |
| `planner.py` | 兼容路径：保留原有纯 RAG 查询及规则后处理，输出 `FrequencyPlanResult`。 |
| `../interference_analysis/analyzer.py` | 透明的工程初筛模型：链路预算、同频/邻频/带外、互调候选、候选信道与避让范围。 |

前端主路径使用 `/api/frequency-planning/agent/stream`。`agent.py` 依次执行意图理解、干扰工具、ITU-R RAG、真实 LLM 综合规划和系统置信度评估；旧 `/api/rag/frequency_plan/stream` 继续保留，供兼容和纯 RAG 查询使用。当原有向量/关键词索引不可用时，频率规划 profile 会从 `data/parsed` 的页级解析缓存进行只读词法检索，保留来源与页码，并在可信度中对该降级路径设置上限。
