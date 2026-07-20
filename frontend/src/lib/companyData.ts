import { backendUrl } from "./seo";

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
  roic?: number;
  dividend_yield?: number;
  revenue?: number;
  net_income?: number;
  [k: string]: unknown;
}

// Server-side fetch of the company profile + TTM snapshot. Used by both
// generateMetadata and the CompanyHeader server component on the company
// page; Next dedupes the two identical fetches within one request. Failures
// resolve to null so the page/metadata degrade gracefully rather than throwing.
export async function getCompanyData(
  symbol: string,
): Promise<{ meta: CompanyMeta | null; snap: CompanySnap | null }> {
  if (!symbol) return { meta: null, snap: null };
  const enc = encodeURIComponent(symbol);
  const opts = { next: { revalidate: 3600 } } as const;
  const [meta, snap] = await Promise.all([
    fetch(backendUrl(`/api/company?symbol=${enc}`), opts)
      .then((r) => (r.ok ? (r.json() as Promise<CompanyMeta>) : null))
      .catch(() => null),
    fetch(backendUrl(`/api/snapshot?symbol=${enc}`), opts)
      .then((r) => (r.ok ? (r.json() as Promise<CompanySnap>) : null))
      .catch(() => null),
  ]);
  return { meta, snap };
}

export interface CompanyListItem {
  symbol: string;
  name: string;
  sector: string | null;
  ftse_index: string | null;
  // Quote currency (GBP for most LSE lines) — the denomination of market_cap,
  // which comes from Yahoo's info.marketCap. Format per-row, never assume GBP.
  currency: string | null;
  market_cap: number | null;
}

// Full active universe (name/sector/index/market cap) for the /companies A–Z
// directory and the /companies/sector/[slug] hub pages — one cheap cached query
// shared across all of them. Failures resolve to [] — safe for
// generateStaticParams (fewer prebuilt paths, filled on demand), but the PAGES
// must treat an empty list as an error and throw: a successful render of a
// "temporarily unavailable" page (or a notFound()) would be cached by ISR for
// the full revalidate window, whereas a throw keeps serving the last good page.
export async function getCompaniesList(): Promise<CompanyListItem[]> {
  return fetch(backendUrl("/api/companies"), { next: { revalidate: 86400 } })
    .then((r) => (r.ok ? (r.json() as Promise<CompanyListItem[]>) : []))
    .catch(() => []);
}

export interface RnsItem {
  id?: number;
  published_at?: string;
  wire?: string;
  headline?: string;
  url?: string;
  tier?: string;
  category?: string;
  score?: number;
}

export interface AnalystSnapshot {
  snapshot_date?: string;
  consensus?: string;
  buy_pct?: number;
  total_analysts?: number;
  strong_buy?: number;
  buy?: number;
  hold?: number;
  sell?: number;
  strong_sell?: number;
  price_target_mean?: number;
  price_target_high?: number;
  price_target_low?: number;
  price_target_median?: number;
  current_price?: number;
  upside_pct?: number;
  [k: string]: unknown;
}

export interface PeerRef {
  symbol: string;
  name: string;
}

export interface ValuationData {
  fair_value?: number | null;
  peer_basis?: string;
  current_price?: number;
  upside_pct?: number;
  multiple_used?: string;
  caution?: boolean;
  peers?: PeerRef[];
  [k: string]: unknown;
}

export interface CompanyExtras {
  rns: RnsItem[] | null;
  analyst: AnalystSnapshot | null;
  valuation: ValuationData | null;
  sector_peers: PeerRef[] | null;
}

const EMPTY_EXTRAS: CompanyExtras = {
  rns: null,
  analyst: null,
  valuation: null,
  sector_peers: null,
};

// Server-side fetch of the enrichment payload (latest RNS, analyst consensus, peer
// valuation, sector mates) for the company page. One combined always-200 endpoint
// so empty long-tail results still cache (see backend /api/company-extras note).
export async function getCompanyExtras(symbol: string): Promise<CompanyExtras> {
  if (!symbol) return EMPTY_EXTRAS;
  const enc = encodeURIComponent(symbol);
  return fetch(backendUrl(`/api/company-extras?symbol=${enc}`), {
    next: { revalidate: 900 },
  })
    .then((r) => (r.ok ? (r.json() as Promise<CompanyExtras>) : EMPTY_EXTRAS))
    .catch(() => EMPTY_EXTRAS);
}
