"use client";

import { fmt } from "@/lib/format";
import { S } from "@/lib/theme";
import StreakBadge from "./StreakBadge";

// Prices are stored in pence (LSE convention); show as pounds like the watchlist.
const fmtPence = (p: number | null) => (p == null ? "—" : `£${(p / 100).toFixed(2)}`);

interface Item {
  symbol: string;
  name: string;
  streak: number;
  price: number | null;
  market_cap: number | null;
  currency: string;
}

interface Props {
  title: string;
  accent: string;
  up: boolean;
  items: Item[];
  selected: string | null;
  onSelect: (symbol: string) => void;
  height?: string | number;
}

export default function TrendingList({ title, accent, up, items, selected, onSelect, height }: Props) {
  return (
    <div style={{ ...S.card, padding: 0, overflow: "hidden", display: "flex", flexDirection: "column", height }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid #2a2a2a", color: accent, fontSize: 11, fontFamily: "monospace", textTransform: "uppercase", letterSpacing: 1, fontWeight: 700, display: "flex", justifyContent: "space-between" }}>
        <span>{title}</span>
        <span style={{ color: "#555" }}>{items.length}</span>
      </div>
      <div style={{ overflowY: "auto", flex: height && height !== "auto" ? "1 1 auto" : "none", maxHeight: height && height !== "auto" ? "none" : "calc(100vh - 220px)", minHeight: 0 }}>
        {items.length === 0 ? (
          <div style={{ padding: 24, color: "#555", fontSize: 12, fontFamily: "monospace", textAlign: "center" }}>None on a 3+ day run</div>
        ) : (
          items.map((it) => {
            const active = it.symbol === selected;
            return (
              <button
                key={it.symbol}
                onClick={() => onSelect(it.symbol)}
                style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left", background: active ? "#1f1200" : "none", border: "none", borderBottom: "1px solid #1a1a1a", borderLeft: `2px solid ${active ? accent : "transparent"}`, padding: "10px 12px", cursor: "pointer" }}
              >
                <StreakBadge days={it.streak} up={up} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: "#e5e5e5", fontSize: 12, fontFamily: "monospace", fontWeight: 700 }}>{it.symbol.replace(".L", "")}</div>
                  <div style={{ color: "#94a3b8", fontSize: 10, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</div>
                </div>
                <div style={{ textAlign: "right", flexShrink: 0 }}>
                  <div style={{ color: "#f1f5f9", fontSize: 12, fontFamily: "monospace", fontWeight: 700 }}>{fmtPence(it.price)}</div>
                  <div style={{ color: "#94a3b8", fontSize: 11, fontFamily: "monospace", marginTop: 1 }}>{fmt(it.market_cap, "currency", it.currency)}</div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
