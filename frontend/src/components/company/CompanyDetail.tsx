"use client";

import { useState, useEffect } from "react";
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area, ComposedChart, Cell, LabelList,
  XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";
import { API } from "@/lib/api";
import { fmt, gc, currSym, dividendDataUrl } from "@/lib/format";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { S } from "@/lib/theme";
import MetricCard from "./MetricCard";
import InfoDot from "@/components/InfoDot";
import FairValueCard from "./FairValueCard";
import PriceChart from "./PriceChart";
import AnalystTab from "@/components/AnalystTab";
import NewsTab from "@/components/NewsTab";

// The waterfall's category labels ("Cost of Revenue", "Other Expenses", …) are
// too wide to sit horizontally on mobile without overlapping. Rather than rotate
// them, wrap multi-word labels onto two lines (split at the midpoint word) so
// they stay horizontal. A custom tick is needed because Recharts ticks are
// single-line by default.
const WrapTick = ({ x, y, payload }: any) => {
  const words = String(payload?.value ?? "").split(" ");
  const mid = Math.ceil(words.length / 2);
  const lines = words.length <= 1 ? words : [words.slice(0, mid).join(" "), words.slice(mid).join(" ")];
  return (
    <text x={x} y={y} textAnchor="middle" fill="#cbd5e1" fontSize={11} fontFamily="monospace">
      {lines.map((ln, i) => (
        <tspan key={i} x={x} dy={12}>{ln}</tspan>
      ))}
    </text>
  );
};

// Company logo badge. Pulls the logo from logo.dev keyed by ticker (LSE tickers
// keep the ".L" suffix, which is exactly the format logo.dev expects). We pass
// fallback=404 so a miss fires the img onError and we drop back to the original
// purple ticker-initials badge. Needs NEXT_PUBLIC_LOGODEV_TOKEN (a publishable
// pk_ key); with no token set we skip the fetch and just show the initials.
function LogoBadge({ symbol, paysDividend }: { symbol: string; paysDividend: boolean }) {
  const [failed, setFailed] = useState(false);
  const label = symbol.replace(".L", "").slice(0, 4);
  const token = process.env.NEXT_PUBLIC_LOGODEV_TOKEN;
  // logo.dev bakes each brand's own background into the PNG (its theme param
  // doesn't strip it). We let the logo fill the chip edge-to-edge with no padding
  // so its background reaches the rounded corners; the chip itself is transparent
  // so any letterboxing blends into the page rather than showing a white ring.
  // Misses (fallback=404) drop to the purple initials.
  const logoUrl = token
    ? `https://img.logo.dev/ticker/${encodeURIComponent(symbol)}?token=${token}&size=120&format=png&retina=true&fallback=404`
    : null;
  const showLogo = !!logoUrl && !failed;

  const base = {
    width: 64, height: 64, marginTop: 9, borderRadius: 12, flexShrink: 0,
    display: "flex", alignItems: "center", justifyContent: "center",
    overflow: "hidden", textDecoration: "none",
    cursor: paysDividend ? "pointer" : "default",
  } as const;
  const wrapStyle = showLogo
    ? { ...base, background: "transparent" }
    : { ...base, background: "#6366f1", color: "#fff", fontFamily: "DM Serif Display,serif", fontSize: 13, fontWeight: 700 };

  const inner = showLogo ? (
    <img
      src={logoUrl as string}
      alt={label}
      onError={() => setFailed(true)}
      style={{ width: "100%", height: "100%", objectFit: "cover" }}
    />
  ) : (
    label
  );

  return paysDividend ? (
    <a href={dividendDataUrl(symbol)} target="_blank" rel="noopener noreferrer" title="View on Dividend Data" style={wrapStyle as any}>
      {inner}
    </a>
  ) : (
    <div style={wrapStyle as any}>{inner}</div>
  );
}

interface Props {
  symbol: string;
  onBack: () => void;
  initialTab?: string;
}

export default function CompanyDetail({ symbol, onBack, initialTab }: Props) {
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

  if (loading) return <div style={S.loading}>Loading {symbol}…</div>;
  if (!snap) return <div style={S.loading}>No data for {symbol}</div>;

  const fcur = meta?.financial_currency || "GBP";
  const sym = currSym(fcur);

  const paysDividend =
    (snap?.dividend_yield ?? 0) > 0 ||
    (snap?.dividends_per_share ?? 0) > 0 ||
    annual.some((r: any) => (r.dividends_paid ?? 0) < 0);

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

  const tabs = ["chart", "overview", "financials", "valuation", "health", "growth", "analysts", "news"];

  return (
    <div>
      <button onClick={onBack} style={S.backBtn}>← Back to Screener</button>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16, marginBottom: 28 }}>
        <div>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 10 }}>
            <LogoBadge symbol={symbol} paysDividend={paysDividend} />
            <div>
              <h2 style={{ margin: 0, fontFamily: "DM Serif Display,serif", fontSize: 26, color: "#f1f5f9" }}>{meta?.name || symbol}</h2>
              <div style={{ display: "flex", gap: 6, marginTop: 5, flexWrap: "wrap" }}>
                {[symbol, meta?.exchange, meta?.sector, meta?.country, meta?.ftse_index].filter(Boolean).map((t: string) => (
                  <span key={t} style={S.badge}>{t}</span>
                ))}
              </div>
              {paysDividend && (
                <div style={{ display: "flex", gap: 14, marginTop: 8, flexWrap: "wrap", fontFamily: "monospace", fontSize: 11, letterSpacing: 1, textTransform: "uppercase" }}>
                  <a href={dividendDataUrl(symbol)} target="_blank" rel="noopener noreferrer" style={{ color: "#a78bfa", textDecoration: "none", borderBottom: "1px dashed #a78bfa55", paddingBottom: 1 }}>
                    Dividend Data ↗
                  </a>
                </div>
              )}
            </div>
          </div>
          {meta?.description && (
            <p style={{ color: "#94a3b8", fontSize: 13, maxWidth: 680, lineHeight: 1.7, margin: 0 }}>
              {meta.description.slice(0, 300)}{meta.description.length > 300 ? "…" : ""}
            </p>
          )}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 30, fontFamily: "DM Serif Display,serif", color: "#f1f5f9" }}>{fmt(snap.market_cap, "currency", fcur)}</div>
          <div style={{ fontSize: 12, color: "#64748b" }}>Market Cap</div>
          {snap.enterprise_value && <div style={{ fontSize: 13, color: "#94a3b8", marginTop: 2 }}>EV: {fmt(snap.enterprise_value, "currency", fcur)}</div>}
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", flexWrap: isMobile ? "wrap" : "nowrap", rowGap: isMobile ? 2 : 0, columnGap: 2, borderBottom: isMobile ? "none" : "1px solid #334155", marginBottom: 24 }}>
        {tabs.map((t) => (
          <button key={t} onClick={() => setTab(t)} style={{ ...S.tab, ...(isMobile ? { padding: "8px 10px", fontSize: 11 } : {}), ...(tab === t ? S.tabActive : {}) }}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "chart" && <PriceChart symbol={symbol} fcur={fcur} />}

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
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={annualChart} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <XAxis dataKey="year" tick={{ fontSize: 11, fill: "#666", fontFamily: "monospace" }} />
                <YAxis tick={{ fontSize: 11, fill: "#666", fontFamily: "monospace" }} />
                <Tooltip formatter={(v: any) => sym + v?.toFixed(2) + "B"} contentStyle={S.tooltip} />
                <Bar dataKey="revenue" fill="#f97316" radius={[2, 2, 0, 0]} name="Revenue" />
                <Bar dataKey="net_income" fill="#10b981" radius={[2, 2, 0, 0]} name="Net Income" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {tab === "financials" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {waterfall && (
            <div style={S.card}>
              <h3 style={S.cardTitle}>{`Earnings & Revenue (FY ${latestAnnual.period_end_date?.slice(0, 4)})`}</h3>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={waterfall} margin={{ top: 24, right: 10, bottom: 5, left: 4 }} barCategoryGap="12%">
                  <XAxis dataKey="name" tick={isMobile ? <WrapTick /> : { fontSize: 12, fill: "#cbd5e1" }} interval={0} tickLine={false} axisLine={{ stroke: "#334155" }} {...(isMobile ? { height: 48 } : {})} />
                  <YAxis hide />
                  <Tooltip
                    cursor={{ fill: "#ffffff08" }}
                    contentStyle={S.tooltip}
                    itemStyle={{ color: "#e5e7eb" }}
                    formatter={(_v: any, _n: any, p: any) => [fmt(p?.payload?.amount, "currency", fcur), p?.payload?.name]}
                    labelFormatter={() => ""}
                  />
                  <Bar dataKey="range" radius={[2, 2, 0, 0]}>
                    {waterfall.map((d, i) => <Cell key={i} fill={d.fill} />)}
                    <LabelList
                      dataKey="amount"
                      content={(props: any) => {
                        const { x, y, width, value } = props;
                        return (
                          <text x={x + width / 2} y={y - 6} textAnchor="middle" fill="#e5e7eb" fontSize={12} fontFamily="monospace">
                            {fmt(value, "currency", fcur)}
                          </text>
                        );
                      }}
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 20 }}>
            <div style={S.card}>
              <h3 style={S.cardTitle}>{`Revenue, EBITDA & FCF (Annual ${sym}B)`}</h3>
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={annualChart} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                  <defs>
                    <linearGradient id="gR" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} /><stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="gE" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.25} /><stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: any) => sym + v?.toFixed(2) + "B"} contentStyle={S.tooltip} />
                  <Area type="monotone" dataKey="revenue" stroke="#6366f1" fill="url(#gR)" strokeWidth={2} dot={singleDot("revenue", "#6366f1")} name="Revenue" />
                  <Area type="monotone" dataKey="ebitda" stroke="#10b981" fill="url(#gE)" strokeWidth={2} dot={singleDot("ebitda", "#10b981")} name="EBITDA" />
                  <Line type="monotone" dataKey="fcf" stroke="#f59e0b" strokeWidth={2} dot={singleDot("fcf", "#f59e0b")} name="FCF" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div style={S.card}>
              <h3 style={S.cardTitle}>EPS Diluted (Annual)</h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={annualChart} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: any) => sym + v?.toFixed(2)} contentStyle={S.tooltip} />
                  <ReferenceLine y={0} stroke="#334155" />
                  <Line type="monotone" dataKey="eps" stroke="#6366f1" strokeWidth={2.5} dot={singleDot("eps", "#6366f1")} name="EPS" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
          {hasQuarterlyRevenue && (
            <div style={S.card}>
              <h3 style={S.cardTitle}>{`Quarterly Revenue (${sym}B)`}</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={qChart} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                  <XAxis dataKey="q" tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: any) => sym + v?.toFixed(2) + "B"} contentStyle={S.tooltip} />
                  <Bar dataKey="revenue" fill="#6366f1" radius={[4, 4, 0, 0]} name="Revenue" />
                </BarChart>
              </ResponsiveContainer>
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
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={annualChart} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} unit="%" />
                  <Tooltip formatter={(v: any) => `${v?.toFixed(1)}%`} contentStyle={S.tooltip} />
                  <ReferenceLine y={0} stroke="#334155" />
                  <Line type="monotone" dataKey="roe" stroke="#6366f1" strokeWidth={2} dot={singleDot("roe", "#6366f1")} name="ROE" />
                  <Line type="monotone" dataKey="roic" stroke="#10b981" strokeWidth={2} dot={singleDot("roic", "#10b981")} name="ROIC" />
                  <Line type="monotone" dataKey="roa" stroke="#f59e0b" strokeWidth={2} dot={singleDot("roa", "#f59e0b")} name="ROA" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {tab === "health" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div style={{ background: "#141414", borderRadius: 2, padding: "18px 22px", border: "1px solid #2a2a2a", display: "flex", alignItems: "center", gap: 24 }}>
            <div>
              <div style={{ fontSize: 10, color: "#666", marginBottom: 8, textTransform: "uppercase", letterSpacing: 1, fontFamily: "monospace" }}>Risk Score</div>
              {snap.risk_score == null ? (
                <span style={{ fontSize: 28, fontFamily: "monospace", fontWeight: 700, color: "#444" }}>—</span>
              ) : (
                <span style={{ display: "inline-block", padding: "4px 14px", borderRadius: 6, fontSize: 28, fontFamily: "monospace", fontWeight: 700, background: snap.risk_score <= 3 ? "#14532d" : snap.risk_score <= 6 ? "#78350f" : "#7f1d1d", color: snap.risk_score <= 3 ? "#4ade80" : snap.risk_score <= 6 ? "#fbbf24" : "#f87171" }}>
                  {snap.risk_score}
                </span>
              )}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, color: "#888", fontSize: 12, fontFamily: "monospace" }}>
              <span>Altman Z: {snap.altman_z != null ? snap.altman_z.toFixed(2) : "—"}</span>
              <span>Volatility: {snap.volatility_annualised != null ? `${snap.volatility_annualised}% ann.` : "—"}</span>
              <span style={{ color: "#555", fontSize: 11, marginTop: 2 }}>Z &gt; 3.0 safe · 1.8–3.0 grey · &lt; 1.8 distress</span>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(145px,1fr))", gap: 10 }}>
            {[["Current Ratio",snap.current_ratio,"ratio"],["Debt/Equity",snap.debt_to_equity,"ratio"],["Debt/Assets",snap.debt_to_assets,"ratio"],["Cash",snap.cash_and_equiv,"currency"],["Net Debt",snap.net_debt,"currency"],["Working Capital",snap.working_capital,"currency"],["Interest Coverage",snap.interest_coverage,"ratio"],["Book Value",snap.book_value,"currency"]].map(([l,v,t]: any) => (
              <MetricCard key={l} label={l} value={fmt(v, t, fcur)} />
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 20 }}>
            <div style={S.card}>
              <h3 style={S.cardTitle}>Debt / Equity History</h3>
              {hasDebtEq ? (
                <ResponsiveContainer width="100%" height={210}>
                  <AreaChart data={annualChart} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                    <defs>
                      <linearGradient id="gD" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} /><stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="year" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
                    <Tooltip contentStyle={S.tooltip} />
                    <Area type="monotone" dataKey="debt_eq" stroke="#ef4444" fill="url(#gD)" strokeWidth={2} dot={singleDot("debt_eq", "#ef4444")} name="D/E" />
                  </AreaChart>
                </ResponsiveContainer>
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
              <ResponsiveContainer width="100%" height={210}>
                <LineChart data={annualChart} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={S.tooltip} />
                  <ReferenceLine y={1} stroke="#f59e0b" strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="curr_ratio" stroke="#10b981" strokeWidth={2.5} dot={singleDot("curr_ratio", "#10b981")} name="Current Ratio" />
                </LineChart>
              </ResponsiveContainer>
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
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={annualChart} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <XAxis dataKey="year" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} unit="%" />
                <Tooltip formatter={(v: any) => `${v?.toFixed(1)}%`} contentStyle={S.tooltip} />
                <ReferenceLine y={0} stroke="#334155" />
                <Line type="monotone" dataKey="gross_margin" stroke="#6366f1" strokeWidth={2} dot={singleDot("gross_margin", "#6366f1")} name="Gross Margin" />
                <Line type="monotone" dataKey="op_margin" stroke="#10b981" strokeWidth={2} dot={singleDot("op_margin", "#10b981")} name="Op. Margin" />
                <Line type="monotone" dataKey="net_margin" stroke="#f59e0b" strokeWidth={2} dot={singleDot("net_margin", "#f59e0b")} name="Net Margin" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {tab === "analysts" && <AnalystTab symbol={symbol} />}
      {tab === "news" && <NewsTab symbol={symbol} split />}
    </div>
  );
}
