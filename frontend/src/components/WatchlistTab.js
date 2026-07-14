"use client";
import { useState, useEffect, useMemo, useRef } from "react";
import { API } from "@/lib/api";
import { loadTargets, saveTargets, DEFAULT_LIST_ID } from "@/lib/storage";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useIsAdmin } from "@/hooks/useAdmin";
import { lseStatus, latestSessionDate } from "@/lib/lse";
import PageHeader from "@/components/layout/PageHeader";

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
// (or always, with refresh=true). Sits right of the table on wide screens,
// underneath on narrow ones.
function NewsPanel({ symbol, name, sideBySide }) {
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
        // Grow into whatever room the table leaves (e.g. when the sidebar is
        // closed), down to a sensible minimum. Full width when stacked.
        flex: sideBySide ? "1 1 360px" : "0 0 auto",
        minWidth: sideBySide ? 320 : "auto",
        background: "#0d0d0d",
        border: "1px solid #1e1e1e",
        borderRadius: 3,
        display: "flex",
        flexDirection: "column",
        maxHeight: sideBySide ? "calc(100vh - 245px)" : 520,
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

  const allSymbolSet = useMemo(() => new Set(symbols), [symbols]);

  // Side-by-side once there's room; the news panel stacks underneath below this.
  const sideBySide = useMediaQuery("(min-width: 1280px)");

  return (
    <div>
      <PageHeader
        title="Watchlists"
        subtitle="Track and compare the stocks you're following, with live prices and notes."
        right={
          <span style={{ color: "#64748b", fontSize: 12, fontFamily: "monospace" }}>
            {symbols.length === 0
              ? "no stocks in this list"
              : `${symbols.length} in list${loading ? " · loading…" : ""}`}
          </span>
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
        <div style={{ marginLeft: "auto" }}>
          <AddStockBox
            onAdd={(sym) => onAddSymbol(activeId, sym)}
            existing={allSymbolSet}
          />
        </div>
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: sideBySide ? "row" : "column",
          gap: 16,
          alignItems: "stretch",
        }}
      >
        <div
          style={{
            // When populated, size to the table's content so the news panel can
            // claim the rest of the row (and grow when the sidebar closes). When
            // empty, let the placeholder fill the width instead.
            flex: sideBySide
              ? symbols.length
                ? "0 1 auto"
                : "1 1 auto"
              : "1 1 auto",
            minWidth: 0,
          }}
        >
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

                      {/* News — click to load this share's news in the panel */}
                      <td
                        title="Show this share's news in the panel"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedNewsSymbol(r.symbol);
                        }}
                        style={{
                          ...S.td,
                          cursor: "pointer",
                          borderLeft: `3px solid ${
                            r.symbol === selectedNewsSymbol ? "#f97316" : "transparent"
                          }`,
                          background:
                            r.symbol === selectedNewsSymbol
                              ? "rgba(249,115,22,0.08)"
                              : undefined,
                        }}
                      >
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

        <NewsPanel
          symbol={selectedNewsSymbol}
          name={
            rows.find((r) => r.symbol === selectedNewsSymbol)?.name ||
            (selectedNewsSymbol ? selectedNewsSymbol.replace(".L", "") : "")
          }
          sideBySide={sideBySide}
        />
      </div>
    </div>
  );
}
