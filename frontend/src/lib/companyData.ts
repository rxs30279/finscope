import { apiUrl } from "./seo";

export interface CompanyMeta {
  symbol?: string;
  name?: string;
  sector?: string;
  industry?: string;
  exchange?: string;
  country?: string;
  ftse_index?: string;
  financial_currency?: string;
  [k: string]: unknown;
}

export interface CompanySnap {
  market_cap?: number;
  price_to_earnings?: number;
  price_to_book?: number;
  roe?: number;
  dividend_yield?: number;
  revenue?: number;
  net_income?: number;
  [k: string]: unknown;
}

// Server-side fetch of the company profile + TTM snapshot. Used by both
// generateMetadata and the CompanySeoContent server component on the company
// page; Next dedupes the two identical fetches within one request. Failures
// resolve to null so the page/metadata degrade gracefully rather than throwing.
export async function getCompanyData(
  symbol: string,
): Promise<{ meta: CompanyMeta | null; snap: CompanySnap | null }> {
  if (!symbol) return { meta: null, snap: null };
  const enc = encodeURIComponent(symbol);
  const opts = { next: { revalidate: 3600 } } as const;
  const [meta, snap] = await Promise.all([
    fetch(apiUrl(`/api/company?symbol=${enc}`), opts)
      .then((r) => (r.ok ? (r.json() as Promise<CompanyMeta>) : null))
      .catch(() => null),
    fetch(apiUrl(`/api/snapshot?symbol=${enc}`), opts)
      .then((r) => (r.ok ? (r.json() as Promise<CompanySnap>) : null))
      .catch(() => null),
  ]);
  return { meta, snap };
}
