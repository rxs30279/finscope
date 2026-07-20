import Link from "next/link";
import { companyHref, sectorHref } from "@/lib/company";
import type { CompanyMeta, CompanyExtras } from "@/lib/companyData";

// Server-rendered enrichment below the (client-only) dashboard: latest RNS,
// analyst consensus, peer valuation and sector mates. This is real, per-company,
// crawlable content + a dense mesh of internal links to other company pages,
// which is what lifts these pages out of "thin templated page" territory.
//
// Presented as native <details> accordions, collapsed by default, so the page
// stays visually clean: the full text is still in the server HTML (Google
// indexes content inside collapsed <details>), users can expand on demand, and
// no client JS is needed. The company description is NOT here — it lives in the
// visible CompanyHeader up top. All headings are <h2> (the single <h1> lives in
// CompanyHeader).

interface Props {
  symbol: string;
  meta: CompanyMeta | null;
  extras: CompanyExtras;
}

const ticker = (symbol: string) => symbol.replace(/\.L$/i, "");

function fmtDate(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

const pence = (v?: number | null) =>
  v == null ? "" : `${Math.round(v).toLocaleString("en-GB")}p`;

const detailsStyle: React.CSSProperties = {
  borderBottom: "1px solid #1e1e1e",
};
const summaryStyle: React.CSSProperties = {
  cursor: "pointer",
  padding: "12px 0",
  color: "#94a3b8",
  fontSize: 13,
};
const h2Style: React.CSSProperties = {
  display: "inline",
  fontFamily: "monospace",
  fontSize: 13,
  fontWeight: 400,
  color: "#94a3b8",
  margin: 0,
};
const bodyStyle: React.CSSProperties = {
  padding: "2px 0 16px",
};
const proseStyle: React.CSSProperties = {
  color: "#94a3b8",
  fontSize: 13,
  lineHeight: 1.7,
  margin: 0,
  maxWidth: 820,
};
const linkStyle: React.CSSProperties = { color: "#a78bfa", textDecoration: "none" };

export default function CompanyEnrichment({ symbol, meta, extras }: Props) {
  const name = (meta?.name as string) || ticker(symbol);
  const sector = (meta?.sector as string) || "";
  const { rns, analyst, valuation, sector_peers } = extras;

  const hasRns = !!rns && rns.length > 0;
  const hasPeers = !!valuation?.peers && valuation.peers.length > 0;
  const hasSectorPeers = !!sector_peers && sector_peers.length > 0;

  if (!hasRns && !analyst && !valuation && !hasSectorPeers) return null;

  return (
    <section style={{ marginTop: 32, fontFamily: "monospace", borderTop: "1px solid #1e1e1e" }}>
      {hasRns && (
        <details style={detailsStyle}>
          <summary style={summaryStyle}>
            <h2 style={h2Style}>Latest RNS from {name}</h2>
          </summary>
          <div style={bodyStyle}>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {rns!.map((r) => (
                <li key={r.id ?? r.url} style={{ padding: "7px 0", borderBottom: "1px solid #1e1e1e", fontSize: 13 }}>
                  <time dateTime={r.published_at} style={{ color: "#64748b", marginRight: 10 }}>
                    {fmtDate(r.published_at)}
                  </time>
                  {r.category && (
                    <span style={{ fontSize: 10, color: "#94a3b8", background: "#1f1f1f", borderRadius: 3, padding: "1px 6px", marginRight: 8 }}>
                      {r.category}
                    </span>
                  )}
                  {r.url ? (
                    <a href={r.url} rel="noopener" target="_blank" style={{ color: "#e5e7eb", textDecoration: "none" }}>
                      {r.headline}
                    </a>
                  ) : (
                    <span style={{ color: "#e5e7eb" }}>{r.headline}</span>
                  )}
                </li>
              ))}
            </ul>
            <p style={{ ...proseStyle, marginTop: 10 }}>
              <Link href={companyHref(symbol, "news")} style={linkStyle}>All {ticker(symbol)} news →</Link>
              {"  ·  "}
              <Link href="/rns" style={linkStyle}>RNS daily feed</Link>
            </p>
          </div>
        </details>
      )}

      {analyst && analyst.total_analysts != null && (analyst.total_analysts as number) > 0 && (
        <details style={detailsStyle}>
          <summary style={summaryStyle}>
            <h2 style={h2Style}>Analyst consensus{analyst.consensus ? `: ${analyst.consensus}` : ""}</h2>
          </summary>
          <div style={bodyStyle}>
            <p style={proseStyle}>
              {`As of ${fmtDate(analyst.snapshot_date)}, ${analyst.total_analysts} analyst${
                analyst.total_analysts === 1 ? "" : "s"
              } rate ${name}`}
              {analyst.consensus ? ` a ${analyst.consensus}` : ""}
              {analyst.buy_pct != null ? `, with ${Math.round(analyst.buy_pct as number)}% buy ratings` : ""}
              {analyst.price_target_mean != null
                ? ` and a mean price target of ${pence(analyst.price_target_mean)}`
                : ""}
              {analyst.price_target_low != null && analyst.price_target_high != null
                ? ` (range ${pence(analyst.price_target_low)}–${pence(analyst.price_target_high)})`
                : ""}
              {analyst.upside_pct != null
                ? `, ${(analyst.upside_pct as number) >= 0 ? "+" : ""}${Math.round(analyst.upside_pct as number)}% vs the current price`
                : ""}
              .
            </p>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 8, fontSize: 12, color: "#64748b" }}>
              {[
                ["Strong buy", analyst.strong_buy],
                ["Buy", analyst.buy],
                ["Hold", analyst.hold],
                ["Sell", analyst.sell],
                ["Strong sell", analyst.strong_sell],
              ]
                .filter(([, v]) => v != null)
                .map(([label, v]) => (
                  <span key={label as string}>{label}: <span style={{ color: "#e5e7eb" }}>{v as number}</span></span>
                ))}
            </div>
            <p style={{ ...proseStyle, marginTop: 10 }}>
              <Link href={companyHref(symbol, "analysts")} style={linkStyle}>Full analyst history →</Link>
            </p>
          </div>
        </details>
      )}

      {valuation?.fair_value != null && (
        <details style={detailsStyle}>
          <summary style={summaryStyle}>
            <h2 style={h2Style}>Valuation vs peers</h2>
          </summary>
          <div style={bodyStyle}>
            <p style={proseStyle}>
              {`Peer-relative fair value estimate: ${pence(valuation.fair_value)}`}
              {valuation.current_price != null ? ` against a current price of ${pence(valuation.current_price)}` : ""}
              {valuation.upside_pct != null
                ? ` (${(valuation.upside_pct as number) >= 0 ? "+" : ""}${Math.round(valuation.upside_pct as number)}%)`
                : ""}
              {valuation.multiple_used ? `, based on ${valuation.multiple_used}` : ""}.
              {valuation.caution ? " Treat as indicative — the peer set is small or the multiples vary widely." : ""}
            </p>
            {hasPeers && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                {valuation.peers!.map((p) => (
                  <Link key={p.symbol} href={companyHref(p.symbol)} style={{ ...linkStyle, fontSize: 12, background: "#1f1f1f", borderRadius: 4, padding: "3px 8px" }}>
                    {p.name}
                  </Link>
                ))}
              </div>
            )}
          </div>
        </details>
      )}

      {hasSectorPeers && (
        <details style={detailsStyle}>
          <summary style={summaryStyle}>
            <h2 style={h2Style}>More {sector || "sector"} companies</h2>
          </summary>
          <div style={bodyStyle}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {sector_peers!.map((p) => (
                <Link key={p.symbol} href={companyHref(p.symbol)} style={{ ...linkStyle, fontSize: 12, background: "#1f1f1f", borderRadius: 4, padding: "3px 8px" }}>
                  {p.name}
                </Link>
              ))}
            </div>
            <p style={{ ...proseStyle, marginTop: 10 }}>
              {sector && (
                <>
                  <Link href={sectorHref(sector)} style={linkStyle}>All UK {sector} companies →</Link>
                  {"  ·  "}
                </>
              )}
              <Link href="/companies" style={linkStyle}>Browse all UK companies →</Link>
            </p>
          </div>
        </details>
      )}
    </section>
  );
}
