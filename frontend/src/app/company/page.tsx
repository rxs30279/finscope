import type { Metadata } from "next";
import CompanyClient from "./_client";
import CompanySeoContent from "@/components/company/CompanySeoContent";
import { getCompanyData } from "@/lib/companyData";
import { fmt } from "@/lib/format";

interface PageProps {
  searchParams: Promise<{ symbol?: string; tab?: string }>;
}

const ticker = (symbol: string) => symbol.replace(/\.L$/i, "");

export async function generateMetadata({ searchParams }: PageProps): Promise<Metadata> {
  const { symbol: raw = "" } = await searchParams;
  const symbol = decodeURIComponent(raw);
  if (!symbol) {
    return {
      title: "Company",
      description: "UK company fundamentals, valuation, analyst consensus and RNS news.",
      robots: { index: false, follow: true },
    };
  }

  const { meta, snap } = await getCompanyData(symbol);
  const name = meta?.name || ticker(symbol);
  const canonical = `/company?symbol=${encodeURIComponent(symbol)}`;

  const cur = (meta?.financial_currency as string) || "GBP";
  const bits: string[] = [];
  if (meta?.sector) bits.push(meta.sector as string);
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

export default async function CompanyPage({ searchParams }: PageProps) {
  const { symbol: raw = "", tab } = await searchParams;
  const symbol = decodeURIComponent(raw);
  const { meta, snap } = symbol
    ? await getCompanyData(symbol)
    : { meta: null, snap: null };

  return (
    <>
      {symbol ? <CompanySeoContent symbol={symbol} meta={meta} snap={snap} /> : null}
      <CompanyClient symbol={symbol} initialTab={tab} />
    </>
  );
}
