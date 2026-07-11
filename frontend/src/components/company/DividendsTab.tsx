"use client";
import { useState, useEffect } from "react";
import {
  BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import { API } from "@/lib/api";
import { fmt, fmtUKDate, currSym, dividendDataUrl } from "@/lib/format";
import { S } from "@/lib/theme";
import MetricCard from "./MetricCard";
import InfoDot from "@/components/InfoDot";

interface DividendEvent {
  ex_date: string;
  amount: number;
}

interface DividendData {
  symbol: string;
  currency: string | null;
  price: number | null;
  price_date: string | null;
  ttm_dps: number | null;
  ttm_yield: number | null;
  ttm_yield_suspect: boolean;
  last_ex_date: string | null;
  last_amount: number | null;
  next_ex_date: string | null;
  next_amount: number | null;
  years_paid: number;
  years_of_growth: number;
  annual_totals: { year: number; total: number; partial: boolean }[];
  events: DividendEvent[];
}

export default function DividendsTab({ symbol }: { symbol: string }) {
  const [data, setData] = useState<DividendData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/dividends?symbol=${encodeURIComponent(symbol)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setData(d))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [symbol]);

  if (loading) {
    return <div style={{ color: "#444", padding: 32, fontFamily: "monospace" }}>Loading dividend history…</div>;
  }

  const unit = data?.currency === "GBp" ? "p" : currSym(data?.currency || "GBP");
  const fmtAmt = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${v.toFixed(2)}${unit}`;

  if (!data || !data.events.length) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16, alignItems: "flex-start" }}>
        <div style={{ color: "#666", fontFamily: "monospace", fontSize: 13, padding: "12px 0" }}>
          No dividend payments on record for {symbol}.
        </div>
        <a
          href={dividendDataUrl(symbol)}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "#a78bfa", textDecoration: "none", borderBottom: "1px dashed #a78bfa55", paddingBottom: 1, fontFamily: "monospace", fontSize: 11, letterSpacing: 1, textTransform: "uppercase" }}
        >
          Check Dividend Data ↗
        </a>
      </div>
    );
  }

  const chartData = data.annual_totals.map((r) => ({ ...r, amount: r.total }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(155px,1fr))", gap: 10 }}>
        <MetricCard
          label={
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
              Trailing Yield <InfoDot text="Trailing-12-month dividends ÷ current price. May differ slightly from the yield shown elsewhere on the site, which comes from Yahoo Finance directly." />
            </span>
          }
          value={data.ttm_yield_suspect ? "—" : fmt(data.ttm_yield, "pct")}
        />
        <MetricCard label="TTM Dividend/Share" value={fmtAmt(data.ttm_dps)} />
        <MetricCard
          label="Next Ex-Div"
          value={data.next_ex_date ? `${fmtUKDate(data.next_ex_date)}` : "—"}
          color={data.next_ex_date ? "#a78bfa" : undefined}
        />
        <MetricCard label="Last Ex-Div" value={data.last_ex_date ? fmtUKDate(data.last_ex_date) : "—"} />
        <MetricCard label="Years Paid" value={data.years_paid || "—"} />
        <MetricCard label="Years of Growth" value={data.years_of_growth || "—"} />
      </div>

      {chartData.length > 0 && (
        <div style={S.card}>
          <h3 style={S.cardTitle}>{`Annual Dividends (${unit})`}</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: "#666", fontFamily: "monospace" }} />
              <YAxis tick={{ fontSize: 11, fill: "#666", fontFamily: "monospace" }} />
              <Tooltip
                formatter={(v: any, _n: any, p: any) => [`${Number(v).toFixed(2)}${unit}${p?.payload?.partial ? " (YTD)" : ""}`, "Total"]}
                contentStyle={S.tooltip}
              />
              <Bar dataKey="amount" fill="#6366f1" radius={[2, 2, 0, 0]} name="Total">
                {chartData.map((d, i) => (
                  <Cell key={i} fillOpacity={d.partial ? 0.45 : 1} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div style={S.card}>
        <h3 style={S.cardTitle}>Recent Payments</h3>
        <table style={S.table}>
          <thead>
            <tr>
              <th style={S.th}>Ex-Dividend Date</th>
              <th style={S.th}>Amount</th>
            </tr>
          </thead>
          <tbody>
            {data.events.map((e) => {
              const future = e.ex_date > (data.price_date || "");
              return (
                <tr key={e.ex_date}>
                  <td style={{ ...S.td, color: future ? "#a78bfa" : S.td.color }}>
                    {fmtUKDate(e.ex_date)}{future ? " (declared)" : ""}
                  </td>
                  <td style={S.td}>{fmtAmt(e.amount)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div>
        <a
          href={dividendDataUrl(symbol)}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "#a78bfa", textDecoration: "none", borderBottom: "1px dashed #a78bfa55", paddingBottom: 1, fontFamily: "monospace", fontSize: 11, letterSpacing: 1, textTransform: "uppercase" }}
        >
          Full Payment Calendar on Dividend Data ↗
        </a>
      </div>
    </div>
  );
}
