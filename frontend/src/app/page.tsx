import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: {
    absolute: "Alpha Move AI — Free UK Stock Screener (FTSE 100, 250, SmallCap, AIM)",
  },
  description:
    "Alpha Move AI is a free UK stock screener covering the FTSE 100, 250, SmallCap and " +
    "AIM. Screen by fundamentals, quality, value, growth, momentum and risk, track analyst " +
    "consensus, read AI-scored RNS news and watch market signals — all in one place.",
  alternates: { canonical: "/" },
};

const FEATURES: { href: string; title: string; body: string }[] = [
  {
    href: "/screener",
    title: "Stock Screener",
    body: "Filter 500+ UK shares by valuation, quality, growth, momentum and risk, with composite scores computed daily.",
  },
  {
    href: "/markets",
    title: "Market Signals",
    body: "Read the room with the UK Fear & Greed index, market breadth, sector rotation and cross-asset signals.",
  },
  {
    href: "/trending",
    title: "Trending Movers",
    body: "Today's biggest risers and fallers, plus momentum streaks across every London index.",
  },
  {
    href: "/analysts",
    title: "Analyst Consensus",
    body: "Broker ratings, price-target upside and the latest upgrades and downgrades for UK shares.",
  },
  {
    href: "/rns",
    title: "RNS News, Scored",
    body: "London Stock Exchange regulatory announcements filtered and ranked by significance.",
  },
  {
    href: "/subscribe",
    title: "Free Email Digest",
    body: "A weekday email of notable movers and the most significant RNS news, straight to your inbox.",
  },
];

const card: React.CSSProperties = {
  display: "block",
  padding: "20px 22px",
  background: "#111",
  border: "1px solid #2a2a2a",
  borderRadius: 8,
  textDecoration: "none",
};

export default function Home() {
  return (
    <div style={{ maxWidth: 960, margin: "0 auto", color: "#e5e7eb", fontFamily: "monospace" }}>
      <section style={{ padding: "32px 0 8px" }}>
        <p
          style={{
            color: "#f97316",
            fontSize: 12,
            letterSpacing: 3,
            textTransform: "uppercase",
            margin: "0 0 14px",
          }}
        >
          Alpha Move AI
        </p>
        <h1
          style={{
            fontFamily: '"DM Serif Display", serif',
            fontSize: 40,
            lineHeight: 1.15,
            color: "#f1f5f9",
            margin: "0 0 18px",
          }}
        >
          The free UK stock screener for asymmetric opportunities
        </h1>
        <p style={{ fontSize: 16, lineHeight: 1.6, color: "#94a3b8", maxWidth: 720, margin: "0 0 26px" }}>
          Research the entire London market — FTSE 100, FTSE 250, FTSE SmallCap and AIM — in
          one place. Screen on fundamentals and composite quality, value, growth, momentum and
          risk scores; track analyst consensus and price-target upside; read AI-scored RNS news;
          and gauge the market with a UK Fear &amp; Greed index, breadth and sector rotation.
        </p>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Link
            href="/screener"
            style={{
              ...card,
              background: "linear-gradient(135deg, #2a1a00 0%, #1a1200 100%)",
              border: "1px solid #3a2600",
              color: "#f97316",
              padding: "12px 22px",
              fontWeight: 700,
            }}
          >
            Open the screener →
          </Link>
          <Link
            href="/markets"
            style={{ ...card, padding: "12px 22px", color: "#e5e7eb" }}
          >
            See market signals
          </Link>
        </div>
      </section>

      <section style={{ padding: "36px 0" }}>
        <h2 style={{ fontSize: 14, letterSpacing: 2, textTransform: "uppercase", color: "#64748b", margin: "0 0 18px" }}>
          What's inside
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: 14,
          }}
        >
          {FEATURES.map((f) => (
            <Link key={f.href} href={f.href} style={card}>
              <h3 style={{ margin: "0 0 8px", fontSize: 16, color: "#f1f5f9" }}>{f.title}</h3>
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.55, color: "#94a3b8" }}>{f.body}</p>
            </Link>
          ))}
        </div>
      </section>

      <section style={{ padding: "8px 0 48px", color: "#64748b", fontSize: 12, lineHeight: 1.6 }}>
        <p style={{ margin: 0 }}>
          Alpha Move AI is a free research tool for UK equities and does not provide financial
          advice. Always do your own research before investing.
        </p>
      </section>
    </div>
  );
}
