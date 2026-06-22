import {
  AlertTriangle,
  Bot,
  Check,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
  User,
} from "lucide-react";
import Markdown from "../Markdown.jsx";

export default function MessageList({ bodyRef, messages, onFeedback, onRetry }) {
  return (
    <div className="chat-body" ref={bodyRef}>
      {messages.map((m, i) => (
        <div className={`message ${m.role} ${m.meta?.error ? "error" : ""}`} key={`${m.role}-${i}`}>
          <div className="avatar">
            {m.meta?.error ? <AlertTriangle size={15} /> : m.role === "assistant" ? <Bot size={16} /> : <User size={16} />}
          </div>
          <div className="bubble">
            <div className="who">
              <strong>{m.meta?.error ? "错误" : m.role === "assistant" ? "SPECTRUMCLAW" : "USER"}</strong>
              {m.meta?.ts && <span className="ts mono">· {m.meta.ts}</span>}
              {m.meta?.streaming && !m.content && <span className="streaming-dot" />}
            </div>
            {m.reasoning && (
              <details className="reasoning-box" open={!m.content}>
                <summary>思考过程{m.meta?.streaming && !m.content ? "…" : ""}</summary>
                <p>{m.reasoning}</p>
              </details>
            )}
            {m.content ? <Markdown>{m.content}</Markdown> : m.meta?.streaming && <span className="cursor-blink" />}
            {m.meta?.error && (
              <button className="retry-btn" onClick={() => onRetry(i)} title="重新发送">
                <RefreshCw size={13} /> 重试
              </button>
            )}
            {m.pipeline && (
              <div className="pipeline-bubble">
                {m.pipeline.map((step, idx) => (
                  <span className="step" data-status={step.status || "done"} key={step.id || step.name}>
                    <span className="check">{step.status === "active" ? null : <Check size={11} />}</span>
                    <span className="sn">{step.name}</span>
                    {idx < m.pipeline.length - 1 && <span className="arr">→</span>}
                  </span>
                ))}
              </div>
            )}
            {m.role === "assistant" && m.meta?.done && !m.meta?.error && (
              <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
                <button
                  className={`feedback-btn ${m.meta?.feedbackRating === 1 ? "on" : ""}`}
                  onClick={() => onFeedback(i, 1)}
                  title="有用"
                  disabled={m.meta?.feedbackRating != null}
                >
                  <ThumbsUp size={12} />
                </button>
                <button
                  className={`feedback-btn ${m.meta?.feedbackRating === -1 ? "on" : ""}`}
                  onClick={() => onFeedback(i, -1)}
                  title="没用"
                  disabled={m.meta?.feedbackRating != null}
                >
                  <ThumbsDown size={12} />
                </button>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
