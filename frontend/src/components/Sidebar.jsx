import { LogoMark } from "./Logo.jsx";
import { navSections } from "../data/mockData.js";

export default function Sidebar({ activeId, onNavigate }) {
  return (
    <aside className="sidebar">
      <div className="brand-block">
        <LogoMark size={30} />
        <div className="brand-text">
          <strong>
            Spectrum<span style={{ color: "var(--accent)" }}>Claw</span>
          </strong>
          <span className="brand-en">Electromagnetic Agent</span>
          <span className="brand-cn">频谱智能体控制台</span>
        </div>
      </div>

      <div className="nav-scroll">
        {navSections.map((section) => (
          <div className="nav-section" key={section.id}>
            <span className="nav-section-title">{section.label}</span>
            <nav>
              {section.items.map((item) => {
                const Icon = item.icon;
                const active = activeId === item.id;
                return (
                  <button
                    key={item.id}
                    className={`nav-item ${active ? "active" : ""}`}
                    onClick={() => onNavigate(item.id)}
                  >
                    <span className="ni-icon">
                      <Icon size={16} />
                    </span>
                    <span className="ni-text">
                      <span className="ni-cn">{item.label}</span>
                      {item.chinese && <span className="ni-en">{item.chinese}</span>}
                    </span>
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
          <span className="online-dot" title="在线" />
        </div>
      </div>
    </aside>
  );
}
