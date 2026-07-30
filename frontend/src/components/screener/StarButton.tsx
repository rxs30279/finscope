"use client";

interface Props {
  active: boolean;
  onClick: (e: React.MouseEvent) => void;
  size?: number;
}

export default function StarButton({ active, onClick, size = 14 }: Props) {
  // The glyph stays `size`; the button box is padded out to at least 24x24 CSS
  // px for WCAG 2.2 target size. At the screener's default (14) that's a 24px
  // box inside a 22px-tall row body, so rows grow ~2px — the star was 18x14 and
  // failed the audit on all 30 rendered rows.
  const box = Math.max(24, size + 8);
  return (
    <button
      onClick={onClick}
      title={active ? "Remove from watchlist" : "Add to watchlist"}
      style={{ background: "none", border: "none", cursor: "pointer", padding: 0, width: box, height: box, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0, color: active ? "#f59e0b" : "#6b6b6b", fontSize: size, lineHeight: 1 }}
      onMouseEnter={(e) => { if (!active) e.currentTarget.style.color = "#b08a3a"; }}
      onMouseLeave={(e) => { if (!active) e.currentTarget.style.color = "#6b6b6b"; }}
    >
      {active ? "★" : "☆"}
    </button>
  );
}
