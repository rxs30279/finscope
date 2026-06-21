"use client";

import { useState, useEffect, useRef } from "react";
import { S } from "@/lib/theme";

interface Props {
  sectors: string[];
  selected: string[];
  excluded: string[];
  onToggleInclude: (s: string) => void;
  onClear: () => void;
  onToggleExclude: (s: string) => void;
}

export default function SectorDropdown({ sectors, selected, excluded, onToggleInclude, onClear, onToggleExclude }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const label =
    selected.length === 1 ? selected[0] :
    selected.length > 1 ? `${selected.length} sectors` :
    excluded.length ? `All Sectors (−${excluded.length})` : "All Sectors";
  const active = selected.length > 0 || excluded.length > 0;

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button onClick={() => setOpen((o) => !o)} style={{ ...S.select, ...(active ? S.selectActive : {}), minWidth: 170, textAlign: "left", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
        <span style={{ fontSize: 8, opacity: 0.6 }}>▾</span>
      </button>
      {open && (
        <div style={{ position: "absolute", top: "100%", left: 0, marginTop: 4, background: "#141414", border: "1px solid #2a2a2a", borderRadius: 4, minWidth: 260, zIndex: 200, boxShadow: "0 8px 24px rgba(0,0,0,0.8)", maxHeight: 360, overflowY: "auto" }}>
          <div onClick={() => onClear()} style={{ padding: "8px 12px", cursor: "pointer", fontFamily: "monospace", fontSize: 12, color: selected.length === 0 ? "#f97316" : "#cbd5e1", borderBottom: "1px solid #1f1f1f" }}>
            All Sectors
          </div>
          {sectors.map((s) => {
            const isExcluded = excluded.includes(s);
            const isSelected = selected.includes(s);
            return (
              <div key={s} style={{ display: "flex", alignItems: "stretch", borderBottom: "1px solid #1f1f1f" }}>
                <div
                  onClick={() => { if (!isExcluded) onToggleInclude(s); }}
                  style={{ flex: 1, padding: "8px 8px 8px 12px", cursor: isExcluded ? "not-allowed" : "pointer", fontFamily: "monospace", fontSize: 12, color: isSelected ? "#f97316" : isExcluded ? "#555" : "#cbd5e1", textDecoration: isExcluded ? "line-through" : "none", display: "flex", alignItems: "center", gap: 8 }}
                >
                  <span style={{ width: 11, display: "inline-block", color: "#f97316" }}>{isSelected ? "✓" : ""}</span>
                  {s}
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); onToggleExclude(s); }}
                  title={isExcluded ? "Stop excluding" : "Exclude this sector"}
                  style={{ background: "none", border: "none", padding: "0 12px", cursor: "pointer", fontSize: 13, lineHeight: 1, color: isExcluded ? "#ef4444" : "#555" }}
                >
                  ⊘
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
