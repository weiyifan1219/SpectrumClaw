# Skill 系统

SpectrumClaw 的 skill 是后端领域能力模块，不等同于 Codex/Claude 的 Agent Skill。项目 skill 位于 `backend/skills/`，通过 `backend/api/` 暴露。

## 当前 skill 清单

| Skill | 目录 | 状态 | API |
| --- | --- | --- | --- |
| 频率规划 | `frequency_planning/` | 可用 | `/api/rag/frequency_plan/stream`，另有 `planner.py` 薄封装。 |
| 频谱构建 | `spectrum_construction/` | 可用 | `/api/spectrum-construction/generate`, `/api/spectrum-construction/uav-rem/overview` |
| 频谱决策 | `spectrum_decision/` | 可用 | `/api/spectrum-decision/allocate`, `/api/spectrum-decision/allocate/stream` |
| 态势构建 | `situation_building/` | 兼容占位 | 历史名称，当前真实实现迁移到 `spectrum_construction/`。 |
| 干扰分析 | `interference_analysis/` | 预留 | 暂无算法实现。 |
| 调制识别 | `modulation_recognition/` | 预留 | 暂无模型实现。 |

## 审计与记忆

可执行 skill API 使用 `backend.memory.hooks.track_skill_run()` 包裹：

```text
API handler
  -> with track_skill_run(...)
  -> skill implementation
  -> output_summary/status/latency/error
  -> memory skill_runs
```

当前已接入：

| API | skill run name |
| --- | --- |
| `/api/spectrum-construction/generate` | `spectrum_construction` |
| `/api/spectrum-construction/uav-rem/overview` | `uav_rem_overview` |
| `/api/spectrum-decision/allocate` | `spectrum_decision` 或 `spectrum_decision_agent` |
| `/api/spectrum-decision/allocate/stream` | `spectrum_decision_agent` |

## 实现边界

| 规则 | 说明 |
| --- | --- |
| 算法隔离 | 重依赖模型如 GenSpectra 通过 sidecar/子进程隔离。 |
| 结果结构化 | API 返回应包含可视化数据、metrics、status 和错误原因。 |
| 可降级 | 外部 checkpoint/产物缺失时返回明确状态，不阻塞整个系统。 |
| 不修改外部实验仓库 | UAV REM 适配器只读 `/workspace/YiFan/Agent_UAV_REM`。 |

## 新增 skill 流程

| 步骤 | 要求 |
| --- | --- |
| 1 | 在 `backend/skills/<name>/` 放实现和 README。 |
| 2 | 在 `backend/api/` 增加路由和 Pydantic schema。 |
| 3 | 在 `backend/app.py` 注册 router。 |
| 4 | 使用 `track_skill_run()` 记录审计。 |
| 5 | 在 `frontend/src/pages/` 或 Console skill registry 增加入口。 |
| 6 | 更新本文件和 `backend/skills/README.md`。 |
