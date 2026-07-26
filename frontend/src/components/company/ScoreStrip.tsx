"use client";

import ScorePill from "@/components/screener/ScorePill";

// Compact MOM / QUAL / VAL / RSK factor strip for the company-page header —
// the same four composite scores the screener and High Impact pages show,
// shrunk to a labelled-pill row that sits under the market cap / EV figures.
// Hovering a column shows the full score description; risk is inverted so a
// low score reads green. Renders nothing when no score is available (e.g.
// brand-new listings).

// Exported so other surfaces that show the same four factors as separate,
// sortable table columns (the watchlist) stay in step with the strip's labels,
// tooltips and invert flags.
export const MEASURES = [
  { key: "momentum_score", label: "MOM", title: "Momentum score (0–10)", invert: false },
  { key: "quality_score", label: "QUAL", title: "Quality score (0–10)", invert: false },
  { key: "value_score", label: "VAL", title: "Value score (0–10, higher = cheaper)", invert: false },
  { key: "risk_score", label: "RSK", title: "Risk score (0–10, lower is safer)", invert: true },
];

interface Props {
  snap: any;
  align?: "left" | "right";
}

export default function ScoreStrip({ snap, align = "left" }: Props) {
  if (MEASURES.every((m) => snap?.[m.key] == null)) return null;
  return (
    <div style={{ display: "flex", gap: 10, justifyContent: align === "right" ? "flex-end" : "flex-start" }}>
      {MEASURES.map((m) => (
        <div
          key={m.key}
          title={m.title}
          // Fixed column width: the labels vary ("QUAL" vs "VAL"), and without
          // it the columns size to their label so the pills space unevenly.
          style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3, cursor: "default", width: 38 }}
        >
          <span style={{ color: "#475569", fontSize: 8, fontWeight: 700, letterSpacing: 0.5 }}>{m.label}</span>
          <ScorePill value={snap[m.key]} invert={m.invert} />
        </div>
      ))}
    </div>
  );
}
