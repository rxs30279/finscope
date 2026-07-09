"use client";

/**
 * A fuller, faithful mock of a morning RNS digest — multiple cap-bucket
 * sections, each with a couple of items — rendered in the real email's light
 * theme so visitors see exactly what lands in their inbox. Mirrors the layout
 * in backend/email_rns_digest.py (section heading bar + per-item card).
 *
 * The entries are real recent RNS announcements with their actual AI score,
 * thesis, risk and action — a static snapshot, not a live feed.
 */
type Action = "Research" | "Watch" | "Ignore";

type Item = {
  time: string;
  tier: "A" | "B";
  ticker: string;
  mc: string;
  company: string;
  headline: string;
  category: string;
  score: number;
  action: Action;
  thesis: string;
  risk: string;
};

type Section = {
  label: string;
  sub: string;
  color: string;
  items: Item[];
};

// Real recent RNS entries, bucketed by cap per _CAP_META.
const SECTIONS: Section[] = [
  {
    label: "Mid Cap",
    sub: "FTSE 250",
    color: "#60a5fa",
    items: [
      {
        time: "07:00", tier: "A", ticker: "RPI", mc: "£1.6bn", company: "Raspberry Pi Holdings (WI)",
        headline: "Trading Update", category: "Trading Update",
        score: 85, action: "Research",
        thesis: "FY2026 EBITDA guidance significantly above consensus ($42m) implies material earnings upgrade, driving re-rating for a high-growth FTSE 250 tech stock.",
        risk: "DRAM price increases and supply constraints could erode unit economics in H2, disappointing if guidance proves too optimistic.",
      },
      {
        time: "07:00", tier: "A", ticker: "WIZZ", mc: "£1.1bn", company: "Wizz Air Holdings",
        headline: "Final Results", category: "Final Results",
        score: 30, action: "Watch",
        thesis: "Final results show a dramatic profit collapse (€1.3m vs €213.9m) despite revenue growth, highlighting cost pressures and geopolitical headwinds, but the stock is already down 13.8% over 6 months and consensus is Hold with limited upside, so much may be priced in.",
        risk: "If forward guidance or cost outlook is worse than expected, the stock could fall further.",
      },
    ],
  },
  {
    label: "Small Cap",
    sub: "SmallCap / AIM / other",
    color: "#6b7280",
    items: [
      {
        time: "07:01", tier: "A", ticker: "SAG", mc: "£238m", company: "Science Group",
        headline: "AGM Trading Update and Capital Allocation", category: "Trading Update",
        score: 70, action: "Research",
        thesis: "Strong cash generation and aggressive buyback signal management's view of undervaluation, with net cash now £57m (24% of market cap) and 8.8% of shares repurchased, supporting earnings per share growth and potential further capital returns.",
        risk: "Geopolitical impacts or UK defence contracting challenges could materially reduce revenue or margins, invalidating the resilient outlook.",
      },
      {
        time: "07:00", tier: "A", ticker: "DEBS", mc: "£353m", company: "Boohoo Group",
        headline: "Final Results", category: "Final Results",
        score: 70, action: "Research",
        thesis: "Final results confirm a strong turnaround with 35% EBITDA growth, Debenhams GMV up 11.6%, and PLT swinging to profit, all brands now profitable, which is material for a £353m market cap and supports the recent 42.9% rally.",
        risk: "Net debt at 1.75x EBITDA and high financial leverage (D/E 31.5) could reverse gains if trading deteriorates.",
      },
    ],
  },
];

const TOTAL = SECTIONS.reduce((n, s) => n + s.items.length, 0);

function Row({ it }: { it: Item }) {
  const tierC = it.tier === "A" ? "#f97316" : "#60a5fa";
  const actionC = it.action === "Research" ? "#f97316" : it.action === "Watch" ? "#60a5fa" : "#888";
  return (
    <div style={{ border: "1px solid #eee", borderRadius: 6, overflow: "hidden", marginBottom: 8 }}>
      {/* Meta strip */}
      <div style={{ padding: "8px 12px", background: "#fafafa", borderBottom: "1px solid #eee", display: "flex", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <span style={{ fontFamily: "monospace", color: "#666", fontSize: 12 }}>{it.time}</span>
        <span style={{ background: `${tierC}22`, color: tierC, padding: "2px 6px", borderRadius: 2, fontFamily: "monospace", fontSize: 10, fontWeight: 700 }}>{it.tier}</span>
        <span style={{ fontFamily: "monospace", fontWeight: 700, color: "#111", fontSize: 13 }}>{it.ticker}</span>
        {it.mc && <span style={{ fontFamily: "monospace", color: "#888", fontSize: 11 }}>{it.mc}</span>}
        <span style={{ marginLeft: "auto", fontFamily: "monospace", fontSize: 13, fontWeight: 700, color: "#f97316" }}>{it.score}</span>
      </div>
      {/* Body */}
      <div style={{ padding: "10px 12px" }}>
        <div style={{ fontWeight: 500, color: "#222", fontSize: 13, marginBottom: 2 }}>{it.company}</div>
        <div style={{ color: "#1d4ed8", fontSize: 14, lineHeight: 1.35, marginBottom: 6 }}>{it.headline}</div>
        <div style={{ color: "#555", fontSize: 12, lineHeight: 1.45 }}>
          {it.thesis}
          <div style={{ marginTop: 3, color: "#888", fontSize: 11, lineHeight: 1.45 }}>
            <span style={{ color: "#dc2626" }}>risk:</span> {it.risk}
          </div>
        </div>
        <div style={{ marginTop: 10, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <span style={{ color: "#666", fontSize: 11, fontFamily: "monospace" }}>{it.category}</span>
          <span style={{ background: `${actionC}22`, color: actionC, padding: "2px 8px", borderRadius: 3, fontSize: 10, fontFamily: "monospace", textTransform: "uppercase", letterSpacing: 1 }}>{it.action}</span>
        </div>
      </div>
    </div>
  );
}

function SectionBlock({ s }: { s: Section }) {
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{
        padding: "8px 12px", background: `${s.color}1a`, borderLeft: `4px solid ${s.color}`,
        display: "flex", alignItems: "baseline", flexWrap: "wrap", gap: 12, marginBottom: 8,
      }}>
        <span style={{ fontFamily: "monospace", fontWeight: 700, color: s.color, fontSize: 12, letterSpacing: 2, textTransform: "uppercase" }}>{s.label}</span>
        <span style={{ fontFamily: "monospace", color: "#888", fontSize: 11 }}>{s.sub}</span>
        <span style={{ marginLeft: "auto", fontFamily: "monospace", color: "#666", fontSize: 11 }}>{s.items.length} item{s.items.length !== 1 ? "s" : ""}</span>
      </div>
      {s.items.map((it) => <Row key={it.ticker} it={it} />)}
    </div>
  );
}

export function DigestSample() {
  return (
    <div style={{
      fontFamily: "var(--font-inter), system-ui, sans-serif",
      background: "#fff",
      color: "#222",
      border: "1px solid #e5e5e5",
      borderRadius: 8,
      padding: 16,
    }}>
      {/* Subject / masthead */}
      <div style={{ borderBottom: "1px solid #eee", paddingBottom: 14 }}>
        <div style={{ fontFamily: "monospace", fontWeight: 700, color: "#f97316", fontSize: 11, letterSpacing: 2, textTransform: "uppercase" }}>Alpha Move AI</div>
        <div style={{ color: "#222", fontSize: 16, fontWeight: 600, marginTop: 6 }}>RNS Digest</div>
        <div style={{ color: "#888", fontSize: 12, marginTop: 3 }}>The last 24h of high-impact RNS, AI-ranked · {TOTAL} items</div>
      </div>

      {SECTIONS.map((s) => <SectionBlock key={s.label} s={s} />)}

      <div style={{ marginTop: 18, color: "#aaa", fontSize: 11, fontFamily: "monospace", textAlign: "center" }}>
        Real RNS announcements, AI-ranked — an example morning.
      </div>
    </div>
  );
}
