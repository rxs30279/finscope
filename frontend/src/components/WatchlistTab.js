"use client";
import { useState, useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { API } from "@/lib/api";
import { companyHref } from "@/lib/company";
import { loadTargets, saveTargets, DEFAULT_LIST_ID } from "@/lib/storage";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { useIsAdmin } from "@/hooks/useAdmin";
import { lseStatus, latestSessionDate } from "@/lib/lse";
import PageHeader from "@/components/layout/PageHeader";
import ScorePill from "@/components/screener/ScorePill";
import ScoreStrip, { MEASURES as SCORE_COLS } from "@/components/company/ScoreStrip";

// Relative time for recent items ("2h", "3d"); a real date once past a week,
// which reads better than "5w" for older news.
const fmtWhen = (iso) => {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d`;
  const d = new Date(then);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "2-digit" }),
  });
};

// Prices are stored in pence (LSE convention) — show as pounds.
const fmtPounds = (pence) =>
  pence == null ? "—" : `£${(pence / 100).toFixed(2)}`;

const pctColor = (v) =>
  v == null ? "#64748b" : v > 0.05 ? "#10b981" : v < -0.05 ? "#ef4444" : "#94a3b8";

// Investegate-style tier colours, reused for the RNS signal badge.
const TIER_COLOR = { A: "#f87171", B: "#fbbf24", C: "#94a3b8" };

const S = {
  th: {
    textAlign: "left",
    padding: "8px 14px",
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
    cursor: "pointer",
    userSelect: "none",
  },
  td: {
    padding: "9px 14px",
    borderBottom: "1px solid #1a1a1a",
    color: "#ccc",
    whiteSpace: "nowrap",
    fontFamily: "monospace",
    fontSize: 12,
  },
};

// ── Small signal pieces ───────────────────────────────────────────────────────
function StreakBadge({ streak }) {
  if (!streak) return null;
  const up = streak > 0;
  const days = Math.abs(streak);
  return (
    <span
      title={`${days} consecutive ${up ? "up" : "down"} day${days > 1 ? "s" : ""}`}
      style={{
        background: up ? "#0d2318" : "#2a0d0d",
        color: up ? "#10b981" : "#ef4444",
        border: `1px solid ${up ? "#10b98133" : "#ef444433"}`,
        padding: "1px 6px",
        borderRadius: 2,
        fontSize: 10,
        fontWeight: 700,
      }}
    >
      {up ? "▲" : "▼"}
      {days}d
    </span>
  );
}

// Combined news indicator — RNS + press together, last 7 days. Clickable: opens
// the company's News tab. The dot is tier-coloured by the latest RNS.
function NewsCluster({ rnsCount, rnsLatest, pressCount, onClick }) {
  if (!rnsCount && !pressCount) return null;
  const tier = rnsLatest?.tier || "C";
  const dotColor = rnsCount ? TIER_COLOR[tier] || TIER_COLOR.C : "#94a3b8";
  const parts = [];
  if (rnsCount) parts.push(`${rnsCount} RNS`);
  if (pressCount) parts.push(`${pressCount} press`);
  const title = rnsLatest
    ? `Last 7d — latest RNS: ${rnsLatest.headline} (open News)`
    : "News in the last 7 days — open News";
  return (
    <span
      title={title}
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        background: "#1a1400",
        border: `1px solid ${dotColor}33`,
        padding: "1px 7px",
        borderRadius: 2,
        fontSize: 10,
        fontWeight: 700,
        cursor: "pointer",
      }}
    >
      <span style={{ color: dotColor }}>●</span>
      <span style={{ color: "#cbd5e1" }}>{parts.join(" · ")}</span>
    </span>
  );
}

// Thumbnail price graph — last ~3 months of closes. Indigo line + filled area to
// match the price chart on the company detail page.
// `fluid` stretches the chart to whatever width its cell gives it (the table's
// columns are percentages) instead of drawing at a fixed pixel width; `width`
// then only sets the coordinate space.
function Sparkline({ points, width = 76, height = 26, fluid = false }) {
  if (!points || points.length < 2)
    return <span style={{ color: "#3a3a3a", fontSize: 11 }}>—</span>;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const n = points.length;
  const coords = points.map((v, i) => {
    const x = (i / (n - 1)) * (width - 2) + 1;
    const y = height - 1 - ((v - min) / span) * (height - 2);
    return [x, y];
  });
  const line = coords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
  const area =
    `M${coords[0][0].toFixed(1)},${height} ` +
    coords.map(([x, y]) => `L${x.toFixed(1)},${y.toFixed(1)}`).join(" ") +
    ` L${coords[n - 1][0].toFixed(1)},${height} Z`;
  const color = "#6366f1";
  return (
    <svg
      width={fluid ? "100%" : width}
      height={height}
      viewBox={fluid ? `0 0 ${width} ${height}` : undefined}
      preserveAspectRatio={fluid ? "none" : undefined}
      style={{ display: "block", flexShrink: fluid ? 1 : 0 }}
      title="Last 3 months"
    >
      <path d={area} fill={color} opacity={0.13} />
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth={1.25}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

// 52-week range bar: a solid fill from the 52w low (left) to the current price,
// colour-coded by where in the range the price sits — red near the low, amber in
// the middle, green near the 52w high.
// `fluid` lets the bar grow to fill its table cell; fixed at 64px otherwise
// (the mobile card, where it sits in a flex row beside other content).
function RangeBar({ pos, fluid = false }) {
  if (pos == null)
    return <span style={{ color: "#444", fontSize: 11 }}>—</span>;
  const clamped = Math.max(0, Math.min(100, pos));
  const color =
    clamped >= 66 ? "#10b981" : clamped >= 33 ? "#f59e0b" : "#ef4444";
  return (
    <div
      title={`${clamped.toFixed(0)}% of 52-week range`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        width: fluid ? "100%" : undefined,
      }}
    >
      <div
        style={{
          width: fluid ? undefined : 64,
          flex: fluid ? 1 : undefined,
          height: 8,
          background: "#0b1120",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${clamped}%`,
            height: "100%",
            background: color,
            borderRadius: 2,
          }}
        />
      </div>
      <span style={{ color, fontSize: 10, fontWeight: 700 }}>
        {clamped.toFixed(0)}%
      </span>
    </div>
  );
}

// ── Inline target editor ──────────────────────────────────────────────────────
function TargetCell({ symbol, target, price, onCommit }) {
  const [draft, setDraft] = useState(target != null ? String(target) : "");
  useEffect(() => {
    setDraft(target != null ? String(target) : "");
  }, [target]);

  const commit = () => {
    if (draft === "" && target == null) return;
    if (draft !== (target != null ? String(target) : "")) onCommit(symbol, draft);
  };

  // Gap: where today's price sits relative to the buy target (price in pounds).
  let gap = null;
  if (target != null && price != null) gap = price / 100 / target - 1;
  const atOrBelow = gap != null && gap <= 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
      <input
        type="text"
        inputMode="decimal"
        value={draft}
        placeholder="set £"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            commit();
            e.currentTarget.blur();
          }
        }}
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 60,
          textAlign: "right",
          background: "rgba(255,255,255,0.06)",
          border: "1px solid rgba(148,163,184,0.25)",
          borderRadius: 4,
          padding: "3px 6px",
          fontFamily: "monospace",
          fontSize: 12,
          color: gap == null ? "#cbd5e1" : atOrBelow ? "#10b981" : "#ef4444",
          outline: "none",
        }}
      />
    </div>
  );
}

// ── List tabs + management ────────────────────────────────────────────────────
function ListTabs({ lists, activeId, onSelect, counts }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      {lists.map((l) => {
        const active = l.id === activeId;
        const empty = (counts[l.id] || 0) === 0;
        return (
          <button
            key={l.id}
            onClick={() => onSelect(l.id)}
            title={
              empty
                ? "This list is empty — tap the ☆ next to any stock in the Screener to add it here."
                : undefined
            }
            style={{
              background: active ? "#f97316" : "#1a1a1a",
              color: active ? "#0a0a0a" : "#cbd5e1",
              border: `1px solid ${active ? "#f97316" : "#2a2a2a"}`,
              borderRadius: 999,
              padding: "5px 13px",
              fontSize: 12,
              fontWeight: 700,
              fontFamily: "monospace",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            {l.name}
            <span style={{ opacity: 0.6, marginLeft: 6 }}>{counts[l.id] || 0}</span>
          </button>
        );
      })}
    </div>
  );
}

// Type-ahead box that searches the universe (/api/search) and adds the chosen
// stock to the active list.
function AddStockBox({ onAdd, existing }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const boxRef = useRef(null);

  useEffect(() => {
    if (q.trim().length < 1) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const id = setTimeout(() => {
      fetch(`${API}/search?q=${encodeURIComponent(q.trim())}`)
        .then((r) => r.json())
        .then((d) => !cancelled && setResults(Array.isArray(d) ? d : []))
        .catch(() => !cancelled && setResults([]));
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [q]);

  useEffect(() => {
    const onDoc = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const pick = (sym) => {
    onAdd(sym);
    setQ("");
    setResults([]);
    setOpen(false);
  };

  return (
    <div ref={boxRef} style={{ position: "relative", width: 240 }}>
      <input
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="+ Add stock by ticker or name…"
        style={{
          width: "100%",
          background: "rgba(255,255,255,0.06)",
          border: "1px solid rgba(148,163,184,0.25)",
          borderRadius: 4,
          padding: "6px 9px",
          fontFamily: "monospace",
          fontSize: 12,
          color: "#e5e5e5",
          outline: "none",
        }}
      />
      {open && results.length > 0 && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            maxHeight: 260,
            overflowY: "auto",
            background: "#0f172a",
            border: "1px solid #2a2a2a",
            borderRadius: 4,
            zIndex: 5,
            boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
          }}
        >
          {results.map((r) => {
            const already = existing.has(r.symbol);
            return (
              <div
                key={r.symbol}
                onClick={() => !already && pick(r.symbol)}
                style={{
                  padding: "7px 10px",
                  borderBottom: "1px solid #1a1a1a",
                  cursor: already ? "default" : "pointer",
                  opacity: already ? 0.45 : 1,
                  fontFamily: "monospace",
                  fontSize: 12,
                }}
                onMouseEnter={(e) =>
                  !already && (e.currentTarget.style.background = "#1e293b")
                }
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <span style={{ color: "#f1f5f9", fontWeight: 700 }}>
                  {r.symbol.replace(".L", "")}
                </span>
                <span style={{ color: "#64748b", marginLeft: 8 }}>{r.name}</span>
                {already && (
                  <span style={{ color: "#10b981", marginLeft: 8, fontSize: 10 }}>
                    ✓ in list
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── News panel ────────────────────────────────────────────────────────────────
// News for a single selected share: RNS + press, newest first. Defaults to the
// first share in the list; clicking a row's News cell switches it to that share.
// Reuses /api/news/{symbol}, which live-fetches press when the cache is stale
// (or always, with refresh=true). Always sits underneath the table/cards, at
// every width.
function NewsPanel({ symbol, name }) {
  const isAdmin = useIsAdmin();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const reqRef = useRef("");

  const load = (sym, refresh) => {
    if (!sym) return Promise.resolve();
    setLoading(true);
    return fetch(
      `${API}/news/${encodeURIComponent(sym)}${refresh ? "?refresh=true" : ""}`,
    )
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (reqRef.current !== sym) return;
        const rns = (d?.rns || []).map((r) => ({
          kind: "rns",
          headline: r.headline,
          tier: r.tier,
          category: r.category,
          published_at: r.published_at,
          url: r.url,
        }));
        const press = (d?.google || []).map((g) => ({
          kind: "press",
          headline: g.title,
          source: g.source,
          published_at: g.published_at,
          url: g.link,
        }));
        const merged = [...rns, ...press].sort(
          (a, b) =>
            new Date(b.published_at || 0) - new Date(a.published_at || 0),
        );
        setItems(merged);
      })
      .catch(() => reqRef.current === sym && setItems([]))
      .finally(() => reqRef.current === sym && setLoading(false));
  };

  useEffect(() => {
    reqRef.current = symbol || "";
    if (!symbol) {
      setItems([]);
      return;
    }
    load(symbol, false);
    // eslint-disable-next-line
  }, [symbol]);

  const ticker = symbol ? symbol.replace(".L", "") : "";

  return (
    <div
      style={{
        flex: "0 0 auto",
        background: "#0d0d0d",
        border: "1px solid #1e1e1e",
        borderRadius: 3,
        display: "flex",
        flexDirection: "column",
        maxHeight: 520,
      }}
    >
      <div
        style={{
          padding: "10px 14px",
          borderBottom: "1px solid #1e1e1e",
          display: "flex",
          alignItems: "baseline",
          gap: 8,
        }}
      >
        <span
          style={{
            color: "#f97316",
            fontSize: 10,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          News
        </span>
        <span
          style={{
            color: "#e2e8f0",
            fontFamily: "monospace",
            fontSize: 12,
            fontWeight: 700,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={name || ticker}
        >
          {symbol ? `${ticker}${name ? ` · ${name}` : ""}` : "—"}
        </span>
        {loading && (
          <span style={{ color: "#475569", fontSize: 10, fontFamily: "monospace" }}>
            loading…
          </span>
        )}
        {isAdmin && (
          <button
            onClick={() => load(symbol, true)}
            disabled={loading || !symbol}
            title="Pull fresh press now"
            style={{
              marginLeft: "auto",
              background: "none",
              border: "1px solid #2a2a2a",
              borderRadius: 4,
              color: loading ? "#475569" : "#94a3b8",
              cursor: loading || !symbol ? "default" : "pointer",
              fontSize: 12,
              lineHeight: 1,
              padding: "3px 7px",
            }}
          >
            {loading ? "…" : "↻"}
          </button>
        )}
      </div>
      <div style={{ overflowY: "auto" }}>
        {items.length === 0 ? (
          <div
            style={{
              padding: "28px 16px",
              textAlign: "center",
              color: "#475569",
              fontFamily: "monospace",
              fontSize: 12,
            }}
          >
            {!symbol
              ? "Add stocks to see their news here."
              : loading
                ? "Loading news…"
                : "No recent news for this share."}
          </div>
        ) : (
          items.map((it, i) => {
            const isRns = it.kind === "rns";
            // Left accent: tier-coloured for RNS, neutral for press — separates
            // the two kinds at a glance and conveys RNS importance by colour.
            const accent = isRns ? TIER_COLOR[it.tier] || TIER_COLOR.C : "#3f4b5b";
            const meta = isRns
              ? (it.category || "").replace(/_/g, " ")
              : it.source || "";
            const body = (
              <>
                {/* Dim, secondary meta line — kind · category/source · when */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 7,
                    marginBottom: 4,
                    fontFamily: "monospace",
                    fontSize: 9.5,
                    letterSpacing: 0.3,
                    color: "#64748b",
                  }}
                >
                  <span style={{ color: isRns ? accent : "#7c8a9c", fontWeight: 700 }}>
                    {isRns ? "RNS" : "PRESS"}
                  </span>
                  {meta && (
                    <span
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {meta}
                    </span>
                  )}
                  <span style={{ marginLeft: "auto", flexShrink: 0 }}>
                    {fmtWhen(it.published_at)}
                  </span>
                </div>
                {/* Primary line — the headline */}
                <div
                  style={{
                    color: "#f1f5f9",
                    fontSize: 13,
                    fontWeight: 500,
                    lineHeight: 1.45,
                  }}
                >
                  {it.headline}
                </div>
              </>
            );
            // Zebra striping so adjacent headlines are easy to tell apart.
            const baseBg = i % 2 ? "rgba(255,255,255,0.035)" : "transparent";
            const style = {
              display: "block",
              padding: "10px 14px",
              borderBottom: "1px solid #161616",
              borderLeft: `3px solid ${accent}`,
              background: baseBg,
              cursor: it.url ? "pointer" : "default",
              textDecoration: "none",
            };
            const hover = {
              onMouseEnter: (e) => (e.currentTarget.style.background = "#15202e"),
              onMouseLeave: (e) => (e.currentTarget.style.background = baseBg),
            };
            return it.url ? (
              <a
                key={`${it.kind}-${it.published_at}-${i}`}
                href={it.url}
                target="_blank"
                rel="noreferrer"
                style={style}
                {...hover}
              >
                {body}
              </a>
            ) : (
              <div key={`${it.kind}-${it.published_at}-${i}`} style={style} {...hover}>
                {body}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
// Desktop sparkline width — wide enough that the trend + 52-week range fill their
// shared column instead of leaving a gap before Target buy.
const SPARK_W = 110;

// The four factor columns — identical width AND padding, so the pills sit on an
// even pitch. (Giving MOM extra left padding to open up the divider knocked its
// pill out of step with the other three.) MOM carries the faint rule; the space
// before it comes from Target buy's right padding.
const SCORE_TABLE_COLS = SCORE_COLS.map((c, i) => ({
  ...c,
  align: "center",
  width: "4%",
  padding: "8px 10px",
  cellPadding: "9px 10px",
  divider: i === 0,
}));

// Widths sum to 100% and drive a fixed table layout, so the columns keep the same
// proportions at every page width instead of auto-layout handing the spare space
// to whichever columns happen to hold the widest content. The bulk (72%) goes to
// the price/trend block left of the divider; the four score pills and the news
// chip only need what their fixed-size content occupies.
// The news column's left padding is the gap between the RSK pill and the news
// chip. Named because the header cell and the body cell are written separately
// (the body <td> is hand-rolled, not part of the COLS map) and silently drifted
// apart once already.
const NEWS_HEAD_PAD = "8px 14px 8px 76px";
const NEWS_CELL_PAD = "9px 14px 9px 76px";
// How far into the news column the orange "showing this share" marker sits, so it
// leads the chip rather than crowding the RSK pill. Keep it under the left padding
// above or it will overlap the chip.
const NEWS_MARK_LEFT = 62;

const COLS = [
  {
    key: "name",
    // Indent past the row's ★ button (icon + gap) so the header lines up with the ticker.
    label: <span style={{ marginLeft: 22 }}>Stock</span>,
    // Only as wide as a ticker + elided company name needs; any more and it opens
    // a dead gap that pushes every other column to the right.
    align: "left",
    width: "15%",
  },
  { key: "price", label: "Price", align: "right", width: "7%" },
  { key: "day", label: "Day", align: "right", width: "7%" },
  { key: "run", label: "Run", align: "right", width: "7%" },
  // No sort: the sparkline has no single number to order by — 52W Range next to
  // it covers "where is this trading".
  { key: "trend", label: "Trend", align: "left", width: "11%", noSort: true },
  { key: "range", label: "52W Range", align: "left", width: "11%" },
  // Extra right padding here and extra left padding on MOM below open up the
  // faint divider that separates the price block from the factor block.
  {
    key: "target",
    label: "Target buy",
    align: "right",
    width: "7%",
    padding: "8px 24px 8px 10px",
    cellPadding: "9px 24px 9px 10px",
  },
  ...SCORE_TABLE_COLS,
  // Deep left padding sets the news chip well clear of the RSK pill, and the wider
  // column pulls everything to its left further left.
  {
    key: "signals",
    label: "News",
    align: "left",
    noSort: true,
    width: "18%",
    padding: NEWS_HEAD_PAD,
    cellPadding: NEWS_CELL_PAD,
  },
];

// Faint vertical rule marking a group boundary between columns.
const DIVIDER = "1px solid rgba(148,163,184,0.18)";

// Cards have no column headers to click, so mobile gets its own sort chips.
// Price/trend keys only — the four factor scores are shown on the card but not
// offered as sorts, to keep the chip row to a single line.
const MOBILE_SORTS = [
  { key: "day", label: "Day" },
  { key: "price", label: "Price" },
  { key: "name", label: "Name" },
  { key: "range", label: "52W" },
  { key: "run", label: "Run" },
];

// ── Mobile card ───────────────────────────────────────────────────────────────
// One card per holding, replacing the (horizontally scrolling) table row on
// phones. Tapping the card points the news panel below at this share; the
// ticker/name block is a link through to the company page.
function WatchlistCard({
  row,
  price,
  live,
  dayChange,
  rangePosition,
  selected,
  listName,
  onRemove,
  onPickNews,
}) {
  const hasNews = !!(row.rns_count || row.news_count);
  return (
    <div
      onClick={onPickNews}
      style={{
        background: selected ? "rgba(249,115,22,0.07)" : "#131c2e",
        border: "1px solid #24314a",
        borderLeft: `3px solid ${selected ? "#f97316" : "#24314a"}`,
        borderRadius: 8,
        padding: "11px 13px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        fontFamily: "monospace",
        cursor: "pointer",
      }}
    >
      {/* Ticker + name on the left, price + day move on the right */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <button
          title={`Remove from "${listName || "list"}"`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "#f59e0b",
            fontSize: 18,
            lineHeight: 1,
            padding: "2px 2px 0 0",
            flexShrink: 0,
          }}
        >
          ★
        </button>
        <Link
          prefetch={false}
          href={companyHref(row.symbol)}
          onClick={(e) => e.stopPropagation()}
          style={{ minWidth: 0, flex: 1, textDecoration: "none", color: "inherit" }}
        >
          <div style={{ color: "#e5e5e5", fontWeight: 700, fontSize: 14 }}>
            {row.symbol.replace(".L", "")}
          </div>
          <div
            style={{
              color: "#64748b",
              fontSize: 11,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              marginTop: 2,
            }}
          >
            {row.name}
          </div>
        </Link>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <div style={{ color: "#f1f5f9", fontWeight: 700, fontSize: 15 }}>
            {live && (
              <span
                title="Live (yfinance, 60s cache)"
                style={{ marginRight: 4, fontSize: 8, color: "#10b981", verticalAlign: "middle" }}
              >
                ●
              </span>
            )}
            {fmtPounds(price)}
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "flex-end",
              gap: 6,
              marginTop: 3,
            }}
          >
            <StreakBadge streak={row.streak} />
            <span style={{ color: pctColor(dayChange), fontWeight: 700, fontSize: 12 }}>
              {dayChange == null
                ? "—"
                : `${dayChange >= 0 ? "+" : ""}${dayChange.toFixed(2)}%`}
            </span>
          </div>
        </div>
      </div>

      {/* 3-month trend + where the price sits in its 52-week range */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          borderTop: "1px solid #1e293b",
          paddingTop: 9,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ color: "#475569", fontSize: 9, fontWeight: 700 }}>3M</span>
          <Sparkline points={row.spark} width={88} height={26} />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: "auto" }}>
          <span style={{ color: "#475569", fontSize: 9, fontWeight: 700 }}>52W</span>
          <RangeBar pos={rangePosition} />
        </div>
      </div>

      {/* News for the last 7 days + the four factor scores. Wraps to two lines
          on the narrowest phones rather than squashing the pills. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          rowGap: 12,
          flexWrap: "wrap",
          borderTop: "1px solid #1e293b",
          paddingTop: 9,
        }}
      >
        {hasNews ? (
          <NewsCluster
            rnsCount={row.rns_count}
            rnsLatest={row.rns_latest}
            pressCount={row.news_count}
            onClick={(e) => {
              e.stopPropagation();
              onPickNews();
            }}
          />
        ) : (
          <span style={{ color: "#475569", fontSize: 10 }}>no news in 7d</span>
        )}
        <div style={{ marginLeft: "auto" }}>
          <ScoreStrip snap={row} align="right" />
        </div>
      </div>
    </div>
  );
}

export default function WatchlistTab({
  watchlists,
  onCreateList,
  onRenameList,
  onDeleteList,
  onAddSymbol,
  onRemoveSymbol,
  onSelect,
}) {
  const lists = watchlists?.lists || [];
  const members = watchlists?.members || {};
  const [activeId, setActiveId] = useState(DEFAULT_LIST_ID);

  // Fall back to the default list if the active one was deleted.
  useEffect(() => {
    if (!lists.some((l) => l.id === activeId)) setActiveId(DEFAULT_LIST_ID);
  }, [lists, activeId]);

  const activeList = lists.find((l) => l.id === activeId) || lists[0];
  const isDefault = activeList?.id === DEFAULT_LIST_ID;

  const symbols = useMemo(
    () => [...new Set(members[activeId] || [])],
    [members, activeId],
  );
  const counts = useMemo(() => {
    const c = {};
    for (const l of lists) c[l.id] = (members[l.id] || []).length;
    return c;
  }, [lists, members]);

  const createList = () => {
    const name = (window.prompt("Name for the new watchlist:") || "").trim();
    if (name) setActiveId(onCreateList(name));
  };
  const renameList = () => {
    if (!activeList || isDefault) return;
    const name = (window.prompt("Rename watchlist:", activeList.name) || "").trim();
    if (name) onRenameList(activeList.id, name);
  };
  const deleteList = () => {
    if (!activeList || isDefault) return;
    if (window.confirm(`Delete "${activeList.name}"? Its stocks are removed from this list only.`)) {
      onDeleteList(activeList.id);
      setActiveId(DEFAULT_LIST_ID);
    }
  };
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [liveQuotes, setLiveQuotes] = useState({});
  const [targets, setTargets] = useState(() => loadTargets());
  const [sortCol, setSortCol] = useState("day");
  const [sortDir, setSortDir] = useState("desc");
  // Which share the news panel is showing — defaults to the first in the list,
  // changed by clicking a row's News cell.
  const [selectedNewsSymbol, setSelectedNewsSymbol] = useState(null);

  // Default the news panel to the first share; keep it valid as the list changes.
  useEffect(() => {
    if (symbols.length === 0) {
      setSelectedNewsSymbol(null);
    } else if (!selectedNewsSymbol || !symbols.includes(selectedNewsSymbol)) {
      setSelectedNewsSymbol(symbols[0]);
    }
  }, [symbols, selectedNewsSymbol]);

  // Enriched per-stock data — refetched whenever the watchlist changes.
  useEffect(() => {
    if (symbols.length === 0) {
      setRows([]);
      return;
    }
    setLoading(true);
    let cancelled = false;
    fetch(`${API}/watchlist?symbols=${encodeURIComponent(symbols.join(","))}`)
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled) {
          setRows(Array.isArray(d) ? d : []);
          setLoading(false);
        }
      })
      .catch(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [symbols]);

  // Live last-price poll (pence). Only polls during LSE trading hours (08:00–16:30
  // London, Mon–Fri) and only when the tab is visible. Pauses in background tabs
  // and resumes with an immediate fetch when the user switches back.
  useEffect(() => {
    if (symbols.length === 0) {
      setLiveQuotes({});
      return;
    }
    let cancelled = false;
    const fetchQuotes = () => {
      if (document.hidden || !lseStatus().open) return;
      fetch(`${API}/quotes?symbols=${encodeURIComponent(symbols.join(","))}`)
        .then((r) => r.json())
        .then((d) => {
          if (!cancelled && d && typeof d === "object") setLiveQuotes(d);
        })
        .catch(() => {});
    };
    fetchQuotes();
    const id = setInterval(fetchQuotes, 5 * 60 * 1000);
    const onVisible = () => fetchQuotes();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [symbols]);

  const setTarget = (symbol, value) => {
    setTargets((prev) => {
      const next = { ...prev };
      const num = parseFloat(value);
      if (!Number.isFinite(num) || num <= 0) delete next[symbol];
      else next[symbol] = num;
      saveTargets(next);
      return next;
    });
  };

  // Derived per-row values (live price overrides last close where available).
  const priceOf = (r) => {
    const live = liveQuotes[r.symbol];
    return live != null ? live : r.current_price;
  };
  const isLive = (r) => liveQuotes[r.symbol] != null;
  const dayPct = (r) => {
    const p = priceOf(r);
    // A live quote from a session the stored history doesn't have yet must be
    // measured against the last close — using prev_close (two sessions back)
    // showed a two-day move as "today's" change.
    const base =
      isLive(r) && r.latest_close_date && latestSessionDate() > r.latest_close_date
        ? r.current_price
        : r.prev_close;
    if (p == null || !base) return null;
    return (p / base - 1) * 100;
  };
  const rangePos = (r) => {
    const p = priceOf(r);
    if (p == null || r.high_52w == null || r.low_52w == null) return null;
    const span = r.high_52w - r.low_52w;
    if (span <= 0) return null;
    return ((p - r.low_52w) / span) * 100;
  };
  const targetGap = (r) => {
    const t = targets[r.symbol];
    const p = priceOf(r);
    if (t == null || p == null) return null;
    return p / 100 / t - 1;
  };

  const sortVal = (r) => {
    switch (sortCol) {
      case "name":
        return r.name || r.symbol;
      case "price":
        return priceOf(r);
      case "day":
        return dayPct(r);
      case "run":
        return r.streak;
      case "target":
        return targetGap(r);
      case "range":
        return rangePos(r);
      default:
        // The four factor columns are keyed by their field name (momentum_score,
        // quality_score, value_score, risk_score).
        return sortCol.endsWith("_score") ? r[sortCol] : null;
    }
  };

  const sorted = useMemo(() => {
    const arr = [...rows];
    arr.sort((a, b) => {
      const va = sortVal(a);
      const vb = sortVal(b);
      // Nulls always sink to the bottom regardless of direction.
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "string")
        return sortDir === "asc"
          ? va.localeCompare(vb)
          : vb.localeCompare(va);
      return sortDir === "asc" ? va - vb : vb - va;
    });
    return arr;
  }, [rows, sortCol, sortDir, liveQuotes, targets]);

  const toggleSort = (key) => {
    if (key === sortCol) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortCol(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  };

  const allSymbolSet = useMemo(() => new Set(symbols), [symbols]);

  // Phones/small tablets get cards instead of the horizontally scrolling table.
  const isMobile = useIsMobile();

  return (
    <div>
      <PageHeader
        title="Watchlists"
        subtitle="Track and compare the stocks you're following, with live prices and notes."
        // The count lives on the list tab's pill, so the header only reports
        // the in-flight fetch.
        right={
          loading ? (
            <span style={{ color: "#64748b", fontSize: 12, fontFamily: "monospace" }}>
              loading…
            </span>
          ) : null
        }
      />

      {/* List tabs + management + add-stock box */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 16,
          paddingBottom: 14,
          borderBottom: "1px solid #1e1e1e",
        }}
      >
        <ListTabs
          lists={lists}
          activeId={activeId}
          onSelect={setActiveId}
          counts={counts}
        />
        <button
          onClick={createList}
          title="Create a new watchlist"
          style={{
            background: "#1a1a1a",
            color: "#f97316",
            border: "1px dashed #f9731677",
            borderRadius: 999,
            padding: "5px 13px",
            fontSize: 12,
            fontWeight: 700,
            fontFamily: "monospace",
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          + New list
        </button>
        {!isDefault && (
          <div style={{ display: "flex", gap: 6 }}>
            <button
              onClick={renameList}
              title="Rename this list"
              style={{
                background: "none",
                border: "1px solid #2a2a2a",
                borderRadius: 4,
                color: "#94a3b8",
                cursor: "pointer",
                fontSize: 12,
                padding: "4px 8px",
              }}
            >
              Rename
            </button>
            <button
              onClick={deleteList}
              title="Delete this list"
              style={{
                background: "none",
                border: "1px solid #2a2a2a",
                borderRadius: 4,
                color: "#f87171",
                cursor: "pointer",
                fontSize: 12,
                padding: "4px 8px",
              }}
            >
              Delete
            </button>
          </div>
        )}
        <AddStockBox
          onAdd={(sym) => onAddSymbol(activeId, sym)}
          existing={allSymbolSet}
        />
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          alignItems: "stretch",
        }}
      >
        <div style={{ flex: "1 1 auto", minWidth: 0 }}>
      {symbols.length === 0 ? (
        <div
          style={{
            background: "#111",
            border: "1px solid #1e1e1e",
            borderRadius: 3,
            padding: "48px 24px",
            textAlign: "center",
            color: "#555",
            fontFamily: "monospace",
            fontSize: 13,
          }}
        >
          {isDefault
            ? "This list is empty. Use the search box above to add stocks, or tap the ☆ next to any stock in the Screener."
            : "This list is empty. Use the search box above to add stocks."}
        </div>
      ) : isMobile ? (
        <>
          {/* Sort chips — the cards have no clickable column headers. */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              flexWrap: "wrap",
              marginBottom: 12,
            }}
          >
            <span
              style={{
                color: "#475569",
                fontSize: 9,
                fontWeight: 700,
                fontFamily: "monospace",
                letterSpacing: 0.5,
              }}
            >
              SORT
            </span>
            {MOBILE_SORTS.map((s) => {
              const active = s.key === sortCol;
              return (
                <button
                  key={s.key}
                  onClick={() => toggleSort(s.key)}
                  style={{
                    background: active ? "rgba(249,115,22,0.15)" : "#131c2e",
                    color: active ? "#fbbf24" : "#94a3b8",
                    border: `1px solid ${active ? "#f9731677" : "#24314a"}`,
                    borderRadius: 999,
                    padding: "4px 10px",
                    fontSize: 11,
                    fontWeight: 700,
                    fontFamily: "monospace",
                    cursor: "pointer",
                  }}
                >
                  {s.label}
                  {active ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                </button>
              );
            })}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {sorted.map((r) => (
              <WatchlistCard
                key={r.symbol}
                row={r}
                price={priceOf(r)}
                live={isLive(r)}
                dayChange={dayPct(r)}
                rangePosition={rangePos(r)}
                selected={r.symbol === selectedNewsSymbol}
                listName={activeList?.name}
                onRemove={() =>
                  onRemoveSymbol && onRemoveSymbol(activeId, r.symbol)
                }
                onPickNews={() => setSelectedNewsSymbol(r.symbol)}
              />
            ))}
          </div>
        </>
      ) : (
        <div
          style={{
            overflow: "auto",
            maxHeight: "calc(100vh - 245px)",
            scrollbarGutter: "stable",
          }}
        >
            <table
              style={{
                borderCollapse: "separate",
                borderSpacing: 0,
                fontSize: 12,
                fontFamily: "monospace",
                // Match the full-width news panel below, with COLS' percentage
                // widths deciding the spacing.
                tableLayout: "fixed",
                width: "100%",
              }}
            >
              <thead>
                <tr>
                  {COLS.map((c) => {
                    const active = c.key === sortCol;
                    return (
                      <th
                        key={c.key}
                        title={c.title}
                        onClick={c.noSort ? undefined : () => toggleSort(c.key)}
                        style={{
                          ...S.th,
                          width: c.width,
                          ...(c.padding ? { padding: c.padding } : {}),
                          borderLeft: c.divider ? DIVIDER : undefined,
                          textAlign: c.align,
                          cursor: c.noSort ? "default" : "pointer",
                          color: active ? "#fbbf24" : "#f97316",
                        }}
                      >
                        {c.label}
                        {active ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {sorted.map((r, i) => {
                  const dp = dayPct(r);
                  const live = isLive(r);
                  const baseBg = i % 2 === 0 ? "#1e293b" : "#162032";
                  return (
                    <tr
                      key={r.symbol}
                      onClick={() => onSelect && onSelect(r.symbol)}
                      style={{ cursor: "pointer", background: baseBg }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.background = "#334155")
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.background = baseBg)
                      }
                    >
                      {/* Stock — star + symbol + name */}
                      <td style={S.td}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <button
                            title={`Remove from "${activeList?.name || "list"}"`}
                            onClick={(e) => {
                              e.stopPropagation();
                              onRemoveSymbol && onRemoveSymbol(activeId, r.symbol);
                            }}
                            style={{
                              background: "none",
                              border: "none",
                              cursor: "pointer",
                              color: "#f59e0b",
                              fontSize: 14,
                              lineHeight: 1,
                              padding: 0,
                            }}
                          >
                            ★
                          </button>
                          <Link
                            prefetch={false}
                            href={companyHref(r.symbol)}
                            onClick={(e) => e.stopPropagation()}
                            style={{ minWidth: 0, textDecoration: "none", color: "inherit" }}
                          >
                            <div
                              style={{
                                color: "#e5e5e5",
                                fontWeight: 700,
                              }}
                            >
                              {r.symbol.replace(".L", "")}
                            </div>
                            <div
                              style={{
                                color: "#64748b",
                                fontSize: 10,
                                maxWidth: 200,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {r.name}
                            </div>
                          </Link>
                        </div>
                      </td>

                      {/* Price */}
                      <td style={{ ...S.td, textAlign: "right" }}>
                        {live && (
                          <span
                            title="Live (yfinance, 60s cache)"
                            style={{ marginRight: 4, fontSize: 9, color: "#10b981" }}
                          >
                            ●
                          </span>
                        )}
                        <span style={{ color: "#f1f5f9", fontWeight: 700 }}>
                          {fmtPounds(priceOf(r))}
                        </span>
                      </td>

                      {/* Day change % */}
                      <td
                        style={{
                          ...S.td,
                          textAlign: "right",
                          color: pctColor(dp),
                          fontWeight: 700,
                        }}
                      >
                        {dp == null
                          ? "—"
                          : `${dp >= 0 ? "+" : ""}${dp.toFixed(2)}%`}
                      </td>

                      {/* Trend run — consecutive up/down days */}
                      <td style={{ ...S.td, textAlign: "right" }}>
                        {r.streak ? (
                          <StreakBadge streak={r.streak} />
                        ) : (
                          <span style={{ color: "#3a3a3a" }}>—</span>
                        )}
                      </td>

                      {/* 3-month sparkline */}
                      <td style={S.td}>
                        <Sparkline points={r.spark} width={SPARK_W} fluid />
                      </td>

                      {/* 52-week range position */}
                      <td style={S.td}>
                        <RangeBar pos={rangePos(r)} fluid />
                      </td>

                      {/* Target buy */}
                      <td
                        style={{
                          ...S.td,
                          textAlign: "right",
                          padding: "9px 24px 9px 10px",
                        }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <TargetCell
                          symbol={r.symbol}
                          target={targets[r.symbol]}
                          price={priceOf(r)}
                          onCommit={setTarget}
                        />
                      </td>

                      {/* MOM / QUAL / VAL / RSK — same pills as the company header */}
                      {SCORE_TABLE_COLS.map((c) => (
                        <td
                          key={c.key}
                          title={c.title}
                          style={{
                            ...S.td,
                            textAlign: "center",
                            padding: c.cellPadding,
                            borderLeft: c.divider ? DIVIDER : undefined,
                          }}
                        >
                          <ScorePill value={r[c.key]} invert={c.invert} />
                        </td>
                      ))}

                      {/* News — click to load this share's news in the panel */}
                      <td
                        title="Show this share's news in the panel"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedNewsSymbol(r.symbol);
                        }}
                        style={{
                          ...S.td,
                          padding: NEWS_CELL_PAD,
                          cursor: "pointer",
                          // The selection marker is drawn by the overlay below, not
                          // as a border here: a border sits on the column edge, hard
                          // against the RSK pill, where no amount of padding moves it.
                          position: "relative",
                        }}
                      >
                        {r.symbol === selectedNewsSymbol && (
                          <span
                            aria-hidden="true"
                            style={{
                              position: "absolute",
                              left: NEWS_MARK_LEFT,
                              right: 0,
                              top: 0,
                              bottom: 0,
                              borderLeft: "3px solid #f97316",
                              background: "rgba(249,115,22,0.08)",
                              pointerEvents: "none",
                            }}
                          />
                        )}
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            flexWrap: "wrap",
                            // Sits above the marker overlay (both auto z-index, so
                            // DOM order decides).
                            position: "relative",
                          }}
                        >
                          <NewsCluster
                            rnsCount={r.rns_count}
                            rnsLatest={r.rns_latest}
                            pressCount={r.news_count}
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedNewsSymbol(r.symbol);
                            }}
                          />
                          {!r.rns_count && !r.news_count && (
                            <span style={{ color: "#64748b", fontSize: 11 }}>
                              view ›
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
        </div>
      )}
        </div>

        <NewsPanel
          symbol={selectedNewsSymbol}
          name={
            rows.find((r) => r.symbol === selectedNewsSymbol)?.name ||
            (selectedNewsSymbol ? selectedNewsSymbol.replace(".L", "") : "")
          }
        />
      </div>
    </div>
  );
}
