import type { Metadata } from "next";
import CompanyClient from "../_client";
import CompanyHeader from "@/components/company/CompanyHeader";
import CompanyBreadcrumb from "@/components/company/CompanyBreadcrumb";
import CompanyEnrichment from "@/components/company/CompanyEnrichment";
import EmailDigestCTA from "@/components/EmailDigestCTA";
import { getCompanyData, getCompanyExtras } from "@/lib/companyData";
import { slugToSymbol, tickerSlug } from "@/lib/company";
import { fmt, fmtPrice } from "@/lib/format";

interface PageProps {
  params: Promise<{ symbol: string }>;
  searchParams: Promise<{ tab?: string }>;
}

const ticker = (symbol: string) => symbol.replace(/\.L$/i, "");

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { symbol: slug } = await params;
  const symbol = slugToSymbol(slug);

  const { meta, snap } = await getCompanyData(symbol);
  const name = meta?.name || ticker(symbol);
  const canonical = `/company/${tickerSlug(symbol)}`;

  // Market cap comes from Yahoo's `info`, denominated in the QUOTE (trading)
  // currency — not the reporting currency. Using financial_currency here labelled
  // Anglo American's £40.00B cap as "$40.00B" in the indexed meta description,
  // contradicting the header on the same page. Same fallback chain as
  // CompanyHeader's quoteCurrency().
  const cur = (meta?.currency as string) || (meta?.financial_currency as string) || "GBP";
  const bits: string[] = [];
  if (meta?.sector) bits.push(meta.sector as string);
  // Price first — it's what "<name> share price" searchers are looking for, and
  // it's the one fact the title promises.
  if (snap?.last_close != null)
    bits.push(`last close ${fmtPrice(snap.last_close as number, (snap.price_currency as string) || "GBp")}`);
  if (snap?.market_cap != null) bits.push(`mkt cap ${fmt(snap.market_cap, "currency", cur)}`);
  if (snap?.price_to_earnings != null) bits.push(`P/E ${fmt(snap.price_to_earnings, "x")}`);
  if (snap?.dividend_yield != null && (snap.dividend_yield as number) > 0)
    bits.push(`yield ${fmt(snap.dividend_yield, "pct")}`);
  const stats = bits.length ? ` ${bits.join(" · ")}.` : "";

  const title = `${name} (${ticker(symbol)}) Share Price & Fundamentals`;
  const description =
    `${name} (${ticker(symbol)}) share price, fundamentals, valuation, financial health, ` +
    `growth, analyst consensus and RNS news on Alpha Move AI.${stats}`;

  // No profile row at all → likely an unknown/delisted symbol; don't let it be indexed.
  const indexable = Boolean(meta);

  return {
    title,
    description,
    alternates: { canonical },
    robots: indexable ? undefined : { index: false, follow: true },
    openGraph: {
      type: "website",
      title,
      description,
      url: canonical,
    },
    twitter: { card: "summary_large_image", title, description },
  };
}

export default async function CompanyPage({ params, searchParams }: PageProps) {
  const { symbol: slug } = await params;
  const { tab } = await searchParams;
  const symbol = slugToSymbol(slug);
  const [{ meta, snap }, extras] = await Promise.all([
    getCompanyData(symbol),
    getCompanyExtras(symbol),
  ]);

  return (
    <>
      <CompanyBreadcrumb symbol={symbol} meta={meta} />
      <EmailDigestCTA source="company_page" />
      <CompanyHeader symbol={symbol} meta={meta} snap={snap} />
      <CompanyClient symbol={symbol} initialTab={tab} />
      <CompanyEnrichment symbol={symbol} meta={meta} extras={extras} />
    </>
  );
}
