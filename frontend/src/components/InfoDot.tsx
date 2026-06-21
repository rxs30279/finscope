"use client";
import { useRef, useState } from "react";

const TIP_BOX: React.CSSProperties = {
  width: 260, maxWidth: "80vw",
  background: "#1a1a1a", border: "1px solid #2a2a2a", borderRadius: 4,
  padding: "9px 11px", boxShadow: "0 6px 18px rgba(0,0,0,0.55)",
  color: "#e5e5e5", fontSize: 11, fontWeight: 400, lineHeight: 1.55,
  fontFamily: "monospace", textTransform: "none", letterSpacing: 0, textAlign: "left",
  whiteSpace: "pre-line", pointerEvents: "none", zIndex: 1000,
};

// Wraps any content and shows the same dark tooltip on hover — without adding a
// visible marker. Positioned fixed (from the trigger's bounding rect) so it
// escapes scroll/overflow containers such as a table's horizontal scroller.
export function HoverTip({ text, children }: { text: string; children: React.ReactNode }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const show = () => {
    const r = ref.current?.getBoundingClientRect();
    if (r) setPos({ x: r.left + r.width / 2, y: r.top });
  };
  return (
    <span
      ref={ref}
      onMouseEnter={show}
      onMouseLeave={() => setPos(null)}
      style={{ cursor: "inherit" }}
    >
      {children}
      {pos && (
        <span
          style={{
            ...TIP_BOX,
            position: "fixed",
            left: Math.min(Math.max(pos.x, 140), (typeof window !== "undefined" ? window.innerWidth : 1280) - 140),
            top: pos.y - 8,
            transform: "translate(-50%, -100%)",
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}

// Small "i" circle that reveals a styled explanation on hover. Uses a custom
// dark tooltip rather than the native (unstyleable, white) title attribute.
export default function InfoDot({ text, size = 14 }: { text: string; size?: number }) {
  const [show, setShow] = useState(false);
  return (
    <span
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      style={{
        position: "relative",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        width: size, height: size, borderRadius: "50%",
        border: "1px solid #64748b", color: "#64748b",
        fontSize: Math.round(size * 0.64), fontWeight: 700, fontFamily: "monospace",
        cursor: "help", textTransform: "none", letterSpacing: 0, flexShrink: 0,
      }}
    >
      i
      {show && (
        <span
          style={{
            ...TIP_BOX,
            position: "absolute", bottom: "calc(100% + 8px)", left: "50%", transform: "translateX(-50%)",
            maxWidth: "70vw",
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}
