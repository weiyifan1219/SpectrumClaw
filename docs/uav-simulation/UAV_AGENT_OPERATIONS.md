# 无人机任务智能体操作说明

## 范围

本模块仅面向当前 PX4 SITL + Gazebo 仿真。自然语言、固定模板和 MCP 都只能产生声明式 `MissionPlan`，不能发送原始坐标、速度、MAVLink、Shell 或真实飞行器指令。频谱态势、信号源推理和真实设备接入仍是预留接口，当前不参与任务决策。

## 执行流程

```text
自然语言 / 固定任务 / MCP
          -> 受限计划编译与 DeepSeek 提案校验
          -> MissionPolicy 预检
          -> 人工明确批准
          -> UavMissionService -> PX4/Gazebo
          -> 审计、状态与任务报告
```

| 阶段 | 页面状态 | 可执行操作 | 终态 / 处理 |
| --- | --- | --- | --- |
| 草案 | `awaiting_approval` | 查看计划、拒绝或批准 | 策略拒绝为 `rejected` |
| 运行 | `running` | 观察公开日志、取消、人工 WASD 接管 | 接管立即清除导航目标 |
| 成功 | `completed` | 查看报告和轨迹 | 安全终点悬停或模板定义的终端动作 |
| 受控终止 | `cancelled` | 查看取消原因 | 请求悬停 |
| 异常 | `failed` / `interrupted` | 查看错误码后重新建任务 | 超时、桥断开、服务重启均不续飞 |

## 固定任务

`inspect_safe_perimeter`、`collect_camera_evidence`、`search_safe_route`、`takeoff_and_hover`、`hover`、`land`、`return_to_launch` 是当前唯一允许的任务模板。涉及拍摄的任务仅能选用 `north_gate`、`south_gate`、`east_gate`、`west_gate` 等已知安全地标。所有导航均由服务端写入预审目标，并由 Gazebo 实际位姿确认到达。

## 运行记录与排障

每次任务写入 `data/uav-agent-runs/<run_id>/`：`mission_plan.json`、`mission_program.json`、`planner_record.json`、`run_state.json` 与 `report.md`。该目录是非可执行沙箱，未列入白名单的文件（例如 Python、Shell、MAVLink 脚本）不能写入。页面和 SSE 只展示可审计的事实摘要，不展示或存储模型的隐藏推理。

出现人工接管、PX4/导航桥超时、相机状态异常或编排服务重启时，应以 `run_id`、`trace_id` 查询任务记录；确认无人机处于悬停或已降落后，再创建新草案，不能恢复旧任务继续飞行。
