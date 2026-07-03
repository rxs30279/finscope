"use client";

import Link from "next/link";
import { companyHref } from "@/lib/company";
import { useIsMobile } from "@/hooks/useMediaQuery";

// Peer-relative fair value for the Valuation tab. Fed by /api/valuation: the
// company's price vs the fair value implied by its peers' median multiple.
// Deliberately shows an empty state rather than a number when peers are too thin
// (peer_basis === 'insufficient' or no fair_value) — a median of one or two
// names is noise, not a valuation.

interface Peer {
  symbol: string;
  name: string;
}

interface ValuationData {
  fair_value: number | null;
  current_price: number | null;
  upside_pct: number | null;
  multiple_used: string | null;
  peer_basis: string; // 'industry' | 'sector' | 'insufficient'
  peer_count: number;
  peers: Peer[];
  caution: boolean;
}

function PeerDropdown({ peers }: { peers: Peer[] }) {
  if (!peers || peers.length === 0) return null;
  return (
    <details style={{ marginTop: 6 }}>
      <summary style={{ fontSize: 11, color: "#888", fontFamily: "monospace", cursor: "pointer" }}>
        View peer companies ({peers.length})
      </summary>
      <ul style={{ margin: "6px 0 0", padding: 0, listStyle: "none" }}>
        {peers.map((p) => (
          <li key={p.symbol} style={{ fontSize: 11, fontFamily: "monospace", padding: "3px 0" }}>
            <Link href={companyHref(p.symbol, "valuation")} style={{ color: "#999", textDecoration: "none" }}>
              {p.name}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}

const card: React.CSSProperties = {
  background: "#141414",
  borderRadius: 2,
  padding: "16px 20px",
  border: "1px solid #2a2a2a",
};
const title: React.CSSProperties = {
  fontSize: 10,
  color: "#666",
  textTransform: "uppercase",
  letterSpacing: 1,
  fontFamily: "monospace",
};
const disclaimer: React.CSSProperties = {
  color: "#555",
  fontSize: 11,
  lineHeight: 1.6,
  margin: "12px 0 0",
  fontFamily: "monospace",
};
const px = (v: number) => `${Math.round(v)}p`;

export default function FairValueCard({ val }: { val: ValuationData | null }) {
  // Peer breakdown is desktop-only — a secondary detail not worth the vertical
  // space it costs on a phone-width Valuation tab.
  const isMobile = useIsMobile();

  // Empty state — no defensible peer-based estimate. peer_basis distinguishes
  // "this sector isn't modeled at all" (banks/insurers/REITs trade on book
  // value, not EV/EBITDA — no peer search was ever attempted) from "this
  // company's industry genuinely has too few peers."
  if (!val || val.fair_value == null || val.upside_pct == null || val.current_price == null) {
    const excludedSector = val?.peer_basis === "excluded_sector";
    return (
      <div style={card}>
        <div style={title}>Peer Fair Value Estimate</div>
        <div style={{ color: "#777", fontSize: 14, fontFamily: "monospace", marginTop: 10 }}>
          {excludedSector
            ? "No fair-value model for this sector."
            : "Not enough comparable peers to estimate a fair value."}
        </div>
        <p style={disclaimer}>
          {excludedSector
            ? "Banks, insurers and REITs trade on book/NAV value, not EV/EBITDA — a peer-multiple estimate would be misleading, so none is shown."
            : "Peer-multiple estimate — needs at least 3 comparable companies in the same industry. Too few here to be meaningful."}
        </p>
        {!excludedSector && !isMobile && val?.peers && val.peers.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 11, color: "#666", fontFamily: "monospace" }}>Only found:</div>
            <PeerDropdown peers={val.peers} />
          </div>
        )}
      </div>
    );
  }

  const up = val.upside_pct;
  const cheap = up >= 0; // current price below fair value → undervalued
  const accent = cheap ? "#22c55e" : "#ef4444";
  const verdict = `${Math.abs(up).toFixed(0)}% ${cheap ? "below" : "above"} fair value`;

  // Proportional track: both prices on a 0..max scale, so the cheaper sits left.
  const scaleMax = Math.max(val.current_price, val.fair_value) * 1.08;
  const curPos = (val.current_price / scaleMax) * 100;
  const fairPos = (val.fair_value / scaleMax) * 100;

  return (
    <div style={card}>
      <div style={title}>Peer Fair Value Estimate</div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 24, fontWeight: 700, fontFamily: "monospace", color: accent }}>
          {verdict}
        </span>
      </div>

      {/* Proportional position bar with current + fair markers */}
      <div style={{ position: "relative", height: 46, margin: "20px 4px 8px" }}>
        <div style={{ position: "absolute", top: 20, left: 0, right: 0, height: 4, background: "#262626", borderRadius: 2 }} />
        {[
          { pos: fairPos, color: "#a78bfa", label: "Fair", value: val.fair_value },
          { pos: curPos, color: accent, label: "Now", value: val.current_price },
        ].map((m) => (
          <div key={m.label} style={{ position: "absolute", left: `${m.pos}%`, top: 0, transform: "translateX(-50%)", textAlign: "center" }}>
            <div style={{ fontSize: 10, color: "#888", fontFamily: "monospace" }}>{m.label}</div>
            <div style={{ width: 2, height: 8, background: m.color, margin: "2px auto 0" }} />
            <div style={{ width: 10, height: 10, borderRadius: 5, background: m.color, margin: "0 auto" }} />
            <div style={{ fontSize: 11, color: m.color, fontFamily: "monospace", marginTop: 2, whiteSpace: "nowrap" }}>{px(m.value)}</div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 11, color: "#777", fontFamily: "monospace", marginTop: 8 }}>
        Based on {val.peer_count} {val.peer_basis} {val.peer_count === 1 ? "peer" : "peers"} · {val.multiple_used}
      </div>
      {!isMobile && <PeerDropdown peers={val.peers} />}

      {val.caution && (
        <div style={{ fontSize: 11, color: "#fbbf24", fontFamily: "monospace", marginTop: 6 }}>
          ⚠ Revenue-multiple estimate (company unprofitable) — treat as low-confidence.
        </div>
      )}

      <p style={disclaimer}>
        Fair value if it traded at its peers&apos; median EV/EBITDA. A relative estimate,
        not a price prediction — quality and growth differences vs peers aren&apos;t adjusted for.
      </p>
    </div>
  );
}
