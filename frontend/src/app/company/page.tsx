import type { Metadata } from "next";
import { permanentRedirect } from "next/navigation";
import CompanyClient from "./_client";
import { tickerSlug } from "@/lib/company";

interface PageProps {
  searchParams: Promise<{ symbol?: string; tab?: string }>;
}

export const metadata: Metadata = {
  title: "Company",
  description: "UK company fundamentals, valuation, analyst consensus and RNS news.",
  robots: { index: false, follow: true },
};

// Legacy query-string URLs (/company?symbol=TSCO.L) 308-redirect to the clean
// path (/company/TSCO) so existing indexed pages and inbound links keep their
// equity. With no symbol there's nothing to redirect to — render the empty
// (noindex) shell, which prompts for a search.
export default async function CompanyRedirect({ searchParams }: PageProps) {
  const { symbol: raw = "", tab } = await searchParams;
  const symbol = decodeURIComponent(raw);
  if (symbol) {
    const dest = `/company/${tickerSlug(symbol)}${tab ? `?tab=${encodeURIComponent(tab)}` : ""}`;
    permanentRedirect(dest);
  }
  return <CompanyClient symbol="" />;
}
