"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { API } from "@/lib/api";
import { fmt, gc } from "@/lib/format";
import { S } from "@/lib/theme";
import { companyHref } from "@/lib/company";
import { useIsMobile } from "@/hooks/useMediaQuery";
import dynamic from "next/dynamic";
import MetricCard from "@/components/company/MetricCard";
const PriceChart = dynamic(() => import("@/components/company/PriceChart"), { ssr: false });

interface Props {
  symbol: string;
  onOpenFull: (symbol: string) => void;
}

export default function TrendingProfile({ symbol, onOpenFull }: Props) {
  const [meta, setMeta] = useState<any>(null);
  const [snap, setSnap] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const isMobile = useIsMobile();

  useEffect(() => {
    setLoading(true);
    const enc = encodeURIComponent(symbol);
    Promise.all([
      fetch(`${API}/company?symbol=${enc}`).then((r) => r.json()),
      fetch(`${API}/snapshot?symbol=${enc}`).then((r) => r.json()),
    ])
      .then(([m, s]) => { setMeta(m); setSnap(s); setLoading(false); })
      .catch(() => setLoading(false));
  }, [symbol]);

  if (loading) return <div style={S.loading}>Loading {symbol}…</div>;
  if (!snap) return <div style={S.loading}>No data for {symbol}</div>;

  const badges = (
    <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
      {[symbol, meta?.sector, meta?.ftse_index].filter(Boolean).map((t: string) => (
        <span key={t} style={S.badge}>{t}</span>
      ))}
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <h2 style={{ margin: 0, fontFamily: "DM Serif Display,serif", fontSize: 22, color: "#f1f5f9" }}>{meta?.name || symbol}</h2>
          {!isMobile && badges}
        </div>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <Link prefetch={false} href={companyHref(symbol)} style={{ ...S.backBtn, textDecoration: "none", display: "inline-block" }}>Open full view →</Link>
        </div>
      </div>

      {isMobile && badges}

      {!isMobile && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(92px,1fr))", gap: 6 }}>
          <MetricCard compact label="P/E" value={fmt(snap.price_to_earnings, "ratio")} />
          <MetricCard compact label="P/B" value={fmt(snap.price_to_book, "ratio")} />
          <MetricCard compact label="ROE" value={fmt(snap.roe, "pct")} color={gc(snap.roe)} />
          <MetricCard compact label="Rev Growth" value={fmt(snap.revenue_growth, "pct")} color={gc(snap.revenue_growth)} />
          <MetricCard compact label="Net Margin" value={fmt(snap.net_income_margin, "pct")} color={gc(snap.net_income_margin)} />
          <MetricCard compact label="Risk" value={snap.risk_score == null ? "—" : snap.risk_score} color={snap.risk_score == null ? "#94a3b8" : snap.risk_score <= 3 ? "#10b981" : snap.risk_score <= 6 ? "#f59e0b" : "#ef4444"} />
        </div>
      )}

      <PriceChart symbol={symbol} simple />
    </div>
  );
}
