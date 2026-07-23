"use client";

import { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import { API } from "@/lib/api";
import { fmt, gc, currSym } from "@/lib/format";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { S } from "@/lib/theme";
import MetricCard from "./MetricCard";
import InfoDot from "@/components/InfoDot";
import FairValueCard from "./FairValueCard";
import AnalystTab from "@/components/AnalystTab";
import NewsTab from "@/components/NewsTab";
import DividendsTab from "./DividendsTab";
import ShortInterestMetric from "./ShortInterestSection";

// Every chart below is dynamically imported (ssr:false) so recharts is not
// part of CompanyDetail's own chunk — it streams in per chart, behind a
// fixed-height placeholder matching the chart's rendered height (no CLS),
// instead of blocking the whole dashboard shell's parse/mount.
// height:400 matches PriceChart's own internal loading/error states and
// CompanyDetail's loading state above, so the placeholder doesn't shift once
// the chunk resolves.
const PriceChart = dynamic(() => import("./PriceChart"), {
  ssr: false,
  loading: () => <div style={{ minHeight: 400 }} />,
});
const OverviewChart = dynamic(() => import("./charts/OverviewChart"), {
  ssr: false,
  loading: () => <div style={{ height: 220 }} />,
});
const WaterfallChart = dynamic(() => import("./charts/WaterfallChart"), {
  ssr: false,
  loading: () => <div style={{ height: 260 }} />,
});
const RevenueEbitdaFcfChart = dynamic(() => import("./charts/RevenueEbitdaFcfChart"), {
  ssr: false,
  loading: () => <div style={{ height: 220 }} />,
});
const EpsChart = dynamic(() => import("./charts/EpsChart"), {
  ssr: false,
  loading: () => <div style={{ height: 220 }} />,
});
const QuarterlyRevenueChart = dynamic(() => import("./charts/QuarterlyRevenueChart"), {
  ssr: false,
  loading: () => <div style={{ height: 200 }} />,
});
const ReturnOnCapitalChart = dynamic(() => import("./charts/ReturnOnCapitalChart"), {
  ssr: false,
  loading: () => <div style={{ height: 220 }} />,
});
const DebtEquityChart = dynamic(() => import("./charts/DebtEquityChart"), {
  ssr: false,
  loading: () => <div style={{ height: 210 }} />,
});
const CurrentRatioChart = dynamic(() => import("./charts/CurrentRatioChart"), {
  ssr: false,
  loading: () => <div style={{ height: 210 }} />,
});
const ProfitMarginsChart = dynamic(() => import("./charts/ProfitMarginsChart"), {
  ssr: false,
  loading: () => <div style={{ height: 250 }} />,
});

interface Props {
  symbol: string;
  initialTab?: string;
}

export default function CompanyDetail({ symbol, initialTab }: Props) {
  const [meta, setMeta] = useState<any>(null);
  const [snap, setSnap] = useState<any>(null);
  const [annual, setAnnual] = useState<any[]>([]);
  const [quarterly, setQuarterly] = useState<any[]>([]);
  const [valuation, setValuation] = useState<any>(null);
  const [tab, setTab] = useState(initialTab || "chart");
  const [loading, setLoading] = useState(true);
  const isMobile = useIsMobile();

  useEffect(() => { setTab(initialTab || "chart"); }, [symbol, initialTab]);

  useEffect(() => {
    setLoading(true);
    const enc = encodeURIComponent(symbol);
    Promise.all([
      fetch(`${API}/company?symbol=${enc}`).then((r) => r.json()),
      fetch(`${API}/snapshot?symbol=${enc}`).then((r) => r.json()),
      fetch(`${API}/annual?symbol=${enc}`).then((r) => r.json()),
      fetch(`${API}/quarterly?symbol=${enc}`).then((r) => r.json()),
      fetch(`${API}/valuation?symbol=${enc}`).then((r) => r.json()).catch(() => null),
    ])
      .then(([m, s, a, q, v]) => {
        setMeta(m); setSnap(s);
        setAnnual(Array.isArray(a) ? a : []);
        setQuarterly(Array.isArray(q) ? q : []);
        setValuation(v && !v.detail ? v : null);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [symbol]);

  // minHeight cuts layout shift: the server-rendered header + enrichment are
  // static around this block, so we hold vertical space while the tabs load.
  if (loading) return <div style={{ ...S.loading, minHeight: 400 }}>Loading {symbol}…</div>;
  if (!snap) return <div style={{ ...S.loading, minHeight: 400 }}>No data for {symbol}</div>;

  const fcur = meta?.financial_currency || "GBP";
  const sym = currSym(fcur);
  // Market cap / EV come from Yahoo's `info` and are denominated in the quote
  // (trading) currency — GBP for LSE stocks — not the reporting currency that the
  // financial statements use. Multinationals that file in USD (HSBC, Shell, BP…)
  // otherwise show a $ on a GBP value. Mirrors the screener/trending fix.
  const qcur = meta?.currency || fcur;

  const annualChart = annual.map((r: any) => ({
    year: r.period_end_date?.slice(0, 4),
    revenue: r.revenue ? r.revenue / 1e9 : null,
    net_income: r.net_income ? r.net_income / 1e9 : null,
    ebitda: r.ebitda ? r.ebitda / 1e9 : null,
    fcf: r.fcf ? r.fcf / 1e9 : null,
    gross_margin: r.gross_margin ? r.gross_margin * 100 : null,
    op_margin: r.operating_margin ? r.operating_margin * 100 : null,
    net_margin: r.net_income_margin ? r.net_income_margin * 100 : null,
    roe: r.roe ? r.roe * 100 : null,
    roic: r.roic ? r.roic * 100 : null,
    roa: r.roa ? r.roa * 100 : null,
    eps: r.eps_diluted,
    debt_eq: r.debt_to_equity,
    curr_ratio: r.current_ratio,
  }));

  const qChart = quarterly.slice(-8).map((r: any) => ({
    q: r.fiscal_quarter_key || r.period_end_date?.slice(0, 7),
    revenue: r.revenue ? r.revenue / 1e9 : null,
    net_income: r.net_income ? r.net_income / 1e9 : null,
    eps: r.eps_diluted,
  }));
  const hasQuarterlyRevenue = qChart.some((r: any) => r.revenue != null);
  const hasDebtEq = annualChart.some((r: any) => r.debt_eq != null);

  // A line/area with a single plottable point draws no segment and so renders as
  // nothing. Show a marker dot only in that case; multi-point series stay dot-free.
  const singleDot = (key: string, fill: string) =>
    annualChart.filter((d: any) => d[key] != null).length === 1 ? { r: 4, fill } : false;

  // Latest-year income-statement waterfall: Revenue → Cost of Revenue →
  // Gross Profit → Other Expenses → Earnings. Cost of Revenue and Other
  // Expenses are the reconciling bridges (revenue−gross profit, gross
  // profit−net income), so the bars always tie out even if the reported
  // `cogs` field is missing. Each bar is a floating [low, high] range — the
  // native recharts way to draw hanging bars — which also renders a loss-making
  // year correctly (negative `low`) with no clamping.
  const latestAnnual = annual.length ? annual[annual.length - 1] : null;
  const waterfall = (() => {
    if (!latestAnnual) return null;
    const revenue = latestAnnual.revenue;
    const grossProfit = latestAnnual.gross_profit;
    const earnings = latestAnnual.net_income;
    if (revenue == null || grossProfit == null || earnings == null) return null;
    return [
      { name: "Revenue", range: [0, revenue], amount: revenue, fill: "#6366f1" },
      { name: "Cost of Revenue", range: [grossProfit, revenue], amount: revenue - grossProfit, fill: "#ef4444" },
      { name: "Gross Profit", range: [0, grossProfit], amount: grossProfit, fill: "#10b981" },
      { name: "Other Expenses", range: [earnings, grossProfit], amount: grossProfit - earnings, fill: "#ef4444" },
      { name: "Earnings", range: [0, earnings], amount: earnings, fill: "#22d3ee" },
    ];
  })();

  // The bars are floating [low, high] ranges that can dip below zero (a loss).
  // Recharts anchors a hidden axis at 0 by default, which squashes the negative
  // extent against the baseline instead of drawing it to scale — so we pin the
  // domain explicitly to the true min/max, padding the loss side to leave room
  // for its label.
  const wfDomain = (() => {
    if (!waterfall) return undefined;
    const vals = waterfall.flatMap((d) => d.range as number[]);
    const lo = Math.min(0, ...vals);
    const hi = Math.max(0, ...vals);
    const pad = (hi - lo) * 0.07 || 1;
    return [lo < 0 ? lo - pad : lo, hi] as [number, number];
  })();

  const tabs = ["chart", "overview", "financials", "valuation", "health", "growth", "dividends", "analysts", "news"];

  return (
    <div>
      {/* Tabs */}
      <div style={{ display: "flex", flexWrap: isMobile ? "wrap" : "nowrap", rowGap: isMobile ? 2 : 0, columnGap: 2, borderBottom: isMobile ? "none" : "1px solid #334155", marginBottom: 24 }}>
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`company-tab${tab === t ? " company-tab--active" : ""}`}
            style={{ ...S.tab, ...(isMobile ? { padding: "8px 10px", fontSize: 11 } : {}), ...(tab === t ? S.tabActive : {}) }}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "chart" && <PriceChart symbol={symbol} fcur={qcur} />}

      {tab === "overview" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(155px,1fr))", gap: 10 }}>
            <MetricCard label="Revenue" value={fmt(snap.revenue, "currency", fcur)} />
            <MetricCard label="Net Income" value={fmt(snap.net_income, "currency", fcur)} color={snap.net_income > 0 ? "#10b981" : "#ef4444"} />
            <MetricCard label="EBITDA" value={fmt(snap.ebitda, "currency", fcur)} />
            <MetricCard label="Free Cash Flow" value={fmt(snap.fcf, "currency", fcur)} color={snap.fcf > 0 ? "#10b981" : "#ef4444"} />
            <MetricCard label="P/E" value={fmt(snap.price_to_earnings, "ratio")} />
            <MetricCard label="P/B" value={fmt(snap.price_to_book, "ratio")} />
            <MetricCard label="ROE" value={fmt(snap.roe, "pct")} color={gc(snap.roe)} />
            <MetricCard label="ROIC" value={fmt(snap.roic, "pct")} color={gc(snap.roic)} />
            <MetricCard label="Gross Margin" value={fmt(snap.gross_margin, "pct")} />
            <MetricCard label="Net Margin" value={fmt(snap.net_income_margin, "pct")} color={gc(snap.net_income_margin)} />
            <MetricCard label="Debt/Equity" value={fmt(snap.debt_to_equity, "ratio")} color={snap.debt_to_equity > 2 ? "#ef4444" : "#e5e5e5"} />
            <MetricCard label="Current Ratio" value={fmt(snap.current_ratio, "ratio")} />
          </div>
          <div style={S.card}>
            <h3 style={S.cardTitle}>{`Revenue & Net Income (Annual ${sym}B)`}</h3>
            <OverviewChart data={annualChart} sym={sym} />
          </div>
        </div>
      )}

      {tab === "financials" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {waterfall && (
            <div style={S.card}>
              <h3 style={S.cardTitle}>{`Earnings & Revenue (FY ${latestAnnual.period_end_date?.slice(0, 4)})`}</h3>
              <WaterfallChart data={waterfall} domain={wfDomain} fcur={fcur} isMobile={isMobile} />
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 20 }}>
            <div style={S.card}>
              <h3 style={S.cardTitle}>{`Revenue, EBITDA & FCF (Annual ${sym}B)`}</h3>
              <RevenueEbitdaFcfChart data={annualChart} sym={sym} singleDot={singleDot} />
            </div>
            <div style={S.card}>
              <h3 style={S.cardTitle}>EPS Diluted (Annual)</h3>
              <EpsChart data={annualChart} sym={sym} singleDot={singleDot} />
            </div>
          </div>
          {hasQuarterlyRevenue && (
            <div style={S.card}>
              <h3 style={S.cardTitle}>{`Quarterly Revenue (${sym}B)`}</h3>
              <QuarterlyRevenueChart data={qChart} sym={sym} />
            </div>
          )}
          <div style={S.card}>
            <h3 style={S.cardTitle}>{`Income Statement (${sym}B)`}</h3>
            <div style={{ overflowX: "auto" }}>
              <table style={S.table}>
                <thead>
                  <tr>
                    <th style={S.th}>Metric</th>
                    {annual.slice(-5).map((r: any) => <th key={r.period_end_date} style={{ ...S.th, textAlign: "right" }}>{r.period_end_date?.slice(0, 4)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {[["Revenue","revenue"],["Gross Profit","gross_profit"],["Operating Income","operating_income"],["EBITDA","ebitda"],["Net Income","net_income"],["FCF","fcf"]].map(([l, k]) => (
                    <tr key={k} style={{ borderBottom: "1px solid #334155" }}>
                      <td style={S.td}>{l}</td>
                      {annual.slice(-5).map((r: any) => <td key={r.period_end_date} style={{ ...S.tdNum, color: r[k] < 0 ? "#ef4444" : "#ccc" }}>{r[k] ? sym + (r[k] / 1e9).toFixed(2) + "B" : "—"}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {tab === "valuation" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(145px,1fr))", gap: 10 }}>
            {[["P/E",snap.price_to_earnings,"ratio"],["P/B",snap.price_to_book,"ratio"],["P/S",snap.price_to_sales,"ratio"],["EV/EBITDA",snap.ev_to_ebitda,"ratio"],["EV/Sales",snap.ev_to_sales,"ratio"],["ROE",snap.roe,"pct"],["ROIC",snap.roic,"pct"],["ROCE",snap.roce,"pct"]].map(([l,v,t]: any) => (
              <MetricCard key={l} label={l} value={fmt(v, t)} />
            ))}
          </div>
          <FairValueCard val={valuation} />
          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 20 }}>
            <div style={S.card}>
              <h3 style={S.cardTitle}>Return on Capital (%)</h3>
              <ReturnOnCapitalChart data={annualChart} singleDot={singleDot} />
            </div>
          </div>
        </div>
      )}

      {tab === "health" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div style={{ background: "#141414", borderRadius: 2, padding: "18px 22px", border: "1px solid #2a2a2a", display: "flex", alignItems: "center", gap: 24 }}>
            <div>
              <div style={{ fontSize: 10, color: "#666", marginBottom: 8, textTransform: "uppercase", letterSpacing: 1, fontFamily: "monospace", display: "flex", alignItems: "center", gap: 6 }}>
                Risk Score
                <InfoDot text={"Risk Score 1–10, lower is safer\n\nEach company is scored by the model that fits its business:\n\n  • General — Altman Z-Score (60%) + volatility (40%).\n      Z ≥ 3.0 safe · Z ≤ 1.0 distress\n\n  • Asset-heavy (utilities, REITs, telecoms, miners, and low asset-turnover names like payment processors) — Altman Z″ (40%; drops the asset-turnover term: Z″ ≥ 2.6 safe · ≤ 1.1 distress) + debt service from interest cover & net-debt/EBITDA (30%) + volatility (30%).\n\n  • Banks — ROE quality (30%), equity/assets leverage (25%), price-to-book (20%), volatility (25%).\n\n  • Insurers — ROE (35%), price-to-book (25%), volatility (40%).\n\n  • Other financials — volatility (60%) + ROE (40%).\n\n  • Investment trusts — volatility only.\n\nMissing inputs hand their weight to the remaining components."} placement="bottom-right" />
              </div>
              {snap.risk_score == null ? (
                <span style={{ fontSize: 28, fontFamily: "monospace", fontWeight: 700, color: "#444" }}>—</span>
              ) : (
                <span style={{ display: "inline-block", padding: "4px 14px", borderRadius: 6, fontSize: 28, fontFamily: "monospace", fontWeight: 700, background: snap.risk_score <= 3 ? "#14532d" : snap.risk_score <= 6 ? "#78350f" : "#7f1d1d", color: snap.risk_score <= 3 ? "#4ade80" : snap.risk_score <= 6 ? "#fbbf24" : "#f87171" }}>
                  {snap.risk_score}
                </span>
              )}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, color: "#888", fontSize: 12, fontFamily: "monospace" }}>
              {snap.risk_model === "trust" ? (
                <span>Investment trust — volatility only</span>
              ) : ["bank", "insurer", "financial"].includes(snap.risk_model) ? (
                <span>
                  {snap.risk_model === "bank" ? "Bank model: ROE · leverage · P/B"
                    : snap.risk_model === "insurer" ? "Insurer model: ROE · P/B"
                    : "Financial: ROE quality"} (Altman N/A)
                </span>
              ) : (
                <span>Altman {snap.risk_model === "asset_heavy" ? "Z″" : "Z"}: {snap.altman_z != null ? snap.altman_z.toFixed(2) : "—"}</span>
              )}
              {snap.risk_model === "asset_heavy" && snap.risk_components?.debt_service != null && (
                <span>Debt service: {snap.risk_components.debt_service}/10</span>
              )}
              <span>Volatility: {snap.volatility_annualised != null ? `${snap.volatility_annualised}% ann.` : "—"}</span>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(145px,1fr))", gap: 10 }}>
            {[["Current Ratio",snap.current_ratio,"ratio"],["Debt/Equity",snap.debt_to_equity,"ratio"],["Debt/Assets",snap.debt_to_assets,"ratio"],["Cash",snap.cash_and_equiv,"currency"],["Net Debt",snap.net_debt,"currency"],["Working Capital",snap.working_capital,"currency"],["Interest Coverage",snap.interest_coverage,"ratio"],["Book Value",snap.book_value,"currency"]].map(([l,v,t]: any) => (
              <MetricCard key={l} label={l} value={fmt(v, t, fcur)} />
            ))}
            <ShortInterestMetric symbol={symbol} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 20 }}>
            <div style={S.card}>
              <h3 style={S.cardTitle}>Debt / Equity History</h3>
              {hasDebtEq ? (
                <DebtEquityChart data={annualChart} singleDot={singleDot} />
              ) : (
                <div style={{ height: 210, display: "flex", alignItems: "center", justifyContent: "center", color: "#64748b", fontSize: 13 }}>
                  No debt / equity data reported
                </div>
              )}
            </div>
            <div style={S.card}>
              <h3 style={{ ...S.cardTitle, display: "flex", alignItems: "center", gap: 7 }}>
                Current Ratio History
                <InfoDot
                  size={15}
                  text="Current ratio = current assets ÷ current liabilities. It gauges short-term liquidity: whether a company can cover the bills due within a year from assets it can turn to cash in that time. Above 1 (the dashed line) means current assets exceed current liabilities — generally healthy. Below 1 can signal a liquidity squeeze, while a very high ratio may mean cash or inventory is sitting idle."
                />
              </h3>
              <CurrentRatioChart data={annualChart} singleDot={singleDot} />
            </div>
          </div>
        </div>
      )}

      {tab === "growth" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(150px,1fr))", gap: 10 }}>
            {[["Revenue Growth",snap.revenue_growth,"pct"],["Net Income Growth",snap.net_income_growth,"pct"],["EPS Growth",snap.eps_diluted_growth,"pct"],["FCF Growth",snap.fcf_growth,"pct"],["Revenue CAGR",snap.revenue_cagr_10,"pct"],["EPS CAGR",snap.eps_cagr_10,"pct"],["FCF CAGR",snap.fcf_cagr_10,"pct"],["Equity CAGR",snap.equity_cagr_10,"pct"]].map(([l,v,t]: any) => (
              <MetricCard key={l} label={l} value={fmt(v, t)} color={gc(v)} />
            ))}
          </div>
          <div style={S.card}>
            <h3 style={S.cardTitle}>Profit Margins History (%)</h3>
            <ProfitMarginsChart data={annualChart} singleDot={singleDot} />
          </div>
        </div>
      )}

      {tab === "dividends" && <DividendsTab symbol={symbol} />}
      {tab === "analysts" && <AnalystTab symbol={symbol} />}
      {tab === "news" && <NewsTab symbol={symbol} split />}
    </div>
  );
}
