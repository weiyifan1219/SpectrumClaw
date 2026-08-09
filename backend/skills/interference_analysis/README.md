# Interference Analysis Skill

该模块提供频率规划智能体使用的确定性工程干扰初筛能力，核心实现为 `analyzer.py`。

后续接入时建议保持以下边界：

| 项 | 建议 |
| --- | --- |
| 输入 | 频段、发射功率、带宽、覆盖半径、传播场景、天线/接收机参数和已知干扰源。 |
| 计算 | 覆盖边缘链路预算、热噪声、同频/邻频/带外耦合、线性功率聚合、三阶互调候选。 |
| 输出 | 可用性、风险等级、SINR/裕量、干扰发现、避让范围、候选信道、依据和局限。 |
| 审计 | 使用 `track_skill_run("interference_analysis", ...)`。 |
| Agent | 由 `/api/frequency-planning/agent/stream` 编排，并作为 `analyze_interference` 内部工具注册。 |

该结果定位为透明、可复核的工程初筛，不替代设备 ACLR/ACS/ACIR 实测、地形射线追踪、台站协调或监管指配。
