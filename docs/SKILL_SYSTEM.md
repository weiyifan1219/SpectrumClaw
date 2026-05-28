# Skill 机制设计

## 核心思想

每个频谱能力都是一个独立 skill。智能体可以根据用户输入自主选择 skill，用户也可以在 Console 中主动选择当前任务。

## Skill 元数据

| 字段 | 说明 |
| --- | --- |
| `id` | 唯一标识，如 `frequency_planning` |
| `name` | 页面展示名称 |
| `status` | `ready` / `planned` / `blocked` / `disabled` |
| `inputs` | 支持的输入类型 |
| `outputs` | 输出文件和结构 |
| `adapter` | Python adapter 或脚本调用入口 |
| `dependencies` | 外部脚本、模型、知识库或 API |
| `owner` | 当前实现责任方 |

## 第一批 Skill

| Skill | 状态 | 说明 |
| --- | --- | --- |
| `frequency_planning` | 第一阶段实现 | 基础 RAG + LLM 生成 |
| `situation_building` | 暂缓 | 等用户准备好态势构建脚本 |
| `modulation_recognition` | 预留 | 后续接入识别模型 |
| `spectrum_decision` | 预留 | 后续接入策略/优化 |
| `interference_analysis` | 预留 | 后续接入干扰检测和分析 |

## 路由策略

| 来源 | 行为 |
| --- | --- |
| 用户显式选择任务 | 优先使用选择的 skill |
| 用户自然语言输入 | agent 根据关键词和上下文选择 skill |
| 无法判断 | 追问用户或默认进入通用对话 |

## 结果规范

每个 skill 后续都应输出：

| 文件 | 用途 |
| --- | --- |
| `result.md` | 人类可读结果 |
| `metadata.json` | 参数、引用、模型、时间、状态 |
| `logs.jsonl` | 执行日志 |
| 图像/表格文件 | 可视化结果或数据表 |

## 进化记录

后续每次 skill 执行都记录：

- 输入摘要。
- 选择原因。
- 成功或失败。
- 用户反馈。
- 可改进点。
- 是否需要更新 prompt、参数或知识库。
