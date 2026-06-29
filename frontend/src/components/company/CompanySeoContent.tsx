import { fmt } from "@/lib/format";
import type { CompanyMeta, CompanySnap } from "@/lib/companyData";
import { SITE_URL } from "@/lib/seo";
import { tickerSlug } from "@/lib/company";

// Server-rendered, crawlable summary that sits above the interactive (client-only)
// CompanyDetail dashboard. This is the real HTML search engines index for each of
// the ~500 stock pages — a unique H1, a descriptive sentence, key facts and JSON-LD.
//
// It is rendered visually hidden (off-screen, not display:none) because the
// dashboard below already shows the name + metrics to sighted users, so an
// on-page copy was redundant. The dashboard is loaded ssr:false, so this block
// is the ONLY content crawlers can read — keep it in the DOM. Do not switch to
// display:none/visibility:hidden, which can suppress the text for indexing.

interface Props {
  symbol: string;
  meta: CompanyMeta | null;
  snap: CompanySnap | null;
}

const ticker = (symbol: string) => symbol.replace(/\.L$/i, "");

function factList(symbol: string, meta: CompanyMeta | null, snap: CompanySnap | null) {
  const cur = (meta?.financial_currency as string) || "GBP";
  const facts: { label: string; value: string }[] = [
    { label: "Ticker", value: ticker(symbol) },
    { label: "Exchange", value: (meta?.exchange as string) || "London Stock Exchange" },
  ];
  if (meta?.sector) facts.push({ label: "Sector", value: meta.sector as string });
  if (meta?.industry) facts.push({ label: "Industry", value: meta.industry as string });
  if (meta?.ftse_index) facts.push({ label: "Index", value: meta.ftse_index as string });
  if (snap?.market_cap != null)
    facts.push({ label: "Market cap", value: fmt(snap.market_cap, "currency", cur) });
  if (snap?.price_to_earnings != null)
    facts.push({ label: "P/E", value: fmt(snap.price_to_earnings, "x") });
  if (snap?.price_to_book != null)
    facts.push({ label: "P/B", value: fmt(snap.price_to_book, "x") });
  if (snap?.roe != null) facts.push({ label: "ROE", value: fmt(snap.roe, "pct") });
  if (snap?.dividend_yield != null && (snap.dividend_yield as number) > 0)
    facts.push({ label: "Dividend yield", value: fmt(snap.dividend_yield, "pct") });
  return facts;
}

function describe(name: string, symbol: string, meta: CompanyMeta | null, snap: CompanySnap | null) {
  const sector = meta?.sector ? ` in the ${meta.sector} sector` : "";
  const idx = meta?.ftse_index ? `, a constituent of the ${meta.ftse_index}` : "";
  const cap =
    snap?.market_cap != null
      ? ` with a market capitalisation of ${fmt(snap.market_cap, "currency", (meta?.financial_currency as string) || "GBP")}`
      : "";
  return (
    `${name} (${ticker(symbol)}) is a UK-listed company${sector}${idx}${cap}. ` +
    `Explore ${name}'s share price, fundamentals, valuation, financial health, growth, ` +
    `analyst consensus and the latest RNS news below.`
  );
}

export default function CompanySeoContent({ symbol, meta, snap }: Props) {
  const name = (meta?.name as string) || ticker(symbol);
  const facts = factList(symbol, meta, snap);

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Corporation",
    name,
    tickerSymbol: ticker(symbol),
    ...(meta?.exchange ? { exchange: meta.exchange } : {}),
    url: `${SITE_URL}/company/${tickerSlug(symbol)}`,
  };
  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
      { "@type": "ListItem", position: 2, name: "Screener", item: `${SITE_URL}/screener` },
      {
        "@type": "ListItem",
        position: 3,
        name,
        item: `${SITE_URL}/company/${tickerSlug(symbol)}`,
      },
    ],
  };

  return (
    <section
      // Visually hidden but kept in the DOM for search engines (see note above).
      style={{
        position: "absolute",
        width: 1,
        height: 1,
        padding: 0,
        margin: -1,
        overflow: "hidden",
        clip: "rect(0, 0, 0, 0)",
        whiteSpace: "nowrap",
        border: 0,
      }}
    >
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify([jsonLd, breadcrumb]) }}
      />
      <h1
        style={{
          fontFamily: '"DM Serif Display", serif',
          fontSize: 24,
          color: "#f1f5f9",
          margin: "0 0 8px",
        }}
      >
        {name} ({ticker(symbol)}) Share Price &amp; Fundamentals
      </h1>
      <p style={{ color: "#94a3b8", fontSize: 13, lineHeight: 1.6, margin: "0 0 12px", maxWidth: 820 }}>
        {describe(name, symbol, meta, snap)}
      </p>
      <dl
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "6px 10px",
          margin: 0,
          fontSize: 12,
        }}
      >
        {facts.map((f) => (
          <div
            key={f.label}
            style={{
              display: "flex",
              gap: 6,
              padding: "4px 10px",
              background: "#111",
              border: "1px solid #2a2a2a",
              borderRadius: 6,
            }}
          >
            <dt style={{ color: "#64748b", margin: 0 }}>{f.label}</dt>
            <dd style={{ color: "#e5e7eb", margin: 0 }}>{f.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
