# Modulation Recognition Skill

预留模块，当前没有真实调制识别模型或 API。

后续接入时建议：

| 项 | 建议 |
| --- | --- |
| 输入 | IQ 数据、频谱图、采样率、中心频率和任务上下文。 |
| 输出 | 调制类别、置信度、关键特征、可视化和模型版本。 |
| 模型隔离 | 重依赖推理环境可通过 sidecar 或子进程隔离。 |
| 审计 | 使用 `track_skill_run("modulation_recognition", ...)`。 |
