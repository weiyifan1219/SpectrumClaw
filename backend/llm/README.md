# LLM Client

`backend/llm/client.py` 是所有 LLM 调用的统一入口。

## 能力

| 能力 | 说明 |
| --- | --- |
| Provider | DeepSeek、OpenAI、Qwen、Anthropic、OpenAI-compatible、Anthropic-compatible。 |
| API 类型 | OpenAI chat completions 与 Anthropic messages。 |
| Streaming | `stream_chat()` 输出 `thinking/content/done/error` 事件。 |
| Tool loop | 支持 OpenAI tool calls 和 Anthropic tool_use，最多 `MAX_TOOL_ROUNDS=5`。 |
| Thinking | 支持 thinking 开关和 reasoning effort。 |
| Dynamic system prompt | 扫描 `backend/skills/` 区分已实现/规划中 skill，并注入最近 evolution summary。 |

## 主要函数

| 函数 | 说明 |
| --- | --- |
| `chat(messages, ...)` | 非流式调用，返回 `(reply, metadata)`。 |
| `stream_chat(messages, ...)` | 流式调用，yield SSE event dict。 |
| `reset_system_prompt_cache()` | 强制下一次调用重建系统提示词。 |

## 配置

常用环境变量见 `.env.example` 和 `backend/config.py`。
