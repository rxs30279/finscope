"use client";

import { useState, useEffect, useMemo, Fragment } from "react";
import Link from "next/link";
import { API } from "@/lib/api";
import { companyHref } from "@/lib/company";
import { S, colors } from "@/lib/theme";
import { useIsMobile } from "@/hooks/useMediaQuery";
import InfoDot from "@/components/InfoDot";
import ScorePill from "@/components/screener/ScorePill";
import type { ShortLeaderboard, ShortLeaderRow } from "@/lib/shorts";

// Same four composites (and hover text) as the company-page ScoreStrip.
const SCORE_COLS = [
  { key: "momentum_score", label: "Mom", title: "Momentum score (0–10)", invert: false },
  { key: "quality_score", label: "Qual", title: "Quality score (0–10)", invert: false },
  { key: "value_score", label: "Val", title: "Value score (0–10, higher = cheaper)", invert: false },
  { key: "risk_score", label: "Rsk", title: "Risk score (0–10, lower is safer)", invert: true },
] as const;

const ARTICLE_HREF = "/research/fca-short-selling-regime-change-hidden-short-interest";

// "2026-07-17" → "17 Jul 2026"
const fmtDate = (s: string | null | undefined): string => {
  if (!s) return "—";
  const d = new Date(s);
  return isNaN(d.getTime())
    ? s
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

// Rising short interest = mounting bearish pressure (red); falling = green.
const deltaColor = (v: number | null): string =>
  v == null || v === 0 ? colors.textFaint : v > 0 ? colors.red : colors.green;

const fmtDelta = (v: number | null): string =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}pp`;

// Effective change for ranking risers/fallers: the 1-month delta once the
// series is old enough, else the delta over the issuer's available window.
const effDelta = (r: ShortLeaderRow): number =>
  r.change_1m != null ? r.change_1m : r.change_window;

function scalePoints(history: { pct: number }[], w: number, h: number, pad: number) {
  const vals = history.map((p) => p.pct);
  let min = Math.min(...vals);
  let max = Math.max(...vals);
  if (max - min < 0.05) {
    // near-flat series: open the domain up so the line sits mid-box
    min -= 0.1;
    max += 0.1;
  }
  const span = max - min;
  const n = history.length;
  const pts = history.map((p, i) => ({
    x: n === 1 ? w / 2 : (i / (n - 1)) * w,
    y: pad + (1 - (p.pct - min) / span) * (h - pad * 2),
  }));
  return { pts, min, max };
}

function Sparkline({ row }: { row: ShortLeaderRow }) {
  const w = 90;
  const h = 26;
  const { pts } = scalePoints(row.history, w, h, 3);
  const color = deltaColor(effDelta(row));
  const line = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block" }} aria-hidden="true">
      {pts.length === 1 ? (
        <circle cx={pts[0].x} cy={pts[0].y} r={2} fill={color} />
      ) : (
        <polyline points={line} fill="none" stroke={color} strokeWidth={1.5} />
      )}
    </svg>
  );
}

// Expanded per-issuer trend chart. The plot is a stretched SVG (vector-only, so
// preserveAspectRatio="none" is safe); the min/max/date labels are HTML overlays
// so they don't distort with it.
function TrendChart({ row, isMobile }: { row: ShortLeaderRow; isMobile: boolean }) {
  const H = isMobile ? 120 : 160;
  const W = 600; // viewBox units, stretched to container width
  const { pts, min, max } = scalePoints(row.history, W, 100, 8);
  const line = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const area = `0,100 ${line} ${W},100`;
  const first = row.history[0];
  const last = row.history[row.history.length - 1];
  return (
    // Sticky-left + viewport-capped width so the chart stays fully visible even
    // when its parent table overflows horizontally (mobile) — the colspan cell
    // is as wide as the whole table, which can be wider than the screen.
    <div
      style={{
        padding: isMobile ? "10px 4px 4px" : "12px 8px 6px",
        position: "sticky",
        left: 0,
        maxWidth: "calc(100vw - 60px)",
      }}
    >
      <div style={{ position: "relative" }}>
        <svg
          width="100%"
          height={H}
          viewBox="0 0 600 100"
          preserveAspectRatio="none"
          style={{ display: "block" }}
        >
          <polygon points={area} fill="rgba(239,68,68,0.08)" />
          {pts.length === 1 ? (
            <circle cx={pts[0].x} cy={pts[0].y} r={3} fill={colors.red} />
          ) : (
            <polyline
              points={line}
              fill="none"
              stroke={colors.red}
              strokeWidth={1.6}
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>
        <span style={{ position: "absolute", top: 0, left: 4, fontSize: 10, color: colors.textMuted }}>
          {max.toFixed(2)}%
        </span>
        <span style={{ position: "absolute", bottom: 0, left: 4, fontSize: 10, color: colors.textMuted }}>
          {min.toFixed(2)}%
        </span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: colors.textFaint, marginTop: 4 }}>
        <span>{fmtDate(first?.date)}</span>
        <span>{fmtDate(last?.date)}</span>
      </div>
      <div style={{ fontSize: 10, color: colors.textDim, marginTop: 6 }}>
        Aggregate net short position, all FCA-disclosed positions ≥0.2% summed. The series
        begins 13 Jul 2026, when the FCA&apos;s aggregate disclosure regime started.
      </div>
    </div>
  );
}

function MoversCard({
  title,
  rows,
  deltaLabel,
  onToggle,
}: {
  title: string;
  rows: ShortLeaderRow[];
  deltaLabel: string;
  onToggle: (isin: string) => void;
}) {
  return (
    <div style={{ ...S.card, padding: 16 }}>
      <div style={{ ...S.cardTitle, margin: "0 0 4px", fontSize: 11 }}>{title}</div>
      <div style={{ fontSize: 9, color: colors.textFaint, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 10 }}>
        {deltaLabel}
      </div>
      {rows.length === 0 && (
        <div style={{ fontSize: 11, color: colors.textDim }}>No movers yet</div>
      )}
      {rows.map((r) => (
        <div
          key={r.isin}
          onClick={() => onToggle(r.isin)}
          style={{
            display: "flex", alignItems: "baseline", gap: 8,
            padding: "5px 0", borderBottom: `1px solid ${colors.borderSubtle}`,
            cursor: "pointer", fontSize: 12,
          }}
        >
          <span style={{ color: colors.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0, flex: 1 }}>
            {r.name}
          </span>
          <span style={{ color: colors.textMuted }}>{r.pct.toFixed(2)}%</span>
          <span style={{ color: deltaColor(effDelta(r)), fontWeight: 700, minWidth: 62, textAlign: "right" }}>
            {fmtDelta(effDelta(r))}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function MostShortedPageClient({
  initialData,
}: {
  initialData: ShortLeaderboard | null;
}) {
  const isMobile = useIsMobile();
  const [data, setData] = useState<ShortLeaderboard | null>(initialData);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  // SSR fetch failed (or was skipped) — fall back to fetching in the browser.
  useEffect(() => {
    if (data) return;
    let cancelled = false;
    fetch(`${API}/shorts/top`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled) return;
        if (d && Array.isArray(d.rows)) setData(d);
        else setFailed(true);
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [data]);

  const rows = useMemo(() => data?.rows ?? [], [data]);

  // Column header adapts as the series matures: the 1-month delta takes over
  // from the since-inception delta once ~30 days of disclosures exist.
  const hasMonth = rows.some((r) => r.change_1m != null);
  const windowStart = rows.length
    ? rows.reduce((m, r) => (r.window_start < m ? r.window_start : m), rows[0].window_start)
    : null;
  const deltaLabel = hasMonth ? "1M change" : `Change since ${fmtDate(windowStart)}`;

  const movers = useMemo(() => {
    const moved = rows.filter((r) => effDelta(r) !== 0);
    const byDelta = [...moved].sort((a, b) => effDelta(b) - effDelta(a));
    return {
      risers: byDelta.filter((r) => effDelta(r) > 0).slice(0, 5),
      fallers: byDelta.filter((r) => effDelta(r) < 0).reverse().slice(0, 5),
    };
  }, [rows]);

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        (r.symbol || "").toLowerCase().includes(q) ||
        (r.ftse_index || "").toLowerCase().includes(q),
    );
  }, [rows, filter]);

  const toggle = (isin: string) => setExpanded((e) => (e === isin ? null : isin));

  // Movers cards can reference a row far down the table — expand it AND bring
  // it into view, otherwise the click appears to do nothing.
  const jumpTo = (isin: string) => {
    setExpanded(isin);
    setFilter("");
    // after the expanded row renders
    setTimeout(() => {
      document.getElementById(`short-row-${isin}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
  };

  if (!data) {
    return (
      <div style={S.loading}>
        {failed ? "Short-interest data unavailable — try again shortly." : "Loading short positions…"}
      </div>
    );
  }

  const heavilyShorted = rows.filter((r) => r.pct >= 5).length;

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ margin: "4px 0 6px", fontSize: isMobile ? 18 : 22, color: colors.white, fontFamily: "monospace" }}>
          Most Shorted UK Stocks
          {/* superscript-style: raised to the title's cap height, small gap */}
          <span style={{ display: "inline-block", marginLeft: 7, verticalAlign: "super" }}>
            <InfoDot text="Ranked by FCA-disclosed Aggregate Net Short Position (ANSP) — the sum of all short positions ≥0.2% of a company's issued share capital, published each working day with a ~2 working-day lag." />
          </span>
        </h1>
        <div style={{ fontSize: 12, color: colors.textMuted, lineHeight: 1.6 }}>
          Every UK company with disclosed short interest, ranked by the FCA&apos;s daily
          aggregate net short position. {rows.length} issuers · {heavilyShorted} at ≥5% ·
          updated {fmtDate(data.as_of)}.
        </div>
        <div style={{ fontSize: 11, color: colors.textFaint, marginTop: 4 }}>
          Short sellers stopped being named on 13 Jul 2026 —{" "}
          <Link href={ARTICLE_HREF} style={{ color: colors.accent }}>
            read why, and what was hiding in the old data
          </Link>
          .
        </div>
      </div>

      {/* Risers / fallers */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 12, marginBottom: 16 }}>
        <MoversCard title="▲ Biggest Risers" rows={movers.risers} deltaLabel={deltaLabel} onToggle={jumpTo} />
        <MoversCard title="▼ Biggest Fallers" rows={movers.fallers} deltaLabel={deltaLabel} onToggle={jumpTo} />
      </div>

      {/* Leaderboard */}
      <div style={{ ...S.card, padding: 0, overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", padding: isMobile ? "12px 12px 8px" : "16px 20px 10px", gap: 12 }}>
          <div style={{ ...S.cardTitle, margin: 0, flex: 1 }}>Short Interest Leaderboard</div>
          <input
            placeholder="Filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ ...S.searchInput, width: isMobile ? 110 : 180, padding: "6px 10px", fontSize: 12 }}
          />
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={S.table}>
            <thead>
              <tr>
                <th style={{ ...S.th, width: 34 }}>#</th>
                <th style={S.th}>Ticker</th>
                <th style={S.th}>Company</th>
                <th style={S.th}>Market</th>
                <th style={{ ...S.th, textAlign: "right" }}>Short&nbsp;%</th>
                <th style={{ ...S.th, textAlign: "right" }}>{deltaLabel}</th>
                <th style={{ ...S.th, width: 100 }}>Trend</th>
                {SCORE_COLS.map((c) => (
                  <th key={c.key} title={c.title} style={{ ...S.th, textAlign: "center", width: 44 }}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((r, i) => (
                <Fragment key={r.isin}>
                  <tr
                    id={`short-row-${r.isin}`}
                    onClick={() => toggle(r.isin)}
                    style={{ cursor: "pointer", background: expanded === r.isin ? "#101010" : "none" }}
                  >
                    <td style={{ ...S.td, color: colors.textFaint }}>{i + 1}</td>
                    <td style={S.td}>
                      {r.symbol ? (
                        <Link
                          href={companyHref(r.symbol)}
                          onClick={(e) => e.stopPropagation()}
                          style={{ color: colors.indigo, fontWeight: 700, textDecoration: "none" }}
                        >
                          {r.symbol.replace(/\.L$/, "")}
                        </Link>
                      ) : (
                        <span style={{ color: colors.textDim }}>—</span>
                      )}
                    </td>
                    <td
                      style={
                        isMobile
                          ? { ...S.td, overflow: "hidden", textOverflow: "ellipsis", maxWidth: 150 }
                          : { ...S.td, whiteSpace: "normal" }
                      }
                    >
                      {r.symbol ? (
                        <Link
                          href={companyHref(r.symbol)}
                          onClick={(e) => e.stopPropagation()}
                          style={{ color: colors.text, textDecoration: "none" }}
                        >
                          {r.name}
                        </Link>
                      ) : (
                        <span style={{ color: colors.textMuted }}>{r.name}</span>
                      )}
                    </td>
                    <td style={{ ...S.td, color: colors.textFaint }} title={r.ftse_index || undefined}>
                      {r.ftse_index ? r.ftse_index.replace("FTSE ", "") : "—"}
                    </td>
                    <td style={{ ...S.tdNum, fontWeight: 700, color: r.pct >= 5 ? colors.red : colors.text }}>
                      {r.pct.toFixed(2)}%
                    </td>
                    <td style={{ ...S.tdNum, color: deltaColor(hasMonth ? r.change_1m : r.change_window) }}>
                      {fmtDelta(hasMonth ? r.change_1m : r.change_window)}
                    </td>
                    <td style={S.td}>
                      <Sparkline row={r} />
                    </td>
                    {SCORE_COLS.map((c) => (
                      <td key={c.key} title={c.title} style={{ ...S.td, textAlign: "center" }}>
                        <ScorePill value={r[c.key]} invert={c.invert} />
                      </td>
                    ))}
                  </tr>
                  {expanded === r.isin && (
                    <tr>
                      <td colSpan={11} style={{ ...S.td, background: "#101010" }}>
                        <TrendChart row={r} isMobile={isMobile} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={11} style={{ ...S.td, color: colors.textDim, textAlign: "center", padding: 24 }}>
                    No issuers match “{filter}”
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Methodology footer */}
      <div style={{ fontSize: 10, color: colors.textDim, lineHeight: 1.7, padding: "14px 4px" }}>
        Source: FCA aggregate net short position disclosures, published each working day
        (~2 working-day reporting lag). An issuer&apos;s aggregate is the sum of all individual
        short positions of 0.2% or more of issued share capital, so real short interest can be
        higher — positions under 0.2% are invisible. Companies drop off this table when their
        aggregate falls below 0.2%. Not investment advice.
      </div>
    </div>
  );
}
