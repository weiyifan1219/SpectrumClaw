import {
  ArrowRight,
  Check,
  ChevronDown,
  Loader2,
  MessageSquare,
  Mic,
  Plus,
} from "lucide-react";
import { skills } from "../../data/mockData.js";
import ModelMenu from "./ModelMenu.jsx";

export default function Composer({
  activeSkill,
  draft,
  modelProps,
  onSubmit,
  sending,
  setDraft,
  setSkillOpen,
  setSkillSel,
  skillOpen,
  skillSel,
  skillSelLabel,
}) {
  return (
    <form className="composer-v2" onSubmit={onSubmit}>
      <button type="button" className="comp-btn plus" aria-label="附件" title="上传文件 / 添加附件">
        <Plus size={18} />
      </button>

      <div className="comp-input">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            skillSel === "chat"
              ? "和 SpectrumClaw 对话，问问题或下达指令…"
              : `调用「${activeSkill?.label}」技能 — 输入任务描述…`
          }
          aria-label="Message"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSubmit(); }
          }}
        />
      </div>

      <div className="comp-divider" />

      <ModelMenu {...modelProps} setSkillOpen={setSkillOpen} />

      <div className="comp-select" onClick={(e) => e.stopPropagation()}>
        <span className="sel-label">技能</span>
        <button
          type="button"
          className={`sel-btn ${skillSel !== "chat" ? "active" : ""}`}
          onClick={() => { setSkillOpen((v) => !v); modelProps.setModelOpen(false); }}
        >
          <span>{skillSelLabel}</span>
          <ChevronDown size={13} />
        </button>
        {skillOpen && (
          <div className="sel-pop wide">
            <button
              type="button"
              className={`pop-item ${skillSel === "chat" ? "on" : ""}`}
              onClick={() => { setSkillSel("chat"); setSkillOpen(false); }}
            >
              <span className="pi-dot pi-chat"><MessageSquare size={10} /></span>
              <span className="pi-label">普通对话</span>
              <span className="pi-check">{skillSel === "chat" && <Check size={12} />}</span>
            </button>
            <div className="pop-sep" />
            {skills.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`pop-item ${skillSel === s.id ? "on" : ""}`}
                onClick={() => { setSkillSel(s.id); setSkillOpen(false); }}
              >
                <span className={`pi-dot acc-${s.accent}`} />
                <span className="pi-label">{s.label}</span>
                <span className="pi-check">{skillSel === s.id && <Check size={12} />}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <button type="button" className="comp-btn mic" aria-label="语音输入">
        <Mic size={16} />
      </button>

      <button type="submit" className="comp-btn send" aria-label="发送" disabled={sending}>
        {sending ? <Loader2 size={17} className="spin" /> : <ArrowRight size={17} />}
      </button>
    </form>
  );
}
