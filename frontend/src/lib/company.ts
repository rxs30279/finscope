// Clean company URLs: /company/<TICKER>, where TICKER is the LSE symbol with its
// ".L" suffix stripped (e.g. TSCO.L -> /company/TSCO). The API and DB always use
// the full ".L" symbol, so we strip it on the way out (links, canonicals, sitemap)
// and reconstruct it on the way in (the dynamic route). Stripping ".L" also means
// no slug ever contains a dot, which avoids the dot-in-path routing wrinkle.

// Symbol -> URL slug. Upper-cased and URL-encoded so the canonical form is stable
// regardless of how a caller cased the symbol.
export function tickerSlug(symbol: string): string {
  return encodeURIComponent(symbol.replace(/\.L$/i, "").toUpperCase());
}

// Symbol (+ optional tab) -> in-app href.
export function companyHref(symbol: string, tab?: string): string {
  const base = `/company/${tickerSlug(symbol)}`;
  return tab ? `${base}?tab=${encodeURIComponent(tab)}` : base;
}

// URL slug -> full DB symbol. LSE tickers carry a ".L" suffix; a slug that already
// contains a dot is treated as a complete symbol and left alone.
export function slugToSymbol(slug: string): string {
  const s = decodeURIComponent(slug).toUpperCase();
  return s.includes(".") ? s : `${s}.L`;
}
