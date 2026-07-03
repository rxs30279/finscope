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
  peer_basis: string; // 'industry' | 'excluded_sector' | 'insufficient' | 'out_of_range'
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

// Five sentiment-style bands across upside_pct, clamped to -50..+50 — same
// palette family as the Fear & Greed dial (FG_BANDS in FearGreedTab.js), just
// centred on 0 (fair value) instead of 50 (neutral). Positive = cheap (current
// price below fair value) sits on the left/green side, negative = overvalued
// on the right/red side.
const FV_BANDS: { lo: number; hi: number; norm: [number, number]; color: string; label: string }[] = [
  { lo: 25, hi: 50, norm: [0, 25], color: "#16d96b", label: "Very Cheap" },
  { lo: 10, hi: 25, norm: [25, 40], color: "#7ed321", label: "Cheap" },
  { lo: -10, hi: 10, norm: [40, 60], color: "#9ca3af", label: "Near Fair" },
  { lo: -25, hi: -10, norm: [60, 75], color: "#ff7a14", label: "Expensive" },
  { lo: -50, hi: -25, norm: [75, 100], color: "#ff2e3f", label: "Very Expensive" },
];
function fvBandIndex(up: number) {
  const clamped = Math.max(-50, Math.min(50, up));
  const idx = FV_BANDS.findIndex((b) => clamped >= b.lo && clamped < (b.hi === 50 ? 51 : b.hi));
  return idx < 0 ? 2 : idx;
}

// CNN-style semicircular dial, adapted from FearGreedGauge (FearGreedTab.js):
// same donut-band-with-gaps geometry, active-band-lit/rest-muted treatment,
// curved band labels and triangle needle — remapped to a -50%..+50% upside
// scale centred on "fair value" instead of a 0-100 sentiment scale, and
// trimmed down (no dot tick-ring, smaller footprint) to fit a compact card.
function FairValueGauge({ up }: { up: number }) {
  const cx = 180, cy = 195, R = 175, r = 115;
  const rmid = R - 19;
  const tip = r + 16;
  const clamped = Math.max(-50, Math.min(50, up));
  const norm = 50 - clamped; // cheap (+50) → 0 (left), overvalued (-50) → 100 (right)

  const polar = (v: number, rad: number): [number, number] => {
    const t = ((180 - 1.8 * v) * Math.PI) / 180;
    return [cx + rad * Math.cos(t), cy - rad * Math.sin(t)];
  };
  const GAP = 5;
  const bandPath = (lo: number, hi: number, gapLo: boolean, gapHi: boolean) => {
    const tLo = ((180 - 1.8 * lo) * Math.PI) / 180;
    const tHi = ((180 - 1.8 * hi) * Math.PI) / 180;
    const sLo = gapLo ? GAP / 2 : 0;
    const sHi = gapHi ? GAP / 2 : 0;
    const oLx = Math.sin(tLo) * sLo, oLy = Math.cos(tLo) * sLo;
    const oHx = -Math.sin(tHi) * sHi, oHy = -Math.cos(tHi) * sHi;
    const [ox1, oy1] = polar(lo, R), [ox2, oy2] = polar(hi, R);
    const [ix2, iy2] = polar(hi, r), [ix1, iy1] = polar(lo, r);
    return `M ${ox1 + oLx} ${oy1 + oLy} A ${R} ${R} 0 0 1 ${ox2 + oHx} ${oy2 + oHy} L ${ix2 + oHx} ${iy2 + oHy} A ${r} ${r} 0 0 0 ${ix1 + oLx} ${iy1 + oLy} Z`;
  };
  const labelArc = (lo: number, hi: number) => {
    const [x1, y1] = polar(lo, rmid), [x2, y2] = polar(hi, rmid);
    return `M ${x1} ${y1} A ${rmid} ${rmid} 0 0 1 ${x2} ${y2}`;
  };

  const activeIdx = fvBandIndex(up);
  const activeColor = FV_BANDS[activeIdx].color;

  const tA = ((180 - 1.8 * norm) * Math.PI) / 180;
  const tipX = cx + tip * Math.cos(tA), tipY = cy - tip * Math.sin(tA);
  const bw = 7;
  const bx1 = cx + bw * Math.sin(tA), by1 = cy + bw * Math.cos(tA);
  const bx2 = cx - bw * Math.sin(tA), by2 = cy - bw * Math.cos(tA);

  // Displayed as a discount/premium to fair value — negative means trading
  // below fair value (cheap), positive means trading above it (overvalued) —
  // so it reads with the same sign as its position on the now cheap-left dial.
  const gap = -up;
  const hubLabel = `${gap >= 0 ? "+" : ""}${Math.round(gap)}%`;

  return (
    <svg viewBox="0 0 360 244" width="100%" style={{ maxWidth: 420, display: "block", margin: "4px auto 0" }}>
      <defs>
        {FV_BANDS.map((b, i) => (
          <path key={i} id={`fv-lbl-${i}`} d={labelArc(b.norm[0], b.norm[1])} fill="none" />
        ))}
        <radialGradient id="fv-dial" cx={cx} cy={cy} r={R} gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#2a2a34" />
          <stop offset="0.6" stopColor="#1a1a20" />
          <stop offset="1" stopColor="#111111" />
        </radialGradient>
        <radialGradient id="fv-seg-on" cx={cx} cy={cy} r={R} gradientUnits="userSpaceOnUse">
          <stop offset="0.6" stopColor={activeColor} stopOpacity="1" />
          <stop offset="1" stopColor={activeColor} stopOpacity="0.62" />
        </radialGradient>
        <radialGradient id="fv-seg-off" cx={cx} cy={cy} r={R} gradientUnits="userSpaceOnUse">
          <stop offset="0.6" stopColor="#2c2c34" />
          <stop offset="1" stopColor="#1a1a1e" />
        </radialGradient>
        {/* The needle's base is a few px wide, so off-vertical angles poke one
            corner past the hub's flat baseline — clip everything to the top
            half so that sliver never shows below the dial. */}
        <clipPath id="fv-clip-top">
          <rect x="0" y="0" width="360" height={cy} />
        </clipPath>
      </defs>

      {/* Gradient backdrop, top half only */}
      <path d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy} Z`} fill="url(#fv-dial)" />

      {/* Bands — active one lit in its colour, the rest muted grey */}
      {FV_BANDS.map((b, i) => {
        const active = i === activeIdx;
        return (
          <path
            key={i}
            d={bandPath(b.norm[0], b.norm[1], i > 0, i < FV_BANDS.length - 1)}
            fill={active ? "url(#fv-seg-on)" : "url(#fv-seg-off)"}
            stroke={active ? b.color : "#2c2c30"}
            strokeWidth={1}
          />
        );
      })}

      {/* Curved band labels */}
      {FV_BANDS.map((b, i) => (
        <text
          key={i}
          fontSize="10.5"
          fontFamily="monospace"
          fontWeight="800"
          letterSpacing="0.5"
          textAnchor="middle"
          fill={i === activeIdx ? "#0b0b0b" : "#71717a"}
        >
          <textPath href={`#fv-lbl-${i}`} startOffset="50%">{b.label.toUpperCase()}</textPath>
        </text>
      ))}

      {/* Scale ticks — just the five boundary numbers, no dot ring. v is in
          "up" terms (positions the tick), but the printed label is the
          negated discount/premium value, matching the hub's sign convention. */}
      {[-50, -25, 0, 25, 50].map((v) => {
        const [x, y] = polar(50 - v, r - 12);
        const dy = v === -50 || v === 50 ? 0 : 4;
        const label = -v;
        return (
          <text key={v} x={x} y={y + dy} fontSize="11" fontFamily="monospace" fill="#71717a" textAnchor="middle">
            {label > 0 ? `+${label}` : label}
          </text>
        );
      })}

      {/* Needle */}
      <g clipPath="url(#fv-clip-top)">
        <polygon
          points={`${tipX},${tipY} ${bx1},${by1} ${bx2},${by2}`}
          fill="#e5e5e5"
          stroke="#0b0b0b"
          strokeWidth="0.5"
          strokeLinejoin="round"
        />
      </g>

      {/* Hub + signed upside readout */}
      <path d={`M ${cx - 48} ${cy} A 48 48 0 0 1 ${cx + 48} ${cy} Z`} fill="#0b0b0b" />
      <text x={cx} y={cy - 6} fontSize="26" fontWeight="700" fontFamily="monospace" fill={activeColor} textAnchor="middle">
        {hubLabel}
      </text>
    </svg>
  );
}

export default function FairValueCard({ val }: { val: ValuationData | null }) {
  // Peer breakdown is desktop-only — a secondary detail not worth the vertical
  // space it costs on a phone-width Valuation tab.
  const isMobile = useIsMobile();

  // Empty state — no defensible peer-based estimate. peer_basis distinguishes
  // "this sector isn't modeled at all" (banks/insurers/REITs trade on book
  // value, not EV/EBITDA — no peer search was ever attempted), "this company's
  // industry genuinely has too few peers", and "peers were found but the
  // implied value tripped the sanity guards" (e.g. a very cheap name vs a much
  // richer peer median implies >150% upside — suppressed as indefensible).
  if (!val || val.fair_value == null || val.upside_pct == null || val.current_price == null) {
    const excludedSector = val?.peer_basis === "excluded_sector";
    const outOfRange = val?.peer_basis === "out_of_range";
    return (
      <div style={card}>
        <div style={title}>Peer Fair Value Estimate</div>
        <div style={{ color: "#777", fontSize: 14, fontFamily: "monospace", marginTop: 10 }}>
          {excludedSector
            ? "No fair-value model for this sector."
            : outOfRange
              ? "Peer estimate outside defensible range."
              : "Not enough comparable peers to estimate a fair value."}
        </div>
        <p style={disclaimer}>
          {excludedSector
            ? "Banks, insurers and REITs trade on book/NAV value, not EV/EBITDA — a peer-multiple estimate would be misleading, so none is shown."
            : outOfRange
              ? "This company's peer multiples imply a fair value beyond what this method can defend (over 150% from the current price, or a negative equity value) — usually a sign the peer group doesn't reflect its economics — so no estimate is shown."
              : "Peer-multiple estimate — needs at least 3 comparable companies in the same industry. Too few here to be meaningful."}
        </p>
        {!excludedSector && !isMobile && val?.peers && val.peers.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 11, color: "#666", fontFamily: "monospace" }}>
              {outOfRange ? "Peers used:" : "Only found:"}
            </div>
            <PeerDropdown peers={val.peers} />
          </div>
        )}
      </div>
    );
  }

  const up = val.upside_pct;
  const cheap = up >= 0; // current price below fair value → undervalued
  const band = FV_BANDS[fvBandIndex(up)];

  return (
    <div style={card}>
      <div style={title}>Peer Fair Value Estimate</div>

      <div style={{ fontSize: 12, fontFamily: "monospace", color: "#555", textAlign: "left", marginTop: 8 }}>
        <span style={{ color: band.color, fontWeight: 700 }}>{band.label}</span>
        {" · "}{Math.abs(up).toFixed(1)}% {cheap ? "below" : "above"} fair value
        {" · "}Fair {px(val.fair_value)} · Now {px(val.current_price)}
      </div>

      <div style={{ marginTop: 4 }}>
        <FairValueGauge up={up} />
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
