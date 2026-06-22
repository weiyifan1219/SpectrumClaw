import { Brain, Check, ChevronDown } from "lucide-react";

export default function ModelMenu({
  activeModel,
  availableReasoningOptions,
  canUseReasoning,
  handleModelChange,
  modelId,
  modelOpen,
  modelOptions,
  reasoningButtonLabel,
  reasoningEffort,
  setModelOpen,
  setReasoningEffort,
  setSkillOpen,
  setThinkingEnabled,
  thinkingEnabled,
}) {
  return (
    <div className="comp-select model-select" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={`sel-btn model-trigger ${thinkingEnabled && canUseReasoning ? "active" : ""}`}
        onClick={() => { setModelOpen((v) => !v); setSkillOpen(false); }}
      >
        <span className="model-trigger-main">{activeModel.label}</span>
        <span className={`model-trigger-reason ${thinkingEnabled && canUseReasoning ? "on" : ""}`}>{reasoningButtonLabel}</span>
        <ChevronDown size={13} />
      </button>
      {modelOpen && (
        <div className="sel-pop model-pop codex-pop">
          <div className="pop-label">MODEL</div>
          {modelOptions.map((m) => (
            <button
              key={m.id}
              type="button"
              className={`pop-item model-row ${m.id === modelId ? "on" : ""}`}
              onClick={() => { handleModelChange(m.id); setModelOpen(false); }}
            >
              <span className={`pi-dot provider-dot ${m.configured ? "configured" : ""}`} />
              <span className="pi-stack">
                <span className="pi-label">{m.label}</span>
                <span className="pi-meta">{m.provider_label} · {m.model}</span>
              </span>
              <span className="pi-check">{m.id === modelId && <Check size={12} />}</span>
            </button>
          ))}
          <div className="pop-sep" />
          <div className="pop-label">REASONING</div>
          {canUseReasoning ? (
            <>
              {availableReasoningOptions.map((r) => {
                const isOff = r.id === "off";
                const on = isOff ? !thinkingEnabled : thinkingEnabled && r.id === reasoningEffort;
                return (
                  <button
                    key={r.id}
                    type="button"
                    className={`pop-item reason-row ${on ? "on" : ""}`}
                    onClick={() => {
                      setThinkingEnabled(!isOff);
                      setReasoningEffort(isOff ? "off" : r.id);
                    }}
                  >
                    <span className={`pi-dot ${on && !isOff ? "pi-think-on" : ""}`}>{on && !isOff && <Brain size={10} />}</span>
                    <span className="pi-stack">
                      <span className="pi-label">{r.label}</span>
                      <span className="pi-meta">{r.description}</span>
                    </span>
                    <span className="pi-check">{on && <Check size={12} />}</span>
                  </button>
                );
              })}
            </>
          ) : (
            <div className="model-empty-state">当前模型不支持推理强度</div>
          )}
        </div>
      )}
    </div>
  );
}
