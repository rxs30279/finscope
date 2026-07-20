import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getCompaniesList, type CompanyListItem } from "@/lib/companyData";
import { companyHref, sectorSlug, sectorHref } from "@/lib/company";
import { fmt } from "@/lib/format";
import { SITE_URL, SITE_NAME, jsonLdString } from "@/lib/seo";

export const revalidate = 86400;

const ticker = (symbol: string) => symbol.replace(/\.L$/i, "");

interface PageProps {
  params: Promise<{ slug: string }>;
}

// Resolve a slug back to the sector name (+ its constituents) from the shared list.
// Returns null ONLY for a genuinely unknown slug (→ notFound). An empty list means
// the API call failed, so throw instead: notFound() during an ISR revalidation
// would cache a 404 for every sector hub for the whole revalidate window, while a
// throw keeps serving the last good page.
async function resolveSector(slug: string): Promise<{ sector: string; rows: CompanyListItem[]; allSectors: string[] } | null> {
  const companies = await getCompaniesList();
  if (!companies.length) {
    throw new Error("companies list unavailable — refusing to 404 sector hubs");
  }
  const allSectors = Array.from(
    new Set(companies.map((c) => c.sector).filter(Boolean) as string[]),
  ).sort();
  const sector = allSectors.find((s) => sectorSlug(s) === slug);
  if (!sector) return null;
  const rows = companies
    .filter((c) => c.sector === sector)
    .sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0));
  return { sector, rows, allSectors };
}

export async function generateStaticParams() {
  const companies = await getCompaniesList();
  const sectors = new Set(companies.map((c) => c.sector).filter(Boolean) as string[]);
  return Array.from(sectors).map((s) => ({ slug: sectorSlug(s) }));
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const resolved = await resolveSector(slug);
  if (!resolved) return { title: "Sector not found" };
  const { sector, rows } = resolved;
  const title = `UK ${sector} Stocks — Share Prices & Fundamentals`;
  const description =
    `All ${rows.length} UK-listed ${sector} companies — share prices, fundamentals, valuation, ` +
    `analyst consensus and RNS news on ${SITE_NAME}.`;
  return {
    title,
    description,
    alternates: { canonical: `/companies/sector/${slug}` },
    openGraph: { type: "website", title, description, url: `/companies/sector/${slug}` },
  };
}

export default async function SectorHubPage({ params }: PageProps) {
  const { slug } = await params;
  const resolved = await resolveSector(slug);
  if (!resolved) notFound();
  const { sector, rows, allSectors } = resolved;

  // market_cap is denominated in each row's quote currency (GBP for most LSE
  // lines, but not all). Only quote a combined figure when every cap in the
  // sector shares one currency — a cross-currency sum would be meaningless.
  const capCurrencies = new Set(
    rows.filter((r) => r.market_cap != null).map((r) => r.currency || "GBP"),
  );
  const capCurrency = capCurrencies.size === 1 ? Array.from(capCurrencies)[0] : null;
  const totalCap = capCurrency
    ? rows.reduce((sum, r) => sum + (r.market_cap || 0), 0)
    : 0;
  const largest = rows[0];
  const indexCounts = new Map<string, number>();
  for (const r of rows) {
    if (r.ftse_index) indexCounts.set(r.ftse_index, (indexCounts.get(r.ftse_index) || 0) + 1);
  }
  const indexSplit = Array.from(indexCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${v} ${k}`)
    .join(", ");

  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
      { "@type": "ListItem", position: 2, name: "Companies", item: `${SITE_URL}/companies` },
      { "@type": "ListItem", position: 3, name: sector, item: `${SITE_URL}${sectorHref(sector)}` },
    ],
  };

  return (
    <div style={{ padding: "16px 0", fontFamily: "monospace" }}>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumb) }} />

      <nav aria-label="Breadcrumb" style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
        <Link href="/" style={{ color: "#64748b", textDecoration: "none" }}>Home</Link>
        <span style={{ margin: "0 6px" }}>›</span>
        <Link href="/companies" style={{ color: "#64748b", textDecoration: "none" }}>Companies</Link>
        <span style={{ margin: "0 6px" }}>›</span>
        <span style={{ color: "#94a3b8" }}>{sector}</span>
      </nav>

      <h1 style={{ fontFamily: '"DM Serif Display", serif', fontSize: 28, color: "#f1f5f9", margin: "0 0 8px" }}>
        UK {sector} Stocks
      </h1>
      <p style={{ color: "#94a3b8", fontSize: 13, lineHeight: 1.6, maxWidth: 820, margin: "0 0 16px" }}>
        {rows.length} UK-listed {sector} {rows.length === 1 ? "company" : "companies"}
        {capCurrency && totalCap > 0 && ` with a combined market capitalisation of ${fmt(totalCap, "currency", capCurrency)}`}
        {largest && `. The largest is ${largest.name} (${ticker(largest.symbol)})`}
        {indexSplit && ` — ${indexSplit}`}.
      </p>

      {/* Other sectors */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
        <Link href="/companies" style={{ fontSize: 12, color: "#a78bfa", textDecoration: "none", background: "#1f1f1f", borderRadius: 4, padding: "3px 8px" }}>
          All companies
        </Link>
        {allSectors.filter((s) => s !== sector).map((s) => (
          <Link key={s} href={sectorHref(s)} style={{ fontSize: 12, color: "#a78bfa", textDecoration: "none", background: "#1f1f1f", borderRadius: 4, padding: "3px 8px" }}>
            {s}
          </Link>
        ))}
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #2a2a2a", color: "#f97316", textAlign: "left" }}>
            <th style={{ padding: "8px 8px 8px 0" }}>Company</th>
            <th style={{ padding: "8px" }}>Ticker</th>
            <th style={{ padding: "8px" }}>Index</th>
            <th style={{ padding: "8px", textAlign: "right" }}>Market cap</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} style={{ borderBottom: "1px solid #1a1a1a" }}>
              <td style={{ padding: "7px 8px 7px 0" }}>
                <Link prefetch={false} href={companyHref(r.symbol)} style={{ color: "#e5e7eb", textDecoration: "none" }}>
                  {r.name}
                </Link>
              </td>
              <td style={{ padding: "7px 8px", color: "#64748b" }}>{ticker(r.symbol)}</td>
              <td style={{ padding: "7px 8px", color: "#94a3b8" }}>{r.ftse_index || "—"}</td>
              <td style={{ padding: "7px 8px", textAlign: "right", color: "#e5e7eb" }}>
                {r.market_cap != null ? fmt(r.market_cap, "currency", r.currency || "GBP") : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
