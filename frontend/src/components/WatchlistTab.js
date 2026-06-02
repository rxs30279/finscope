import { useState, useEffect, useMemo } from "react";
import { API, loadTargets, saveTargets } from "../utils";

// Prices are stored in pence (LSE convention) — show as pounds.
const fmtPounds = (pence) =>
  pence == null ? "—" : `£${(pence / 100).toFixed(2)}`;

const pctColor = (v) =>
  v == null ? "#64748b" : v > 0.05 ? "#10b981" : v < -0.05 ? "#ef4444" : "#94a3b8";

const riskColor = (s) =>
  s == null
    ? "#444"
    : s <= 3
      ? "#4ade80"
      : s <= 6
        ? "#fbbf24"
        : "#f87171";
const riskBg = (s) =>
  s == null ? "transparent" : s <= 3 ? "#14532d" : s <= 6 ? "#78350f" : "#7f1d1d";

// Investegate-style tier colours, reused for the RNS signal badge.
const TIER_COLOR = { A: "#f87171", B: "#fbbf24", C: "#94a3b8" };

const S = {
  th: {
    textAlign: "left",
    padding: "8px 18px",
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
    padding: "9px 18px",
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
function Sparkline({ points, width = 76, height = 26 }) {
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
      width={width}
      height={height}
      style={{ display: "block", flexShrink: 0 }}
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
function RangeBar({ pos }) {
  if (pos == null)
    return <span style={{ color: "#444", fontSize: 11 }}>—</span>;
  const clamped = Math.max(0, Math.min(100, pos));
  const color =
    clamped >= 66 ? "#10b981" : clamped >= 33 ? "#f59e0b" : "#ef4444";
  return (
    <div
      title={`${clamped.toFixed(0)}% of 52-week range`}
      style={{ display: "flex", alignItems: "center", gap: 8 }}
    >
      <div
        style={{
          width: 64,
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

// ── Main component ────────────────────────────────────────────────────────────
const COLS = [
  {
    key: "name",
    // Indent past the row's ★ button (icon + gap) so the header lines up with the ticker.
    label: <span style={{ marginLeft: 22 }}>Stock</span>,
    align: "left",
  },
  { key: "price", label: "Price", align: "right" },
  { key: "day", label: "Day", align: "right" },
  { key: "run", label: "Run", align: "right" },
  {
    key: "range",
    label: (
      <span style={{ display: "inline-flex", gap: 12 }}>
        <span style={{ width: 76, display: "inline-block" }}>Trend</span>
        <span>52W Range</span>
      </span>
    ),
    align: "left",
  },
  { key: "target", label: "Target buy", align: "right" },
  { key: "signals", label: "News", align: "left", noSort: true },
  { key: "risk", label: "Risk", align: "right" },
];

export default function WatchlistTab({ watchlist, onToggleWatchlist, onSelect }) {
  const symbols = useMemo(
    () => [...(watchlist instanceof Set ? watchlist : new Set(watchlist || []))],
    [watchlist],
  );
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [liveQuotes, setLiveQuotes] = useState({});
  const [targets, setTargets] = useState(() => loadTargets());
  const [sortCol, setSortCol] = useState("day");
  const [sortDir, setSortDir] = useState("desc");

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

  // Live last-price poll (pence), same cadence/endpoint as the old watchlist.
  useEffect(() => {
    if (symbols.length === 0) {
      setLiveQuotes({});
      return;
    }
    let cancelled = false;
    const fetchQuotes = () => {
      fetch(`${API}/quotes?symbols=${encodeURIComponent(symbols.join(","))}`)
        .then((r) => r.json())
        .then((d) => {
          if (!cancelled && d && typeof d === "object") setLiveQuotes(d);
        })
        .catch(() => {});
    };
    fetchQuotes();
    const id = setInterval(fetchQuotes, 60000);
    return () => {
      cancelled = true;
      clearInterval(id);
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
    if (p == null || !r.prev_close) return null;
    return (p / r.prev_close - 1) * 100;
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
      case "risk":
        return r.risk_score;
      default:
        return null;
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

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: "DM Serif Display,serif",
            fontSize: 24,
            color: "#f1f5f9",
          }}
        >
          Watchlist
        </h2>
        <span style={{ color: "#64748b", fontSize: 12, fontFamily: "monospace" }}>
          {symbols.length === 0
            ? "no stocks saved"
            : `${symbols.length} saved${loading ? " · loading…" : ""}`}
        </span>
      </div>

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
          Your watchlist is empty. Tap the ☆ next to any stock in the Screener to
          add it here.
        </div>
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
                tableLayout: "auto",
              }}
            >
              <thead>
                <tr>
                  {COLS.map((c) => {
                    const active = c.key === sortCol;
                    return (
                      <th
                        key={c.key}
                        onClick={c.noSort ? undefined : () => toggleSort(c.key)}
                        style={{
                          ...S.th,
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
                            title="Remove from watchlist"
                            onClick={(e) => {
                              e.stopPropagation();
                              onToggleWatchlist && onToggleWatchlist(r.symbol);
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
                          <div style={{ minWidth: 0 }}>
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
                          </div>
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

                      {/* 3-month sparkline + 52-week range position */}
                      <td style={S.td}>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 12,
                          }}
                        >
                          <Sparkline points={r.spark} />
                          <RangeBar pos={rangePos(r)} />
                        </div>
                      </td>

                      {/* Target buy */}
                      <td
                        style={{ ...S.td, textAlign: "right" }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <TargetCell
                          symbol={r.symbol}
                          target={targets[r.symbol]}
                          price={priceOf(r)}
                          onCommit={setTarget}
                        />
                      </td>

                      {/* News (RNS + press combined) */}
                      <td style={S.td}>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            flexWrap: "wrap",
                          }}
                        >
                          <NewsCluster
                            rnsCount={r.rns_count}
                            rnsLatest={r.rns_latest}
                            pressCount={r.news_count}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelect && onSelect(r.symbol, "news");
                            }}
                          />
                          {!r.rns_count && !r.news_count && (
                            <span style={{ color: "#3a3a3a" }}>—</span>
                          )}
                        </div>
                      </td>

                      {/* Risk */}
                      <td style={{ ...S.td, textAlign: "right" }}>
                        {r.risk_score == null ? (
                          <span style={{ color: "#444" }}>—</span>
                        ) : (
                          <span
                            style={{
                              display: "inline-block",
                              minWidth: 22,
                              textAlign: "center",
                              padding: "2px 6px",
                              borderRadius: 4,
                              fontWeight: 700,
                              background: riskBg(r.risk_score),
                              color: riskColor(r.risk_score),
                            }}
                          >
                            {r.risk_score}
                          </span>
                        )}
                      </td>
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
