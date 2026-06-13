"use client";

interface Props {
  days: number;
  up: boolean;
}

export default function StreakBadge({ days, up }: Props) {
  return (
    <span
      style={{
        flexShrink: 0,
        background: up ? "#0d2318" : "#2a0d0d",
        color: up ? "#10b981" : "#ef4444",
        border: `1px solid ${up ? "#10b98133" : "#ef444433"}`,
        padding: "2px 7px",
        borderRadius: 2,
        fontSize: 11,
        fontFamily: "monospace",
        fontWeight: 700,
        minWidth: 42,
        textAlign: "center",
      }}
    >
      {up ? "▲" : "▼"} {days}d
    </span>
  );
}
