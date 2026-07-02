import {
  AlertTriangle,
  Bot,
  Check,
  Loader2,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
  User,
} from "lucide-react";
import Markdown from "../Markdown.jsx";

export default function MessageList({ bodyRef, loading = false, loadingSubtitle = "", loadingTitle = "正在加载聊天记录", messages, onFeedback, onRetry }) {
  return (
    <div className="chat-body" ref={bodyRef}>
      {loading ? (
        <div className="chat-history-loading" role="status" aria-live="polite">
          <div className="chl-head">
            <span className="chl-icon"><Loader2 size={15} className="spin" /></span>
            <div>
              <strong>{loadingTitle}</strong>
              <p>{loadingSubtitle ? `正在恢复：${loadingSubtitle.slice(0, 80)}` : "正在恢复消息、时间线与上下文…"}</p>
            </div>
          </div>
          <div className="chl-message user">
            <span className="chl-avatar" />
            <div className="chl-lines">
              <span className="chl-line short" />
              <span className="chl-line mid" />
            </div>
          </div>
          <div className="chl-message assistant">
            <span className="chl-avatar accent" />
            <div className="chl-lines">
              <span className="chl-line wide" />
              <span className="chl-line mid" />
              <span className="chl-line short" />
            </div>
          </div>
        </div>
      ) : messages.length > 0 ? (
        messages.map((m, i) => (
          <div className={`message ${m.role} ${m.meta?.error ? "error" : ""}`} key={`${m.role}-${i}`}>
            <div className="avatar">
              {m.meta?.error ? <AlertTriangle size={15} /> : m.role === "assistant" ? <Bot size={16} /> : <User size={16} />}
            </div>
            <div className="bubble">
              <div className="who">
                <strong>{m.meta?.error ? "错误" : m.role === "assistant" ? "SPECTRUMCLAW" : "USER"}</strong>
                {m.meta?.ts ? <span className="ts mono">· {m.meta.ts}</span> : null}
                {m.meta?.streaming && !m.content ? <span className="streaming-dot" /> : null}
              </div>
              {m.reasoning ? (
                <details className="reasoning-box" open={!m.content}>
                  <summary>思考过程{m.meta?.streaming && !m.content ? "…" : ""}</summary>
                  <p>{m.reasoning}</p>
                </details>
              ) : null}
              {m.content ? <Markdown>{m.content}</Markdown> : m.meta?.streaming ? <span className="cursor-blink" /> : null}
              {m.meta?.error ? (
                <button className="retry-btn" onClick={() => onRetry(i)} title="重新发送">
                  <RefreshCw size={13} /> 重试
                </button>
              ) : null}
              {m.pipeline ? (
                <div className="pipeline-bubble">
                  {m.pipeline.map((step, idx) => (
                    <span className="step" data-status={step.status || "done"} key={step.id || step.name}>
                      <span className="check">{step.status === "active" ? null : <Check size={11} />}</span>
                      <span className="sn">{step.name}</span>
                      {idx < m.pipeline.length - 1 ? <span className="arr">→</span> : null}
                    </span>
                  ))}
                </div>
              ) : null}
              {m.role === "assistant" && m.meta?.done && !m.meta?.error ? (
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
              ) : null}
            </div>
          </div>
        ))
      ) : (
        <div className="chat-empty-state">
          <Bot size={18} />
          <span>暂无可显示的消息</span>
        </div>
      )}
    </div>
  );
}
