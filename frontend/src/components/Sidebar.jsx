import { LogoMark } from "./Logo.jsx";
import { navSections } from "../data/mockData.js";
import { ChevronRight, X } from "lucide-react";

export default function Sidebar({ activeId, open = false, onNavigate, onClose }) {
  return (
    <aside className="sidebar" aria-label="主导航" aria-hidden={!open ? undefined : false}>
      <div className="sidebar-mobile-head">
        <span>导航</span>
        <button type="button" onClick={onClose} aria-label="关闭导航"><X size={18} /></button>
      </div>
      <button className="brand-block" type="button" onClick={() => onNavigate("console")} aria-label="返回 SpectrumClaw 控制台">
        <LogoMark size={30} />
        <div className="brand-text">
          <strong>
            Spectrum<span style={{ color: "var(--accent)" }}>Claw</span>
          </strong>
          <span className="brand-en">Electromagnetic Agent</span>
          <span className="brand-cn">频谱智能体控制台</span>
        </div>
      </button>

      <div className="nav-scroll">
        {navSections.map((section) => (
          <div className="nav-section" key={section.id}>
            <span className="nav-section-title">{section.label}</span>
            <nav aria-label={section.label}>
              {section.items.map((item) => {
                const Icon = item.icon;
                const active = activeId === item.id;
                return (
                  <button
                    key={item.id}
                    className={`nav-item ${active ? "active" : ""}`}
                    onClick={() => onNavigate(item.id)}
                    aria-current={active ? "page" : undefined}
                  >
                    <span className="ni-icon">
                      <Icon size={16} />
                    </span>
                    <span className="ni-text">
                      <span className="ni-cn">{item.label}</span>
                      {item.chinese && <span className="ni-en">{item.chinese}</span>}
                    </span>
                    {item.step ? <span className="ni-step">{item.step}</span> : <ChevronRight className="ni-chevron" size={13} />}
                  </button>
                );
              })}
            </nav>
          </div>
        ))}
      </div>

      <div className="sidebar-footer">
        <div className="agent-pill">
          <div className="avatar">
            <LogoMark size={18} />
          </div>
          <div className="info">
            <strong>SpectrumClaw</strong>
            <span>AI Agent</span>
          </div>
          <span className="online-dot" title="在线" aria-label="智能体在线" />
        </div>
      </div>
    </aside>
  );
}
