# Skills

每个频谱任务模块都按 skill 目录隔离。当前状态如下：

| 目录 | 状态 | 说明 |
| --- | --- | --- |
| `frequency_planning/` | 可用 | 封装 RAG 频率规划结果。 |
| `spectrum_construction/` | 已接入 | Gudmundson 数据生成、GenSpectra 重建、Agent_UAV_REM 结果读取。 |
| `situation_building/` | 兼容占位 | 历史路径保留；新实现使用 `spectrum_construction/`。 |
| `spectrum_decision/` | 已接入 | 多用户资源分配优化器和可选 agent 包装。 |
| `modulation_recognition/` | 预留 | 等真实模型或数据。 |
| `interference_analysis/` | 预留 | 等真实算法或数据。 |
