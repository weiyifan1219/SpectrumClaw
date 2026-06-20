# Interference Analysis Skill

预留模块，当前没有真实干扰分析算法或 API。

后续接入时建议保持以下边界：

| 项 | 建议 |
| --- | --- |
| 输入 | 频段、发射功率、带宽、地理/拓扑参数、业务类型和干扰类型。 |
| 输出 | 干扰类型、风险等级、受影响业务、依据、建议和可视化产物。 |
| 审计 | 使用 `track_skill_run("interference_analysis", ...)`。 |
| API | 新增 `backend/api/interference_analysis.py` 并在 `backend/app.py` 注册。 |
