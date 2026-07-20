import Link from "next/link";
import { sectorHref } from "@/lib/company";
import type { CompanyMeta } from "@/lib/companyData";

// Visible breadcrumb for the company page, rendered at the very top (above the
// CTA banner and header). The matching BreadcrumbList JSON-LD stays in
// CompanyHeader alongside the Corporation schema. Server component — no hooks.

const ticker = (symbol: string) => symbol.replace(/\.L$/i, "");

const crumbLink: React.CSSProperties = { color: "#64748b", textDecoration: "none" };
const sep = <span style={{ margin: "0 6px" }}>›</span>;

export default function CompanyBreadcrumb({ symbol, meta }: { symbol: string; meta: CompanyMeta | null }) {
  const sector = (meta?.sector as string) || "";
  return (
    <nav
      aria-label="Breadcrumb"
      style={{ fontSize: 12, color: "#64748b", marginBottom: 12, fontFamily: "monospace" }}
    >
      <Link href="/" style={crumbLink}>Home</Link>
      {sep}
      <Link href="/companies" style={crumbLink}>Companies</Link>
      {sector && (
        <>
          {sep}
          <Link href={sectorHref(sector)} style={crumbLink}>{sector}</Link>
        </>
      )}
      {sep}
      <span style={{ color: "#94a3b8" }}>{ticker(symbol)}</span>
    </nav>
  );
}
