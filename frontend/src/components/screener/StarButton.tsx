"use client";

interface Props {
  active: boolean;
  onClick: (e: React.MouseEvent) => void;
  size?: number;
}

export default function StarButton({ active, onClick, size = 14 }: Props) {
  return (
    <button
      onClick={onClick}
      title={active ? "Remove from watchlist" : "Add to watchlist"}
      style={{ background: "none", border: "none", cursor: "pointer", padding: "0 6px 0 0", color: active ? "#f59e0b" : "#6b6b6b", fontSize: size, lineHeight: 1 }}
      onMouseEnter={(e) => { if (!active) e.currentTarget.style.color = "#b08a3a"; }}
      onMouseLeave={(e) => { if (!active) e.currentTarget.style.color = "#6b6b6b"; }}
    >
      {active ? "★" : "☆"}
    </button>
  );
}
