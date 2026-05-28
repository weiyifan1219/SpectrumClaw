# 态势构建模块预留设计

## 当前状态

态势构建模块暂缓。用户仍在运行相关实验和准备脚本，等脚本稳定并上传服务器后再开始对接。

## 后续目标

将 `/home/lenovo/workspace/Agent_UAV_REM` 中可复用的态势构建脚本、模型或神经网络封装为 `situation_building` skill。

## 预期接口

| 输入 | 输出 |
| --- | --- |
| 场景配置、采样点、频段、模型参数 | 频谱态势图、REM 结果、统计指标、执行日志 |

## 后续对接步骤

| 步骤 | 说明 |
| --- | --- |
| 1 | 用户确认最终脚本和模型路径 |
| 2 | Codex 设计 adapter 输入输出 |
| 3 | Claude Code MCP 实现调用脚本 |
| 4 | 前端增加结果图层和下载入口 |
| 5 | 在 4090 服务器验证 GPU/依赖/路径 |

## 输出目录规划

后续结果统一写入：

```text
outputs/situation_building/<task_id>/
```

每个任务至少包含 `result.md`、`metadata.json`、`logs.jsonl` 和图形结果文件。
