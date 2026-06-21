"use client";

// Renders a 0–10 composite score as a pill, coloured on the app's original
// three-tier spectrum: ≥7 green, ≥4 amber, else red. `invert` is set for Risk,
// where a low score is good — the colour is graded on (10 − value) so risk ≤3
// reads green, while the displayed number stays the real risk score. Base
// colours match theme.ts (#10b981 / #f59e0b / #ef4444).
interface Props {
  value: number | null | undefined;
  invert?: boolean;
}

function palette(grade: number) {
  if (grade >= 7) return { bg: "rgba(16,185,129,.15)", color: "#10b981", border: "rgba(16,185,129,.34)" };
  if (grade >= 4) return { bg: "rgba(245,158,11,.14)", color: "#f59e0b", border: "rgba(245,158,11,.30)" };
  return { bg: "rgba(239,68,68,.14)", color: "#ef4444", border: "rgba(239,68,68,.32)" };
}

export default function ScorePill({ value, invert }: Props) {
  if (value == null) return <span style={{ color: "#444" }}>—</span>;
  const p = palette(invert ? 10 - value : value);
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        minWidth: 28, height: 22, padding: "0 6px", borderRadius: 6,
        border: `1px solid ${p.border}`, background: p.bg, color: p.color,
        fontWeight: 600, fontSize: 12,
      }}
    >
      {value}
    </span>
  );
}
