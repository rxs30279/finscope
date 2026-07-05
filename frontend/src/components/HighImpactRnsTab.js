"use client";
import { Fragment, useState, useEffect, useMemo, useRef, useCallback } from "react";
import { API, adminHeaders } from "@/lib/api";
import { useIsAdmin } from "@/hooks/useAdmin";
import { lseStatus } from "@/lib/lse";
import PageHeader from "@/components/layout/PageHeader";
import ScorePill from "@/components/screener/ScorePill";

// ── formatting ────────────────────────────────────────────────────────────────
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

// Absolute calendar date, e.g. "1 Jul 26" — the anchor date of the impact story.
const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" });
};

// Prices are stored in pence (LSE convention) — show as pounds.
const fmtPounds = (pence) =>
  pence == null ? "—" : `£${(pence / 100).toFixed(2)}`;

const pctColor = (v) =>
  v == null ? "#64748b" : v > 0.05 ? "#10b981" : v < -0.05 ? "#ef4444" : "#94a3b8";

const TIER_COLOR = { A: "#f87171", B: "#fbbf24", C: "#94a3b8" };

const VET_STYLE = {
  include: { color: "#10b981", bg: "#0d2318", label: "vet: include" },
  caution: { color: "#f59e0b", bg: "#2a1c00", label: "vet: caution" },
  exclude: { color: "#ef4444", bg: "#2a0d0d", label: "vet: exclude" },
};

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

// ── small pieces ──────────────────────────────────────────────────────────────
function IndexBadge({ index }) {
  if (!index) return null;
  return (
    <span
      title={index}
      style={{
        fontSize: 8.5,
        fontWeight: 700,
        color: "#93c5fd",
        background: "#0d1a2a",
        border: "1px solid #1e3a5f",
        borderRadius: 2,
        padding: "1px 4px",
        letterSpacing: 0.3,
        whiteSpace: "nowrap",
      }}
    >
      {index.replace("FTSE ", "")}
    </span>
  );
}

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

// AI (LLM) score, coloured on the RNS page's bands.
function ScoreCell({ value }) {
  if (value == null) return <span style={{ color: "#333" }}>—</span>;
  const colour =
    value >= 75 ? "#f97316" : value >= 50 ? "#60a5fa" : value >= 25 ? "#94a3b8" : "#555";
  return (
    <span
      title="AI significance score (0–100)"
      style={{
        color: colour,
        fontFamily: "monospace",
        fontSize: 12,
        fontWeight: 700,
      }}
    >
      AI {value}
    </span>
  );
}

// Post-selection news tally: positives ▲ vs negatives ▼ since we started tracking.
// A red ▼ count is the "watch out" signal (e.g. a CEO exit after the good story).
function FollowupTally({ pos, neg, expanded, onToggle }) {
  const has = pos || neg;
  return (
    <span
      onClick={(e) => {
        e.stopPropagation();
        if (has) onToggle();
      }}
      title={has ? "Show subsequent announcements" : "No news since tracking began"}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        cursor: has ? "pointer" : "default",
        fontWeight: 700,
      }}
    >
      <span style={{ color: pos ? "#10b981" : "#3a3a3a" }}>{pos || 0}▲</span>
      <span style={{ color: neg ? "#ef4444" : "#3a3a3a" }}>{neg || 0}▼</span>
      {has && (
        <span style={{ color: "#64748b", fontSize: 9 }}>{expanded ? "▾" : "▸"}</span>
      )}
    </span>
  );
}

// Trend line over the last ~3 months. The segment SINCE the pick was selected
// (the last `sinceCount` closes) is drawn in a gain/loss colour — green if up
// since selection, red if down — with a dot marking the selection point, so you
// can see at a glance how the stock has moved since the story.
function Sparkline({ points, sinceCount = 0, sinceUp = null, width = 84, height = 26 }) {
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
  const toPath = (arr) =>
    arr.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  // Split at the selection point; share the junction so the two lines connect.
  const sc = Math.max(0, Math.min(n - 1, sinceCount || 0));
  const splitIdx = sc > 0 ? n - sc : n;
  const before = coords.slice(0, Math.min(splitIdx + 1, n));
  const since = sc > 0 ? coords.slice(splitIdx) : [];
  const baseColor = "#6366f1";
  const sinceColor = sinceUp == null ? "#94a3b8" : sinceUp ? "#10b981" : "#ef4444";
  const area =
    `M${coords[0][0].toFixed(1)},${height} ` +
    coords.map(([x, y]) => `L${x.toFixed(1)},${y.toFixed(1)}`).join(" ") +
    ` L${coords[n - 1][0].toFixed(1)},${height} Z`;
  return (
    <svg width={width} height={height} style={{ display: "block", flexShrink: 0 }} title="Price — coloured since selection">
      <path d={area} fill={baseColor} opacity={0.1} />
      {before.length >= 2 && (
        <path d={toPath(before)} fill="none" stroke={baseColor} strokeWidth={1.25} strokeLinejoin="round" strokeLinecap="round" />
      )}
      {since.length >= 2 && (
        <path d={toPath(since)} fill="none" stroke={sinceColor} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
      )}
      {sc > 0 && splitIdx < n && (
        <circle cx={coords[splitIdx][0]} cy={coords[splitIdx][1]} r={1.7} fill={sinceColor} />
      )}
    </svg>
  );
}

function RangeBar({ pos }) {
  if (pos == null) return <span style={{ color: "#444", fontSize: 11 }}>—</span>;
  const clamped = Math.max(0, Math.min(100, pos));
  const color = clamped >= 66 ? "#10b981" : clamped >= 33 ? "#f59e0b" : "#ef4444";
  return (
    <div
      title={`${clamped.toFixed(0)}% of 52-week range`}
      style={{ display: "flex", alignItems: "center", gap: 8 }}
    >
      <div style={{ width: 64, height: 8, background: "#0b1120", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${clamped}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ color, fontSize: 10, fontWeight: 700 }}>{clamped.toFixed(0)}%</span>
    </div>
  );
}

// ── news panel (single selected share) ────────────────────────────────────────
function NewsPanel({ symbol, name, sideBySide }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const reqRef = useRef("");

  useEffect(() => {
    reqRef.current = symbol || "";
    if (!symbol) {
      setItems([]);
      return;
    }
    setLoading(true);
    fetch(`${API}/news/${encodeURIComponent(symbol)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (reqRef.current !== symbol) return;
        const rns = (d?.rns || []).map((r) => ({
          kind: "rns", headline: r.headline, tier: r.tier,
          category: r.category, published_at: r.published_at, url: r.url,
        }));
        const press = (d?.google || []).map((g) => ({
          kind: "press", headline: g.title, source: g.source,
          published_at: g.published_at, url: g.link,
        }));
        setItems(
          [...rns, ...press].sort(
            (a, b) => new Date(b.published_at || 0) - new Date(a.published_at || 0),
          ),
        );
      })
      .catch(() => reqRef.current === symbol && setItems([]))
      .finally(() => reqRef.current === symbol && setLoading(false));
  }, [symbol]);

  const ticker = symbol ? symbol.replace(".L", "") : "";
  return (
    <div
      style={{
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
      <div style={{ padding: "10px 14px", borderBottom: "1px solid #1e1e1e", display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ color: "#f97316", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
          News
        </span>
        <span
          title={name || ticker}
          style={{ color: "#e2e8f0", fontFamily: "monospace", fontSize: 12, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          {symbol ? `${ticker}${name ? ` · ${name}` : ""}` : "—"}
        </span>
        {loading && <span style={{ color: "#475569", fontSize: 10, fontFamily: "monospace" }}>loading…</span>}
      </div>
      <div style={{ overflowY: "auto" }}>
        {items.length === 0 ? (
          <div style={{ padding: "28px 16px", textAlign: "center", color: "#475569", fontFamily: "monospace", fontSize: 12 }}>
            {!symbol ? "Select a stock to see its news." : loading ? "Loading news…" : "No recent news for this share."}
          </div>
        ) : (
          items.map((it, i) => {
            const isRns = it.kind === "rns";
            const accent = isRns ? TIER_COLOR[it.tier] || TIER_COLOR.C : "#3f4b5b";
            const meta = isRns ? (it.category || "").replace(/_/g, " ") : it.source || "";
            const baseBg = i % 2 ? "rgba(255,255,255,0.035)" : "transparent";
            const body = (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4, fontFamily: "monospace", fontSize: 9.5, letterSpacing: 0.3, color: "#64748b" }}>
                  <span style={{ color: isRns ? accent : "#7c8a9c", fontWeight: 700 }}>{isRns ? "RNS" : "PRESS"}</span>
                  {meta && <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{meta}</span>}
                  <span style={{ marginLeft: "auto", flexShrink: 0 }}>{fmtWhen(it.published_at)}</span>
                </div>
                <div style={{ color: "#f1f5f9", fontSize: 13, fontWeight: 500, lineHeight: 1.45 }}>{it.headline}</div>
              </>
            );
            const style = {
              display: "block", padding: "10px 14px", borderBottom: "1px solid #161616",
              borderLeft: `3px solid ${accent}`, background: baseBg,
              cursor: it.url ? "pointer" : "default", textDecoration: "none",
            };
            return it.url ? (
              <a key={`${it.kind}-${it.published_at}-${i}`} href={it.url} target="_blank" rel="noreferrer" style={style}>
                {body}
              </a>
            ) : (
              <div key={`${it.kind}-${it.published_at}-${i}`} style={style}>{body}</div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── admin approval card (pending candidates) ──────────────────────────────────
function PendingCard({ entry, onApprove, onReject }) {
  const st = entry.story || {};
  const vet = st.vet_verdict ? VET_STYLE[st.vet_verdict] : null;
  return (
    <div style={{ background: "#0f0f0f", border: "1px solid #262626", borderRadius: 4, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ color: "#f1f5f9", fontWeight: 700, fontFamily: "monospace" }}>
          {(entry.symbol || "").replace(".L", "")}
        </span>
        <IndexBadge index={entry.ftse_index} />
        <ScoreCell value={st.llm_score} />
        {vet && (
          <span title={st.vet_rationale || ""} style={{ color: vet.color, background: vet.bg, border: `1px solid ${vet.color}55`, borderRadius: 2, padding: "1px 6px", fontSize: 10, fontWeight: 700, fontFamily: "monospace" }}>
            {vet.label}
          </span>
        )}
        <span style={{ marginLeft: "auto", color: "#64748b", fontSize: 11, fontFamily: "monospace" }}>
          {fmtDate(st.published_at)}
        </span>
      </div>
      <a href={st.url} target="_blank" rel="noreferrer" style={{ color: "#e2e8f0", fontSize: 13, fontWeight: 600, textDecoration: "none", lineHeight: 1.4 }}>
        {st.headline}
      </a>
      {st.llm_thesis && <div style={{ color: "#94a3b8", fontSize: 12, lineHeight: 1.45 }}>{st.llm_thesis}</div>}
      {vet && st.vet_rationale && (
        <div style={{ color: vet.color, fontSize: 11.5, lineHeight: 1.45, opacity: 0.9 }}>
          <span style={{ fontWeight: 700 }}>Vet:</span> {st.vet_rationale}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 2 }}>
        <button onClick={() => onApprove(entry.showcase_id)} style={btn("#10b981")}>Approve</button>
        <button onClick={() => onReject(entry.showcase_id)} style={btn("#f87171")}>Reject</button>
      </div>
    </div>
  );
}

const btn = (color) => ({
  background: "transparent",
  border: `1px solid ${color}66`,
  color,
  borderRadius: 4,
  padding: "4px 12px",
  fontSize: 12,
  fontWeight: 700,
  fontFamily: "monospace",
  cursor: "pointer",
});

// ── columns ───────────────────────────────────────────────────────────────────
const COLS = [
  { key: "name", label: "Stock", align: "left" },
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
  { key: "date", label: "Date", align: "right" },
  { key: "days", label: "Days", align: "right" },
  { key: "m", label: "M", align: "center" },
  { key: "q", label: "Q", align: "center" },
  { key: "v", label: "V", align: "center" },
  { key: "r", label: "R", align: "center" },
  { key: "pct_news", label: "Since story", align: "right" },
  { key: "fu", label: "Since ±", align: "right", noSort: true },
  { key: "signals", label: "News", align: "left", noSort: true },
];

// ── main component ────────────────────────────────────────────────────────────
export default function HighImpactRnsTab({ onSelect }) {
  const isAdmin = useIsAdmin();

  const [rows, setRows] = useState([]);
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(true);
  const [liveQuotes, setLiveQuotes] = useState({});
  const [sortCol, setSortCol] = useState("pct_news");
  const [sortDir, setSortDir] = useState("desc");
  const [selectedNewsSymbol, setSelectedNewsSymbol] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const [refreshKey, setRefreshKey] = useState(0);

  const symbols = useMemo(() => rows.map((r) => r.symbol), [rows]);

  // Approved showcase (public) + pending candidates (admin only).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const jobs = [fetch(`${API}/showcase`).then((r) => (r.ok ? r.json() : []))];
    jobs.push(
      isAdmin
        ? fetch(`${API}/showcase/pending`, { headers: adminHeaders() }).then((r) => (r.ok ? r.json() : []))
        : Promise.resolve([]),
    );
    Promise.all(jobs)
      .then(([approved, pend]) => {
        if (cancelled) return;
        setRows(Array.isArray(approved) ? approved : []);
        setPending(Array.isArray(pend) ? pend : []);
        setLoading(false);
      })
      .catch(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [isAdmin, refreshKey]);

  // Keep the news panel pointed at a valid share.
  useEffect(() => {
    if (symbols.length === 0) setSelectedNewsSymbol(null);
    else if (!selectedNewsSymbol || !symbols.includes(selectedNewsSymbol))
      setSelectedNewsSymbol(symbols[0]);
  }, [symbols, selectedNewsSymbol]);

  // Live last-price poll (pence), LSE hours + visible tab only.
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
        .then((d) => !cancelled && d && typeof d === "object" && setLiveQuotes(d))
        .catch(() => {});
    };
    fetchQuotes();
    const id = setInterval(fetchQuotes, 5 * 60 * 1000);
    const onVisible = () => fetchQuotes();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [symbols]);

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

  const sortVal = (r) => {
    switch (sortCol) {
      case "name": return r.name || r.symbol;
      case "price": return priceOf(r);
      case "day": return dayPct(r);
      case "run": return r.streak;
      case "range": return rangePos(r);
      case "date": return r.story?.published_at ? new Date(r.story.published_at).getTime() : null;
      case "days": return r.days_since_news;
      case "m": return r.momentum_score;
      case "q": return r.quality_score;
      case "v": return r.value_score;
      case "r": return r.risk_score;
      case "pct_news": return r.pct_since_news;
      default: return null;
    }
  };

  const sorted = useMemo(() => {
    const arr = [...rows];
    arr.sort((a, b) => {
      const va = sortVal(a);
      const vb = sortVal(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "string")
        return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
      return sortDir === "asc" ? va - vb : vb - va;
    });
    return arr;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sortCol, sortDir, liveQuotes]);

  const toggleSort = (key) => {
    if (key === sortCol) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortCol(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  };

  const refetch = useCallback(() => setRefreshKey((n) => n + 1), []);

  const setStatus = useCallback(
    (id, status) =>
      fetch(`${API}/showcase/${id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...adminHeaders() },
        body: JSON.stringify({ status }),
      })
        .then(() => refetch())
        .catch(() => {}),
    [refetch],
  );

  const extendTracking = useCallback(
    (id) =>
      fetch(`${API}/showcase/${id}/extend`, { method: "POST", headers: adminHeaders() })
        .then(() => refetch())
        .catch(() => {}),
    [refetch],
  );

  const toggleExpand = (id) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const daysLeft = (r) => {
    if (!r.track_until) return null;
    return Math.ceil((new Date(r.track_until).getTime() - Date.now()) / 86400000);
  };

  return (
    <div>
      <PageHeader
        title="High Impact RNS"
        subtitle="A curated showcase of high-impact, positive RNS stories — each tracked for a month to show whether the signal played out."
        right={
          <span style={{ color: "#64748b", fontSize: 12, fontFamily: "monospace" }}>
            {loading ? "loading…" : `${rows.length} tracked`}
            {isAdmin && pending.length > 0 ? ` · ${pending.length} pending` : ""}
          </span>
        }
      />

      {/* Admin: candidates awaiting approval */}
      {isAdmin && pending.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ color: "#f97316", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 10 }}>
            Pending approval ({pending.length})
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
            {pending.map((e) => (
              <PendingCard
                key={e.showcase_id}
                entry={e}
                onApprove={(id) => setStatus(id, "approved")}
                onReject={(id) => setStatus(id, "rejected")}
              />
            ))}
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 16, alignItems: "stretch" }}>
        <div style={{ flex: "1 1 auto", minWidth: 0 }}>
          {rows.length === 0 ? (
            <div style={{ background: "#111", border: "1px solid #1e1e1e", borderRadius: 3, padding: "48px 24px", textAlign: "center", color: "#555", fontFamily: "monospace", fontSize: 13 }}>
              {loading ? "Loading…" : "No stories are being showcased yet."}
            </div>
          ) : (
            <div style={{ overflow: "auto", maxHeight: "calc(100vh - 245px)", scrollbarGutter: "stable" }}>
              <table style={{ borderCollapse: "separate", borderSpacing: 0, fontSize: 12, fontFamily: "monospace", tableLayout: "auto" }}>
                <thead>
                  <tr>
                    {COLS.map((c) => {
                      const active = c.key === sortCol;
                      return (
                        <th
                          key={c.key}
                          onClick={c.noSort ? undefined : () => toggleSort(c.key)}
                          style={{ ...S.th, textAlign: c.align, cursor: c.noSort ? "default" : "pointer", color: active ? "#fbbf24" : "#f97316" }}
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
                    const st = r.story || {};
                    const dl = daysLeft(r);
                    const isExpanded = expanded.has(r.showcase_id);
                    return (
                      <Fragment key={r.showcase_id}>
                        <tr
                          onClick={() => onSelect && onSelect(r.symbol)}
                          style={{ cursor: "pointer", background: baseBg }}
                        >
                          {/* Stock — ticker + name + index badge */}
                          <td style={S.td}>
                            <div style={{ minWidth: 0 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <span style={{ color: "#e5e5e5", fontWeight: 700 }}>{r.symbol.replace(".L", "")}</span>
                                <IndexBadge index={r.ftse_index} />
                              </div>
                              <div style={{ color: "#64748b", fontSize: 10, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {r.name}
                              </div>
                            </div>
                          </td>

                          {/* Price */}
                          <td style={{ ...S.td, textAlign: "right" }}>
                            {live && <span title="Live" style={{ marginRight: 4, fontSize: 9, color: "#10b981" }}>●</span>}
                            <span style={{ color: "#f1f5f9", fontWeight: 700 }}>{fmtPounds(priceOf(r))}</span>
                          </td>

                          {/* Day change % */}
                          <td style={{ ...S.td, textAlign: "right", color: pctColor(dp), fontWeight: 700 }}>
                            {dp == null ? "—" : `${dp >= 0 ? "+" : ""}${dp.toFixed(2)}%`}
                          </td>

                          {/* Streak run */}
                          <td style={{ ...S.td, textAlign: "right" }}>
                            {r.streak ? <StreakBadge streak={r.streak} /> : <span style={{ color: "#3a3a3a" }}>—</span>}
                          </td>

                          {/* Trend + 52w range */}
                          <td style={S.td}>
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                              <Sparkline
                                points={r.spark}
                                sinceCount={r.spark_since}
                                sinceUp={r.pct_since_news == null ? null : r.pct_since_news >= 0}
                              />
                              <RangeBar pos={rangePos(r)} />
                            </div>
                          </td>

                          {/* Date of the impact story */}
                          <td style={{ ...S.td, textAlign: "right" }} title="Date of the impact news story">
                            <span style={{ color: "#cbd5e1" }}>{fmtDate(st.published_at)}</span>
                          </td>

                          {/* Days since the impact story */}
                          <td style={{ ...S.td, textAlign: "right" }} title="Days since the impact news story">
                            <span style={{ color: "#94a3b8" }}>{r.days_since_news != null ? `${r.days_since_news}d` : "—"}</span>
                          </td>

                          {/* MQVR */}
                          <td style={{ ...S.td, textAlign: "center" }}><ScorePill value={r.momentum_score} /></td>
                          <td style={{ ...S.td, textAlign: "center" }}><ScorePill value={r.quality_score} /></td>
                          <td style={{ ...S.td, textAlign: "center" }}><ScorePill value={r.value_score} /></td>
                          <td style={{ ...S.td, textAlign: "center" }}><ScorePill value={r.risk_score} invert /></td>

                          {/* % since the story */}
                          <td style={{ ...S.td, textAlign: "right", fontWeight: 700, color: pctColor(r.pct_since_news) }}>
                            {r.pct_since_news == null ? "—" : `${r.pct_since_news >= 0 ? "+" : ""}${r.pct_since_news.toFixed(1)}%`}
                          </td>

                          {/* Follow-up tally since tracking began */}
                          <td style={{ ...S.td, textAlign: "right" }}>
                            <FollowupTally
                              pos={r.followup_pos}
                              neg={r.followup_neg}
                              expanded={isExpanded}
                              onToggle={() => toggleExpand(r.showcase_id)}
                            />
                          </td>

                          {/* News → open in panel */}
                          <td
                            title="Show this share's news in the panel"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedNewsSymbol(r.symbol);
                            }}
                            style={{
                              ...S.td,
                              cursor: "pointer",
                              borderLeft: `3px solid ${r.symbol === selectedNewsSymbol ? "#f97316" : "transparent"}`,
                              background: r.symbol === selectedNewsSymbol ? "rgba(249,115,22,0.08)" : undefined,
                            }}
                          >
                            <span style={{ color: "#64748b", fontSize: 11 }}>view ›</span>
                          </td>
                        </tr>

                        {/* Story strip — the announcement that got this pick selected */}
                        <tr style={{ background: baseBg }}>
                          <td colSpan={COLS.length} style={{ ...S.td, whiteSpace: "normal", borderBottom: "1px solid #1a1a1a", paddingTop: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                              <ScoreCell value={st.llm_score} />
                              {st.tier && (
                                <span style={{ color: TIER_COLOR[st.tier] || TIER_COLOR.C, fontSize: 10, fontWeight: 700 }}>
                                  {st.tier}
                                </span>
                              )}
                              <a
                                href={st.url}
                                target="_blank"
                                rel="noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                style={{ color: "#e2e8f0", fontSize: 12, fontWeight: 600, textDecoration: "none" }}
                              >
                                {st.headline}
                              </a>
                              <span style={{ color: "#475569", fontSize: 10 }}>{fmtDate(st.published_at)}</span>
                              {st.vet_verdict && VET_STYLE[st.vet_verdict] && (
                                <span
                                  title={st.vet_rationale || ""}
                                  style={{
                                    color: VET_STYLE[st.vet_verdict].color,
                                    background: VET_STYLE[st.vet_verdict].bg,
                                    border: `1px solid ${VET_STYLE[st.vet_verdict].color}55`,
                                    borderRadius: 2,
                                    padding: "1px 6px",
                                    fontSize: 9.5,
                                    fontWeight: 700,
                                    fontFamily: "monospace",
                                  }}
                                >
                                  {VET_STYLE[st.vet_verdict].label}
                                </span>
                              )}
                              {st.llm_thesis && (
                                <span title={st.llm_thesis} style={{ color: "#94a3b8", fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 460 }}>
                                  — {st.llm_thesis}
                                </span>
                              )}
                              {isAdmin && (
                                <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }} onClick={(e) => e.stopPropagation()}>
                                  {dl != null && dl <= 5 && (
                                    <span style={{ color: dl <= 0 ? "#f87171" : "#f59e0b", fontSize: 10, fontWeight: 700 }}>
                                      {dl <= 0 ? "expired" : `${dl}d left`}
                                    </span>
                                  )}
                                  <button onClick={() => extendTracking(r.showcase_id)} style={btn("#60a5fa")}>Extend</button>
                                  <button onClick={() => setStatus(r.showcase_id, "archived")} style={btn("#94a3b8")}>Archive</button>
                                </span>
                              )}
                            </div>

                            {/* Expanded: subsequent announcements since tracking began */}
                            {isExpanded && (r.followups || []).length > 0 && (
                              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 5, paddingLeft: 4 }}>
                                {r.followups.map((f, fi) => {
                                  const c = f.sentiment === "positive" ? "#10b981" : f.sentiment === "negative" ? "#ef4444" : "#94a3b8";
                                  const sym = f.sentiment === "positive" ? "▲" : f.sentiment === "negative" ? "▼" : "—";
                                  const inner = (
                                    <>
                                      <span style={{ color: c, fontWeight: 700, width: 14, flexShrink: 0 }}>{sym}</span>
                                      <span style={{ color: "#475569", fontSize: 10, width: 40, flexShrink: 0 }}>{fmtWhen(f.published_at)}</span>
                                      <span style={{ color: "#cbd5e1", fontSize: 11.5 }}>{f.headline}</span>
                                    </>
                                  );
                                  return f.url ? (
                                    <a key={fi} href={f.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} style={{ display: "flex", alignItems: "baseline", gap: 8, textDecoration: "none" }}>
                                      {inner}
                                    </a>
                                  ) : (
                                    <div key={fi} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>{inner}</div>
                                  );
                                })}
                              </div>
                            )}
                          </td>
                        </tr>
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <NewsPanel
          symbol={selectedNewsSymbol}
          name={rows.find((r) => r.symbol === selectedNewsSymbol)?.name || (selectedNewsSymbol ? selectedNewsSymbol.replace(".L", "") : "")}
          sideBySide={false}
        />
      </div>
    </div>
  );
}
