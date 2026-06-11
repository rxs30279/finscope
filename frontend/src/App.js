import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  ComposedChart,
  Cell,
  Customized,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import {
  API,
  fmt,
  gc,
  currSym,
  loadWatchlists,
  saveWatchlists,
  genListId,
  DEFAULT_LIST_ID,
  dividendDataUrl,
  loadChartPrefs,
  saveChartPrefs,
} from "./utils";
import { Analytics } from "@vercel/analytics/react";
import { SpeedInsights } from "@vercel/speed-insights/react";
import { useIsMobile, useIsNarrowDesktop } from "./useMediaQuery";
import Sidebar from "./components/Sidebar";
import RotationTab from "./components/RotationTab";
import BreadthTab from "./components/BreadthTab";
import FearGreedTab from "./components/FearGreedTab";
import CrossAssetTab from "./components/CrossAssetTab";
import AnalystTab from "./components/AnalystTab";
import AnalystMonitorTab from "./components/AnalystMonitorTab";
import RnsTab from "./components/RnsTab";
import NewsTab from "./components/NewsTab";
import SubscribeTab from "./components/SubscribeTab";
import DonateTab from "./components/DonateTab";
import FeedbackTab from "./components/FeedbackTab";
import WatchlistTab from "./components/WatchlistTab";
import HeatmapTab from "./components/HeatmapTab";

function MetricCard({ label, value, color, compact }) {
  return (
    <div
      style={{
        background: "#141414",
        borderRadius: 2,
        padding: compact ? "7px 10px" : "14px 18px",
        border: "1px solid #2a2a2a",
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: "#666",
          marginBottom: compact ? 2 : 6,
          textTransform: "uppercase",
          letterSpacing: 1,
          fontFamily: "monospace",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: compact ? 15 : 18,
          fontFamily: "monospace",
          fontWeight: 700,
          color: color || "#e5e5e5",
        }}
      >
        {value}
      </div>
    </div>
  );
}

// ── Company Detail ────────────────────────────────────────────────────────────
function CompanyDetail({ symbol, onBack, initialTab }) {
  const [meta, setMeta] = useState(null);
  const [snap, setSnap] = useState(null);
  const [annual, setAnnual] = useState([]);
  const [quarterly, setQuarterly] = useState([]);
  const [tab, setTab] = useState(initialTab || "chart");
  const [loading, setLoading] = useState(true);
  const isMobile = useIsMobile();

  // Honour a requested tab (e.g. opening straight to News from the watchlist),
  // and reset to that tab when the viewed company changes.
  useEffect(() => {
    setTab(initialTab || "chart");
  }, [symbol, initialTab]);

  useEffect(() => {
    setLoading(true);
    const enc = encodeURIComponent(symbol);
    Promise.all([
      fetch(`${API}/company?symbol=${enc}`).then((r) => r.json()),
      fetch(`${API}/snapshot?symbol=${enc}`).then((r) => r.json()),
      fetch(`${API}/annual?symbol=${enc}`).then((r) => r.json()),
      fetch(`${API}/quarterly?symbol=${enc}`).then((r) => r.json()),
    ])
      .then(([m, s, a, q]) => {
        setMeta(m);
        setSnap(s);
        setAnnual(Array.isArray(a) ? a : []);
        setQuarterly(Array.isArray(q) ? q : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [symbol]);

  if (loading) return <div style={S.loading}>Loading {symbol}…</div>;
  if (!snap) return <div style={S.loading}>No data for {symbol}</div>;

  const fcur = meta?.financial_currency || "GBP";
  const sym = currSym(fcur);

  // Only link out to Dividend Data for actual payers — the page is a dead end for
  // non-dividend stocks. Treat a positive yield or DPS as paying, and fall back to
  // historical cash dividends paid (a negative cash outflow in any recent annual
  // period). The fallback covers payers like ITH whose yfinance yield never made
  // it into the snapshot, so they'd otherwise look like non-payers.
  const paysDividend =
    (snap?.dividend_yield ?? 0) > 0 ||
    (snap?.dividends_per_share ?? 0) > 0 ||
    annual.some((r) => (r.dividends_paid ?? 0) < 0);

  const annualChart = annual.map((r) => ({
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

  const qChart = quarterly.slice(-8).map((r) => ({
    q: r.fiscal_quarter_key || r.period_end_date?.slice(0, 7),
    revenue: r.revenue ? r.revenue / 1e9 : null,
    net_income: r.net_income ? r.net_income / 1e9 : null,
    eps: r.eps_diluted,
  }));
  const hasQuarterlyRevenue = qChart.some((r) => r.revenue != null);

  const tabs = [
    "chart",
    "overview",
    "financials",
    "valuation",
    "health",
    "growth",
    "analysts",
    "news",
  ];

  return (
    <div>
      <button onClick={onBack} style={S.backBtn}>
        ← Back to Screener
      </button>

      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: 16,
          marginBottom: 28,
        }}
      >
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              marginBottom: 10,
            }}
          >
            {(() => {
              const badgeStyle = {
                background: "#6366f1",
                color: "#fff",
                borderRadius: 10,
                width: 50,
                height: 50,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: "DM Serif Display,serif",
                fontSize: 13,
                fontWeight: 700,
                textDecoration: "none",
                cursor: paysDividend ? "pointer" : "default",
              };
              const label = symbol.replace(".L", "").slice(0, 4);
              return paysDividend ? (
                <a
                  href={dividendDataUrl(symbol)}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="View on Dividend Data"
                  style={badgeStyle}
                >
                  {label}
                </a>
              ) : (
                <div style={badgeStyle}>{label}</div>
              );
            })()}
            <div>
              <h1
                style={{
                  margin: 0,
                  fontFamily: "DM Serif Display,serif",
                  fontSize: 26,
                  color: "#f1f5f9",
                }}
              >
                {meta?.name || symbol}
              </h1>
              <div
                style={{
                  display: "flex",
                  gap: 6,
                  marginTop: 5,
                  flexWrap: "wrap",
                }}
              >
                {[
                  symbol,
                  meta?.exchange,
                  meta?.sector,
                  meta?.country,
                  meta?.ftse_index,
                ]
                  .filter(Boolean)
                  .map((t) => (
                    <span key={t} style={S.badge}>
                      {t}
                    </span>
                  ))}
              </div>
              {/* External link — Dividend Data. Payers only; dead page otherwise. */}
              {paysDividend && (
                <div
                  style={{
                    display: "flex",
                    gap: 14,
                    marginTop: 8,
                    flexWrap: "wrap",
                    fontFamily: "monospace",
                    fontSize: 11,
                    letterSpacing: 1,
                    textTransform: "uppercase",
                  }}
                >
                  <a
                    href={dividendDataUrl(symbol)}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      color: "#a78bfa",
                      textDecoration: "none",
                      borderBottom: "1px dashed #a78bfa55",
                      paddingBottom: 1,
                    }}
                  >
                    Dividend Data ↗
                  </a>
                </div>
              )}
            </div>
          </div>
          {meta?.description && (
            <p
              style={{
                color: "#94a3b8",
                fontSize: 13,
                maxWidth: 680,
                lineHeight: 1.7,
                margin: 0,
              }}
            >
              {meta.description.slice(0, 300)}
              {meta.description.length > 300 ? "…" : ""}
            </p>
          )}
        </div>
        <div style={{ textAlign: "right" }}>
          <div
            style={{
              fontSize: 30,
              fontFamily: "DM Serif Display,serif",
              color: "#f1f5f9",
            }}
          >
            {fmt(snap.market_cap, "currency", fcur)}
          </div>
          <div style={{ fontSize: 12, color: "#64748b" }}>Market Cap</div>
          {snap.enterprise_value && (
            <div style={{ fontSize: 13, color: "#94a3b8", marginTop: 2 }}>
              EV: {fmt(snap.enterprise_value, "currency", fcur)}
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div
        style={{
          display: "flex",
          flexWrap: isMobile ? "wrap" : "nowrap",
          rowGap: isMobile ? 2 : 0,
          gap: 2,
          // On mobile the row wraps, so the container border would only sit
          // under the bottom row — let each tab's own border show the active state.
          borderBottom: isMobile ? "none" : "1px solid #334155",
          marginBottom: 24,
        }}
      >
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              ...S.tab,
              ...(isMobile ? { padding: "8px 10px", fontSize: 11 } : {}),
              ...(tab === t ? S.tabActive : {}),
            }}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* CHART */}
      {tab === "chart" && (
        <div>
          <PriceChart symbol={symbol} fcur={fcur} />
        </div>
      )}

      {/* OVERVIEW */}
      {tab === "overview" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill,minmax(155px,1fr))",
              gap: 10,
            }}
          >
            <MetricCard
              label="Revenue"
              value={fmt(snap.revenue, "currency", fcur)}
            />
            <MetricCard
              label="Net Income"
              value={fmt(snap.net_income, "currency", fcur)}
              color={snap.net_income > 0 ? "#10b981" : "#ef4444"}
            />
            <MetricCard
              label="EBITDA"
              value={fmt(snap.ebitda, "currency", fcur)}
            />
            <MetricCard
              label="Free Cash Flow"
              value={fmt(snap.fcf, "currency", fcur)}
              color={snap.fcf > 0 ? "#10b981" : "#ef4444"}
            />
            <MetricCard
              label="P/E"
              value={fmt(snap.price_to_earnings, "ratio")}
            />
            <MetricCard label="P/B" value={fmt(snap.price_to_book, "ratio")} />
            <MetricCard
              label="ROE"
              value={fmt(snap.roe, "pct")}
              color={gc(snap.roe)}
            />
            <MetricCard
              label="ROIC"
              value={fmt(snap.roic, "pct")}
              color={gc(snap.roic)}
            />
            <MetricCard
              label="Gross Margin"
              value={fmt(snap.gross_margin, "pct")}
            />
            <MetricCard
              label="Net Margin"
              value={fmt(snap.net_income_margin, "pct")}
              color={gc(snap.net_income_margin)}
            />
            <MetricCard
              label="Debt/Equity"
              value={fmt(snap.debt_to_equity, "ratio")}
              color={snap.debt_to_equity > 2 ? "#ef4444" : "#e5e5e5"}
            />
            <MetricCard
              label="Current Ratio"
              value={fmt(snap.current_ratio, "ratio")}
            />
          </div>
          <div style={S.card}>
            <h3
              style={S.cardTitle}
            >{`Revenue & Net Income (Annual ${sym}B)`}</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={annualChart}
                margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
                <XAxis
                  dataKey="year"
                  tick={{ fontSize: 11, fill: "#666", fontFamily: "monospace" }}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "#666", fontFamily: "monospace" }}
                />
                <Tooltip
                  formatter={(v) => sym + v?.toFixed(2) + "B"}
                  contentStyle={S.tooltip}
                />
                <Bar
                  dataKey="revenue"
                  fill="#f97316"
                  radius={[2, 2, 0, 0]}
                  name="Revenue"
                />
                <Bar
                  dataKey="net_income"
                  fill="#10b981"
                  radius={[2, 2, 0, 0]}
                  name="Net Income"
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* FINANCIALS */}
      {tab === "financials" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div style={S.card}>
            <h3
              style={S.cardTitle}
            >{`Revenue, EBITDA & FCF (Annual ${sym}B)`}</h3>
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart
                data={annualChart}
                margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
              >
                <defs>
                  <linearGradient id="gR" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gE" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip
                  formatter={(v) => sym + v?.toFixed(2) + "B"}
                  contentStyle={S.tooltip}
                />
                <Area
                  type="monotone"
                  dataKey="revenue"
                  stroke="#6366f1"
                  fill="url(#gR)"
                  strokeWidth={2}
                  name="Revenue"
                />
                <Area
                  type="monotone"
                  dataKey="ebitda"
                  stroke="#10b981"
                  fill="url(#gE)"
                  strokeWidth={2}
                  name="EBITDA"
                />
                <Line
                  type="monotone"
                  dataKey="fcf"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={false}
                  name="FCF"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                isMobile || !hasQuarterlyRevenue ? "1fr" : "1fr 1fr",
              gap: 20,
            }}
          >
            {hasQuarterlyRevenue && (
              <div style={S.card}>
                <h3 style={S.cardTitle}>{`Quarterly Revenue (${sym}B)`}</h3>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart
                    data={qChart}
                    margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                    <XAxis dataKey="q" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip
                      formatter={(v) => sym + v?.toFixed(2) + "B"}
                      contentStyle={S.tooltip}
                    />
                    <Bar
                      dataKey="revenue"
                      fill="#6366f1"
                      radius={[4, 4, 0, 0]}
                      name="Revenue"
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            <div style={S.card}>
              <h3 style={S.cardTitle}>EPS Diluted (Annual)</h3>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart
                  data={annualChart}
                  margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v) => sym + v?.toFixed(2)}
                    contentStyle={S.tooltip}
                  />
                  <ReferenceLine y={0} stroke="#334155" />
                  <Line
                    type="monotone"
                    dataKey="eps"
                    stroke="#6366f1"
                    strokeWidth={2.5}
                    dot={{ r: 4, fill: "#6366f1" }}
                    name="EPS"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div style={S.card}>
            <h3 style={S.cardTitle}>{`Income Statement (${sym}B)`}</h3>
            <div style={{ overflowX: "auto" }}>
              <table style={S.table}>
                <thead>
                  <tr>
                    <th style={S.th}>Metric</th>
                    {annual.slice(-5).map((r) => (
                      <th
                        key={r.period_end_date}
                        style={{ ...S.th, textAlign: "right" }}
                      >
                        {r.period_end_date?.slice(0, 4)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["Revenue", "revenue"],
                    ["Gross Profit", "gross_profit"],
                    ["Operating Income", "operating_income"],
                    ["EBITDA", "ebitda"],
                    ["Net Income", "net_income"],
                    ["FCF", "fcf"],
                  ].map(([l, k]) => (
                    <tr key={k} style={{ borderBottom: "1px solid #334155" }}>
                      <td style={S.td}>{l}</td>
                      {annual.slice(-5).map((r) => (
                        <td
                          key={r.period_end_date}
                          style={{
                            ...S.tdNum,
                            color: r[k] < 0 ? "#ef4444" : "#ccc",
                          }}
                        >
                          {r[k] ? sym + (r[k] / 1e9).toFixed(2) + "B" : "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* VALUATION */}
      {tab === "valuation" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill,minmax(145px,1fr))",
              gap: 10,
            }}
          >
            {[
              ["P/E", snap.price_to_earnings, "ratio"],
              ["P/B", snap.price_to_book, "ratio"],
              ["P/S", snap.price_to_sales, "ratio"],
              ["EV/EBITDA", snap.ev_to_ebitda, "ratio"],
              ["EV/Sales", snap.ev_to_sales, "ratio"],
              ["ROE", snap.roe, "pct"],
              ["ROIC", snap.roic, "pct"],
              ["ROCE", snap.roce, "pct"],
            ].map(([l, v, t]) => (
              <MetricCard key={l} label={l} value={fmt(v, t)} />
            ))}
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
              gap: 20,
            }}
          >
            <div style={S.card}>
              <h3 style={S.cardTitle}>EPS History</h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart
                  data={annualChart}
                  margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={S.tooltip} />
                  <ReferenceLine y={0} stroke="#334155" />
                  <Line
                    type="monotone"
                    dataKey="eps"
                    stroke="#6366f1"
                    strokeWidth={2.5}
                    dot={{ r: 3 }}
                    name="EPS"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div style={S.card}>
              <h3 style={S.cardTitle}>Return on Capital (%)</h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart
                  data={annualChart}
                  margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} unit="%" />
                  <Tooltip
                    formatter={(v) => `${v?.toFixed(1)}%`}
                    contentStyle={S.tooltip}
                  />
                  <ReferenceLine y={0} stroke="#334155" />
                  <Line
                    type="monotone"
                    dataKey="roe"
                    stroke="#6366f1"
                    strokeWidth={2}
                    dot={false}
                    name="ROE"
                  />
                  <Line
                    type="monotone"
                    dataKey="roic"
                    stroke="#10b981"
                    strokeWidth={2}
                    dot={false}
                    name="ROIC"
                  />
                  <Line
                    type="monotone"
                    dataKey="roa"
                    stroke="#f59e0b"
                    strokeWidth={2}
                    dot={false}
                    name="ROA"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* HEALTH */}
      {tab === "health" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Risk Score card */}
          <div
            style={{
              background: "#141414",
              borderRadius: 2,
              padding: "18px 22px",
              border: "1px solid #2a2a2a",
              display: "flex",
              alignItems: "center",
              gap: 24,
            }}
          >
            <div>
              <div
                style={{
                  fontSize: 10,
                  color: "#666",
                  marginBottom: 8,
                  textTransform: "uppercase",
                  letterSpacing: 1,
                  fontFamily: "monospace",
                }}
              >
                Risk Score
              </div>
              {snap.risk_score == null ? (
                <span
                  style={{
                    fontSize: 28,
                    fontFamily: "monospace",
                    fontWeight: 700,
                    color: "#444",
                  }}
                >
                  —
                </span>
              ) : (
                <span
                  style={{
                    display: "inline-block",
                    padding: "4px 14px",
                    borderRadius: 6,
                    fontSize: 28,
                    fontFamily: "monospace",
                    fontWeight: 700,
                    background:
                      snap.risk_score <= 3
                        ? "#14532d"
                        : snap.risk_score <= 6
                          ? "#78350f"
                          : "#7f1d1d",
                    color:
                      snap.risk_score <= 3
                        ? "#4ade80"
                        : snap.risk_score <= 6
                          ? "#fbbf24"
                          : "#f87171",
                  }}
                >
                  {snap.risk_score}
                </span>
              )}
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                color: "#888",
                fontSize: 12,
                fontFamily: "monospace",
              }}
            >
              <span>
                Altman Z:{" "}
                {snap.altman_z != null ? snap.altman_z.toFixed(2) : "—"}
              </span>
              <span>
                Volatility:{" "}
                {snap.volatility_annualised != null
                  ? `${snap.volatility_annualised}% ann.`
                  : "—"}
              </span>
              <span style={{ color: "#555", fontSize: 11, marginTop: 2 }}>
                Z &gt; 3.0 safe · 1.8–3.0 grey · &lt; 1.8 distress
              </span>
            </div>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill,minmax(145px,1fr))",
              gap: 10,
            }}
          >
            {[
              ["Current Ratio", snap.current_ratio, "ratio"],
              ["Debt/Equity", snap.debt_to_equity, "ratio"],
              ["Debt/Assets", snap.debt_to_assets, "ratio"],
              ["Cash", snap.cash_and_equiv, "currency"],
              ["Net Debt", snap.net_debt, "currency"],
              ["Working Capital", snap.working_capital, "currency"],
              ["Interest Coverage", snap.interest_coverage, "ratio"],
              ["Book Value", snap.book_value, "currency"],
            ].map(([l, v, t]) => (
              <MetricCard key={l} label={l} value={fmt(v, t, fcur)} />
            ))}
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
              gap: 20,
            }}
          >
            <div style={S.card}>
              <h3 style={S.cardTitle}>Debt / Equity History</h3>
              <ResponsiveContainer width="100%" height={210}>
                <AreaChart
                  data={annualChart}
                  margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
                >
                  <defs>
                    <linearGradient id="gD" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={S.tooltip} />
                  <Area
                    type="monotone"
                    dataKey="debt_eq"
                    stroke="#ef4444"
                    fill="url(#gD)"
                    strokeWidth={2}
                    name="D/E"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div style={S.card}>
              <h3 style={S.cardTitle}>Current Ratio History</h3>
              <ResponsiveContainer width="100%" height={210}>
                <LineChart
                  data={annualChart}
                  margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={S.tooltip} />
                  <ReferenceLine y={1} stroke="#f59e0b" strokeDasharray="4 4" />
                  <Line
                    type="monotone"
                    dataKey="curr_ratio"
                    stroke="#10b981"
                    strokeWidth={2.5}
                    dot={{ r: 3 }}
                    name="Current Ratio"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* GROWTH */}
      {tab === "growth" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill,minmax(150px,1fr))",
              gap: 10,
            }}
          >
            {[
              ["Revenue Growth", snap.revenue_growth, "pct"],
              ["Net Income Growth", snap.net_income_growth, "pct"],
              ["EPS Growth", snap.eps_diluted_growth, "pct"],
              ["FCF Growth", snap.fcf_growth, "pct"],
              ["Revenue CAGR", snap.revenue_cagr_10, "pct"],
              ["EPS CAGR", snap.eps_cagr_10, "pct"],
              ["FCF CAGR", snap.fcf_cagr_10, "pct"],
              ["Equity CAGR", snap.equity_cagr_10, "pct"],
            ].map(([l, v, t]) => (
              <MetricCard key={l} label={l} value={fmt(v, t)} color={gc(v)} />
            ))}
          </div>
          <div style={S.card}>
            <h3 style={S.cardTitle}>Profit Margins History (%)</h3>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart
                data={annualChart}
                margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} unit="%" />
                <Tooltip
                  formatter={(v) => `${v?.toFixed(1)}%`}
                  contentStyle={S.tooltip}
                />
                <ReferenceLine y={0} stroke="#334155" />
                <Line
                  type="monotone"
                  dataKey="gross_margin"
                  stroke="#6366f1"
                  strokeWidth={2}
                  dot={false}
                  name="Gross Margin"
                />
                <Line
                  type="monotone"
                  dataKey="op_margin"
                  stroke="#10b981"
                  strokeWidth={2}
                  dot={false}
                  name="Op. Margin"
                />
                <Line
                  type="monotone"
                  dataKey="net_margin"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={false}
                  name="Net Margin"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ANALYSTS */}
      {tab === "analysts" && <AnalystTab symbol={symbol} />}

      {/* NEWS */}
      {tab === "news" && <NewsTab symbol={symbol} split />}
    </div>
  );
}

// ── Hybrid select (presets + custom input) ────────────────────────────────────
function HybridSelect({
  selectMode,
  onSelectChange,
  onCustomCommit,
  children,
  placeholder,
  inputWidth = 80,
}) {
  const [draft, setDraft] = useState("");
  const isCustom = selectMode === "custom";

  const commit = () => {
    const n = parseFloat(draft);
    if (!isNaN(n)) onCustomCommit(n);
  };

  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
      <select
        style={S.select}
        value={selectMode}
        onChange={(e) => {
          setDraft("");
          onSelectChange(e.target.value);
        }}
      >
        {children}
        <option value="custom">Custom…</option>
      </select>
      {isCustom && (
        <input
          type="number"
          placeholder={placeholder}
          value={draft}
          style={{ ...S.select, width: inputWidth, padding: "8px 8px" }}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && commit()}
          autoFocus
        />
      )}
    </div>
  );
}

// ── PriceChart ────────────────────────────────────────────────────────────────
function PriceChart({ symbol, fcur = "GBP" }) {
  const [priceData, setPriceData] = useState([]);
  const [liveQuote, setLiveQuote] = useState(null);
  const [loading, setLoading] = useState(true);
  // Seed display prefs from the last-used values (persisted) so toggles like
  // "no candles" stick when moving between stocks rather than resetting.
  const [prefs] = useState(loadChartPrefs);
  const [range, setRange] = useState(prefs.range);
  const [showMA20, setShowMA20] = useState(prefs.showMA20);
  const [showMA50, setShowMA50] = useState(prefs.showMA50);
  const [showVolume, setShowVolume] = useState(prefs.showVolume);
  const [showCandles, setShowCandles] = useState(prefs.showCandles);
  const [showMACD, setShowMACD] = useState(prefs.showMACD);
  const [showRSI, setShowRSI] = useState(prefs.showRSI);

  // Persist whenever any preference changes so the next chart that mounts (a
  // different stock, or after a reload) picks up the same choices.
  useEffect(() => {
    saveChartPrefs({
      range,
      showMA20,
      showMA50,
      showVolume,
      showCandles,
      showMACD,
      showRSI,
    });
  }, [range, showMA20, showMA50, showVolume, showCandles, showMACD, showRSI]);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    fetch(`${API}/prices/refresh/${symbol}`, { method: "POST" })
      .then(() => fetch(`${API}/prices/${symbol}`))
      .then((r) => r.json())
      .then((data) => {
        setPriceData(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [symbol]);

  // Live last-price poll (pence, intraday during market hours; 60s server cache).
  // Same /quotes endpoint as the watchlist; overrides the latest stored close.
  useEffect(() => {
    if (!symbol) return;
    setLiveQuote(null);
    let cancelled = false;
    const fetchQuote = () => {
      fetch(`${API}/quotes?symbols=${encodeURIComponent(symbol)}`)
        .then((r) => r.json())
        .then((d) => {
          if (cancelled || !d || typeof d !== "object") return;
          const q = d[symbol];
          setLiveQuote(typeof q === "number" ? q : null);
        })
        .catch(() => {});
    };
    fetchQuote();
    const id = setInterval(fetchQuote, 60000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol]);

  const computeMA = (data, n) =>
    data.map((_, i) => {
      if (i < n - 1) return null;
      const slice = data.slice(i - n + 1, i + 1);
      return (
        Math.round((slice.reduce((s, d) => s + d.close, 0) / n) * 100) / 100
      );
    });

  const ma20 = computeMA(priceData, 20);
  const ma50 = computeMA(priceData, 50);

  // MACD (12/26/9) over close. EMA seeded on the first value; computed across
  // the full 5Y history so it's fully warmed up before any visible window.
  const emaSeries = (vals, period) => {
    const k = 2 / (period + 1);
    let prev = null;
    return vals.map((v) => {
      if (v == null) return null;
      prev = prev == null ? v : v * k + prev * (1 - k);
      return prev;
    });
  };
  const closes = priceData.map((d) => d.close);
  const ema12 = emaSeries(closes, 12);
  const ema26 = emaSeries(closes, 26);
  const macdArr = closes.map((_, i) =>
    ema12[i] != null && ema26[i] != null ? ema12[i] - ema26[i] : null
  );
  const signalArr = emaSeries(macdArr, 9);
  const histArr = macdArr.map((v, i) =>
    v != null && signalArr[i] != null ? v - signalArr[i] : null
  );

  // RSI(14), Wilder's smoothing. >70 overbought, <30 oversold.
  const computeRSI = (period = 14) => {
    const rsi = new Array(closes.length).fill(null);
    let avgGain = 0;
    let avgLoss = 0;
    for (let i = 1; i < closes.length; i++) {
      const ch = closes[i] - closes[i - 1];
      const gain = ch > 0 ? ch : 0;
      const loss = ch < 0 ? -ch : 0;
      if (i <= period) {
        avgGain += gain;
        avgLoss += loss;
        if (i === period) {
          avgGain /= period;
          avgLoss /= period;
          rsi[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
        }
      } else {
        avgGain = (avgGain * (period - 1) + gain) / period;
        avgLoss = (avgLoss * (period - 1) + loss) / period;
        rsi[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
      }
    }
    return rsi;
  };
  const rsiArr = computeRSI(14);

  const RANGE_DAYS = {
    "1M": 30,
    "3M": 90,
    "6M": 180,
    "1Y": 365,
    "3Y": 1095,
    "5Y": 1825,
  };
  const cutoffDays = RANGE_DAYS[range];
  const latest = priceData.length
    ? new Date(priceData[priceData.length - 1].date)
    : new Date();
  const cutoff = cutoffDays
    ? new Date(latest.getTime() - cutoffDays * 86400000)
    : null;

  const chartData = priceData
    .map((d, i) => ({
      date: d.date,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
      volume: d.volume,
      ma20: ma20[i],
      ma50: ma50[i],
      macd: macdArr[i],
      signal: signalArr[i],
      hist: histArr[i],
      rsi: rsiArr[i],
    }))
    .filter((d) => !cutoff || new Date(d.date) >= cutoff);

  // Axis tick label: short ranges show day+month, long ranges show month+year.
  const tickFormatter = (dateStr) => {
    const d = new Date(dateStr);
    const mon = d.toLocaleString("default", { month: "short" });
    if (["3Y", "5Y"].includes(range)) return `${mon} ${d.getFullYear()}`;
    if (["1M", "3M"].includes(range)) return `${d.getDate()} ${mon}`;
    return mon; // 6M, 1Y
  };

  // Tooltip label: always the full, unambiguous date.
  const labelFormatter = (dateStr) =>
    new Date(dateStr).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });

  // Price-axis label with thousands separators (e.g. 13,500) so large-cap,
  // high-priced stocks read cleanly.
  const fmtAxisPrice = (v) =>
    v == null
      ? ""
      : Number(v).toLocaleString("en-GB", { maximumFractionDigits: 2 });

  // Compact volume label, e.g. 1.2M / 845K.
  const fmtVolume = (v) => {
    if (v == null) return "—";
    if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return String(v);
  };

  // Evenly spaced ticks pulled from the actual data so labels never duplicate
  // or crowd, regardless of the selected range.
  const TICK_COUNT = 7;
  const axisTicks =
    chartData.length <= TICK_COUNT
      ? chartData.map((d) => d.date)
      : Array.from({ length: TICK_COUNT }, (_, i) =>
          chartData[Math.round((i * (chartData.length - 1)) / (TICK_COUNT - 1))]
            .date
        );

  // In candle mode the candles are drawn as an SVG overlay (not a data series),
  // so the price axis won't auto-scale to their highs/lows. Derive an explicit
  // domain with a little padding so wicks aren't clipped.
  const UP = "#22c55e";
  const DOWN = "#ef4444";
  const priceDomain = (() => {
    if (!showCandles) return ["auto", "auto"];
    const lows = chartData.map((d) => d.low).filter((v) => v != null);
    const highs = chartData.map((d) => d.high).filter((v) => v != null);
    if (!lows.length || !highs.length) return ["auto", "auto"];
    const lo = Math.min(...lows);
    const hi = Math.max(...highs);
    const span = hi - lo || hi || 1;
    // Round the padded bounds to a "nice" increment (1/2/5 × 10ⁿ) so Recharts
    // generates clean tick values instead of fractional noise — important for
    // high-priced stocks like AZN.L where raw bounds produce labels like 13245.7.
    const mag = Math.pow(10, Math.floor(Math.log10(span / 5)));
    const norm = span / 5 / mag;
    const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const domLo = Math.floor((lo - span * 0.05) / step) * step;
    const domHi = Math.ceil((hi + span * 0.05) / step) * step;
    return [Math.max(0, domLo), domHi];
  })();

  // Candlestick overlay. <Customized> hands us the live axis scales, letting us
  // position wicks/bodies exactly without fighting Recharts' bar layout.
  const renderCandles = ({ xAxisMap, yAxisMap }) => {
    if (!showCandles || !xAxisMap || !yAxisMap) return null;
    const xAxis = xAxisMap[Object.keys(xAxisMap)[0]];
    const priceKey =
      Object.keys(yAxisMap).find((k) => k !== "vol") ??
      Object.keys(yAxisMap)[0];
    const yAxis = yAxisMap[priceKey];
    if (!xAxis || !yAxis) return null;
    const xScale = xAxis.scale;
    const yScale = yAxis.scale;
    // Band scale (when a Bar is present) maps to the band's left edge and has a
    // real bandwidth; point scale (candles only) maps to the centre and reports
    // bandwidth() === 0, so fall back to step()/spacing for the candle width.
    const bw = typeof xScale.bandwidth === "function" ? xScale.bandwidth() : 0;
    const isBand = bw > 0;
    const step =
      typeof xScale.step === "function"
        ? xScale.step()
        : chartData.length > 1
        ? Math.abs(xScale(chartData[1].date) - xScale(chartData[0].date))
        : 6;
    const band = isBand ? bw : step;
    const bodyW = Math.max(1, band * 0.6);
    return (
      <g>
        {chartData.map((d, i) => {
          if (
            d.open == null ||
            d.high == null ||
            d.low == null ||
            d.close == null
          )
            return null;
          const cx = isBand ? xScale(d.date) + bw / 2 : xScale(d.date);
          const color = d.close >= d.open ? UP : DOWN;
          const yHigh = yScale(d.high);
          const yLow = yScale(d.low);
          const yOpen = yScale(d.open);
          const yClose = yScale(d.close);
          const bodyTop = Math.min(yOpen, yClose);
          const bodyH = Math.max(1, Math.abs(yClose - yOpen));
          return (
            <g key={i}>
              <line
                x1={cx}
                y1={yHigh}
                x2={cx}
                y2={yLow}
                stroke={color}
                strokeWidth={1}
              />
              <rect
                x={cx - bodyW / 2}
                y={bodyTop}
                width={bodyW}
                height={bodyH}
                fill={color}
              />
            </g>
          );
        })}
      </g>
    );
  };

  // Custom tooltip: reads the full data point so every active series (OHLC in
  // candle mode, Close otherwise, plus MAs and Volume) is listed in full.
  const ChartTooltip = ({ active, payload }) => {
    if (!active || !payload || !payload.length) return null;
    const d = payload[0].payload;
    if (!d) return null;
    const f = (x) => (x == null ? "—" : x.toFixed(2));
    const row = (label, val, color) => (
      <div
        key={label}
        style={{ display: "flex", justifyContent: "space-between", gap: 16 }}
      >
        <span style={{ color: color || "#94a3b8" }}>{label}</span>
        <span style={{ color: "#e5e5e5" }}>{val}</span>
      </div>
    );
    return (
      <div style={{ ...S.tooltip, padding: "6px 10px" }}>
        <div style={{ marginBottom: 4, color: "#cbd5e1" }}>
          {labelFormatter(d.date)}
        </div>
        {showCandles
          ? [
              row("O", f(d.open)),
              row("H", f(d.high)),
              row("L", f(d.low)),
              row("C", f(d.close)),
            ]
          : row("Close", f(d.close), "#818cf8")}
        {showMA20 && d.ma20 != null && row("MA20", f(d.ma20), "#f59e0b")}
        {showMA50 && d.ma50 != null && row("MA50", f(d.ma50), "#a855f7")}
        {showVolume &&
          d.volume != null &&
          row("Vol", fmtVolume(d.volume), "#22d3ee")}
      </div>
    );
  };

  // Tooltip for the MACD sub-panel.
  const MacdTooltip = ({ active, payload }) => {
    if (!active || !payload || !payload.length) return null;
    const d = payload[0].payload;
    if (!d) return null;
    const f = (x) => (x == null ? "—" : x.toFixed(2));
    const row = (label, val, color) => (
      <div
        key={label}
        style={{ display: "flex", justifyContent: "space-between", gap: 16 }}
      >
        <span style={{ color: color || "#94a3b8" }}>{label}</span>
        <span style={{ color: "#e5e5e5" }}>{val}</span>
      </div>
    );
    return (
      <div style={{ ...S.tooltip, padding: "6px 10px" }}>
        <div style={{ marginBottom: 4, color: "#cbd5e1" }}>
          {labelFormatter(d.date)}
        </div>
        {row("MACD", f(d.macd), "#38bdf8")}
        {row("Signal", f(d.signal), "#f59e0b")}
        {row("Hist", f(d.hist), d.hist >= 0 ? UP : DOWN)}
      </div>
    );
  };

  // Tooltip for the RSI sub-panel, with an overbought/oversold tag.
  const RsiTooltip = ({ active, payload }) => {
    if (!active || !payload || !payload.length) return null;
    const d = payload[0].payload;
    if (!d || d.rsi == null) return null;
    const status =
      d.rsi >= 70
        ? ["Overbought", DOWN]
        : d.rsi <= 30
        ? ["Oversold", UP]
        : ["Neutral", "#94a3b8"];
    return (
      <div style={{ ...S.tooltip, padding: "6px 10px" }}>
        <div style={{ marginBottom: 4, color: "#cbd5e1" }}>
          {labelFormatter(d.date)}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
          <span style={{ color: "#a78bfa" }}>RSI</span>
          <span style={{ color: "#e5e5e5" }}>{d.rsi.toFixed(1)}</span>
        </div>
        <div style={{ marginTop: 2, color: status[1] }}>{status[0]}</div>
      </div>
    );
  };

  const pillBase = {
    border: "1px solid #2a2a2a",
    borderRadius: 4,
    padding: "3px 10px",
    fontSize: 12,
    cursor: "pointer",
    fontFamily: "monospace",
    background: "none",
  };
  const rangePill = (active) => ({
    ...pillBase,
    ...(active
      ? { background: "#3730a3", color: "#e0e7ff", borderColor: "#4338ca" }
      : { color: "#64748b" }),
  });
  const ma20Pill = (active) => ({
    ...pillBase,
    ...(active
      ? { background: "#78350f", color: "#fde68a", borderColor: "#92400e" }
      : { color: "#64748b" }),
  });
  const ma50Pill = (active) => ({
    ...pillBase,
    ...(active
      ? { background: "#4c1d95", color: "#ddd6fe", borderColor: "#5b21b6" }
      : { color: "#64748b" }),
  });
  const volPill = (active) => ({
    ...pillBase,
    ...(active
      ? { background: "#155e75", color: "#cffafe", borderColor: "#0e7490" }
      : { color: "#64748b" }),
  });
  const candlePill = (active) => ({
    ...pillBase,
    ...(active
      ? { background: "#14532d", color: "#bbf7d0", borderColor: "#166534" }
      : { color: "#64748b" }),
  });
  const macdPill = (active) => ({
    ...pillBase,
    ...(active
      ? { background: "#0c4a6e", color: "#bae6fd", borderColor: "#075985" }
      : { color: "#64748b" }),
  });
  const rsiPill = (active) => ({
    ...pillBase,
    ...(active
      ? { background: "#581c87", color: "#e9d5ff", borderColor: "#6b21a8" }
      : { color: "#64748b" }),
  });

  // Headline percent-change stats (3M / YTD / 1Y), anchored to the latest close
  // and computed off the full history so they're independent of the chart range.
  const perfStats = (() => {
    if (!priceData.length) return [];
    const last = priceData[priceData.length - 1];
    const lastClose = last.close;
    const lastDate = new Date(last.date);
    // Close on the most recent trading day at or before a target date.
    const closeAtOrBefore = (target) => {
      for (let i = priceData.length - 1; i >= 0; i--) {
        if (new Date(priceData[i].date) <= target) return priceData[i].close;
      }
      return null;
    };
    const pct = (base) =>
      base == null || !base ? null : ((lastClose - base) / base) * 100;
    const d3m = new Date(lastDate.getTime() - 90 * 86400000);
    const d1y = new Date(lastDate.getTime() - 365 * 86400000);
    const yStart = new Date(lastDate.getFullYear(), 0, 1);
    return [
      ["1Y", pct(closeAtOrBefore(d1y))],
      ["YTD", pct(closeAtOrBefore(yStart))],
      ["3M", pct(closeAtOrBefore(d3m))],
    ];
  })();

  // Headline price: the live intraday quote when available, else the latest
  // stored close. Day % is that price vs the prior trading day's close.
  const lastClose = priceData.length
    ? priceData[priceData.length - 1].close
    : null;
  const prevClose =
    priceData.length >= 2 ? priceData[priceData.length - 2].close : null;
  const shownPrice = liveQuote != null ? liveQuote : lastClose;
  const dayPct =
    shownPrice != null && prevClose ? (shownPrice / prevClose - 1) * 100 : null;

  if (loading)
    return (
      <div
        style={{
          height: 400,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#64748b",
          fontFamily: "monospace",
        }}
      >
        Loading…
      </div>
    );
  if (!priceData.length)
    return (
      <div
        style={{
          height: 400,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#64748b",
        }}
      >
        No price history available
      </div>
    );

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 16,
          marginBottom: 12,
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            alignItems: "flex-start",
          }}
        >
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {["1M", "3M", "6M", "1Y", "3Y", "5Y"].map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              style={rangePill(r === range)}
            >
              {r}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          <button
            onClick={() => setShowCandles((v) => !v)}
            style={candlePill(showCandles)}
          >
            Candles
          </button>
          <button
            onClick={() => setShowMA20((v) => !v)}
            style={ma20Pill(showMA20)}
          >
            MA20
          </button>
          <button
            onClick={() => setShowMA50((v) => !v)}
            style={ma50Pill(showMA50)}
          >
            MA50
          </button>
          <button
            onClick={() => setShowVolume((v) => !v)}
            style={volPill(showVolume)}
          >
            Vol
          </button>
          <button
            onClick={() => setShowMACD((v) => !v)}
            style={macdPill(showMACD)}
          >
            MACD
          </button>
          <button
            onClick={() => setShowRSI((v) => !v)}
            style={rsiPill(showRSI)}
          >
            RSI
          </button>
        </div>
        <div
          style={{
            display: "flex",
            gap: 18,
            flexWrap: "wrap",
            fontFamily: "monospace",
            fontSize: 12,
          }}
        >
          {perfStats.map(([label, v]) => (
            <span
              key={label}
              style={{ display: "flex", gap: 6, alignItems: "baseline" }}
            >
              <span
                style={{
                  color: "#64748b",
                  textTransform: "uppercase",
                  fontSize: 11,
                  letterSpacing: 1,
                }}
              >
                {label}
              </span>
              <span
                style={{
                  color: v == null ? "#64748b" : v >= 0 ? "#22c55e" : "#ef4444",
                  fontWeight: 600,
                }}
              >
                {v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`}
              </span>
            </span>
          ))}
        </div>
        </div>
        {shownPrice != null && (
          <div style={{ textAlign: "right", flexShrink: 0 }}>
            <div
              style={{
                fontFamily: "DM Serif Display,serif",
                fontSize: 28,
                color: "#f1f5f9",
                lineHeight: 1.1,
              }}
            >
              {currSym(fcur)}
              {Number(
                fcur === "GBP" ? shownPrice / 100 : shownPrice
              ).toLocaleString("en-GB", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </div>
            {dayPct != null && (
              <div
                style={{
                  fontFamily: "monospace",
                  fontSize: 14,
                  fontWeight: 600,
                  marginTop: 2,
                  color: dayPct >= 0 ? "#22c55e" : "#ef4444",
                }}
              >
                {dayPct >= 0 ? "+" : "−"}
                {Math.abs(dayPct).toFixed(2)}%
              </div>
            )}
          </div>
        )}
      </div>
      <ResponsiveContainer width="100%" height={380}>
        <ComposedChart
          data={chartData}
          margin={{ top: 5, right: 10, bottom: 5, left: 0 }}
        >
          <defs>
            <linearGradient id="gPrice" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="date"
            tick={showMACD || showRSI ? false : { fontSize: 10 }}
            ticks={axisTicks}
            interval={0}
            tickFormatter={tickFormatter}
            height={showMACD || showRSI ? 4 : 30}
          />
          <YAxis
            tick={{ fontSize: 10 }}
            domain={priceDomain}
            tickFormatter={fmtAxisPrice}
            width={64}
          />
          {showVolume && (
            <YAxis
              yAxisId="vol"
              orientation="right"
              hide
              domain={[0, (dataMax) => (dataMax || 0) * 4]}
            />
          )}
          <Tooltip content={<ChartTooltip />} />
          {showVolume && (
            <Bar
              yAxisId="vol"
              dataKey="volume"
              fill="#0e7490"
              opacity={0.5}
              name="Volume"
              isAnimationActive={false}
            >
              {["1M", "3M", "6M"].includes(range) &&
                chartData.map((d, i) => (
                  <Cell
                    key={i}
                    fill={d.open != null && d.close < d.open ? DOWN : UP}
                  />
                ))}
            </Bar>
          )}
          {showCandles ? (
            <>
              {/* Invisible series so hovering registers (the candles are an SVG
                  overlay, not a data series); it feeds the data point to the
                  tooltip even when MAs and Volume are toggled off. */}
              <Line
                type="monotone"
                dataKey="close"
                stroke="transparent"
                dot={false}
                name="OHLC"
                isAnimationActive={false}
              />
              <Customized component={renderCandles} />
            </>
          ) : (
            <Area
              type="monotone"
              dataKey="close"
              stroke="#6366f1"
              fill="url(#gPrice)"
              strokeWidth={2}
              dot={false}
              name="Close"
            />
          )}
          {showMA20 && (
            <Line
              type="monotone"
              dataKey="ma20"
              stroke="#f59e0b"
              strokeWidth={1.5}
              dot={false}
              strokeDasharray="4 2"
              name="MA20"
              connectNulls={false}
            />
          )}
          {showMA50 && (
            <Line
              type="monotone"
              dataKey="ma50"
              stroke="#a855f7"
              strokeWidth={1.5}
              dot={false}
              name="MA50"
              connectNulls={false}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      {showMACD && (
        <ResponsiveContainer width="100%" height={150}>
          <ComposedChart
            data={chartData}
            margin={{ top: 4, right: 10, bottom: 5, left: 0 }}
          >
            <text
              x={70}
              y={12}
              fill="#64748b"
              fontSize={11}
              fontFamily="monospace"
            >
              MACD (12, 26, 9)
            </text>
            <XAxis
              dataKey="date"
              tick={showRSI ? false : { fontSize: 10 }}
              ticks={axisTicks}
              interval={0}
              tickFormatter={tickFormatter}
              height={showRSI ? 4 : 30}
            />
            <YAxis
              tick={{ fontSize: 10 }}
              tickFormatter={fmtAxisPrice}
              width={64}
            />
            <Tooltip content={<MacdTooltip />} />
            <ReferenceLine y={0} stroke="#334155" />
            <Bar dataKey="hist" name="Hist" isAnimationActive={false}>
              {chartData.map((d, i) => (
                <Cell key={i} fill={d.hist != null && d.hist < 0 ? DOWN : UP} />
              ))}
            </Bar>
            <Line
              type="monotone"
              dataKey="macd"
              stroke="#38bdf8"
              strokeWidth={1.5}
              dot={false}
              name="MACD"
              connectNulls={false}
            />
            <Line
              type="monotone"
              dataKey="signal"
              stroke="#f59e0b"
              strokeWidth={1.5}
              dot={false}
              name="Signal"
              connectNulls={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}
      {showRSI && (
        <ResponsiveContainer width="100%" height={130}>
          <ComposedChart
            data={chartData}
            margin={{ top: 4, right: 10, bottom: 5, left: 0 }}
          >
            <text
              x={70}
              y={12}
              fill="#64748b"
              fontSize={11}
              fontFamily="monospace"
            >
              RSI (14)
            </text>
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10 }}
              ticks={axisTicks}
              interval={0}
              tickFormatter={tickFormatter}
            />
            <YAxis
              tick={{ fontSize: 10 }}
              domain={[0, 100]}
              ticks={[30, 50, 70]}
              width={64}
            />
            <Tooltip content={<RsiTooltip />} />
            <ReferenceLine
              y={70}
              stroke={DOWN}
              strokeDasharray="4 2"
              label={{ value: "70", position: "right", fontSize: 9, fill: DOWN }}
            />
            <ReferenceLine
              y={30}
              stroke={UP}
              strokeDasharray="4 2"
              label={{ value: "30", position: "right", fontSize: 9, fill: UP }}
            />
            <Line
              type="monotone"
              dataKey="rsi"
              stroke="#a78bfa"
              strokeWidth={1.5}
              dot={false}
              name="RSI"
              connectNulls={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── Trending ──────────────────────────────────────────────────────────────────
// Prices are stored in pence (LSE convention); show as pounds like the watchlist.
const fmtPence = (p) => (p == null ? "—" : `£${(p / 100).toFixed(2)}`);

function StreakBadge({ days, up }) {
  return (
    <span
      style={{
        flexShrink: 0,
        background: up ? "#0d2318" : "#2a0d0d",
        color: up ? "#10b981" : "#ef4444",
        border: `1px solid ${up ? "#10b98133" : "#ef444433"}`,
        padding: "2px 7px",
        borderRadius: 2,
        fontSize: 11,
        fontFamily: "monospace",
        fontWeight: 700,
        minWidth: 42,
        textAlign: "center",
      }}
    >
      {up ? "▲" : "▼"} {days}d
    </span>
  );
}

function TrendingList({ title, accent, up, items, selected, onSelect, height }) {
  return (
    <div
      style={{
        ...S.card,
        padding: 0,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        height,
      }}
    >
      <div
        style={{
          padding: "10px 14px",
          borderBottom: "1px solid #2a2a2a",
          color: accent,
          fontSize: 11,
          fontFamily: "monospace",
          textTransform: "uppercase",
          letterSpacing: 1,
          fontWeight: 700,
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>{title}</span>
        <span style={{ color: "#555" }}>{items.length}</span>
      </div>
      <div
        style={{
          overflowY: "auto",
          flex: height && height !== "auto" ? "1 1 auto" : "none",
          maxHeight: height && height !== "auto" ? "none" : "calc(100vh - 220px)",
          minHeight: 0,
        }}
      >
        {items.length === 0 ? (
          <div
            style={{
              padding: 24,
              color: "#555",
              fontSize: 12,
              fontFamily: "monospace",
              textAlign: "center",
            }}
          >
            None on a 3+ day run
          </div>
        ) : (
          items.map((it) => {
            const active = it.symbol === selected;
            return (
              <button
                key={it.symbol}
                onClick={() => onSelect(it.symbol)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  width: "100%",
                  textAlign: "left",
                  background: active ? "#1f1200" : "none",
                  border: "none",
                  borderBottom: "1px solid #1a1a1a",
                  borderLeft: `2px solid ${active ? accent : "transparent"}`,
                  padding: "10px 12px",
                  cursor: "pointer",
                }}
              >
                <StreakBadge days={it.streak} up={up} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      color: "#e5e5e5",
                      fontSize: 12,
                      fontFamily: "monospace",
                      fontWeight: 700,
                    }}
                  >
                    {it.symbol.replace(".L", "")}
                  </div>
                  <div
                    style={{
                      color: "#64748b",
                      fontSize: 10,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {it.name}
                  </div>
                </div>
                <div style={{ textAlign: "right", flexShrink: 0 }}>
                  <div
                    style={{
                      color: "#f1f5f9",
                      fontSize: 12,
                      fontFamily: "monospace",
                      fontWeight: 700,
                    }}
                  >
                    {fmtPence(it.price)}
                  </div>
                  <div
                    style={{
                      color: "#94a3b8",
                      fontSize: 11,
                      fontFamily: "monospace",
                      marginTop: 1,
                    }}
                  >
                    {fmt(it.market_cap, "currency", it.currency)}
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

function TrendingProfile({ symbol, onOpenFull }) {
  const [meta, setMeta] = useState(null);
  const [snap, setSnap] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const enc = encodeURIComponent(symbol);
    Promise.all([
      fetch(`${API}/company?symbol=${enc}`).then((r) => r.json()),
      fetch(`${API}/snapshot?symbol=${enc}`).then((r) => r.json()),
    ])
      .then(([m, s]) => {
        setMeta(m);
        setSnap(s);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [symbol]);

  if (loading) return <div style={S.loading}>Loading {symbol}…</div>;
  if (!snap) return <div style={S.loading}>No data for {symbol}</div>;

  const fcur = meta?.financial_currency || "GBP";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h2
            style={{
              margin: 0,
              fontFamily: "DM Serif Display,serif",
              fontSize: 22,
              color: "#f1f5f9",
            }}
          >
            {meta?.name || symbol}
          </h2>
          <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
            {[symbol, meta?.sector, meta?.ftse_index]
              .filter(Boolean)
              .map((t) => (
                <span key={t} style={S.badge}>
                  {t}
                </span>
              ))}
          </div>
        </div>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <div
            style={{
              fontSize: 22,
              fontFamily: "DM Serif Display,serif",
              color: "#f1f5f9",
            }}
          >
            {fmt(snap.market_cap, "currency", fcur)}
          </div>
          <div style={{ fontSize: 11, color: "#64748b" }}>Market Cap</div>
          <button onClick={() => onOpenFull(symbol)} style={S.backBtn}>
            Open full view →
          </button>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill,minmax(92px,1fr))",
          gap: 6,
        }}
      >
        <MetricCard compact label="P/E" value={fmt(snap.price_to_earnings, "ratio")} />
        <MetricCard compact label="P/B" value={fmt(snap.price_to_book, "ratio")} />
        <MetricCard
          compact
          label="ROE"
          value={fmt(snap.roe, "pct")}
          color={gc(snap.roe)}
        />
        <MetricCard
          compact
          label="Rev Growth"
          value={fmt(snap.revenue_growth, "pct")}
          color={gc(snap.revenue_growth)}
        />
        <MetricCard
          compact
          label="Net Margin"
          value={fmt(snap.net_income_margin, "pct")}
          color={gc(snap.net_income_margin)}
        />
        <MetricCard
          compact
          label="Risk"
          value={snap.risk_score == null ? "—" : snap.risk_score}
          color={
            snap.risk_score == null
              ? "#94a3b8"
              : snap.risk_score <= 3
                ? "#10b981"
                : snap.risk_score <= 6
                  ? "#f59e0b"
                  : "#ef4444"
          }
        />
      </div>

      <PriceChart symbol={symbol} />
    </div>
  );
}

function TrendingTab({ onSelect }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState(null);
  const isMobile = useIsMobile();

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/trending`)
      .then((r) => r.json())
      .then((d) => {
        setData(d);
        setSel(
          (cur) => cur || d.risers?.[0]?.symbol || d.fallers?.[0]?.symbol || null,
        );
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div style={S.loading}>Loading trending stocks…</div>;

  const risers = data?.risers || [];
  const fallers = data?.fallers || [];

  // Shared height for the three top boxes so the Risers/Fallers lists and the
  // profile (graph) box bottoms line up. The News box sits below the profile.
  const colH = isMobile ? "auto" : "calc(100vh - 200px)";

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h1
          style={{
            margin: 0,
            fontFamily: "DM Serif Display,serif",
            fontSize: 26,
            color: "#f1f5f9",
          }}
        >
          Trending <span style={{ color: "#64748b" }}>— Risers and Fallers</span>
        </h1>
        <div style={{ color: "#64748b", fontSize: 12, marginTop: 4 }}>
          Stocks on a run of 3 or more consecutive up or down days, ranked by
          streak length.
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile
            ? "1fr"
            : "minmax(210px,1fr) minmax(210px,1fr) minmax(360px,1.5fr)",
          gap: 16,
          alignItems: "start",
        }}
      >
        <TrendingList
          title="Risers"
          accent="#10b981"
          up
          items={risers}
          selected={sel}
          onSelect={setSel}
          height={colH}
        />
        <TrendingList
          title="Fallers"
          accent="#ef4444"
          up={false}
          items={fallers}
          selected={sel}
          onSelect={setSel}
          height={colH}
        />
        <div>
          {sel ? (
            <div
              style={{
                ...S.card,
                height: colH,
                overflowY: isMobile ? "visible" : "auto",
                minHeight: 0,
              }}
            >
              <TrendingProfile symbol={sel} onOpenFull={onSelect} />
            </div>
          ) : (
            <div style={{ ...S.card, ...S.loading }}>
              Select a stock to see its profile and news.
            </div>
          )}
        </div>
      </div>

      {/* Full-width news below the three columns */}
      {sel && (
        <div style={{ ...S.card, marginTop: 16 }}>
          <h2
            style={{
              margin: "0 0 16px",
              fontFamily: "DM Serif Display,serif",
              fontSize: 20,
              color: "#f1f5f9",
            }}
          >
            News{" "}
            <span style={{ color: "#64748b", fontSize: 15 }}>
              — {sel.replace(".L", "")}
            </span>
          </h2>
          <NewsTab symbol={sel} split />
        </div>
      )}
    </div>
  );
}

// ── Screener ──────────────────────────────────────────────────────────────────
const EMPTY_FILTERS = {
  sector: "",
  exclude_sectors: "",
  ftse_index: "",
  min_market_cap: "",
  max_pe: "",
  min_roe: "",
  min_revenue_growth: "",
  consensus: "",
  min_upside_pct: "",
};
const EMPTY_MODES = {
  min_market_cap: "",
  max_pe: "",
  min_roe: "",
  min_revenue_growth: "",
};
const EMPTY_SCORE_FILTERS = {
  min_momentum: "",
  min_quality: "",
  min_piotroski: "",
  max_risk: "",
  max_pegy: "",
};

// [label, rightAlign, sortKey]
const FUND_COLS_BASE = [
  ["Symbol", false, "symbol"],
  ["Name", false, "name"],
  ["Sector", false, "sector"],
  ["Index", false, "ftse_index"],
  ["Mkt Cap", true, "market_cap"],
  ["P/E", true, "price_to_earnings"],
  ["P/B", true, "price_to_book"],
  ["ROE", true, "roe"],
  ["Rev Growth", true, "revenue_growth"],
  ["D/E", true, "debt_to_equity"],
  ["PEGY", true, "pegy"],
];
const FUND_COLS = [
  ...FUND_COLS_BASE,
  ["Momentum", true, "momentum_score"],
  ["Quality", true, "quality_score"],
  ["Value", true, "piotroski_score"],
  ["Risk", true, "risk_score"],
];
const ANALYST_COLS = [
  ["Symbol", false, "symbol"],
  ["Name", false, "name"],
  ["Sector", false, "sector"],
  ["Index", false, "ftse_index"],
  ["Mkt Cap", true, "market_cap"],
  ["Consensus", false, "consensus"],
  ["Upside", true, "upside_pct"],
  ["Buy%", true, "buy_pct"],
  ["# Analysts", true, "total_analysts"],
  ["Rev Score", true, "revision_score"],
];

function SectorDropdown({
  sectors,
  value,
  excluded,
  onSelect,
  onToggleExclude,
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const label = value
    ? value
    : excluded.length
      ? `All Sectors (−${excluded.length})`
      : "All Sectors";

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          ...S.select,
          minWidth: 170,
          textAlign: "left",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </span>
        <span style={{ fontSize: 8, opacity: 0.6 }}>▾</span>
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            marginTop: 4,
            background: "#141414",
            border: "1px solid #2a2a2a",
            borderRadius: 4,
            minWidth: 260,
            zIndex: 200,
            boxShadow: "0 8px 24px rgba(0,0,0,0.8)",
            maxHeight: 360,
            overflowY: "auto",
          }}
        >
          <div
            onClick={() => {
              onSelect("");
              setOpen(false);
            }}
            style={{
              padding: "8px 12px",
              cursor: "pointer",
              fontFamily: "monospace",
              fontSize: 12,
              color: value === "" ? "#f97316" : "#cbd5e1",
              borderBottom: "1px solid #1f1f1f",
            }}
          >
            All Sectors
          </div>
          {sectors.map((s) => {
            const isExcluded = excluded.includes(s);
            const isSelected = value === s;
            return (
              <div
                key={s}
                style={{
                  display: "flex",
                  alignItems: "stretch",
                  borderBottom: "1px solid #1f1f1f",
                }}
              >
                <div
                  onClick={() => {
                    if (!isExcluded) {
                      onSelect(s);
                      setOpen(false);
                    }
                  }}
                  style={{
                    flex: 1,
                    padding: "8px 8px 8px 12px",
                    cursor: isExcluded ? "not-allowed" : "pointer",
                    fontFamily: "monospace",
                    fontSize: 12,
                    color: isSelected
                      ? "#f97316"
                      : isExcluded
                        ? "#555"
                        : "#cbd5e1",
                    textDecoration: isExcluded ? "line-through" : "none",
                  }}
                >
                  {s}
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleExclude(s);
                  }}
                  title={isExcluded ? "Stop excluding" : "Exclude this sector"}
                  style={{
                    background: "none",
                    border: "none",
                    padding: "0 12px",
                    cursor: "pointer",
                    fontSize: 13,
                    lineHeight: 1,
                    color: isExcluded ? "#ef4444" : "#555",
                  }}
                >
                  ⊘
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function StarButton({ active, onClick }) {
  return (
    <button
      onClick={onClick}
      title={active ? "Remove from watchlist" : "Add to watchlist"}
      style={{
        background: "none",
        border: "none",
        cursor: "pointer",
        padding: "0 6px 0 0",
        color: active ? "#f59e0b" : "#3a3a3a",
        fontSize: 14,
        lineHeight: 1,
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.color = "#7c6a3a";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.color = "#3a3a3a";
      }}
    >
      {active ? "★" : "☆"}
    </button>
  );
}

function Screener({
  onSelect,
  highlightSymbol,
  watchlist,
  onToggleWatchlist,
}) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [selectModes, setSelectModes] = useState(EMPTY_MODES);
  const [filterOpts, setFilterOpts] = useState({ sectors: [], countries: [] });
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [scoreFilters, setScoreFilters] = useState(EMPTY_SCORE_FILTERS);
  const [tableView, setTableView] = useState("fundamentals");
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState("desc");

  useEffect(() => {
    fetch(`${API}/filters`)
      .then((r) => r.json())
      .then(setFilterOpts);
    runScreener(EMPTY_FILTERS);
  }, []);

  useEffect(() => {
    if (highlightSymbol) {
      const el = document.getElementById("row-" + highlightSymbol);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightSymbol, results]);

  const runScreener = useCallback((f) => {
    setLoading(true);
    const p = new URLSearchParams();
    if (f.sector) p.set("sector", f.sector);
    if (f.exclude_sectors) p.set("exclude_sectors", f.exclude_sectors);
    if (f.country) p.set("country", f.country);
    if (f.ftse_index) p.set("ftse_index", f.ftse_index);
    if (f.min_market_cap) p.set("min_market_cap", f.min_market_cap);
    if (f.max_pe) p.set("max_pe", f.max_pe);
    if (f.min_roe) p.set("min_roe", f.min_roe);
    if (f.min_revenue_growth) p.set("min_revenue_growth", f.min_revenue_growth);
    if (f.consensus) p.set("consensus", f.consensus);
    if (f.min_upside_pct) p.set("min_upside_pct", f.min_upside_pct);
    p.set("limit", 1000);
    fetch(`${API}/screener?${p}`)
      .then((r) => r.json())
      .then((d) => {
        setResults(Array.isArray(d) ? d : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const update = (k, v) => {
    const f = { ...filters, [k]: v };
    setFilters(f);
    runScreener(f);
  };

  const updateMany = (patch) => {
    const f = { ...filters, ...patch };
    setFilters(f);
    runScreener(f);
  };

  const excludedSectors = filters.exclude_sectors
    ? filters.exclude_sectors.split(",").filter(Boolean)
    : [];

  const toggleExcludeSector = (s) => {
    const set = new Set(excludedSectors);
    const wasExcluded = set.has(s);
    if (wasExcluded) set.delete(s);
    else set.add(s);
    const patch = { exclude_sectors: Array.from(set).join(",") };
    if (!wasExcluded && filters.sector === s) patch.sector = "";
    updateMany(patch);
  };

  // Called when a HybridSelect dropdown changes (preset or 'custom')
  const handleSelectMode = (key, mode) => {
    setSelectModes((m) => ({ ...m, [key]: mode }));
    if (mode !== "custom") update(key, mode); // preset value — apply immediately
    // custom: just show the input, don't re-run until user commits a value
  };

  // Called when a custom input value is committed (blur / Enter)
  const handleCustomCommit = (key, rawValue, parse) => {
    const apiValue = String(parse(rawValue));
    update(key, apiValue);
  };

  const clearFilters = () => {
    setFilters(EMPTY_FILTERS);
    setSelectModes(EMPTY_MODES);
    setScoreFilters(EMPTY_SCORE_FILTERS);
    runScreener(EMPTY_FILTERS);
  };

  const updateScore = (k, v) => setScoreFilters((sf) => ({ ...sf, [k]: v }));

  const watchlistSet =
    watchlist instanceof Set ? watchlist : new Set(watchlist || []);
  const displayed = results.filter((r) => {
    const sf = scoreFilters;
    if (
      sf.min_momentum &&
      (r.momentum_score == null || r.momentum_score < +sf.min_momentum)
    )
      return false;
    if (
      sf.min_quality &&
      (r.quality_score == null || r.quality_score < +sf.min_quality)
    )
      return false;
    if (
      sf.min_piotroski &&
      (r.piotroski_score == null || r.piotroski_score < +sf.min_piotroski)
    )
      return false;
    if (sf.max_risk && (r.risk_score == null || r.risk_score > +sf.max_risk))
      return false;
    if (sf.max_pegy && (r.pegy == null || r.pegy > +sf.max_pegy))
      return false;
    return true;
  });

  const hasActiveFilters =
    Object.values(filters).some((v) => v !== "") ||
    Object.values(scoreFilters).some((v) => v !== "");
  const hasAdvancedFilters =
    filters.max_pe ||
    filters.min_roe ||
    filters.min_revenue_growth ||
    scoreFilters.min_momentum ||
    scoreFilters.min_quality ||
    scoreFilters.min_piotroski ||
    scoreFilters.max_risk ||
    scoreFilters.max_pegy;

  const handleSort = (key) => {
    if (sortCol === key) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else {
      setSortCol(key);
      setSortDir("desc");
    }
  };

  const lookup = (r, key) => r[key];
  const sorted =
    sortCol == null
      ? displayed
      : [...displayed].sort((a, b) => {
          const av = lookup(a, sortCol),
            bv = lookup(b, sortCol);
          if (av == null && bv == null) return 0;
          if (av == null) return 1;
          if (bv == null) return -1;
          if (typeof av === "string")
            return sortDir === "asc"
              ? av.localeCompare(bv)
              : bv.localeCompare(av);
          return sortDir === "asc" ? av - bv : bv - av;
        });

  return (
    <div>
      <h2
        style={{
          fontFamily: "DM Serif Display,serif",
          fontSize: 26,
          color: "#f1f5f9",
          marginTop: 0,
          marginBottom: 4,
        }}
      >
        UK Stock Screener
      </h2>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 20,
        }}
      >
        <div style={{ fontSize: 13, color: "#64748b" }}>
          {`${filters.ftse_index || "All indices"}${filters.sector ? ` · ${filters.sector}` : ""}`}
        </div>
        <div
          style={{
            background: "#334155",
            color: "#cbd5e1",
            borderRadius: 20,
            padding: "2px 12px",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {displayed.length !== results.length
            ? `${displayed.length} / ${results.length}`
            : displayed.length}{" "}
          companies
        </div>
      </div>

      <div
        style={{
          display: "flex",
          gap: 10,
          flexWrap: "wrap",
          marginBottom: 8,
          alignItems: "center",
        }}
      >
        <SectorDropdown
          sectors={filterOpts.sectors}
          value={filters.sector}
          excluded={excludedSectors}
          onSelect={(v) => update("sector", v)}
          onToggleExclude={toggleExcludeSector}
        />
        <select
          style={S.select}
          value={filters.ftse_index}
          onChange={(e) => update("ftse_index", e.target.value)}
        >
          <option value="">FTSE Market</option>
          <option value="FTSE 100">FTSE 100</option>
          <option value="FTSE 250">FTSE 250</option>
          <option value="FTSE 350">FTSE 350</option>
          <option value="FTSE SmallCap">FTSE SmallCap</option>
          <option value="FTSE AIM 100">AIM 100</option>
        </select>
        <HybridSelect
          selectMode={selectModes.min_market_cap}
          onSelectChange={(mode) => handleSelectMode("min_market_cap", mode)}
          onCustomCommit={(v) =>
            handleCustomCommit("min_market_cap", v, (n) => Math.round(n * 1e9))
          }
          placeholder="£B"
          inputWidth={70}
        >
          <option value="">Any Market Cap</option>
          <option value="1000000000">£1B+</option>
          <option value="10000000000">£10B+</option>
          <option value="50000000000">£50B+</option>
        </HybridSelect>
        <button
          onClick={() => setShowAdvanced((v) => !v)}
          style={{
            ...S.select,
            cursor: "pointer",
            color: showAdvanced || hasAdvancedFilters ? "#f97316" : "#888",
            borderColor: hasAdvancedFilters ? "#f97316" : "#2a2a2a",
          }}
        >
          Advanced {showAdvanced ? "▲" : "▼"}
          {hasAdvancedFilters ? " ●" : ""}
        </button>
        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            style={{
              ...S.select,
              cursor: "pointer",
              color: "#ef4444",
              borderColor: "#3a1a1a",
            }}
          >
            Clear filters ✕
          </button>
        )}
      </div>

      {showAdvanced && (
        <div
          style={{
            display: "flex",
            gap: 10,
            flexWrap: "wrap",
            marginBottom: 8,
          }}
        >
          <select
            style={S.select}
            value={scoreFilters.min_momentum}
            onChange={(e) => updateScore("min_momentum", e.target.value)}
          >
            <option value="">Momentum</option>
            <option value="4">Mom ≥ 4</option>
            <option value="6">Mom ≥ 6</option>
            <option value="8">Mom ≥ 8</option>
          </select>
          <select
            style={S.select}
            value={scoreFilters.min_quality}
            onChange={(e) => updateScore("min_quality", e.target.value)}
          >
            <option value="">Quality</option>
            <option value="4">Quality ≥ 4</option>
            <option value="6">Quality ≥ 6</option>
            <option value="8">Quality ≥ 8</option>
          </select>
          <select
            style={S.select}
            value={scoreFilters.min_piotroski}
            onChange={(e) => updateScore("min_piotroski", e.target.value)}
          >
            <option value="">Value</option>
            <option value="4">Value ≥ 4</option>
            <option value="6">Value ≥ 6</option>
            <option value="8">Value ≥ 8</option>
          </select>
          <select
            style={S.select}
            value={scoreFilters.max_risk}
            onChange={(e) => updateScore("max_risk", e.target.value)}
          >
            <option value="">Risk</option>
            <option value="3">Risk ≤ 3</option>
            <option value="5">Risk ≤ 5</option>
            <option value="7">Risk ≤ 7</option>
          </select>
          <select
            style={S.select}
            value={scoreFilters.max_pegy}
            onChange={(e) => updateScore("max_pegy", e.target.value)}
          >
            <option value="">PEGY</option>
            <option value="1">PEGY ≤ 1</option>
            <option value="1.5">PEGY ≤ 1.5</option>
            <option value="2">PEGY ≤ 2</option>
          </select>
          <HybridSelect
            selectMode={selectModes.max_pe}
            onSelectChange={(mode) => handleSelectMode("max_pe", mode)}
            onCustomCommit={(v) => handleCustomCommit("max_pe", v, (n) => n)}
            placeholder="P/E"
            inputWidth={65}
          >
            <option value="">Any P/E</option>
            <option value="15">P/E &lt; 15</option>
            <option value="25">P/E &lt; 25</option>
            <option value="40">P/E &lt; 40</option>
          </HybridSelect>
          <HybridSelect
            selectMode={selectModes.min_roe}
            onSelectChange={(mode) => handleSelectMode("min_roe", mode)}
            onCustomCommit={(v) =>
              handleCustomCommit("min_roe", v, (n) => n / 100)
            }
            placeholder="ROE %"
            inputWidth={75}
          >
            <option value="">Any ROE</option>
            <option value="0.1">ROE &gt; 10%</option>
            <option value="0.15">ROE &gt; 15%</option>
            <option value="0.2">ROE &gt; 20%</option>
          </HybridSelect>
          <HybridSelect
            selectMode={selectModes.min_revenue_growth}
            onSelectChange={(mode) =>
              handleSelectMode("min_revenue_growth", mode)
            }
            onCustomCommit={(v) =>
              handleCustomCommit("min_revenue_growth", v, (n) => n / 100)
            }
            placeholder="Growth %"
            inputWidth={85}
          >
            <option value="">Any Rev Growth</option>
            <option value="0.05">Rev Growth &gt; 5%</option>
            <option value="0.1">Rev Growth &gt; 10%</option>
            <option value="0.2">Rev Growth &gt; 20%</option>
          </HybridSelect>
          <select
            style={S.select}
            value={filters.consensus}
            onChange={(e) => update("consensus", e.target.value)}
          >
            <option value="">All Consensus</option>
            <option value="Buy">Buy</option>
            <option value="Hold">Hold</option>
            <option value="Sell">Sell</option>
          </select>
          <select
            style={S.select}
            value={filters.min_upside_pct}
            onChange={(e) => update("min_upside_pct", e.target.value)}
          >
            <option value="">Any Upside</option>
            <option value="5">Upside &gt; 5%</option>
            <option value="10">Upside &gt; 10%</option>
            <option value="20">Upside &gt; 20%</option>
          </select>
        </div>
      )}

      {excludedSectors.length > 0 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
            alignItems: "center",
            marginBottom: 8,
          }}
        >
          <span
            style={{
              fontFamily: "monospace",
              fontSize: 10,
              color: "#666",
              textTransform: "uppercase",
              letterSpacing: 1,
            }}
          >
            Excluded:
          </span>
          {excludedSectors.map((s) => (
            <span
              key={s}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                background: "#2a0d0d",
                color: "#fca5a5",
                border: "1px solid #4a1c1c",
                padding: "2px 4px 2px 8px",
                borderRadius: 2,
                fontSize: 11,
                fontFamily: "monospace",
              }}
            >
              {s}
              <button
                onClick={() => toggleExcludeSector(s)}
                title="Remove exclusion"
                style={{
                  background: "none",
                  border: "none",
                  color: "#fca5a5",
                  cursor: "pointer",
                  padding: "0 4px",
                  fontSize: 12,
                  lineHeight: 1,
                }}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}

      {/* View toggle */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {["fundamentals", "analysts"].map((v) => (
          <button
            key={v}
            onClick={() => setTableView(v)}
            style={{
              padding: "5px 14px",
              borderRadius: 2,
              border: "1px solid",
              fontSize: 11,
              fontFamily: "monospace",
              cursor: "pointer",
              textTransform: "uppercase",
              letterSpacing: 0.5,
              background: tableView === v ? "#f97316" : "#141414",
              color: tableView === v ? "#000" : "#666",
              borderColor: tableView === v ? "#f97316" : "#2a2a2a",
              fontWeight: tableView === v ? 700 : 400,
            }}
          >
            {v}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={S.loading}>Screening…</div>
      ) : (
        <div
          style={{
            overflow: "auto",
            maxHeight: "calc(100vh - 245px)",
            scrollbarGutter: "stable",
            // Snap to the nearest row when scrolling settles so rows aren't left
            // half cut-off. "proximity" only snaps near a row, so it never fights
            // an active scroll. scrollPaddingTop clears the sticky header.
            scrollSnapType: "y proximity",
            scrollPaddingTop: 29,
          }}
        >
          <table
            style={{
              ...S.table,
              minWidth: tableView === "analysts" ? 700 : 900,
            }}
          >
            <thead>
              <tr>
                {(tableView === "fundamentals" ? FUND_COLS : ANALYST_COLS).map(
                  ([h, num, key]) => (
                    <th
                      key={h}
                      onClick={() => handleSort(key)}
                      style={{
                        ...S.th,
                        textAlign: num ? "right" : "left",
                        cursor: "pointer",
                        userSelect: "none",
                        color: sortCol === key ? "#fb923c" : "#f97316",
                      }}
                    >
                      {h}
                      {sortCol === key ? (sortDir === "desc" ? " ▼" : " ▲") : ""}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => {
                const isHighlighted = r.symbol === highlightSymbol;
                const baseBg = isHighlighted
                  ? "#2d1e00"
                  : i % 2 === 0
                    ? "#1e293b"
                    : "#162032";
                return (
                  <tr
                    key={r.symbol}
                    id={"row-" + r.symbol}
                    onClick={() => onSelect(r.symbol)}
                    style={{
                      background: baseBg,
                      cursor: "pointer",
                      scrollSnapAlign: "start",
                      boxShadow: isHighlighted
                        ? "inset 3px 0 0 #f97316"
                        : "none",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.background = "#334155")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.background = baseBg)
                    }
                  >
                    {/* Shared columns */}
                    <td
                      style={{
                        ...S.td,
                        fontFamily: "monospace",
                        fontWeight: 700,
                        color: watchlistSet.has(r.symbol)
                          ? "#f59e0b"
                          : "#818cf8",
                      }}
                    >
                      <span
                        style={{ display: "inline-flex", alignItems: "center" }}
                      >
                        <StarButton
                          active={watchlistSet.has(r.symbol)}
                          onClick={(e) => {
                            e.stopPropagation();
                            onToggleWatchlist && onToggleWatchlist(r.symbol);
                          }}
                        />
                        {r.symbol.replace(".L", "")}
                      </span>
                    </td>
                    <td style={S.td}>{r.name?.slice(0, 26)}</td>
                    <td style={{ ...S.td, color: "#64748b" }}>
                      {r.sector?.slice(0, 18)}
                    </td>
                    <td style={{ ...S.td, color: "#64748b" }}>
                      {r.ftse_index?.replace("FTSE ", "")}
                    </td>
                    <td style={S.tdNum}>
                      {fmt(r.market_cap, "currency", r.financial_currency)}
                    </td>
                    {tableView === "fundamentals" ? (
                      <>
                        <td
                          style={{
                            ...S.tdNum,
                            color:
                              r.price_to_earnings < 15
                                ? "#10b981"
                                : r.price_to_earnings > 40
                                  ? "#ef4444"
                                  : "#ccc",
                          }}
                        >
                          {fmt(r.price_to_earnings, "ratio")}
                        </td>
                        <td style={S.tdNum}>{fmt(r.price_to_book, "ratio")}</td>
                        <td style={{ ...S.tdNum, color: gc(r.roe) }}>
                          {fmt(r.roe, "pct")}
                        </td>
                        <td style={{ ...S.tdNum, color: gc(r.revenue_growth) }}>
                          {fmt(r.revenue_growth, "pct")}
                        </td>
                        <td
                          style={{
                            ...S.tdNum,
                            color: r.debt_to_equity > 2 ? "#ef4444" : "#ccc",
                          }}
                        >
                          {fmt(r.debt_to_equity, "ratio")}
                        </td>
                        <td
                          style={{
                            ...S.tdNum,
                            color:
                              r.pegy == null
                                ? "#444"
                                : r.pegy < 1
                                  ? "#10b981"
                                  : r.pegy <= 2
                                    ? "#f59e0b"
                                    : "#ef4444",
                          }}
                        >
                          {r.pegy ?? "—"}
                        </td>
                        <td
                          style={{
                            ...S.tdNum,
                            color:
                              r.momentum_score == null
                                ? "#444"
                                : r.momentum_score >= 7
                                  ? "#10b981"
                                  : r.momentum_score >= 4
                                    ? "#f59e0b"
                                    : "#ef4444",
                            fontWeight: 700,
                          }}
                        >
                          {r.momentum_score ?? "—"}
                        </td>
                        <td
                          style={{
                            ...S.tdNum,
                            color:
                              r.quality_score == null
                                ? "#444"
                                : r.quality_score >= 7
                                  ? "#10b981"
                                  : r.quality_score >= 4
                                    ? "#f59e0b"
                                    : "#ef4444",
                            fontWeight: 700,
                          }}
                        >
                          {r.quality_score ?? "—"}
                        </td>
                        <td
                          style={{
                            ...S.tdNum,
                            color:
                              r.piotroski_score == null
                                ? "#444"
                                : r.piotroski_score >= 7
                                  ? "#10b981"
                                  : r.piotroski_score >= 4
                                    ? "#f59e0b"
                                    : "#ef4444",
                            fontWeight: 700,
                          }}
                        >
                          {r.piotroski_score ?? "—"}
                        </td>
                        <td
                          style={{
                            ...S.tdNum,
                            color:
                              r.risk_score == null
                                ? "#444"
                                : r.risk_score <= 3
                                  ? "#10b981"
                                  : r.risk_score <= 6
                                    ? "#f59e0b"
                                    : "#ef4444",
                            fontWeight: 700,
                          }}
                        >
                          {r.risk_score ?? "—"}
                        </td>
                      </>
                    ) : (
                      <>
                        <td style={S.td}>
                          {r.consensus ? (
                            <span
                              style={{
                                ...({
                                  Buy: {
                                    background: "#0d3320",
                                    color: "#10b981",
                                  },
                                  Hold: {
                                    background: "#1a1400",
                                    color: "#f59e0b",
                                  },
                                  Sell: {
                                    background: "#2a0d0d",
                                    color: "#ef4444",
                                  },
                                }[r.consensus] || {}),
                                padding: "2px 7px",
                                borderRadius: 2,
                                fontSize: 9,
                                fontFamily: "monospace",
                                fontWeight: 700,
                              }}
                            >
                              {r.consensus}
                            </span>
                          ) : (
                            <span style={{ color: "#444" }}>—</span>
                          )}
                        </td>
                        <td
                          style={{
                            ...S.tdNum,
                            color:
                              r.upside_pct > 0
                                ? "#10b981"
                                : r.upside_pct < 0
                                  ? "#ef4444"
                                  : "#555",
                          }}
                        >
                          {r.upside_pct != null
                            ? `${r.upside_pct >= 0 ? "+" : ""}${r.upside_pct.toFixed(1)}%`
                            : "—"}
                        </td>
                        <td
                          style={{
                            ...S.tdNum,
                            color:
                              r.buy_pct != null
                                ? r.buy_pct >= 60
                                  ? "#10b981"
                                  : r.buy_pct >= 40
                                    ? "#f59e0b"
                                    : "#ef4444"
                                : "#444",
                          }}
                        >
                          {r.buy_pct != null ? `${r.buy_pct.toFixed(0)}%` : "—"}
                        </td>
                        <td
                          style={{
                            ...S.tdNum,
                            color:
                              r.total_analysts != null ? "#94a3b8" : "#444",
                          }}
                        >
                          {r.total_analysts ?? "—"}
                        </td>
                        <td
                          style={{
                            ...S.tdNum,
                            color:
                              r.revision_score == null
                                ? "#444"
                                : r.revision_score > 0
                                  ? "#10b981"
                                  : r.revision_score < 0
                                    ? "#ef4444"
                                    : "#f59e0b",
                            fontWeight: 700,
                          }}
                        >
                          {r.revision_score != null
                            ? r.revision_score > 0
                              ? `+${r.revision_score}`
                              : r.revision_score
                            : "—"}
                        </td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── App Shell ─────────────────────────────────────────────────────────────────
export default function App() {
  const isMobile = useIsMobile();
  const isNarrow = useIsNarrowDesktop();
  const [page, setPage] = useState(() => {
    // Deep-link support: emails point at /?tab=subscribe.
    if (typeof window === "undefined") return "screener";
    const t = new URLSearchParams(window.location.search).get("tab");
    // The Markets sub-pages were merged into one page; keep old links working.
    if (["fear-greed", "cross-asset", "rotation", "breadth"].includes(t))
      return "markets";
    return t || "screener";
  }); // screener | watchlist | markets | signals | company | subscribe
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const [selectedTab, setSelectedTab] = useState(null);
  const [watchlists, setWatchlists] = useState(() => loadWatchlists());
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    saveWatchlists(watchlists);
  }, [watchlists]);

  // The Screener ★ always toggles membership of the default list.
  const defaultMembers = useMemo(
    () => new Set(watchlists.members[DEFAULT_LIST_ID] || []),
    [watchlists],
  );
  const toggleWatchlist = useCallback((symbol) => {
    setWatchlists((prev) => {
      const cur = prev.members[DEFAULT_LIST_ID] || [];
      const next = cur.includes(symbol)
        ? cur.filter((s) => s !== symbol)
        : [...cur, symbol];
      return { ...prev, members: { ...prev.members, [DEFAULT_LIST_ID]: next } };
    });
  }, []);

  // ── Watchlist management (used by the Watchlist page) ───────────────────────
  const createWatchlist = useCallback((name) => {
    const id = genListId();
    setWatchlists((prev) => ({
      lists: [...prev.lists, { id, name }],
      members: { ...prev.members, [id]: [] },
    }));
    return id;
  }, []);

  const renameWatchlist = useCallback((id, name) => {
    setWatchlists((prev) => ({
      ...prev,
      lists: prev.lists.map((l) => (l.id === id ? { ...l, name } : l)),
    }));
  }, []);

  const deleteWatchlist = useCallback((id) => {
    if (id === DEFAULT_LIST_ID) return; // the default list is permanent
    setWatchlists((prev) => {
      const members = { ...prev.members };
      delete members[id];
      return { lists: prev.lists.filter((l) => l.id !== id), members };
    });
  }, []);

  const addToWatchlist = useCallback((id, symbol) => {
    setWatchlists((prev) => {
      const cur = prev.members[id] || [];
      if (cur.includes(symbol)) return prev;
      return { ...prev, members: { ...prev.members, [id]: [...cur, symbol] } };
    });
  }, []);

  const removeFromWatchlist = useCallback((id, symbol) => {
    setWatchlists((prev) => {
      const cur = prev.members[id] || [];
      return {
        ...prev,
        members: { ...prev.members, [id]: cur.filter((s) => s !== symbol) },
      };
    });
  }, []);
  const [highlightSymbol, setHighlightSymbol] = useState(null);
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [showSearch, setShowSearch] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [priceRefreshing, setPriceRefreshing] = useState(false);
  const [priceToast, setPriceToast] = useState(null);
  const [toolsOpen, setToolsOpen] = useState(false);

  const doSearch = (q) => {
    setSearchQ(q);
    if (q.length < 1) {
      setSearchResults([]);
      return;
    }
    fetch(`${API}/search?q=${encodeURIComponent(q)}`)
      .then((r) => r.json())
      .then(setSearchResults);
  };

  const selectCompany = (sym, tab = null) => {
    setSelectedSymbol(sym);
    setSelectedTab(tab);
    setPage("company");
    setHighlightSymbol(null);
    setShowSearch(false);
    setSearchQ("");
    setSearchResults([]);
    if (typeof window !== "undefined") {
      // Record the page we're leaving on the current history entry so the
      // browser Back button returns there (e.g. the Analysts monitor) rather
      // than defaulting to the screener. Skip when already on a company entry —
      // its state is already correct.
      if (page !== "company") {
        window.history.replaceState({ page }, "");
      }
      window.history.pushState(
        { page: "company", symbol: sym },
        "",
        `#company/${encodeURIComponent(sym)}`,
      );
    }
  };

  const goBack = () => {
    setPage("screener");
    if (typeof window !== "undefined" && window.location.hash) {
      window.history.pushState(
        { page: "screener" },
        "",
        window.location.pathname + window.location.search,
      );
    }
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onPop = (e) => {
      const st = e.state;
      if (st && st.page === "company" && st.symbol) {
        setSelectedSymbol(st.symbol);
        setPage("company");
      } else if (st && st.page) {
        setPage(st.page);
      } else {
        setPage("screener");
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const highlightInScreener = (sym) => {
    setHighlightSymbol(sym);
    setPage("screener");
    setShowSearch(false);
    setSearchQ("");
    setSearchResults([]);
  };

  // Top-level tab navigation that also records a browser history entry, so the
  // Back/Forward buttons move between the tabs you actually visited rather than
  // always snapping back to the screener. (Company detail manages its own
  // history via selectCompany/goBack.)
  const navigate = (p) => {
    setMobileMenuOpen(false);
    if (p === page) return;
    setPage(p);
    if (typeof window !== "undefined") {
      const url =
        p === "screener"
          ? window.location.pathname + window.location.search
          : `#${p}`;
      window.history.pushState({ page: p }, "", url);
    }
  };

  const handleRefresh = () => {
    setRefreshKey((k) => k + 1);
    setLastUpdated(
      new Date().toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
  };

  const handlePriceRefresh = async () => {
    setPriceRefreshing(true);
    setPriceToast(null);
    try {
      const res = await fetch(`${API}/prices/refresh`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPriceToast({
        ok: true,
        msg: `+${data.rows_added} rows (${data.duration_seconds}s)`,
      });
    } catch {
      setPriceToast({ ok: false, msg: "Price refresh failed" });
    } finally {
      setPriceRefreshing(false);
      setTimeout(() => setPriceToast(null), 4000);
    }
  };

  const NAV_GROUPS = [
    { id: "screener", label: "Screener" },
    { id: "trending", label: "Trending" },
    { id: "watchlist", label: "Watchlist" },
    { id: "analyst-monitor", label: "Analysts" },
    { id: "rns", label: "RNS News" },
    { id: "subscribe", label: "Subscribe" },
    { id: "markets", label: "Markets" },
  ];

  const showSidebar = page !== "company";
  // Default the benchmarks sidebar to collapsed on tablets / smaller laptops
  // (<=1500px) so it doesn't crowd the main view on a Surface Pro-sized screen.
  // Users can still toggle it back on. (Below 768px it's hidden entirely, so the
  // narrow-desktop hook is a fine proxy for the initial default.)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(isNarrow);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0a0a0a",
        fontFamily: "monospace",
      }}
    >
      <link
        href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap"
        rel="stylesheet"
      />

      {/* Nav */}
      <nav
        style={{
          background: "#0a0a0a",
          borderBottom: "1px solid #2a2a2a",
          padding: isMobile ? "0 12px" : "0 32px",
          display: "flex",
          alignItems: "center",
          height: 52,
          position: "sticky",
          top: 0,
          zIndex: 100,
        }}
      >
        {/* Hamburger / Sidebar toggle */}
        {isMobile ? (
          <button
            onClick={() => setMobileMenuOpen((v) => !v)}
            title="Menu"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "4px 8px",
              marginRight: 8,
              display: "flex",
              alignItems: "center",
              color: "#f1f5f9",
            }}
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
        ) : (
          <button
            onClick={() => setSidebarCollapsed((v) => !v)}
            title="Toggle sidebar"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "4px 8px 4px 0",
              marginRight: 8,
              marginLeft: -20,
              display: "flex",
              alignItems: "center",
              opacity: sidebarCollapsed ? 0.35 : 0.75,
              transition: "opacity 0.2s",
            }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <rect
                x="2"
                y="2"
                width="20"
                height="20"
                rx="3"
                stroke="#f1f5f9"
                strokeWidth="1.5"
              />
              <line
                x1="8"
                y1="2"
                x2="8"
                y2="22"
                stroke="#f1f5f9"
                strokeWidth="1.5"
              />
              <line
                x1="11"
                y1="7"
                x2="19"
                y2="7"
                stroke="#f1f5f9"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
              <line
                x1="11"
                y1="12"
                x2="19"
                y2="12"
                stroke="#f1f5f9"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
              <line
                x1="11"
                y1="17"
                x2="16"
                y2="17"
                stroke="#f1f5f9"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        )}
        <div
          onClick={() => navigate("screener")}
          style={{
            fontFamily: '"DM Sans", sans-serif',
            fontSize: isMobile ? 10 : 12,
            fontWeight: 600,
            color: "#f97316",
            letterSpacing: 2,
            textTransform: "uppercase",
            marginRight: isMobile ? 8 : isNarrow ? 12 : 32,
            cursor: "pointer",
            padding: "4px 10px",
            borderRadius: 4,
            background: "linear-gradient(135deg, #2a1a00 0%, #1a1200 100%)",
            boxShadow: "0 0 12px rgba(249, 115, 22, 0.15)",
            whiteSpace: "nowrap",
          }}
        >
          {isMobile ? "AMA" : "Alpha Move AI"}
        </div>

        {/* Desktop nav links. Allowed to shrink and scroll horizontally as a
            last-resort fallback (no visible scrollbar) so the menu can never
            push the page past the viewport on narrow screens. */}
        {!isMobile && (
          <div
            className="no-scrollbar"
            style={{
              display: "flex",
              gap: 2,
              flexShrink: 1,
              minWidth: 0,
              overflowX: "auto",
            }}
          >
            {NAV_GROUPS.map((g) => (
              <button
                key={g.id}
                style={{
                  ...S.navBtn,
                  ...(isNarrow ? { padding: "6px 8px", fontSize: 11 } : {}),
                  flexShrink: 0,
                  whiteSpace: "nowrap",
                  ...(page === g.id ? S.navBtnActive : {}),
                }}
                onClick={() => navigate(g.id)}
              >
                {g.label}
              </button>
            ))}
          </div>
        )}

        {/* Right side: buttons + search */}
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: isMobile ? 6 : isNarrow ? 8 : 12,
            minWidth: 0,
            flexShrink: 0,
          }}
        >
          {/* Tools menu — bundles the Tool Manual link and the market/price
              refresh actions into a single dropdown so the top bar stays
              compact on narrow screens. On mobile these live in the hamburger
              menu instead, so the whole thing is desktop-only. */}
          {!isMobile && (
            <div style={{ position: "relative", flexShrink: 0 }}>
              <button
                onClick={() => setToolsOpen((v) => !v)}
                title="Tools & refresh"
                style={{
                  background: "#1a1a1a",
                  color: priceRefreshing ? "#f97316" : "#999",
                  border: "1px solid #2a2a2a",
                  padding: "4px 10px",
                  borderRadius: 2,
                  fontFamily: "monospace",
                  fontSize: 10,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <span className={priceRefreshing ? "spinning" : ""}>⚙</span>
                Tools ▾
              </button>
              {toolsOpen && (
                <>
                  {/* Click-away overlay */}
                  <div
                    onClick={() => setToolsOpen(false)}
                    style={{ position: "fixed", inset: 0, zIndex: 200 }}
                  />
                  <div
                    style={{
                      position: "absolute",
                      top: "100%",
                      right: 0,
                      marginTop: 6,
                      minWidth: 200,
                      background: "#141414",
                      border: "1px solid #2a2a2a",
                      borderRadius: 4,
                      boxShadow: "0 8px 24px rgba(0,0,0,0.8)",
                      zIndex: 201,
                      overflow: "hidden",
                    }}
                  >
                    <a
                      href={`${API}/help-doc`}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={() => setToolsOpen(false)}
                      style={{
                        display: "block",
                        padding: "10px 14px",
                        color: "#e5e5e5",
                        fontFamily: "monospace",
                        fontSize: 11,
                        textDecoration: "none",
                        borderBottom: "1px solid #1f1f1f",
                      }}
                    >
                      📖 Tool Manual
                    </a>
                    <button
                      onClick={() => {
                        handleRefresh();
                        setToolsOpen(false);
                      }}
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "left",
                        background: "none",
                        border: "none",
                        borderBottom: "1px solid #1f1f1f",
                        padding: "10px 14px",
                        color: "#999",
                        fontFamily: "monospace",
                        fontSize: 11,
                        cursor: "pointer",
                      }}
                    >
                      ↻ Refresh Market
                    </button>
                    <button
                      onClick={handlePriceRefresh}
                      disabled={priceRefreshing}
                      title="Refresh price history"
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "left",
                        background: "none",
                        border: "none",
                        padding: "10px 14px",
                        color: priceRefreshing ? "#f97316" : "#999",
                        fontFamily: "monospace",
                        fontSize: 11,
                        cursor: priceRefreshing ? "not-allowed" : "pointer",
                      }}
                    >
                      <span className={priceRefreshing ? "spinning" : ""}>↻</span>
                      {priceRefreshing ? " Refreshing prices…" : " Refresh Prices"}
                    </button>
                    {(lastUpdated || priceToast) && (
                      <div
                        style={{
                          padding: "8px 14px",
                          borderTop: "1px solid #1f1f1f",
                          background: "#0f0f0f",
                          fontFamily: "monospace",
                          fontSize: 9,
                          lineHeight: 1.5,
                        }}
                      >
                        {lastUpdated && (
                          <div style={{ color: "#555" }}>Updated {lastUpdated}</div>
                        )}
                        {priceToast && (
                          <div
                            style={{
                              color: priceToast.ok ? "#10b981" : "#ef4444",
                            }}
                          >
                            {priceToast.msg}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
          <div style={{ position: "relative", minWidth: 0 }}>
            <input
              placeholder={
                isMobile || isNarrow ? "Search…" : "Search ticker or company…"
              }
              value={searchQ}
              onChange={(e) => {
                doSearch(e.target.value);
                setShowSearch(true);
              }}
              onFocus={() => setShowSearch(true)}
              onBlur={() => setTimeout(() => setShowSearch(false), 200)}
              style={{
                ...S.searchInput,
                width: isMobile ? 120 : isNarrow ? 160 : 260,
                maxWidth: "100%",
                fontSize: isMobile ? 11 : 13,
              }}
            />
            {showSearch && searchResults.length > 0 && (
              <div
                style={{
                  ...S.dropdown,
                  width: isMobile ? 280 : 420,
                  right: isMobile ? -60 : 0,
                }}
              >
                {searchResults.map((r) => (
                  <div
                    key={r.symbol}
                    onClick={() => highlightInScreener(r.symbol)}
                    style={S.dropdownItem}
                  >
                    <span
                      style={{
                        fontFamily: "monospace",
                        fontWeight: 700,
                        color: "#818cf8",
                        minWidth: 70,
                      }}
                    >
                      {r.symbol.replace(".L", "")}
                    </span>
                    <span style={{ color: "#94a3b8", fontSize: 13 }}>
                      {r.name}
                    </span>
                    <span
                      style={{
                        marginLeft: "auto",
                        fontSize: 11,
                        color: "#64748b",
                      }}
                    >
                      {r.exchange}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </nav>

      {/* Mobile drawer */}
      {isMobile && mobileMenuOpen && (
        <>
          <div
            onClick={() => setMobileMenuOpen(false)}
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.6)",
              zIndex: 99,
            }}
          />
          <div
            style={{
              position: "fixed",
              top: 52,
              left: 0,
              bottom: 0,
              width: 260,
              background: "#0d0d0d",
              borderRight: "1px solid #2a2a2a",
              zIndex: 100,
              overflowY: "auto",
              padding: "8px 0",
            }}
          >
            {NAV_GROUPS.map((g) => (
              <button
                key={g.id}
                onClick={() => navigate(g.id)}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  background: page === g.id ? "#1f1200" : "none",
                  border: "none",
                  padding: "12px 20px",
                  color: page === g.id ? "#f97316" : "#999",
                  cursor: "pointer",
                  fontSize: 13,
                  fontFamily: "monospace",
                  fontWeight: page === g.id ? 700 : 400,
                }}
              >
                {g.label}
              </button>
            ))}
            {/* Mobile-only: the desktop sidebar's benchmarks live on their own
                page here, since there's no room for the sidebar on small screens. */}
            <button
              onClick={() => navigate("benchmarks")}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                background: page === "benchmarks" ? "#1f1200" : "none",
                border: "none",
                padding: "12px 20px",
                color: page === "benchmarks" ? "#f97316" : "#999",
                cursor: "pointer",
                fontSize: 13,
                fontFamily: "monospace",
                fontWeight: page === "benchmarks" ? 700 : 400,
              }}
            >
              Benchmarks
            </button>
            <a
              href={`${API}/help-doc`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setMobileMenuOpen(false)}
              style={{
                display: "block",
                width: "100%",
                boxSizing: "border-box",
                textAlign: "left",
                padding: "12px 20px",
                color: "#999",
                cursor: "pointer",
                fontSize: 13,
                fontFamily: "monospace",
                textDecoration: "none",
              }}
            >
              Tool Manual
            </a>
            <div
              style={{
                borderTop: "1px solid #1f1f1f",
                marginTop: 12,
                paddingTop: 12,
              }}
            >
              <button
                onClick={() => navigate("donate")}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  background: page === "donate" ? "#1f1200" : "none",
                  border: "none",
                  padding: "10px 20px",
                  color: page === "donate" ? "#f97316" : "#999",
                  cursor: "pointer",
                  fontSize: 13,
                  fontFamily: "monospace",
                  fontWeight: page === "donate" ? 700 : 400,
                }}
              >
                ♥ Support
              </button>
              <button
                onClick={handleRefresh}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  background: "none",
                  border: "none",
                  padding: "10px 20px",
                  color: "#666",
                  cursor: "pointer",
                  fontSize: 12,
                  fontFamily: "monospace",
                }}
              >
                ↻ Refresh Market Data
              </button>
              <button
                onClick={handlePriceRefresh}
                disabled={priceRefreshing}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  background: "none",
                  border: "none",
                  padding: "10px 20px",
                  color: priceRefreshing ? "#f97316" : "#666",
                  cursor: "pointer",
                  fontSize: 12,
                  fontFamily: "monospace",
                }}
              >
                ↻ {priceRefreshing ? "Refreshing…" : "Refresh Stock Prices"}
              </button>
            </div>
          </div>
        </>
      )}

      {/* Body: sidebar + main */}
      <div style={{ display: "flex", maxWidth: 1600, margin: "0 auto" }}>
        <div
          style={{
            flexShrink: 0,
            display:
              showSidebar && !sidebarCollapsed && !isMobile ? "block" : "none",
          }}
        >
          <Sidebar refreshKey={refreshKey} onNavigate={navigate} />
        </div>
        <main
          style={{
            flex: 1,
            padding: isMobile ? "12px 12px" : "16px 24px",
            minWidth: 0,
          }}
        >
          <div style={{ display: page === "screener" ? "block" : "none" }}>
            <Screener
              onSelect={selectCompany}
              highlightSymbol={highlightSymbol}
              watchlist={defaultMembers}
              onToggleWatchlist={toggleWatchlist}
            />
          </div>
          {page === "watchlist" && (
            <WatchlistTab
              onSelect={selectCompany}
              watchlists={watchlists}
              onCreateList={createWatchlist}
              onRenameList={renameWatchlist}
              onDeleteList={deleteWatchlist}
              onAddSymbol={addToWatchlist}
              onRemoveSymbol={removeFromWatchlist}
            />
          )}
          {page === "trending" && <TrendingTab onSelect={selectCompany} />}
          {page === "heatmap" && (
            <HeatmapTab refreshKey={refreshKey} onSelect={selectCompany} />
          )}
          {page === "markets" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
              <CrossAssetTab refreshKey={refreshKey} />
              <FearGreedTab refreshKey={refreshKey} />
              <BreadthTab refreshKey={refreshKey} />
              <RotationTab refreshKey={refreshKey} />
            </div>
          )}
          {page === "analyst-monitor" && (
            <AnalystMonitorTab
              refreshKey={refreshKey}
              onSelect={selectCompany}
            />
          )}
          {page === "rns" && (
            <RnsTab refreshKey={refreshKey} onSelect={selectCompany} />
          )}
          {page === "benchmarks" && (
            <Sidebar refreshKey={refreshKey} onNavigate={navigate} mobile />
          )}
          {page === "subscribe" && <SubscribeTab />}
          {page === "donate" && <DonateTab />}
          {page === "feedback" && <FeedbackTab />}
          {page === "company" && selectedSymbol && (
            <CompanyDetail
              symbol={selectedSymbol}
              onBack={goBack}
              initialTab={selectedTab}
            />
          )}
        </main>
      </div>
      <Analytics />
      <SpeedInsights />
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const S = {
  loading: {
    textAlign: "center",
    padding: 64,
    color: "#666",
    fontSize: 16,
    fontFamily: "monospace",
  },
  card: {
    background: "#141414",
    borderRadius: 4,
    padding: 24,
    border: "1px solid #2a2a2a",
  },
  cardTitle: {
    margin: "0 0 16px",
    fontFamily: "monospace",
    fontSize: 13,
    fontWeight: 700,
    color: "#f97316",
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  badge: {
    background: "#1f1f1f",
    color: "#888",
    fontSize: 11,
    padding: "3px 10px",
    borderRadius: 2,
    fontFamily: "monospace",
  },
  tab: {
    background: "none",
    border: "none",
    padding: "10px 18px",
    color: "#666",
    cursor: "pointer",
    borderBottom: "2px solid transparent",
    transition: "all 0.15s",
    fontSize: 12,
    fontFamily: "monospace",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  tabActive: {
    color: "#f97316",
    borderBottom: "2px solid #f97316",
    fontWeight: 700,
  },
  navBtn: {
    background: "none",
    border: "none",
    padding: "6px 14px",
    color: "#999",
    cursor: "pointer",
    borderRadius: 2,
    fontSize: 12,
    fontFamily: "monospace",
  },
  navBtnActive: { color: "#f97316", background: "#1f1200", fontWeight: 700 },
  backBtn: {
    background: "none",
    border: "none",
    color: "#f97316",
    cursor: "pointer",
    padding: "0 0 16px",
    display: "block",
    fontSize: 13,
    fontFamily: "monospace",
  },
  searchInput: {
    width: 260,
    padding: "8px 14px",
    borderRadius: 2,
    border: "1px solid #2a2a2a",
    fontSize: 13,
    outline: "none",
    background: "#0a0a0a",
    color: "#e5e5e5",
    fontFamily: "monospace",
  },
  dropdown: {
    position: "absolute",
    right: 0,
    top: "100%",
    width: 420,
    background: "#141414",
    border: "1px solid #2a2a2a",
    borderRadius: 4,
    boxShadow: "0 8px 24px rgba(0,0,0,0.8)",
    zIndex: 200,
    maxHeight: 320,
    overflowY: "auto",
  },
  dropdownItem: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "10px 16px",
    cursor: "pointer",
    borderBottom: "1px solid #1f1f1f",
  },
  select: {
    padding: "8px 12px",
    borderRadius: 2,
    border: "1px solid #2a2a2a",
    fontSize: 12,
    background: "#141414",
    color: "#ccc",
    cursor: "pointer",
    outline: "none",
    fontFamily: "monospace",
  },
  table: {
    width: "100%",
    borderCollapse: "separate",
    borderSpacing: 0,
    fontSize: 12,
    fontFamily: "monospace",
  },
  th: {
    textAlign: "left",
    padding: "8px 12px",
    background: "#0a0a0a",
    color: "#f97316",
    fontSize: 10,
    fontWeight: 700,
    borderBottom: "1px solid #2a2a2a",
    whiteSpace: "nowrap",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    position: "sticky",
    top: 0,
    zIndex: 1,
  },
  td: {
    padding: "9px 12px",
    borderBottom: "1px solid #1a1a1a",
    color: "#ccc",
    whiteSpace: "nowrap",
  },
  tdNum: {
    padding: "9px 12px",
    borderBottom: "1px solid #1a1a1a",
    textAlign: "right",
    fontFamily: "monospace",
    fontSize: 12,
    whiteSpace: "nowrap",
    color: "#e5e5e5",
  },
  tooltip: {
    background: "#141414",
    border: "1px solid #2a2a2a",
    borderRadius: 4,
    fontSize: 12,
    color: "#e5e5e5",
    fontFamily: "monospace",
  },
};
