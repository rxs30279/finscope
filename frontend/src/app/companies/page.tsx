import type { Metadata } from "next";
import Link from "next/link";
import { getCompaniesList, type CompanyListItem } from "@/lib/companyData";
import { companyHref, sectorHref } from "@/lib/company";
import { SITE_URL, SITE_NAME, jsonLdString } from "@/lib/seo";

export const revalidate = 86400;

const ticker = (symbol: string) => symbol.replace(/\.L$/i, "");

export const metadata: Metadata = {
  title: "All UK Companies A–Z — FTSE 100, 250, SmallCap & AIM",
  description:
    "Browse every UK-listed company we cover A–Z — FTSE 100, FTSE 250, SmallCap and AIM. " +
    "Share prices, fundamentals, valuation, analyst consensus and RNS news on " +
    SITE_NAME + ".",
  alternates: { canonical: "/companies" },
  openGraph: {
    type: "website",
    title: "All UK Companies A–Z",
    description:
      "Every UK-listed company we cover — FTSE 100, 250, SmallCap and AIM — with fundamentals and RNS news.",
    url: "/companies",
  },
};

function firstLetter(name: string): string {
  const c = (name || "").trim().charAt(0).toUpperCase();
  return c >= "A" && c <= "Z" ? c : "#";
}

export default async function CompaniesPage() {
  const companies = await getCompaniesList();

  // An empty list means the API call failed, not that the universe is empty.
  // At runtime, throw so an ISR revalidation keeps serving the last good page
  // instead of caching a thin "unavailable" page for the whole revalidate
  // window. During `next build` (e.g. local builds with no backend running)
  // there is no good page to preserve — render a minimal fallback so the build
  // succeeds; the first successful revalidation replaces it.
  if (!companies.length) {
    if (process.env.NEXT_PHASE === "phase-production-build") {
      return (
        <div style={{ padding: "24px 0", fontFamily: "monospace", color: "#94a3b8" }}>
          <h1 style={{ fontFamily: '"DM Serif Display", serif', fontSize: 26, color: "#f1f5f9" }}>
            All UK Companies A–Z
          </h1>
          <p>The company directory is temporarily unavailable. Please try again shortly.</p>
        </div>
      );
    }
    throw new Error("companies list unavailable — refusing to cache an empty directory");
  }

  // Group A–Z (+ "#" bucket for anything not starting with a letter).
  const groups = new Map<string, CompanyListItem[]>();
  for (const c of companies) {
    const key = firstLetter(c.name);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(c);
  }
  const letters = Array.from(groups.keys()).sort();

  // Distinct sectors for the hub chip row.
  const sectors = Array.from(
    new Set(companies.map((c) => c.sector).filter(Boolean) as string[]),
  ).sort();

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "All UK Companies A–Z",
    url: `${SITE_URL}/companies`,
    description: "Directory of UK-listed companies covered on " + SITE_NAME + ".",
  };
  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
      { "@type": "ListItem", position: 2, name: "Companies", item: `${SITE_URL}/companies` },
    ],
  };

  return (
    <div style={{ padding: "16px 0", fontFamily: "monospace" }}>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString([jsonLd, breadcrumb]) }}
      />
      <nav aria-label="Breadcrumb" style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
        <Link href="/" style={{ color: "#64748b", textDecoration: "none" }}>Home</Link>
        <span style={{ margin: "0 6px" }}>›</span>
        <span style={{ color: "#94a3b8" }}>Companies</span>
      </nav>

      <h1 style={{ fontFamily: '"DM Serif Display", serif', fontSize: 28, color: "#f1f5f9", margin: "0 0 8px" }}>
        All UK Companies A–Z
      </h1>
      <p style={{ color: "#94a3b8", fontSize: 13, lineHeight: 1.6, maxWidth: 820, margin: "0 0 16px" }}>
        Browse fundamentals, valuation, analyst consensus and RNS news for {companies.length.toLocaleString("en-GB")}{" "}
        London-listed companies across the FTSE 100, FTSE 250, SmallCap and AIM.
      </p>

      {/* Sector hubs */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
        {sectors.map((s) => (
          <Link key={s} href={sectorHref(s)} style={{ fontSize: 12, color: "#a78bfa", textDecoration: "none", background: "#1f1f1f", borderRadius: 4, padding: "3px 8px" }}>
            {s}
          </Link>
        ))}
      </div>

      {/* Letter jump-nav */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20, borderTop: "1px solid #1e1e1e", paddingTop: 12 }}>
        {letters.map((l) => (
          <a key={l} href={`#letter-${l}`} style={{ fontSize: 13, color: "#f97316", textDecoration: "none", fontWeight: 700 }}>
            {l}
          </a>
        ))}
      </div>

      {letters.map((l) => (
        <section key={l} style={{ marginBottom: 24 }}>
          <h2 id={`letter-${l}`} style={{ fontFamily: '"DM Serif Display", serif', fontSize: 20, color: "#f1f5f9", borderBottom: "1px solid #2a2a2a", paddingBottom: 4, marginBottom: 10 }}>
            {l}
          </h2>
          <ul className="companies-columns" style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {groups.get(l)!.map((c) => (
              <li key={c.symbol} style={{ breakInside: "avoid", padding: "3px 0", fontSize: 13 }}>
                <Link prefetch={false} href={companyHref(c.symbol)} style={{ color: "#e5e7eb", textDecoration: "none" }}>
                  {c.name} <span style={{ color: "#64748b" }}>({ticker(c.symbol)})</span>
                </Link>
                {(c.sector || c.ftse_index) && (
                  <span style={{ color: "#475569", fontSize: 11, marginLeft: 6 }}>
                    {[c.sector, c.ftse_index].filter(Boolean).join(" · ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
