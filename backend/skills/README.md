# Backend Skills

每个频谱任务模块按目录隔离，API 层负责输入校验、审计和对外暴露。

| 目录 | 状态 | 说明 |
| --- | --- | --- |
| `frequency_planning/` | 可用 | RAG 频率规划封装，抽取业务、脚注、约束等结构化字段。 |
| `spectrum_construction/` | 可用 | Gudmundson 物理图、GenSpectra 重建、UAV REM 只读适配。 |
| `spectrum_decision/` | 可用 | CQI-Shannon + SLSQP 比例公平资源分配，支持 LLM agent。 |
| `situation_building/` | 兼容占位 | 历史名称，真实实现见 `spectrum_construction/`。 |
| `interference_analysis/` | 预留 | 尚无真实算法。 |
| `modulation_recognition/` | 预留 | 尚无真实模型。 |

可执行 skill 应通过 `backend.memory.hooks.track_skill_run()` 记录审计。
