import { fmt } from "@/lib/format";
import type { CompanyMeta, CompanySnap } from "@/lib/companyData";
import { SITE_URL, jsonLdString } from "@/lib/seo";
import { tickerSlug, sectorHref } from "@/lib/company";
import { S } from "@/lib/theme";
import LogoBadge from "./LogoBadge";
import CompanyStar from "./CompanyStar";
import ScoreStrip from "./ScoreStrip";
import ExpandableText from "./ExpandableText";

// The real, VISIBLE company-page header, server-rendered so it's the content
// search engines index (the interactive dashboard below is ssr:false). This used
// to be a visually-hidden block duplicating the dashboard; it's now the single
// on-page header, and the dashboard's own header was removed to avoid duplication.
// Keep it in the server component — do not add client-only hooks here.

interface Props {
  symbol: string;
  meta: CompanyMeta | null;
  snap: CompanySnap | null;
}

const ticker = (symbol: string) => symbol.replace(/\.L$/i, "");

// Shared pill/chip box for the header fact row.
const pillStyle: React.CSSProperties = {
  padding: "4px 10px",
  background: "#111",
  border: "1px solid #2a2a2a",
  borderRadius: 6,
};

// Market cap / EV come from Yahoo's `info`, denominated in the QUOTE (trading)
// currency — GBP for most LSE lines — not the reporting currency. Label them
// with the same quote-currency fallback chain everywhere in this header.
function quoteCurrency(meta: CompanyMeta | null): string {
  return (meta?.currency as string) || (meta?.financial_currency as string) || "GBP";
}

// Header facts in two groups: descriptive identity pills (value only — greyed,
// like the original page) shown directly under the name, and numeric metric pills
// (labelled) below them. Market cap is omitted — it's in the top-right aside.
function factList(symbol: string, meta: CompanyMeta | null, snap: CompanySnap | null) {
  const identity: { value: string }[] = [
    { value: ticker(symbol) },
    { value: (meta?.exchange as string) || "London Stock Exchange" },
  ];
  if (meta?.country) identity.push({ value: meta.country as string });
  if (meta?.sector) identity.push({ value: meta.sector as string });
  if (meta?.industry) identity.push({ value: meta.industry as string });
  if (meta?.ftse_index) identity.push({ value: meta.ftse_index as string });

  const metrics: { label: string; value: string }[] = [];
  if (snap?.price_to_earnings != null)
    metrics.push({ label: "P/E", value: fmt(snap.price_to_earnings, "x") });
  if (snap?.price_to_book != null)
    metrics.push({ label: "P/B", value: fmt(snap.price_to_book, "x") });
  if (snap?.roic != null) metrics.push({ label: "ROIC", value: fmt(snap.roic, "pct") });
  if (snap?.dividend_yield != null && (snap.dividend_yield as number) > 0)
    metrics.push({ label: "Dividend yield", value: fmt(snap.dividend_yield, "pct") });

  return { identity, metrics };
}

function describe(name: string, symbol: string, meta: CompanyMeta | null, snap: CompanySnap | null) {
  const sector = meta?.sector ? ` in the ${meta.sector} sector` : "";
  const idx = meta?.ftse_index ? `, a constituent of the ${meta.ftse_index}` : "";
  const cap =
    snap?.market_cap != null
      ? ` with a market capitalisation of ${fmt(snap.market_cap, "currency", quoteCurrency(meta))}`
      : "";
  return (
    `${name} (${ticker(symbol)}) is a UK-listed company${sector}${idx}${cap}. ` +
    `Explore ${name}'s share price, fundamentals, valuation, financial health, growth, ` +
    `analyst consensus and the latest RNS news below.`
  );
}

export default function CompanyHeader({ symbol, meta, snap }: Props) {
  const name = (meta?.name as string) || ticker(symbol);
  const sector = (meta?.sector as string) || "";
  const description = (meta?.description as string) || "";
  const website = (meta?.website as string) || "";
  const { identity: idFacts, metrics: metricFacts } = factList(symbol, meta, snap);
  const qcur = quoteCurrency(meta);

  // Keep the ★ glued to the last word of the name rather than dropping to its
  // own line (matches the old dashboard header behaviour).
  const words = name.split(" ");
  const lastWord = words.pop() as string;
  const nameHead = words.join(" ");

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Corporation",
    name,
    tickerSymbol: ticker(symbol),
    url: `${SITE_URL}/company/${tickerSlug(symbol)}`,
    // Full business description lives here so it stays crawlable even though the
    // visible copy is truncated to "…more" by default (ExpandableText slices it).
    ...(description ? { description } : {}),
    ...(website ? { sameAs: [website] } : {}),
  };
  const crumbs: { name: string; item: string }[] = [
    { name: "Home", item: SITE_URL },
    { name: "Companies", item: `${SITE_URL}/companies` },
  ];
  if (sector) crumbs.push({ name: sector, item: `${SITE_URL}${sectorHref(sector)}` });
  crumbs.push({ name, item: `${SITE_URL}/company/${tickerSlug(symbol)}` });
  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((c, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: c.name,
      item: c.item,
    })),
  };

  // scrollSnapAlign + scrollMarginTop (= 52px sticky-nav height) let a small scroll
  // settle the company name just below the nav (see the html rule in globals.css).
  return (
    <section style={{ marginBottom: 24, scrollSnapAlign: "start", scrollMarginTop: 52 }}>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString([jsonLd, breadcrumb]) }}
      />

      {/* The visible breadcrumb lives in CompanyBreadcrumb, rendered at the very
          top of the page (above the CTA banner). This section keeps only the
          matching JSON-LD. */}

      <div className="company-header company-header--wide">
        <div className="company-header__main">
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 10 }}>
            {/* The logo doubles as the link to the company's own website (when we
                have one), replacing the separate text link below the description. */}
            {website ? (
              <a
                href={website}
                target="_blank"
                rel="noopener nofollow"
                aria-label={`${name} website`}
                title={`${name} website`}
                style={{ display: "inline-flex", flexShrink: 0, borderRadius: 12 }}
              >
                <LogoBadge symbol={symbol} />
              </a>
            ) : (
              <LogoBadge symbol={symbol} />
            )}
            <div>
              <h1 style={{ margin: 0, fontFamily: '"DM Serif Display", serif', fontSize: 26, color: "#f1f5f9", lineHeight: 1.2 }}>
                {nameHead && nameHead + " "}
                <span style={{ whiteSpace: "nowrap" }}>
                  {lastWord}
                  <span style={{ position: "relative", top: -5, marginLeft: 6, display: "inline-flex", verticalAlign: "middle" }}>
                    <CompanyStar symbol={symbol} />
                  </span>
                </span>
              </h1>
              {/* Descriptive identity pills, directly under the name — greyed,
                  matching the original page's badges (S.badge). */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                {idFacts.map((f) => (
                  <span key={f.value} style={S.badge}>{f.value}</span>
                ))}
              </div>
            </div>
          </div>
          {/* The real company description (expandable, like the old dashboard
              header) when we have one; the templated sentence is only a fallback
              so uncovered names still get crawlable prose. */}
          <div style={{ margin: "0 0 12px", maxWidth: 820 }}>
            {description ? (
              <ExpandableText text={description} />
            ) : (
              <p style={{ color: "#94a3b8", fontSize: 13, lineHeight: 1.6, margin: 0 }}>
                {describe(name, symbol, meta, snap)}
              </p>
            )}
          </div>
          {/* Numeric metric pills below the description (labelled — a bare
              "12.5x" is meaningless). */}
          {metricFacts.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 10px", margin: 0, fontSize: 12 }}>
              {metricFacts.map((f) => (
                <span key={f.label} style={{ ...pillStyle, display: "flex", gap: 6 }}>
                  <span style={{ color: "#64748b" }}>{f.label}</span>
                  <span style={{ color: "#e5e7eb" }}>{f.value}</span>
                </span>
              ))}
            </div>
          )}
        </div>

        {snap?.market_cap != null && (
          <div className="company-header__aside">
            <div style={{ fontSize: 30, fontFamily: '"DM Serif Display", serif', color: "#f1f5f9" }}>
              {fmt(snap.market_cap, "currency", qcur)}
            </div>
            <div style={{ fontSize: 12, color: "#64748b" }}>Market Cap</div>
            {snap.enterprise_value != null && (
              <div style={{ fontSize: 13, color: "#94a3b8", marginTop: 2 }}>
                EV: {fmt(snap.enterprise_value as number, "currency", qcur)}
              </div>
            )}
            <div style={{ marginTop: 10 }}>
              <ScoreStrip snap={snap} align="right" />
            </div>
          </div>
        )}
      </div>

      {/* Mobile header — reproduces the original production dashboard layout the
          SEO overhaul replaced: logo top-left with the market cap / EV stacked
          beneath it, the name beside the logo, then a full-width score strip and
          the description (no pill rows, matching the original). Shown only at the
          useIsMobile() breakpoint; the .company-header--wide block above is hidden
          there. Both are server-rendered, so exactly one visible <h1> exists at
          any viewport — no SEO-invisible content. */}
      <div className="company-header-mobile">
        <div
          style={{
            position: "relative",
            display: "flex",
            justifyContent: "flex-start",
            alignItems: "flex-start",
            minHeight: snap?.market_cap != null ? 144 : 64,
          }}
        >
          {/* Logo + market cap, pinned left and out of flow so the block below
              (score strip) lands directly under the EV line, not under the name. */}
          <div style={{ position: "absolute", left: 0, top: 0 }}>
            {website ? (
              <a
                href={website}
                target="_blank"
                rel="noopener nofollow"
                aria-label={`${name} website`}
                title={`${name} website`}
                style={{ display: "inline-flex", borderRadius: 12 }}
              >
                <LogoBadge symbol={symbol} />
              </a>
            ) : (
              <LogoBadge symbol={symbol} />
            )}
            {snap?.market_cap != null && (
              <div style={{ marginTop: 18 }}>
                <div style={{ fontSize: 22, fontFamily: '"DM Serif Display", serif', color: "#f1f5f9" }}>
                  {fmt(snap.market_cap, "currency", qcur)}
                </div>
                <div style={{ fontSize: 11, color: "#64748b" }}>
                  Market Cap
                  {snap.enterprise_value != null
                    ? ` · EV ${fmt(snap.enterprise_value as number, "currency", qcur)}`
                    : ""}
                </div>
              </div>
            )}
          </div>
          {/* Name beside the logo, vertically centred on its 64px height. */}
          <div style={{ minHeight: 64, marginLeft: 84, marginRight: 8, display: "flex", alignItems: "center" }}>
            <h1 style={{ margin: 0, fontFamily: '"DM Serif Display", serif', fontSize: 22, color: "#f1f5f9", lineHeight: 1.2 }}>
              {nameHead && nameHead + " "}
              <span style={{ whiteSpace: "nowrap" }}>
                {lastWord}
                <span style={{ position: "relative", top: -5, marginLeft: 6, display: "inline-flex", verticalAlign: "middle" }}>
                  <CompanyStar symbol={symbol} size={22} />
                </span>
              </span>
            </h1>
          </div>
        </div>
        {snap && <ScoreStrip snap={snap} />}
        <div>
          {description ? (
            <ExpandableText text={description} />
          ) : (
            <p style={{ color: "#94a3b8", fontSize: 13, lineHeight: 1.6, margin: 0 }}>
              {describe(name, symbol, meta, snap)}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
