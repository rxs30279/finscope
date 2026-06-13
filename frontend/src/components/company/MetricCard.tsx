"use client";

interface Props {
  label: string;
  value: React.ReactNode;
  color?: string;
  compact?: boolean;
}

export default function MetricCard({ label, value, color, compact }: Props) {
  return (
    <div
      style={{
        background: "#141414",
        borderRadius: 2,
        padding: compact ? "7px 10px" : "14px 18px",
        border: "1px solid #2a2a2a",
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: "#666",
          marginBottom: compact ? 2 : 6,
          textTransform: "uppercase",
          letterSpacing: 1,
          fontFamily: "monospace",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: compact ? 15 : 18,
          fontFamily: "monospace",
          fontWeight: 700,
          color: color || "#e5e5e5",
        }}
      >
        {value}
      </div>
    </div>
  );
}
