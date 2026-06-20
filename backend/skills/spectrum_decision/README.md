# Spectrum Decision Skill

频谱决策模块已经接入真实资源分配算法。

## 文件

| 文件 | 说明 |
| --- | --- |
| `dataset.py` | 生成用户、环境、SNR、CQI、LOS 和业务类型。 |
| `resource_allocator.py` | CQI-Shannon 速率模型 + SLSQP 比例公平优化 + 贪心吞吐基线。 |
| `agent.py` | LLM 解析自然语言需求，调用优化器，并生成中文解释；支持流式阶段事件。 |

## API

| 路径 | 说明 |
| --- | --- |
| `/api/spectrum-decision/allocate` | 手动参数或 `use_agent=true` 智能体模式。 |
| `/api/spectrum-decision/allocate/stream` | 智能体模式 SSE：intent -> optimize -> explain -> done。 |

## 指标

返回总吞吐、Jain 公平指数、每业务分组结果、可行性、求解方法、贪心最大吞吐基线和公平性增益。
