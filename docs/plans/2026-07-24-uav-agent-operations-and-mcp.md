# UAV Agent Operations and MCP Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** 将无人机页收敛为紧凑的飞行观察与智能体任务工作区，并以安全的 MCP 能力层支持自然语言任务、固定任务和受限脚本任务。

**Architecture:** `UavMissionService` 继续是唯一的飞行任务领域服务；PX4/MAVLink 仍只由持久控制桥拥有。MCP 是跨 Agent/跨 Host 的标准能力边界，内置 Agent 与外部 MCP client 都通过同一份 typed task contract 进入领域服务。编码子智能体只能在每个任务独立的工作区中产生并验证声明式 `MissionPlan`，不得获得 shell、MAVLink、原始坐标或真实飞行器能力。

**Tech Stack:** React + Vite、FastAPI + SSE、LangGraph（现有 Agent runtime）、Python MCP SDK/FastMCP、PX4/Gazebo、pytest。

---

## 已确认的设计决定

| 决定 | 采用方案 | 原因 |
| --- | --- | --- |
| 飞控能力入口 | MCP 为标准边界；`UavMissionService` 为唯一领域实现 | 工具可被内置 Agent、子智能体和外部 Host 复用，且不会形成第二条 MAVLink 通道。 |
| 内置 Agent 调用 | 第一阶段保留同进程 thin wrapper；第二阶段切换为受管 MCP client | 先保证现有控制链路稳定，再以 contract test 防止 MCP 与 native schema 漂移。 |
| 现有 tools 迁移 | 按领域渐进迁移，不做全库一次性搬迁 | 不是所有已有工具都需要网络协议；高频、进程内能力可继续是 native adapter，但共享 schema 与策略。 |
| 自然语言控制 | LLM 仅生成受限 `MissionPlan`，由 validator + policy gate 执行 | 不允许模型产出任意坐标、速度、shell 或 MAVLink。 |
| “智能体思考” | 显示可审计的“执行依据/计划/工具事件/观测/安全判定”，不展示隐藏推理链 | 对用户可解释、可复盘，也不把不可靠的内部思维文本当作事实。 |
| 编码子智能体 | 单独 sandbox + 只写 Mission DSL/任务草案 + 静态校验/模拟测试 | 复用 task-6 的最小编辑、测试、回滚经验，而不向它暴露飞控能力。 |

## 目标信息架构

```text
UAV Operations Page
├── 紧凑顶部状态条（仿真 / 链路 / 飞控模式 / 紧急停止）
├── 主飞行画面（实景、五路相机、本地三维）
│   └── 底部飞行 Dock（WASD 状态、位置、LiDAR、起飞/悬停/降落）
└── Agent Operations 工作区
    ├── 自然语言任务输入 + 固定任务快捷入口
    ├── 任务计划与安全检查（可批准/拒绝/取消）
    ├── 执行时间线（工具、观测、相机证据、状态变更）
    └── 任务总结与可下载的 MissionPlan / 轨迹报告

System Status Page
└── “UAV 环境交付”折叠诊断组（ROS、Gazebo、PX4、Sionna、版本、smoke test）
```

### Task 1: 建立任务契约、审计事件与策略模型

**Files:**
- Create: `backend/skills/uav_spectrum_sim/contracts.py`
- Create: `backend/skills/uav_spectrum_sim/policy.py`
- Create: `backend/skills/uav_spectrum_sim/audit.py`
- Modify: `backend/skills/uav_spectrum_sim/mission.py`
- Test: `tests/test_uav_mission_contracts.py`

**Step 1: Write failing contract tests**

测试 `MissionPlan` 只能接受已登记的任务模板、受限航点名称和高度；原始 ENU 坐标、速度字段、未知动作和过期 plan 必须被拒绝。测试审计事件包含 `intent`、`policy_decision`、`tool_call`、`observation`、`completion` 五类可展示事件，且不含模型隐藏思维文本。

**Step 2: Run the test to verify it fails**

Run: `pytest -q tests/test_uav_mission_contracts.py`

Expected: FAIL，因为 `contracts.py`、策略验证和审计模型尚不存在。

**Step 3: Implement the minimal domain contracts**

实现 Pydantic/dataclass 模型：

```python
class MissionPlan(BaseModel):
    mission_id: str
    template: Literal[
        "takeoff_and_hover", "hover", "land", "return_to_launch",
        "inspect_safe_perimeter", "collect_camera_evidence",
        "search_safe_route",
    ]
    landmark: Literal["north_gate", "south_gate", "east_gate", "west_gate"] | None
    altitude_m: float | None
    return_home: bool = True
    expires_at: float
```

`MissionPolicy.validate(plan, runtime)` 必须验证：仿真标记、运行状态、人工遥控未接管、模板白名单、高度/地理围栏、过期时间和最大步骤数。`AuditEvent` 只记录简短的可审计解释和结构化观测。

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_uav_mission_contracts.py tests/test_uav_mission_service.py`

Expected: PASS。

### Task 2: 把固定任务扩展为可验证的模板库

**Files:**
- Create: `backend/skills/uav_spectrum_sim/templates.py`
- Modify: `backend/skills/uav_spectrum_sim/mission.py`
- Modify: `backend/mcp/uav_server.py`
- Modify: `backend/tools/registry.py`
- Test: `tests/test_uav_mission_templates.py`

**Step 1: Write failing tests**

覆盖以下模板的展开结果与失败回退：

| 模板 | 允许行为 | 结束条件 |
| --- | --- | --- |
| `inspect_safe_perimeter` | 起飞到预审高度、走安全周界、返回、降落 | 每航点真实位姿到达；超时悬停 |
| `collect_camera_evidence` | 到指定安全地标、等待稳定帧、记录五路相机时间戳、返回 | 帧新鲜度与位姿均满足 |
| `search_safe_route` | 走预审路线、逐点记录 LiDAR 摘要、返回 | 仅使用固定路线，不能动态改坐标 |

**Step 2: Run failing tests**

Run: `pytest -q tests/test_uav_mission_templates.py`

Expected: FAIL，因为模板库尚不存在。

**Step 3: Implement templates and execution hooks**

模板只产生 `MissionPlan` 或已验证的 `MissionStep`，实际执行仍只调用 `UavMissionService` 的受限方法。每个步骤必须写 audit event；任一超时、人工 WASD 接管、相机/LiDAR 不健康都清除导航目标并进入 `hover`。首期不做自由搜寻、目标识别或动态路径规划。

**Step 4: Verify**

Run: `pytest -q tests/test_uav_mission_templates.py tests/test_uav_mission_service.py tests/test_uav_agent_tools.py`

Expected: PASS。

### Task 3: 完整化 UAV MCP Server，并增加受管 Client

**Files:**
- Create: `backend/mcp/client.py`
- Modify: `backend/mcp/uav_server.py`
- Modify: `backend/agent/runtime.py`
- Modify: `backend/agent/graph.py`
- Modify: `backend/config.py`
- Test: `tests/test_uav_mcp_contract.py`
- Test: `tests/test_uav_mcp_client.py`

**Step 1: Write failing tests**

验证 MCP `tools/list`、`resources/list` 和任务执行 schema 与 native registry 的 canonical contract 完全一致。验证默认 `stdio` client、仅回环可达的 Streamable HTTP client、连接失败降级、每工具 approval policy 与超时。

**Step 2: Run failing tests**

Run: `pytest -q tests/test_uav_mcp_contract.py tests/test_uav_mcp_client.py`

Expected: FAIL。

**Step 3: Implement standard MCP surfaces**

- MCP tools：`uav_get_state`、`uav_list_templates`、`uav_validate_plan`、`uav_execute_plan`、`uav_cancel_mission`、`uav_get_run_events`。
- MCP resources：`spectrumclaw://uav/capabilities`、`spectrumclaw://uav/safety-policy`、`spectrumclaw://uav/live-state`。
- MCP prompts：`plan_safe_uav_mission`（用户可选模板，不自动执行）。
- `ManagedUavMcpClient` 负责生命周期、只允许白名单 tool、超时、结构化错误和 trace id；不可接受任意 MCP URL。
- 内置 Agent 使用 client 的 feature flag；默认实现必须在 server 不可用时安全失败，不可绕过到 raw PX4。

**Step 4: Verify protocol paths**

Run: `pytest -q tests/test_uav_mcp_contract.py tests/test_uav_mcp_client.py tests/test_uav_agent_tools.py`

Run: `/root/miniconda3/envs/SpectrumClaw/bin/python -m backend.mcp.uav_server`

Expected: contract tests PASS；stdio inspector 可列出工具、资源和提示词。

### Task 4: 增加任务编排 Agent 与受限编码子智能体

**Files:**
- Create: `backend/agents/uav_operations/__init__.py`
- Create: `backend/agents/uav_operations/orchestrator.py`
- Create: `backend/agents/uav_operations/mission_author.py`
- Create: `backend/agents/uav_operations/sandbox.py`
- Create: `backend/agents/uav_operations/prompts.py`
- Modify: `backend/agent/runtime.py`
- Test: `tests/test_uav_agent_orchestrator.py`
- Test: `tests/test_uav_agent_sandbox.py`

**Step 1: Write failing sandbox tests**

覆盖路径越界、绝对路径、`.git`、测试目录、可执行文件、网络、shell、原始 PX4 文件和超时都被拒绝；允许的 sandbox 仅能写入 `data/uav-agent-runs/<run_id>/` 下的 `mission_plan.json`、`report.md` 和测试日志。验证 plan 写入后必须再次经 `MissionPolicy` 校验。

**Step 2: Run failing tests**

Run: `pytest -q tests/test_uav_agent_sandbox.py tests/test_uav_agent_orchestrator.py`

Expected: FAIL。

**Step 3: Implement agent roles**

| 角色 | 输入 | 可用能力 | 禁止能力 |
| --- | --- | --- | --- |
| Orchestrator | 用户自然语言 | 读取 MCP state/template、生成任务草案、请求确认、执行 MCP tool | 直接 PX4、shell、文件写入 |
| Mission Author 子智能体 | 明确任务意图 + 模板说明 | 在 sandbox 输出声明式 plan 和说明，运行 schema/unit validation | 控制飞行、网络、任意代码执行 |
| Evidence Summarizer | 任务事件、位姿、相机/LiDAR 元数据 | 生成中文总结和异常摘要 | 发起飞控 |

复用 task-6 的安全经验：`Path.resolve()` 根目录校验、精确编辑/原子落盘、语法/JSON schema 校验、最小输出截断、失败回滚、独立上下文与步数预算。不得复用其“任意 repo shell/pytest”能力到飞控任务。

**Step 4: Verify**

Run: `pytest -q tests/test_uav_agent_sandbox.py tests/test_uav_agent_orchestrator.py`

Expected: PASS；“去建筑物旁边自由飞”“执行 shell”“写 MAVLink”均得到明确拒绝；“巡检安全周界后返回”生成可批准 plan。

### Task 5: 新增 UAV Agent API 与事件流

**Files:**
- Create: `backend/api/uav_agent.py`
- Modify: `backend/app.py`
- Modify: `backend/api/jobs.py`
- Test: `tests/test_uav_agent_api.py`

**Step 1: Write failing API tests**

覆盖：创建任务草案、读取 run、SSE event ordering、批准执行、取消、人工接管后的 `preempted`、非法执行 token、run 过期和 `agent/sandbox` 错误码。

**Step 2: Run failing tests**

Run: `pytest -q tests/test_uav_agent_api.py`

Expected: FAIL。

**Step 3: Implement endpoints**

```text
POST /api/uav-agent/runs                 # 自然语言 → draft / 计划事件流
GET  /api/uav-agent/runs/{run_id}        # 结构化状态、计划、证据、总结
GET  /api/uav-agent/runs/{run_id}/stream # SSE：公开执行事件
POST /api/uav-agent/runs/{run_id}/approve
POST /api/uav-agent/runs/{run_id}/cancel
GET  /api/uav-agent/templates
```

`approve` 只接受 plan digest + 未过期 run；执行前重新读取实时 PX4/Gazebo 和人工接管状态。所有事件携带 `run_id`、`trace_id`、时间戳和可显示的 `summary`，不携带隐式思维链。

**Step 4: Verify**

Run: `pytest -q tests/test_uav_agent_api.py tests/test_uav_mcp_contract.py`

Expected: PASS；SSE 可重连且不会重复执行任务。

### Task 6: 重构无人机页面为“画面优先 + Agent Operations”

**Files:**
- Create: `frontend/src/components/uav/UavAgentPanel.jsx`
- Create: `frontend/src/components/uav/UavAgentTimeline.jsx`
- Create: `frontend/src/components/uav/FlightControlDock.jsx`
- Create: `frontend/src/hooks/useUavAgentRun.js`
- Modify: `frontend/src/pages/UavSpectrumSimPage.jsx`
- Modify: `frontend/src/lib/api.js`
- Modify: `frontend/src/styles/app.css`
- Test: `frontend/src/components/uav/__tests__/UavAgentPanel.test.jsx`

**Step 1: Write component tests**

验证：任务输入、模板按钮、审批按钮、取消按钮、错误恢复、SSE 重连、手动接管后禁用审批；WASD 仅在飞行 Dock 聚焦/启用时消费按键，文本输入框始终可正常输入。

**Step 2: Run failing tests**

Run: `npm --prefix frontend test -- --run UavAgentPanel`

Expected: FAIL，组件和 hook 尚不存在。

**Step 3: Implement the compact layout**

- 删除四张顶部运行概览卡片和独立右侧“运行控制”大卡；只保留一行紧凑、可点击的状态 chip。
- 将“键盘遥控台”合并为主画面底部 `FlightControlDock`；默认只显示状态、起飞/悬停/返航、WASD 帮助，详细快捷键折叠。
- 主画面占桌面 8/12 列，右侧 `UavAgentPanel` 占 4/12 列；在宽度不足时按“画面 → Agent → 诊断”顺序纵向排列。
- Agent panel 提供：任务输入、三个固定模板、计划卡、必须的确认步骤、可审计时间线、相机/LiDAR 证据摘要、自然语言任务总结。
- 保持 Lucide 图标、已有深色 token、视觉焦点和 keyboard focus ring；使用 150–300ms 的 opacity/transform 微动画，尊重 `prefers-reduced-motion`。

**Step 4: Verify**

Run: `npm --prefix frontend test -- --run UavAgentPanel`

Run: `npm --prefix frontend run build`

Expected: tests PASS，build PASS；1440px 下主画面与 agent panel 同屏，375px 下没有横向滚动。

### Task 7: 将环境交付诊断移入系统状态页

**Files:**
- Create: `frontend/src/components/system/UavEnvironmentDiagnostics.jsx`
- Modify: `frontend/src/pages/SystemPage.jsx`
- Modify: `frontend/src/pages/UavSpectrumSimPage.jsx`
- Modify: `frontend/src/styles/app.css`
- Test: `frontend/src/components/system/__tests__/UavEnvironmentDiagnostics.test.jsx`

**Step 1: Write failing tests**

验证 System Page 读取同一个 runtime status 并呈现阶段标记、版本、smoke test 和最近错误；UAV 页面不再渲染“环境交付状态”大区块。

**Step 2: Run failing tests**

Run: `npm --prefix frontend test -- --run UavEnvironmentDiagnostics`

Expected: FAIL。

**Step 3: Implement diagnostics disclosure**

在系统状态页新增折叠的“UAV 仿真环境”诊断组，默认收起，显示就绪/异常数；展开后显示阶段、版本锁定、bridge 与日志链接。无人机页只留状态 chip 到系统页的跳转，不再占用飞行操作空间。

**Step 4: Verify**

Run: `npm --prefix frontend run build`

Expected: PASS。

### Task 8: 端到端安全验收、迁移与文档

**Files:**
- Modify: `docs/uav-simulation/MCP_FLIGHT_ADAPTER.md`
- Create: `docs/uav-simulation/UAV_AGENT_OPERATIONS.md`
- Create: `docs/uav-simulation/UAV_AGENT_THREAT_MODEL.md`
- Modify: `backend/agent/README.md`
- Test: `tests/test_uav_agent_e2e.py`

**Step 1: Write end-to-end tests**

场景包括：

1. 自然语言“巡检安全周界，采集画面，返回” → draft → 批准 → 事件流 → 返回/降落总结；
2. 人工 WASD 在执行中接管 → agent 中止、清除目标、无后续命令；
3. sandbox 生成的非法 plan → 不进入执行；
4. MCP 断开、PX4 timeout、相机不健康 → 安全失败并保留审计；
5. 旧 native tool 与 MCP tool 对同一 MissionPlan 产生同样 schema 与 policy 结果。

**Step 2: Run failing tests**

Run: `pytest -q tests/test_uav_agent_e2e.py`

Expected: FAIL。

**Step 3: Complete migration safeguards**

在文档中明确 transport：本机 child process 使用 stdio；远程只能是 loopback Streamable HTTP + 认证网关/SSH 转发。迁移 registry 时先双跑只读 contract comparison，再逐个启用 MCP client feature flag；不删除 native wrappers，直至观测到稳定的真实任务结果。

**Step 4: Verify and deploy**

Run: `pytest -q tests/test_uav_*.py tests/test_agent_runtime.py`

Run: `npm --prefix frontend run build`

Run: `git diff --check`

在 3090 执行：模拟器起飞 → 安全任务 → 人工接管 → 悬停/降落验收，并确认网页、MCP inspector、内置 Agent 三个入口的 audit trace 一致。

## 后续频谱模块接口（本计划不实现）

| 接口 | 未来输入 | UAV Agent 当前预留 |
| --- | --- | --- |
| `spectrum_request_measurement` | 频段、位置策略、采样预算 | `MissionPlan` 的受控 `measurement_profile_id`，不可携带自由脚本。 |
| `spectrum_observation` | 位置、姿态、时间、RSS/IQ 摘要、置信度 | 任务 evidence 时间线的可扩展 observation 类型。 |
| `spectrum_map_update` | 重建版本、误差/不确定度 | 任务总结中的关联 artifact，而不是飞控输入。 |
| `spectrum_next_waypoint_proposal` | 模型建议航点 | 必须先映射到已验证的安全航点/走廊，再进入 `MissionPolicy`。 |

## 非目标与退出准则

- 不接真实无人机、不开放任意 MAVLink、任意速度、任意坐标、shell 或网络执行。
- 不把 LLM 生成的 Python 直接作为飞控程序；脚本只能生成并验证声明式任务计划。
- 不显示内部 chain-of-thought；只显示可审计执行摘要。
- 只有在 Task 1–8 全部通过、人工接管可验证、审计可回放后，才开始接入频谱态势模块。
