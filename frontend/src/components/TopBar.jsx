import { systemSignals } from "../data/mockData.js";

export default function TopBar({ crumbs, modelLabel }) {
  const signals = systemSignals.map((s) =>
    s.label === "Model" ? { ...s, value: modelLabel ?? s.value } : s
  );

  return (
    <header className="topbar">
      <div className="crumbs">
        {crumbs.map((c, i) => (
          <span key={c} className={i === crumbs.length - 1 ? "here" : ""}>
            {c}
            {i < crumbs.length - 1 && <span className="sep" style={{ margin: "0 6px" }}>/</span>}
          </span>
        ))}
      </div>
      <div className="signal-row">
        {signals.map((s) => (
          <div className="signal" key={s.label} data-tone={s.tone}>
            <span className="k">{s.label}</span>
            <span className="v">{s.value}</span>
          </div>
        ))}
      </div>
    </header>
  );
}
