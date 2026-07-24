# 无人机 MCP 飞控适配层

## 目标

将 SpectrumClaw 中的无人机仿真能力以 MCP 工具公开，同时保留网页人工遥控。MCP 是**标准接入层**，而不是另一条直连 PX4/MAVLink 的控制通道。

```text
SpectrumClaw 内置智能体     外部 MCP Host（后续 Codex / Claude / 其他智能体）
           │                              │
           └──────────┬───────────────────┘
                      ▼
       UavMissionService（任务、状态、安全边界）
                      ▼
        runtime.execute_vehicle_command（唯一 PX4 适配器）
                      ▼
             PX4 MAVLink → Gazebo 仿真

浏览器 WASD ──人工接管──► PX4 手动控制桥
```

## 当前 MCP 工具

| 工具 | 作用 | 安全限制 |
| --- | --- | --- |
| `uav_get_state` | 读取仿真、人工接管、真实 Gazebo 位姿和允许任务 | 只读 |
| `uav_validate_plan` | 构造并验证声明式 `MissionPlan` | 只读；计划有效期 5--600 秒 |
| `uav_execute_plan` | 执行经策略门控的固定任务模板 | 仅 PX4/Gazebo 仿真；手动接管时拒绝 |
| `uav_cancel_mission` | 取消任务并发出悬停 | 仅仿真 |
| `uav_get_run_events` | 读取适配层公开审计事件 | 只读；不暴露模型私有推理 |

导航任务扩展为 `navigate_to_safe_landmark`（仅 `north_gate`、`south_gate`、`east_gate`、`west_gate`）和 `survey_safe_perimeter`。它们不接收原始坐标：先在开放起飞区升至 20 m，再走预审的城市外周航线；任务以 Gazebo 实际位姿确认每个航点。导航超时会清除目标并请求悬停，网页 WASD 接管会立即清除目标且不再发送后续指令。

禁止公开：任意 MAVLink、任意 shell、任意速度注入、任意原始坐标和真实飞行器控制。起飞任务会先观测 Gazebo 的实际高度，确认到达后才发送悬停；超时不会继续执行后续动作。

## 运行与接入

默认使用 `stdio`，适合把服务器端命令作为受控 MCP 子进程接入。需要远程 MCP 时，使用 Streamable HTTP 并将监听限制在服务器回环地址，再通过 SSH 端口转发或带认证的网关访问；不要直接暴露给局域网。

```bash
# 3090：默认 stdio（由 MCP Host 拉起）
/root/miniconda3/envs/SpectrumClaw/bin/python -m backend.mcp.uav_server

# 3090：仅用于受控本地网关的 Streamable HTTP
SPECTRUMCLAW_UAV_MCP_TRANSPORT=streamable-http \
  /root/miniconda3/envs/SpectrumClaw/bin/python -m backend.mcp.uav_server
```

## 内置 Tool 与 MCP 的迁移边界

网页任务智能体目前通过内置 Tool 调用同一个 `UavMissionService`；MCP Server 也是这一服务的薄适配器。两条入口共享完全相同的 `MissionPlan`、模板白名单、策略检查、人工接管和审计事件，不能各自实现飞控逻辑。

| 层 | 当前职责 | 迁移策略 |
| --- | --- | --- |
| 内置 Tool | Console / 网页任务智能体的低延迟同进程调用 | 保留为兼容包装；新能力优先实现任务服务与契约 |
| MCP Server | 外部 Agent Host 的标准工具发现与调用 | 默认 `stdio`；仅经认证网关或 SSH 隧道启用远程 transport |
| `UavMissionService` | 唯一的策略门控、PX4 命令和人工接管边界 | 永远是权威实现，不允许被包装层绕过 |

每个网页任务运行有 `run_id` 与 `trace_id`。`intent`、`policy_decision`、`run_started`、适配层观测、`completion`、`interruption` 事件都会携带这两个关联标识。任务只能终止为 `completed`、`failed`、`cancelled`、`interrupted` 或 `rejected`；编排服务重启会把未完成任务安全标为 `interrupted`，不会遗留伪 `RUNNING` 状态。

下一步扩展新能力时，只需要实现同一任务服务的受限高层方法，再同时登记为内置 Agent tool 与 MCP tool；不得绕过 `UavMissionService` 直连 PX4。
