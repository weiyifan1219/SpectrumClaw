export function LogoMark({ size = 28, accent = "var(--accent)" }) {
  const stroke = 1.6;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <path
        d="M9 5 L4 10 L4 22 L9 27"
        stroke="currentColor"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M23 5 L28 10 L28 22 L23 27"
        stroke="currentColor"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M8 16 L11 16 L13 11 L15.5 21 L18 13 L20 18 L22 16 L24 16"
        stroke={accent}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="16" r="0.9" fill={accent} />
    </svg>
  );
}

export function LogoLockup({ accent = "var(--accent)", subtitle = true }) {
  return (
    <div className="logo-lockup">
      <LogoMark size={26} accent={accent} />
      <div className="logo-text">
        <strong>
          Spectrum<span style={{ color: accent }}>Claw</span>
        </strong>
        {subtitle && <span>Electromagnetic Agent Console</span>}
      </div>
    </div>
  );
}
