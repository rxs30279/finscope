// ── Support / Donate ──────────────────────────────────────────────────────────
// Ko-fi-backed tip jar. No backend, no PCI scope — the button just deep-links to
// the hosted Ko-fi page. Set KOFI_URL to your own page before shipping.
//
// Copy follows the "fund a free thing" playbook: be concrete about running costs,
// remind people of the value they already got, and keep it explicitly optional —
// no paywall, no guilt. That converts better than a bare tip button.

// TODO: replace with your real Ko-fi (or Buy Me a Coffee) page URL.
const KOFI_URL = "https://ko-fi.com/alphamoveai";

// Rough monthly running costs, shown for transparency to a finance-savvy
// audience. Edit the figures to match reality — concrete numbers build trust.
const COSTS = [
  ["Market & price data", "£0"],
  ["LLM ranking layer", "£10"],
  ["Email digest delivery", "£20"],
  ["Hosting (Render + Vercel + DB)", "£10"],
];

const LABEL = {
  color: "#f97316",
  fontSize: 10,
  fontFamily: "monospace",
  textTransform: "uppercase",
  letterSpacing: 2,
  marginBottom: 8,
};

const CARD = {
  background: "#141414",
  border: "1px solid #2a2a2a",
  borderRadius: 4,
  padding: 24,
  marginBottom: 24,
};

const BTN = {
  display: "inline-block",
  background: "linear-gradient(135deg, #2a1a00 0%, #1a1200 100%)",
  border: "1px solid #f97316",
  color: "#f97316",
  padding: "12px 26px",
  fontSize: 13,
  fontFamily: "monospace",
  fontWeight: 700,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  borderRadius: 3,
  textDecoration: "none",
  boxShadow: "0 0 12px rgba(249, 115, 22, 0.15)",
};

// Suggested amounts, framed against the real cost of running the tool so the
// number means something ("£3 = a day of data") rather than an arbitrary tip.
const TIERS = [
  ["£2", "a day of data flowing"],
  ["£1", "a month of one reader's emails"],
  ["£5", "a good chunk of a month's hosting"],
];

export default function DonateTab() {
  return (
    <div style={{ maxWidth: 640 }}>
      <h2
        style={{
          margin: "0 0 4px",
          fontFamily: "monospace",
          color: "#f97316",
          fontSize: 18,
          letterSpacing: 2,
          textTransform: "uppercase",
        }}
      >
        Support Alpha Move AI
      </h2>
      <div
        style={{
          color: "#666",
          fontSize: 12,
          fontFamily: "monospace",
          marginBottom: 24,
        }}
      >
        Always free — supported by readers, not paywalls.
      </div>

      <div style={CARD}>
        <div style={LABEL}>Why this exists</div>
        <div style={{ color: "#94a3b8", fontSize: 13, lineHeight: 1.7 }}>
          Alpha Move AI is a one-person project — free for everyone, no ads, no
          paywall. If the screener, the AI-ranked RNS digest, or the analyst
          signals have saved you time or sharpened a decision, a small tip helps
          keep it running and independent. More support means a faster, better
          tool: improved hosting to speed up the site, better-curated data, and
          more headroom to build new features. Entirely optional; using it for
          free is always welcome.
        </div>
      </div>

      <div style={CARD}>
        <div style={LABEL}>What it costs to run</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {COSTS.map(([item, cost]) => (
            <div
              key={item}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                fontFamily: "monospace",
                fontSize: 13,
                borderBottom: "1px solid #1f1f1f",
                paddingBottom: 6,
              }}
            >
              <span style={{ color: "#94a3b8" }}>{item}</span>
              <span style={{ color: "#e5e5e5" }}>{cost}/mo</span>
            </div>
          ))}
        </div>
      </div>

      <div style={CARD}>
        <div style={LABEL}>Chip in</div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 6,
            marginBottom: 18,
          }}
        >
          {TIERS.map(([amt, note]) => (
            <div
              key={amt}
              style={{
                display: "flex",
                gap: 10,
                alignItems: "baseline",
                fontFamily: "monospace",
                fontSize: 13,
              }}
            >
              <span style={{ color: "#f97316", fontWeight: 700, minWidth: 44 }}>
                {amt}
              </span>
              <span style={{ color: "#666" }}>= {note}</span>
            </div>
          ))}
        </div>
        <a
          href={KOFI_URL}
          target="_blank"
          rel="noopener noreferrer"
          style={BTN}
        >
          ♥ Buy me a coffee
        </a>
        <div
          style={{
            color: "#555",
            fontSize: 11,
            fontFamily: "monospace",
            marginTop: 12,
          }}
        >
          Secure checkout via Ko-fi · one-off or monthly · cancel anytime
        </div>
      </div>

      <div
        style={{
          color: "#666",
          fontSize: 12,
          fontFamily: "monospace",
          lineHeight: 1.7,
        }}
      >
        Not in a position to give? No problem at all — sharing the tool with
        another investor helps just as much. Thank you.
      </div>
    </div>
  );
}
