"use client";
import { Fragment, memo, useState, useEffect, useMemo, useRef, useCallback } from "react";
import { API, adminHeaders } from "@/lib/api";
import { useIsAdmin } from "@/hooks/useAdmin";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { lseStatus } from "@/lib/lse";
import Link from "next/link";
import { companyHref } from "@/lib/company";
import PageHeader from "@/components/layout/PageHeader";
import EmailDigestCTA from "@/components/EmailDigestCTA";
import LazySection from "@/components/LazySection";
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

// News list: whole days ("1d", "2d", "3d") for the first few days, then the date.
const fmtNewsWhen = (iso) => {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const days = Math.floor(Math.max(0, Date.now() - then) / 86400000);
  if (days <= 3) return `${Math.max(1, days)}d`;
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

// Age of the story, e.g. "1 day." / "5 days." — used in the desktop table in
// place of the raw date, so you can see how long a pick has been tracked at a glance.
const fmtDaysSince = (days) =>
  days == null ? "—" : `${days} day${days === 1 ? "" : "s"}`;

// Prices are stored in pence (LSE convention) — show as pounds.
const fmtPounds = (pence) =>
  pence == null ? "—" : `£${(pence / 100).toFixed(2)}`;

const pctColor = (v) =>
  v == null ? "#64748b" : v > 0.05 ? "#10b981" : v < -0.05 ? "#ef4444" : "#94a3b8";

// Signed percentage, or a dash. Never "0.0%" for a missing figure — a flat gap
// is a claim about the market, and today's story simply has no open yet.
const fmtPct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`);

// Tooltip copy for the two halves of the move, kept in one place because the
// desktop header, the desktop cells and the mobile card all say the same thing.
const GAP_TITLE =
  "Gap — the move from the last close before the announcement to the first open you could have dealt at. " +
  "RNS drops at 07:00, an hour before the market opens, so this part had already happened by the time anyone could buy.";
const SINCE_OPEN_TITLE =
  "Since that first dealable open to the latest price — the part of the move that was actually available to take.";

const TIER_COLOR = { A: "#f87171", B: "#fbbf24", C: "#94a3b8" };

const VET_STYLE = {
  include: { color: "#10b981", bg: "#0d2318", label: "AI vet: include" },
  caution: { color: "#f59e0b", bg: "#2a1c00", label: "AI vet: caution" },
  exclude: { color: "#ef4444", bg: "#2a0d0d", label: "AI vet: exclude" },
};

const S = {
  th: {
    textAlign: "left",
    padding: "10px 14px",
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
    padding: "18px 14px",
    borderBottom: "1px solid #1a1a1a",
    color: "#ccc",
    whiteSpace: "nowrap",
    fontFamily: "monospace",
    fontSize: 13,
  },
};

// ── small pieces ──────────────────────────────────────────────────────────────
function IndexBadge({ index, full = false }) {
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
      {full ? index : index.replace("FTSE ", "")}
    </span>
  );
}

// Vet score, coloured on the RNS page's bands. `bare` drops the "Vet Score"
// label — used in the table column, which already has a header naming it.
// The score shown here is the VET's (migration 029, 2026-08-03) — the second
// LLM pass, and the one that actually decides whether a story reaches this
// page. It is NOT the ranker's llm_score: that one measures price-impact
// likelihood x magnitude and only decides who earns a second look (>= 60).
// This measures conviction in a positive 1-3 month case after the sceptical
// read, and >= 75 is what publishes. Both are shown side by side on /gates.
//
// Every story flagged before 2026-08-03 has vet_score NULL and renders "—".
// That is correct, not a bug: those rows were published under the old
// single-score rule and were never scored on this scale.
function ScoreCell({
  value,
  bare = false,
  size = 12,
  label = "Vet Score",
  title = "AI vet conviction, 0–100: how strong a 1–3 month case this is after the sceptical second read. 75+ is required to appear here.",
  nullTitle = "Not vet-scored — flagged before the vet became a scorer (2026-08-03)",
}) {
  if (value == null) {
    return (
      <span style={{ color: "#333" }} title={nullTitle}>
        —
      </span>
    );
  }
  const colour =
    value >= 75 ? "#f97316" : value >= 50 ? "#60a5fa" : value >= 25 ? "#94a3b8" : "#555";
  return (
    <span
      title={title}
      style={{
        fontFamily: "monospace",
        fontSize: size,
        fontWeight: 700,
      }}
    >
      {!bare && <><span style={{ color: "#fff" }}>{label}</span> </>}
      <span style={{ color: colour }}>{value}</span>
    </span>
  );
}

// Pass 1 — the RANKER's llm_score, shown alongside the vet's. The two measure
// different things on purpose and must not be read as one number drifting:
// llm_score is price-impact likelihood x magnitude (>= 60 earns a vet call),
// vet_score is conviction in a 1-3 month case after the sceptical read (>= 75
// publishes). Deliberately muted — the vet's score is the one that decides.
//
// Rendered secondary rather than equal because a reader comparing them wants
// "did the second pass disagree?", not two competing headline numbers.
function RankScore({ value, size = 12 }) {
  if (value == null) return <span style={{ color: "#333" }} title="Never ranked">—</span>;
  return (
    <span
      title={`Ranker score ${value}/100 — pass 1: likelihood x magnitude of a price move. 60+ earns a vet call. Not a conviction score.`}
      style={{ fontFamily: "monospace", fontSize: size, fontWeight: 700, color: "#64748b" }}
    >
      {value}
    </span>
  );
}

// ▲/▼ when the vet moved a story materially off the ranker's read. Same
// convention as /gates. Threshold is 10 points: below that the two passes are
// saying the same thing in different units, and marking every 5-point wobble
// as "disagreement" would make the marker meaningless.
const VET_DISAGREE_PTS = 10;

function VetDelta({ llm, vet }) {
  if (llm == null || vet == null) return null;
  const d = vet - llm;
  if (Math.abs(d) < VET_DISAGREE_PTS) return null;
  const up = d > 0;
  return (
    <span
      title={
        up
          ? `Vet PROMOTED this: ranker ${llm} → vet ${vet} (+${d}). The sceptical read found a better case than the headline scan.`
          : `Vet DEMOTED this: ranker ${llm} → vet ${vet} (${d}). The sceptical read found less than the headline scan.`
      }
      style={{ color: up ? "#10b981" : "#f87171", fontSize: 9, fontWeight: 700, marginLeft: 3 }}
    >
      {up ? "▲" : "▼"}
    </span>
  );
}

// Forward multiple computed from a figure the announcement itself stated
// (FY guidance, a consensus footnote, or a fresh reported year) — extraction
// is LLM, arithmetic is server-side Python. Null = nothing usable was stated,
// so most rows legitimately show a dash. "<" marks an upper bound ("at least
// £Xm" guidance / "ahead of consensus £Xm": the real multiple is lower).
const FWD_LABEL = { ebitda: "EV/EBITDA", ebit: "EV/EBIT", pbt: "P/PBT" };
const FWD_BASIS = { guidance: "guidance", consensus: "consensus", actual: "reported" };

function FwdMultipleCell({ r, size = 12 }) {
  if (r.fwd_multiple == null) return <span style={{ color: "#333" }}>—</span>;
  const label = FWD_LABEL[r.fwd_metric] || "multiple";
  const basis = FWD_BASIS[r.fwd_basis] || r.fwd_basis || "";
  const title =
    `${label} on the ${r.fwd_period || "full-year"} ${basis} figure stated in the announcement` +
    (r.fwd_is_bound ? " (upper bound)" : "") +
    (r.fwd_quote ? ` — “${r.fwd_quote}”` : "");
  return (
    <span title={title} style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
      <span style={{ color: "#a78bfa", fontWeight: 700, fontFamily: "monospace", fontSize: size }}>
        {r.fwd_is_bound ? "<" : ""}{Number(r.fwd_multiple).toFixed(1)}×
      </span>
      <span style={{ color: "#64748b", fontSize: 8.5, fontWeight: 700, letterSpacing: 0.3, textTransform: "uppercase", whiteSpace: "nowrap" }}>
        {label} · {basis}
      </span>
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
// since selection, red if down — so you can see at a glance how the stock has
// moved since the story. On day one only, a dot marks the latest point.
// Memoised: `points` references are stable across the 5-minute quote-poll
// re-renders, so every row's SVG is skipped on poll ticks.
const Sparkline = memo(function Sparkline({ points, sinceCount = 0, sinceUp = null, width = 84, height = 26 }) {
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
  const sc = Math.max(0, Math.min(n, sinceCount || 0));
  const splitIdx = sc > 0 ? n - sc : n;
  const before = coords.slice(0, Math.min(splitIdx + 1, n));
  // Start "since" one point early too, sharing the pre-news close with "before" —
  // otherwise a 1-day-old story (sc=1) has only a single "since" point and no
  // line can be drawn, so the jump itself never gets coloured (only the dot).
  const since = sc > 0 ? coords.slice(Math.max(0, splitIdx - 1)) : [];
  // Grey: the pre-story stretch is context only — the coloured "since" segment is the story.
  const baseColor = "#334155";
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
      {sc === 0 && (
        // Picked today: no post-selection close exists yet to colour a "since" segment,
        // so mark the latest point instead of leaving the row unmarked. From day two
        // onwards the coloured segment tells the story and no dot is drawn.
        <circle cx={coords[n - 1][0]} cy={coords[n - 1][1]} r={1.7} fill={sinceColor} />
      )}
    </svg>
  );
});

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
        // Below the table the panel holds its full height from first paint so
        // the news arriving (or the LazySection mount) never shifts layout.
        minHeight: sideBySide ? undefined : 520,
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
                  <span style={{ marginLeft: "auto", flexShrink: 0 }}>{fmtNewsWhen(it.published_at)}</span>
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
        <span style={{ fontFamily: "monospace", fontSize: 11, color: "#64748b" }}>
          rank <RankScore value={st.llm_score} size={11} />
          <span style={{ margin: "0 4px", color: "#334155" }}>│</span>
        </span>
        <ScoreCell value={st.vet_score} />
        <VetDelta llm={st.llm_score} vet={st.vet_score} />
        {entry.fwd_multiple != null && <FwdMultipleCell r={entry} />}
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
          <span style={{ fontWeight: 700 }}>AI vet:</span> {st.vet_rationale}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 2 }}>
        <button onClick={() => onApprove(entry.showcase_id)} style={btn("#10b981")}>Approve</button>
        <button onClick={() => onReject(entry.showcase_id)} style={btn("#f87171")}>Reject</button>
      </div>
    </div>
  );
}

// A story the vet scored but withheld (status='shadow'). No longer shown on
// this page at all (see /high-impact-rns/archive) — isWithheld and the
// styling below only still run here because this same table component
// renders that page too, in archiveOnly mode, where every row IS a shadow row.
//
// isWithheld is keyed on status, NOT on `vet_score < 75`. A row can be shadow
// with a NULL score (the vet CALL failed), and an admin can publish a shadow row
// manually — after which its status is 'approved' and it must stop being marked
// withheld even though the score never changed.
const isWithheld = (r) => (r.story || {}).status === "shadow";

// NULL vet_score on a withheld row means the vet call FAILED, not that the story
// scored zero. Kept visually distinct everywhere: presenting a failure as a low
// score would poison the calibration sample these rows exist to provide.
const vetFailed = (r) => isWithheld(r) && (r.story || {}).vet_score == null;

function WithheldBadge({ r, size = 8.5 }) {
  if (!isWithheld(r)) return null;
  const failed = vetFailed(r);
  return (
    <span
      title={
        failed
          ? "Withheld: the vet call failed, so no score was produced. Not a judgement on the story."
          : `Withheld: vet scored ${(r.story || {}).vet_score}, below the 75 publish floor. Expand the row to read why. Not visible to the public.`
      }
      style={{
        fontSize: size, fontWeight: 700, color: failed ? "#f87171" : "#f59e0b",
        background: failed ? "rgba(248,113,113,0.12)" : "rgba(245,158,11,0.12)",
        border: `1px solid ${failed ? "#f87171" : "#f59e0b"}55`,
        borderRadius: 2, padding: "1px 4px", letterSpacing: 0.3, whiteSpace: "nowrap",
        fontFamily: "monospace",
      }}
    >
      {failed ? "VET FAILED" : "WITHHELD"}
    </span>
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

// One labelled line inside the expanded AI-analysis block.
function AnalysisRow({ label, text, color = "#94a3b8" }) {
  if (!text) return null;
  return (
    <div style={{ fontSize: 11.5, lineHeight: 1.5 }}>
      <span style={{ color, fontWeight: 700, textTransform: "uppercase", fontSize: 9, letterSpacing: 0.5, marginRight: 8 }}>
        {label}
      </span>
      <span style={{ color: "#cbd5e1" }}>{text}</span>
    </div>
  );
}

// ── Reported numbers (archive only) ──────────────────────────────────────────
// Two things the ranker and the financials already hold and the page never
// showed: the lines the announcement itself quantified, and the reported net
// debt behind them.
//
// Symbol only where it is unambiguous — "$" alone cannot separate USD from
// CAD/AUD — so anything else renders as a bare code. Mirrors _CCY_SYMBOL in
// showcase.py, and it matters: CTEC reports USD and CGEO GEL, so a hardcoded
// "£" here would mislabel real figures.
const CCY_SYMBOL = { GBP: "£", USD: "$", EUR: "€" };

function fmtReportingMoney(v, ccy) {
  if (v == null) return "—";
  const sym = CCY_SYMBOL[ccy] || "";
  const prefix = sym || (ccy ? `${ccy} ` : "");
  const a = Math.abs(v);
  const [div, unit] = a >= 1e9 ? [1e9, "bn"] : a >= 1e6 ? [1e6, "m"] : [1e3, "k"];
  const n = a / div;
  return `${prefix}${n.toFixed(n >= 100 ? 0 : 1)}${unit}`;
}

// Millions with one decimal, matching how the announcements themselves print
// and how showcase._fmt_money_m renders the same figure inside the vet prompt —
// so "$4,479.0m" on the page is character-for-character the string the vet
// rationale above it quotes. fmtReportingMoney's bn/m/k rounding would say
// "$4.5bn" and break that tie for the reader.
function fmtReportingM(v, ccy) {
  if (v == null) return "—";
  const sym = CCY_SYMBOL[ccy] || "";
  const prefix = sym || (ccy ? `${ccy} ` : "");
  const n = (v / 1e6).toLocaleString("en-GB", {
    minimumFractionDigits: 1, maximumFractionDigits: 1,
  });
  return `${prefix}${n}m`;
}

// Net cash reads as net cash, never as negative net debt — the same double
// negative showcase._fmt_net_debt_m exists to avoid, for the same reason: read
// backwards it inverts a leverage judgement.
function NetDebtFigure({ v, ccy }) {
  if (v == null) return <span style={{ color: "#475569" }}>n/a</span>;
  const isCash = v < 0;
  return (
    <span style={{ color: isCash ? "#10b981" : "#cbd5e1" }}>
      {fmtReportingMoney(Math.abs(v), ccy)}
      {isCash && <span style={{ color: "#10b981", fontSize: 8.5, marginLeft: 3 }}>cash</span>}
    </span>
  );
}

function ReportedNumbers({ r }) {
  const lines = r.reported_lines || [];
  const debt = r.net_debt_series || [];
  const seq = r.sequential_base;
  const ownDebt = r.reported_net_debt;
  if (!lines.length && !debt.length && !seq && !ownDebt) return null;
  const ccy = r.financial_currency;

  return (
    <div style={{ marginTop: 12, paddingLeft: 4, maxWidth: 760 }}>
      <div style={{ fontSize: 10, color: "#64748b", marginBottom: 5 }}>
        Reported numbers
        {ccy && ccy !== "GBP" && (
          // Loud, because the row above it is a GBP market cap and these are
          // not comparable with it.
          <span style={{ color: "#f59e0b", marginLeft: 6 }}>· reported in {ccy}</span>
        )}
      </div>

      {lines.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 11, fontFamily: "monospace", width: "100%" }}>
            <thead>
              <tr>
                {/* "Prior" is named for its source, not its date: it is
                    whatever comparator the filer chose (usually the same period
                    a year earlier), and it is NOT the sequential comparator the
                    vet rationale uses. Saying so in the header is what stops the
                    two revenue reads on this page looking contradictory. */}
                {["Period", "Line", "This period", "Prior · company’s own"].map((h, i) => (
                  <th
                    key={h}
                    style={{
                      textAlign: i >= 2 ? "right" : "left",
                      color: "#475569", fontSize: 8.5, fontWeight: 700,
                      textTransform: "uppercase", letterSpacing: 0.4,
                      padding: "0 8px 4px 0", whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i} style={{ borderTop: "1px solid #1e293b" }}>
                  <td style={{ padding: "4px 8px 4px 0", color: "#64748b", whiteSpace: "nowrap" }}>
                    {l.period || "—"}
                  </td>
                  <td style={{ padding: "4px 8px 4px 0", color: "#94a3b8" }}>
                    {l.item}
                    {/* The one-off the company itself named on this line. It is
                        the whole point of the extraction — a headline figure
                        with a named one-off inside it should never be read at
                        face value. */}
                    {l.one_off_named && (
                      <div style={{ color: "#f59e0b", fontSize: 9.5, lineHeight: 1.4, marginTop: 2 }}>
                        includes {l.one_off_named}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "4px 8px 4px 0", color: "#e2e8f0", textAlign: "right", whiteSpace: "nowrap" }}>
                    {l.value || "—"}
                  </td>
                  <td style={{ padding: "4px 0", color: "#64748b", textAlign: "right", whiteSpace: "nowrap" }}>
                    {l.prior_value || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* Verbatim on purpose: these values span money, percentages, pence
              per share and prose ("down >90%"), so no delta is computed here —
              a parser over that would be wrong often enough to mislead. */}
          <div style={{ fontSize: 9.5, color: "#475569", marginTop: 4, lineHeight: 1.5 }}>
            As printed in the announcement — figures are not normalised, and “prior” is
            whichever comparator the company itself quoted.
          </div>
        </div>
      )}

      {/* The OTHER revenue comparison — the one the vet rationale quotes. It
          measures against the half that just finished rather than the same half
          a year earlier, so it can point the opposite way to the table above it
          and still be right (ANTO: +18% year-on-year, -7.1% sequentially). The
          vet was handed this exact figure as a fact, from this exact function
          (showcase._sequential_base_from_earnings_quality), so the two cannot
          drift apart. Labelled as derived because it is: no company published
          it. */}
      {seq && (
        <div
          style={{
            marginTop: 10, padding: "7px 9px", borderRadius: 4,
            background: "#0f172a", border: "1px solid #1e293b",
          }}
        >
          <div style={{ fontSize: 8.5, color: "#475569", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>
            Sequential · derived by us
          </div>
          <div style={{ fontSize: 11, color: "#cbd5e1", lineHeight: 1.55, fontFamily: "monospace" }}>
            {seq.period} {seq.metric || "revenue"}{" "}
            <span style={{ color: "#e2e8f0", fontWeight: 700 }}>
              {fmtReportingM(seq.current_value, ccy)}
            </span>{" "}
            is{" "}
            <span style={{ color: seq.delta_pct >= 0 ? "#10b981" : "#f87171", fontWeight: 700 }}>
              {Math.abs(seq.delta_pct).toFixed(1)}% {seq.delta_pct >= 0 ? "above" : "below"}
            </span>{" "}
            the preceding half, {fmtReportingM(seq.preceding_value, ccy)}.
          </div>
          <div style={{ fontSize: 9.5, color: "#475569", marginTop: 4, lineHeight: 1.5 }}>
            {seq.basis === "derived_from_fy_total" ? (
              <>
                {seq.preceding_period} derived as the latest full fiscal year’s{" "}
                {seq.metric || "revenue"} minus the prior-year {seq.period} figure of{" "}
                {fmtReportingM(seq.prior_year_value, ccy)} printed above — the company
                did not publish it. Compares against the half just gone, not the same
                half a year earlier, so it can disagree with the table above and both
                still be correct.
              </>
            ) : (
              <>
                Both halves printed in the announcement itself. Compares against the
                half just gone, not the same half a year earlier.
              </>
            )}
          </div>
        </div>
      )}

      {/* The company's own figure, above ours, because where the two disagree
          this is the one that is right. Verbatim as printed — including "net
          cash of ..." where that is the wording — since the sign convention is
          the easiest thing in this panel to invert. */}
      {ownDebt && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 8.5, color: "#475569", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>
            Net debt · as the company reports it
          </div>
          <div style={{ fontSize: 11, color: "#cbd5e1", lineHeight: 1.55, fontFamily: "monospace" }}>
            <span style={{ color: "#e2e8f0", fontWeight: 700 }}>{ownDebt.value}</span>
            {ownDebt.as_at && <span style={{ color: "#64748b" }}> at {ownDebt.as_at}</span>}
            {ownDebt.leverage && <span style={{ color: "#64748b" }}> · {ownDebt.leverage} EBITDA</span>}
            {ownDebt.prior_value && (
              <div style={{ color: "#64748b", marginTop: 2 }}>
                was {ownDebt.prior_value}
                {ownDebt.prior_as_at && ` at ${ownDebt.prior_as_at}`}
                {ownDebt.prior_leverage && ` · ${ownDebt.prior_leverage} EBITDA`}
              </div>
            )}
          </div>
          <div style={{ fontSize: 9.5, color: "#475569", marginTop: 4, lineHeight: 1.5 }}>
            Copied from this announcement. Where it disagrees with our figure
            below, this one is right — and the comparator is usually the previous
            balance-sheet date, not the same date a year earlier.
          </div>
        </div>
      )}

      {debt.length > 0 && (
        <div style={{ marginTop: 10 }}>
          {/* NOT "reported": this series is our own borrowings-minus-cash, and it
              is not the number the company prints. updater.py computes net_debt
              = st_debt + lt_debt - cash_and_equiv and never deducts short-term
              investments, for which there is no live source at all (nothing in
              the codebase writes annual_financials.st_investments). A cash-rich
              filer therefore reads far more levered here than in its own
              accounts — ANTO.L FY2025 shows $4.2bn / 0.80x against the
              $2,749.5m / 0.53x its own HY26 statement prints for the very same
              date. Labelling that "reported" put it directly under a vet
              rationale quoting the company's figure, and made the LLM look
              wrong when it was reading the announcement correctly. */}
          <div style={{ fontSize: 8.5, color: "#475569", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>
            Net debt · our calculation, full years
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {debt.map((d) => (
              <div key={d.fiscal_year} style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                <span style={{ color: "#475569", fontSize: 9 }}>FY{d.fiscal_year}</span>
                <span style={{ fontFamily: "monospace", fontSize: 11.5, fontWeight: 700 }}>
                  <NetDebtFigure v={d.net_debt} ccy={ccy} />
                </span>
                <span style={{ color: "#475569", fontSize: 8.5 }}>
                  {d.net_debt_to_ebitda != null ? `${d.net_debt_to_ebitda.toFixed(2)}× EBITDA` : " "}
                </span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 9.5, color: "#475569", marginTop: 5, lineHeight: 1.5 }}>
            Borrowings minus cash at each year end, computed by us from annual
            financials — not the company’s own net-debt definition. Short-term
            investments are not deducted, so a company that parks its liquidity
            there reports a lower figure than this one.
          </div>
        </div>
      )}
    </div>
  );
}

// A single MQVR pill with its letter label above, for the mobile card's compact row.
function LabelledPill({ label, value, invert }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
      <span style={{ color: "#475569", fontSize: 8, fontWeight: 700 }}>{label}</span>
      <ScorePill value={value} invert={invert} />
    </div>
  );
}

// ── mobile card (phones/narrow viewports) ──────────────────────────────────────
// The desktop layout is a wide sticky-header table meant to be scanned across
// many columns; on a phone that means constant horizontal scrolling just to
// reach the story dropdown. Each row becomes a self-contained card instead —
// tapping it opens the company, tapping the caret expands the same AI-analysis
// block as desktop but full-width, no horizontal scroll involved.
function MobileCard({
  r, isOpen, onToggle, onSelect, isAdmin, live, price, gapPct, sinceOpenPct,
  totalPct, rangePosValue, isNewsSelected, onNewsSelect, vet, st, setStatus,
  archiveOnly = false,
}) {
  const [showMqvrInfo, setShowMqvrInfo] = useState(false);
  const caretColor = isOpen ? "#f97316" : "#93c5fd";
  return (
    <div style={{
      background: isWithheld(r) ? "#16120b" : "#111",
      border: `1px solid ${isWithheld(r) ? "#3f2d1a" : "#1e1e1e"}`,
      borderRadius: 6,
      overflow: "hidden",
    }}>
      <div onClick={onSelect} style={{ padding: "12px 14px", cursor: "pointer", display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={(e) => { e.stopPropagation(); onToggle(); }}
            title={isOpen ? "Hide story & analysis" : "Show story & analysis"}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 28,
              height: 28,
              background: isOpen ? "rgba(249,115,22,0.18)" : "#1c2740",
              border: `1px solid ${isOpen ? "#f97316" : "#3d5273"}`,
              borderRadius: 5,
              color: caretColor,
              cursor: "pointer",
              fontSize: 14,
              padding: 0,
              lineHeight: 1,
              flexShrink: 0,
            }}
          >
            <span
              className={!isOpen ? "chevron-wobble" : undefined}
              style={{
                display: "inline-block",
                transform: isOpen ? "rotate(90deg)" : "none",
                transition: "transform 0.12s ease",
              }}
            >
              ▶
            </span>
          </button>
          <div style={{ width: 88, flexShrink: 0, marginLeft: 8 }}>
            <Link prefetch={false} href={companyHref(r.symbol)} onClick={(e) => e.stopPropagation()} style={{ color: "#e5e5e5", fontWeight: 700, textDecoration: "none" }}>{r.symbol.replace(".L", "")}</Link>
            <div style={{ marginTop: 3, display: "flex", flexWrap: "wrap", gap: 3 }}>
              <IndexBadge index={r.ftse_index} full />
              <WithheldBadge r={r} />
              {vet && (
                <span style={{ fontSize: 8.5, fontWeight: 700, color: vet.color, background: vet.bg, border: `1px solid ${vet.color}55`, borderRadius: 2, padding: "1px 4px", letterSpacing: 0.3, whiteSpace: "nowrap", textTransform: "capitalize" }}>
                  {st.vet_verdict}
                </span>
              )}
            </div>
          </div>
          {/* Both passes. Stacked VERTICALLY on purpose: the sparkline beside
              this block is absolutely positioned off a hand-tuned offset, so
              growing this column sideways would shift it. */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, marginLeft: 2, flexShrink: 0 }}>
            <span style={{ color: "#64748b", fontSize: 10, fontWeight: 700, letterSpacing: 0.3, whiteSpace: "nowrap", textTransform: "uppercase" }}>Vet Score</span>
            <span style={{ display: "inline-flex", alignItems: "center" }}>
              <ScoreCell value={st.vet_score} bare size={20} />
              <VetDelta llm={st.llm_score} vet={st.vet_score} />
            </span>
            <span style={{ color: "#475569", fontSize: 9, fontWeight: 700, whiteSpace: "nowrap", fontFamily: "monospace" }}>
              rank <RankScore value={st.llm_score} size={9} />
            </span>
          </div>
          <div style={{ position: "absolute", left: "50%", top: "50%", transform: "translate(calc(-50% + 66px), -50%)", pointerEvents: "none" }}>
            {/* Coloured on the WHOLE move (close -> now), because that is the
                stretch the line actually draws — not the since-open half. */}
            <Sparkline points={r.spark} sinceCount={r.spark_since} sinceUp={totalPct == null ? null : totalPct >= 0} width={64} height={22} />
          </div>
          <div style={{ textAlign: "right", flexShrink: 0, marginLeft: "auto" }}>
            <div style={{ color: "#f1f5f9", fontWeight: 700, fontSize: 13 }}>
              {live && <span title="Live" style={{ marginRight: 4, fontSize: 9, color: "#10b981" }}>●</span>}
              {fmtPounds(price)}
            </div>
            {/* Same split as the desktop table's two columns, stacked: the
                tradeable half leads, the gap sits under it as context. */}
            <div title={SINCE_OPEN_TITLE} style={{ color: pctColor(sinceOpenPct), fontWeight: 700, fontSize: 12 }}>
              {fmtPct(sinceOpenPct)}
            </div>
            <div title={GAP_TITLE} style={{ color: pctColor(gapPct), fontSize: 9.5, fontWeight: 700, opacity: 0.75, whiteSpace: "nowrap" }}>
              gap {fmtPct(gapPct)}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
          <span
            onClick={(e) => { e.stopPropagation(); onNewsSelect(); }}
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: 0.6,
              textTransform: "uppercase",
              cursor: "pointer",
              flexShrink: 0,
              padding: "3px 10px",
              borderRadius: 4,
              color: isNewsSelected ? "#f97316" : "#94a3b8",
              background: isNewsSelected ? "rgba(249,115,22,0.18)" : "transparent",
              border: `1px solid ${isNewsSelected ? "#f97316" : "#2a3444"}`,
              transition: "background 0.12s ease, color 0.12s ease, border-color 0.12s ease",
            }}
          >
            News
          </span>
        </div>
      </div>

      {isOpen && (
        <div style={{ padding: "0 14px 14px", borderTop: "1px solid #1a1a1a" }} onClick={(e) => e.stopPropagation()}>
          <div style={{ marginTop: 12, color: "#cbd5e1", fontSize: 14, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {r.name}
          </div>
          {/* Factor scores + 52-week range — moved off the crowded card face */}
          <div style={{ marginTop: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ display: "flex", gap: 10 }}>
                <LabelledPill label="M" value={r.momentum_score} />
                <LabelledPill label="Q" value={r.quality_score} />
                <LabelledPill label="V" value={r.value_score} />
                <LabelledPill label="R" value={r.risk_score} invert />
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); setShowMqvrInfo((v) => !v); }}
                title="What do M / Q / V / R mean?"
                aria-label="Explain the factor scores"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 16,
                  height: 16,
                  borderRadius: "50%",
                  border: `1px solid ${showMqvrInfo ? "#60a5fa" : "#3d5273"}`,
                  background: "transparent",
                  color: showMqvrInfo ? "#93c5fd" : "#64748b",
                  fontSize: 10,
                  fontWeight: 700,
                  fontStyle: "italic",
                  fontFamily: "Georgia, serif",
                  lineHeight: 1,
                  cursor: "pointer",
                  padding: 0,
                  flexShrink: 0,
                }}
              >
                i
              </button>
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
              <span style={{ color: "#475569", fontSize: 8, fontWeight: 700, letterSpacing: 0.3, textTransform: "uppercase" }}>
                Price in 52-week range
              </span>
              <RangeBar pos={rangePosValue} />
            </div>
          </div>
          {showMqvrInfo && (
            <div style={{ marginTop: 8, padding: "8px 10px", background: "#0d1420", border: "1px solid #1e2a3d", borderRadius: 4, fontSize: 10.5, color: "#94a3b8", lineHeight: 1.6 }}>
              Factor scores (0–100, higher is better):{" "}
              <b style={{ color: "#cbd5e1" }}>M</b>omentum ·{" "}
              <b style={{ color: "#cbd5e1" }}>Q</b>uality ·{" "}
              <b style={{ color: "#cbd5e1" }}>V</b>alue ·{" "}
              <b style={{ color: "#cbd5e1" }}>R</b>isk. Risk is inverted, so green means lower risk.
            </div>
          )}
          <div style={{ marginTop: 16, marginBottom: 4, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {r.fwd_multiple != null && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 3 }}>
                <span style={{ color: "#475569", fontSize: 8, fontWeight: 700, letterSpacing: 0.3, textTransform: "uppercase" }}>
                  Fwd multiple
                </span>
                <FwdMultipleCell r={r} />
              </div>
            )}
            <div style={{ marginLeft: "auto", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
              <span style={{ color: "#475569", fontSize: 8, fontWeight: 700, letterSpacing: 0.3, textTransform: "uppercase" }}>
                Publish date
              </span>
              <span style={{ color: "#64748b", fontSize: 10 }}>{fmtDate(st.published_at)}</span>
            </div>
          </div>
          <a href={st.url} target="_blank" rel="noreferrer" style={{ display: "block", marginTop: 12, color: "#e2e8f0", fontSize: 13, fontWeight: 600, textDecoration: "none", lineHeight: 1.4 }}>
            {st.headline}
          </a>

          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 14 }}>
            <AnalysisRow label="Thesis" text={st.llm_thesis} color="#60a5fa" />
            <AnalysisRow label="Risks" text={st.llm_risks} color="#f59e0b" />
            {/* On a withheld row this IS the "why did it fail" text, so it is
    labelled as such rather than as generic commentary. */}
{vetFailed(r) ? (
  <AnalysisRow
    label="Vet call failed"
    text="Withheld because the vet produced no score — an API failure, not a judgement on the story."
    color="#f87171"
  />
) : (
  vet && (
    <AnalysisRow
      label={isWithheld(r) ? `Why withheld · vet ${st.vet_score}` : `AI vet · ${st.vet_verdict}`}
      text={st.vet_rationale}
      color={isWithheld(r) ? "#f59e0b" : vet.color}
    />
  )
)}
            {r.fwd_multiple != null && r.fwd_quote && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <AnalysisRow
                  label={`${FWD_LABEL[r.fwd_metric] || "Multiple"} ${r.fwd_is_bound ? "<" : ""}${Number(r.fwd_multiple).toFixed(1)}× · source`}
                  text={`“${r.fwd_quote}”`}
                  color="#a78bfa"
                />
                {r.ttm_ev_ebitda != null && (
                  <div style={{ fontSize: 10.5, color: "#64748b", lineHeight: 1.5 }}>
                    For context: ~{Number(r.ttm_ev_ebitda).toFixed(1)}× EV/EBITDA on trailing twelve-month figures — before this announcement's new number.
                  </div>
                )}
              </div>
            )}
            <AnalysisRow label="AI summary" text={st.summary} />
            {st.llm_confidence && (
              <div style={{ fontSize: 10, color: "#64748b" }}>confidence: {st.llm_confidence}</div>
            )}
          </div>

          {/* Archive only, same as desktop — the table inside scrolls on its
              own so the card itself never scrolls sideways. */}
          {archiveOnly && <ReportedNumbers r={r} />}

          {(r.followups || []).length > 0 && (
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 5 }}>
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
                  <a key={fi} href={f.url} target="_blank" rel="noreferrer" style={{ display: "flex", alignItems: "baseline", gap: 8, textDecoration: "none" }}>
                    {inner}
                  </a>
                ) : (
                  <div key={fi} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>{inner}</div>
                );
              })}
            </div>
          )}

          {isAdmin && (
            <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8 }}>
              <button onClick={() => setStatus(r.showcase_id, "archived")} style={btn("#94a3b8")}>Archive</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── columns ───────────────────────────────────────────────────────────────────
const COLS = [
  { key: "name", label: "Stock", align: "left" },
  { key: "rank", label: "Rank", align: "center" },
  { key: "ai", label: "Vet Score", align: "center" },
  { key: "price", label: "Price", align: "right" },
  // The move, split the way /gates splits it: what gapped away before the open,
  // and what was left to take afterwards. One combined "% Change" column hid
  // which of the two a reader was looking at.
  { key: "gap", label: "Gap", align: "right", title: GAP_TITLE },
  { key: "since_open", label: "Since Open", align: "right", title: SINCE_OPEN_TITLE },
  { key: "fwd", label: "Fwd Multiple", align: "center" },
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
  { key: "date", label: "Days tracked", align: "center" },
  { key: "m", label: "Mom", align: "center" },
  { key: "q", label: "Qual", align: "center" },
  { key: "v", label: "Value", align: "center" },
  { key: "r", label: "Risk", align: "center" },
  { key: "fu", label: "Follow-up RNS", align: "right" },
  { key: "signals", label: "News", align: "left" },
];

// ── main component ────────────────────────────────────────────────────────────
export default function HighImpactRnsTab({ onSelect, initialRows = null, archiveOnly = false }) {
  const isAdmin = useIsAdmin();
  const isMobile = useIsMobile();

  const [rows, setRows] = useState(() => (Array.isArray(initialRows) ? initialRows : []));
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(!Array.isArray(initialRows));
  const [liveQuotes, setLiveQuotes] = useState({});
  const [selectedNewsSymbol, setSelectedNewsSymbol] = useState(null);
  const [openStory, setOpenStory] = useState(() => new Set());
  const [refreshKey, setRefreshKey] = useState(0);
  const [showChangeInfo, setShowChangeInfo] = useState(false);

  const symbols = useMemo(
    () => [...new Set(rows.map((r) => r.symbol))],
    [rows],
  );

  // Approved showcase (public) + pending candidates (admin only). The very
  // first run reuses the SSR-fetched `initialRows` instead of re-requesting
  // `/showcase` (it's already in the initial HTML) — any later run, forced by
  // refetch() advancing refreshKey, always fetches fresh.
  useEffect(() => {
    let cancelled = false;
    // Archive mode has no SSR payload to reuse and always reads the admin-only
    // endpoint instead of the public one; pending doesn't apply to it. Withheld
    // (shadow) rows moved off this page entirely onto /high-impact-rns/archive.
    const skipApproved = !archiveOnly && Array.isArray(initialRows) && refreshKey === 0;
    if (!skipApproved) setLoading(true);
    const jobs = [
      archiveOnly
        ? fetch(`${API}/showcase/shadow`, { headers: adminHeaders() }).then((r) => (r.ok ? r.json() : []))
        : skipApproved
          ? Promise.resolve(null)
          : fetch(`${API}/showcase`).then((r) => (r.ok ? r.json() : [])),
    ];
    jobs.push(
      !archiveOnly && isAdmin
        ? fetch(`${API}/showcase/pending`, { headers: adminHeaders() }).then((r) => (r.ok ? r.json() : []))
        : Promise.resolve([]),
    );
    Promise.all(jobs)
      .then(([approved, pend]) => {
        if (cancelled) return;
        if (approved !== null) setRows(Array.isArray(approved) ? approved : []);
        setPending(Array.isArray(pend) ? pend : []);
        setLoading(false);
      })
      .catch(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [isAdmin, refreshKey, initialRows, archiveOnly]);

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
  // % since the story — recomputed from the live quote when one is present so the
  // Change column matches the Price column; otherwise the backend's EOD figure.
  const pctSinceNews = (r) => {
    const live = liveQuotes[r.symbol];
    if (live != null && r.story_close > 0) return (live / r.story_close - 1) * 100;
    return r.pct_since_news;
  };
  // % since the first open the news could be traded at (the announcement day's
  // own open for a 07:00 RNS — see showcase._entry_open). Recomputed from the
  // live quote for the same reason as above. Null until that open is on record,
  // which is why this morning's story shows a dash rather than a zero.
  const pctSinceOpen = (r) => {
    const live = liveQuotes[r.symbol];
    if (live != null && r.entry_open > 0) return (live / r.entry_open - 1) * 100;
    return r.pct_since_entry_open;
  };
  // The other half: pre-news close -> that open. Purely historical, so unlike
  // the two above it never moves with the live quote.
  const gapPct = (r) => r.gap_pct;
  const rangePos = (r) => {
    const p = priceOf(r);
    if (p == null || r.high_52w == null || r.low_52w == null) return null;
    const span = r.high_52w - r.low_52w;
    if (span <= 0) return null;
    return ((p - r.low_52w) / span) * 100;
  };

  // Newest first. Withheld (shadow) stories no longer interleave here — they
  // moved to their own page, /high-impact-rns/archive, which reads them
  // straight off /api/showcase/shadow instead.
  const sorted = useMemo(() => {
    const dateVal = (r) => (r.story?.published_at ? new Date(r.story.published_at).getTime() : null);
    const arr = [...rows];
    arr.sort((a, b) => {
      const va = dateVal(a);
      const vb = dateVal(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return vb - va;
    });
    return arr;
  }, [rows]);

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

  const toggleStory = (id) =>
    setOpenStory((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <div>
      {!archiveOnly && <EmailDigestCTA source="high_impact_rns" />}

      <PageHeader
        title={
          archiveOnly ? (
            "High Impact RNS — Archive"
          ) : (
            <>
              High Impact RNS
              <sup
                style={{
                  marginLeft: 7,
                  fontSize: 10,
                  fontFamily: "monospace",
                  fontWeight: 700,
                  letterSpacing: 1,
                  textTransform: "uppercase",
                  color: "#10b981",
                }}
              >
                New
              </sup>
            </>
          )
        }
        subtitle={
          archiveOnly ? (
            "Stories the vet scored but withheld from the public page — cleared the ranker at 60+, scored under 75 on the vet's second read. Not rejected outright, just not published. Newest vet score first."
          ) : (
            <>
              Companies flagged by AI for high-scoring, positive RNS updates — each tracked to see how the share price responded after publication.
              <div style={{ marginTop: 6 }}>
                <Link
                  href="/research/how-i-use-ai-to-find-winning-uk-stocks-from-7am-rns-news"
                  style={{ color: "#a78bfa", textDecoration: "none", borderBottom: "1px dashed #a78bfa55", paddingBottom: 1 }}
                >
                  Read how this works on the Research blog →
                </Link>
              </div>
            </>
          )
        }
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

      {sorted.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", marginBottom: 10 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 7, fontFamily: "monospace" }}>
            <span style={{ color: "#64748b", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
              Gap + Since Open
            </span>
            <button
              onClick={() => setShowChangeInfo((v) => !v)}
              title="What do these mean?"
              aria-label="Explain the Gap and Since Open columns"
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 16,
                height: 16,
                borderRadius: "50%",
                border: `1px solid ${showChangeInfo ? "#60a5fa" : "#3d5273"}`,
                background: "transparent",
                color: showChangeInfo ? "#93c5fd" : "#64748b",
                fontSize: 10,
                fontWeight: 700,
                fontStyle: "italic",
                fontFamily: "Georgia, serif",
                lineHeight: 1,
                cursor: "pointer",
                padding: 0,
                flexShrink: 0,
              }}
            >
              i
            </button>
          </div>
          {showChangeInfo && (
            <div style={{ marginTop: 8, padding: "8px 10px", background: "#0d1420", border: "1px solid #1e2a3d", borderRadius: 4, fontSize: 10.5, color: "#94a3b8", lineHeight: 1.6, maxWidth: 420 }}>
              The move is split in two, because only one half was ever available to take.
              <br />
              <b style={{ color: "#cbd5e1" }}>Gap</b> — from the last close before the announcement to the first
              open anyone could deal at. RNS drops at 07:00, an hour before the market opens, so this part had
              already happened.
              <br />
              <b style={{ color: "#cbd5e1" }}>Since Open</b> — from that open to the latest price. This is the
              part you could have captured. A dash means the market hasn&apos;t opened on the story yet.
            </div>
          )}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 16, alignItems: "stretch" }}>
        <div style={{ flex: "1 1 auto", minWidth: 0 }}>
          {sorted.length === 0 ? (
            <div style={{ background: "#111", border: "1px solid #1e1e1e", borderRadius: 3, padding: "48px 24px", textAlign: "center", color: "#555", fontFamily: "monospace", fontSize: 13 }}>
              {loading ? "Loading…" : "No stories are being showcased yet."}
            </div>
          ) : isMobile ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {sorted.map((r) => {
                const st = r.story || {};
                const vet = st.vet_verdict ? VET_STYLE[st.vet_verdict] : null;
                return (
                  <MobileCard
                    key={r.showcase_id}
                    r={r}
                    st={st}
                    vet={vet}
                    isOpen={openStory.has(r.showcase_id)}
                    onToggle={() => toggleStory(r.showcase_id)}
                    onSelect={() => onSelect && onSelect(r.symbol)}
                    isAdmin={isAdmin}
                    archiveOnly={archiveOnly}
                    live={isLive(r)}
                    price={priceOf(r)}
                    gapPct={gapPct(r)}
                    sinceOpenPct={pctSinceOpen(r)}
                    totalPct={pctSinceNews(r)}
                    rangePosValue={rangePos(r)}
                    isNewsSelected={r.symbol === selectedNewsSymbol}
                    onNewsSelect={() => setSelectedNewsSymbol(r.symbol)}
                    setStatus={setStatus}
                  />
                );
              })}
            </div>
          ) : (
            // No height cap: the list stays curated and short, so let the table
            // size to its rows and the page scroll as one — an inner scrollbox
            // left only a narrow strip visible once the pending-approval cards
            // pushed it down. overflowX keeps the wide table scrollable.
            <div style={{ overflowX: "auto", scrollbarGutter: "stable" }}>
              <table style={{ borderCollapse: "separate", borderSpacing: 0, fontSize: 12, fontFamily: "monospace", tableLayout: "auto" }}>
                <thead>
                  <tr>
                    {COLS.map((c) => (
                      <th
                        key={c.key}
                        title={c.title}
                        style={{ ...S.th, textAlign: "center", cursor: c.title ? "help" : "default", color: "#f97316" }}
                      >
                        {c.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((r, i) => {
                    const live = isLive(r);
                    const withheld = isWithheld(r);
                    // Withheld rows get their own darker stripe rather than the
                    // published rows' blue, so the two are separable at a glance
                    // while still sitting in one date-ordered list.
                    const baseBg = withheld
                      ? (i % 2 === 0 ? "#1c1710" : "#161209")
                      : (i % 2 === 0 ? "#1e293b" : "#162032");
                    const st = r.story || {};
                    const isStoryOpen = openStory.has(r.showcase_id);
                    const vet = st.vet_verdict ? VET_STYLE[st.vet_verdict] : null;
                    return (
                      <Fragment key={r.showcase_id}>
                        <tr
                          onClick={() => onSelect && onSelect(r.symbol)}
                          style={{
                            cursor: "pointer",
                            background: baseBg,
                            // Muted, not hidden — still readable, but never
                            // mistaken for a published pick when skimming.
                            opacity: withheld ? 0.82 : 1,
                          }}
                        >
                          {/* Stock — caret + ticker + name + index badge */}
                          <td style={{ ...S.td, paddingLeft: 22 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  toggleStory(r.showcase_id);
                                }}
                                title={isStoryOpen ? "Hide story & analysis" : "Show story & analysis"}
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  width: 28,
                                  height: 28,
                                  background: isStoryOpen ? "rgba(249,115,22,0.12)" : "#161b26",
                                  border: `1px solid ${isStoryOpen ? "#f97316" : "#2a3444"}`,
                                  borderRadius: 5,
                                  color: isStoryOpen ? "#f97316" : "#60a5fa",
                                  cursor: "pointer",
                                  fontSize: 14,
                                  padding: 0,
                                  lineHeight: 1,
                                  flexShrink: 0,
                                }}
                              >
                                <span
                                  style={{
                                    display: "inline-block",
                                    transform: isStoryOpen ? "rotate(90deg)" : "none",
                                    transition: "transform 0.12s ease",
                                  }}
                                >
                                  ▶
                                </span>
                              </button>
                              <div style={{ minWidth: 0 }}>
                                <Link prefetch={false} href={companyHref(r.symbol)} onClick={(e) => e.stopPropagation()} style={{ color: "#e5e5e5", fontWeight: 700, textDecoration: "none", display: "block" }}>
                                  <span>{r.symbol.replace(".L", "")}</span>
                                  <div style={{ color: "#64748b", fontSize: 10, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                    {r.name}
                                  </div>
                                </Link>
                                <div style={{ marginTop: 3, display: "flex", flexWrap: "wrap", gap: 3 }}>
                                  <IndexBadge index={r.ftse_index} full />
                                  <WithheldBadge r={r} />
                                  {vet && (
                                    <span style={{ fontSize: 8.5, fontWeight: 700, color: vet.color, background: vet.bg, border: `1px solid ${vet.color}55`, borderRadius: 2, padding: "1px 4px", letterSpacing: 0.3, whiteSpace: "nowrap", textTransform: "capitalize" }}>
                                      {st.vet_verdict}
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>
                          </td>

                          {/* Pass 1 — the ranker's score */}
                          <td style={{ ...S.td, textAlign: "center" }}>
                            <RankScore value={st.llm_score} />
                          </td>

                          {/* Pass 2 — the vet's score, the one that publishes */}
                          <td style={{ ...S.td, textAlign: "center" }}>
                            <ScoreCell value={st.vet_score} bare />
                            <VetDelta llm={st.llm_score} vet={st.vet_score} />
                          </td>

                          {/* Price */}
                          <td style={{ ...S.td, textAlign: "right" }}>
                            {live && <span title="Live" style={{ marginRight: 4, fontSize: 9, color: "#10b981" }}>●</span>}
                            <span style={{ color: "#f1f5f9", fontWeight: 700 }}>{fmtPounds(priceOf(r))}</span>
                          </td>

                          {/* Gap — the half that had already happened by the open.
                              Deliberately lighter than the column beside it: it is
                              context for the entry price, not a return anyone made. */}
                          <td
                            title={GAP_TITLE}
                            style={{ ...S.td, textAlign: "right", color: pctColor(gapPct(r)), opacity: 0.75 }}
                          >
                            {fmtPct(gapPct(r))}
                          </td>

                          {/* Since that open — the half that was actually available */}
                          <td
                            title={SINCE_OPEN_TITLE}
                            style={{ ...S.td, textAlign: "right", fontWeight: 700, color: pctColor(pctSinceOpen(r)) }}
                          >
                            {fmtPct(pctSinceOpen(r))}
                          </td>

                          {/* Forward multiple on the announcement's own stated figure */}
                          <td style={{ ...S.td, textAlign: "center" }}>
                            <FwdMultipleCell r={r} />
                          </td>

                          {/* Trend + 52w range */}
                          <td style={S.td}>
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                              <Sparkline
                                points={r.spark}
                                sinceCount={r.spark_since}
                                sinceUp={pctSinceNews(r) == null ? null : pctSinceNews(r) >= 0}
                              />
                              <RangeBar pos={rangePos(r)} />
                            </div>
                          </td>

                          {/* Days the pick has been tracked */}
                          <td style={{ ...S.td, textAlign: "center" }} title={fmtDate(st.published_at)}>
                            <span style={{ color: "#cbd5e1" }}>{fmtDaysSince(r.days_since_news)}</span>
                          </td>

                          {/* MQVR */}
                          <td style={{ ...S.td, textAlign: "center" }}><ScorePill value={r.momentum_score} /></td>
                          <td style={{ ...S.td, textAlign: "center" }}><ScorePill value={r.quality_score} /></td>
                          <td style={{ ...S.td, textAlign: "center" }}><ScorePill value={r.value_score} /></td>
                          <td style={{ ...S.td, textAlign: "center" }}><ScorePill value={r.risk_score} invert /></td>

                          {/* Follow-up tally since tracking began */}
                          <td style={{ ...S.td, textAlign: "right" }}>
                            <FollowupTally
                              pos={r.followup_pos}
                              neg={r.followup_neg}
                              expanded={isStoryOpen}
                              onToggle={() => toggleStory(r.showcase_id)}
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

                        {/* Story dropdown — hidden until the row's caret is expanded */}
                        {isStoryOpen && (
                          <tr style={{ background: baseBg }}>
                            <td colSpan={COLS.length} style={{ ...S.td, whiteSpace: "normal", borderBottom: "1px solid #1a1a1a", paddingTop: 0 }}>
                              {/* Headline row — capped to the analysis block's width so the
                                  admin buttons stay on screen rather than at the far right
                                  edge of the horizontally-scrolling table. */}
                              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", maxWidth: 760 }}>
                                <a
                                  href={st.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  style={{ color: "#e2e8f0", fontSize: 13, fontWeight: 600, textDecoration: "none" }}
                                >
                                  {st.headline}
                                </a>
                                {isAdmin && (
                                  <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }} onClick={(e) => e.stopPropagation()}>
                                    {/* Override the vet. Publishes to the PUBLIC
                                        page, so it is confirmed — every other
                                        button here is reversible, this one is
                                        outward-facing. */}
                                    {isWithheld(r) && (
                                      <button
                                        onClick={() => {
                                          if (window.confirm(`Publish ${r.symbol.replace(".L", "")} to the public page, overriding the vet's score of ${st.vet_score ?? "none"}?`)) {
                                            setStatus(r.showcase_id, "approved");
                                          }
                                        }}
                                        title="Override the vet and publish this story to the public page"
                                        style={btn("#10b981")}
                                      >
                                        Publish anyway
                                      </button>
                                    )}
                                    <button onClick={() => setStatus(r.showcase_id, "archived")} style={btn("#94a3b8")}>Archive</button>
                                  </span>
                                )}
                              </div>

                              {/* Full AI analysis */}
                              <div style={{ marginTop: 12, paddingLeft: 4, display: "flex", flexDirection: "column", gap: 14, whiteSpace: "normal", maxWidth: 760 }}>
                                <AnalysisRow label="Thesis" text={st.llm_thesis} color="#60a5fa" />
                                <AnalysisRow label="Risks" text={st.llm_risks} color="#f59e0b" />
                                {/* On a withheld row this IS the "why did it fail" text, so it is
    labelled as such rather than as generic commentary. */}
{vetFailed(r) ? (
  <AnalysisRow
    label="Vet call failed"
    text="Withheld because the vet produced no score — an API failure, not a judgement on the story."
    color="#f87171"
  />
) : (
  vet && (
    <AnalysisRow
      label={isWithheld(r) ? `Why withheld · vet ${st.vet_score}` : `AI vet · ${st.vet_verdict}`}
      text={st.vet_rationale}
      color={isWithheld(r) ? "#f59e0b" : vet.color}
    />
  )
)}
                                {r.fwd_multiple != null && r.fwd_quote && (
                                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                                    <AnalysisRow
                                      label={`${FWD_LABEL[r.fwd_metric] || "Multiple"} ${r.fwd_is_bound ? "<" : ""}${Number(r.fwd_multiple).toFixed(1)}× · source`}
                                      text={`“${r.fwd_quote}”`}
                                      color="#a78bfa"
                                    />
                                    {r.ttm_ev_ebitda != null && (
                                      <div style={{ fontSize: 10.5, color: "#64748b", lineHeight: 1.5 }}>
                                        For context: ~{Number(r.ttm_ev_ebitda).toFixed(1)}× EV/EBITDA on trailing twelve-month figures — before this announcement's new number.
                                      </div>
                                    )}
                                  </div>
                                )}
                                <AnalysisRow label="AI summary" text={st.summary} />
                                {st.llm_confidence && (
                                  <div style={{ fontSize: 10, color: "#64748b" }}>confidence: {st.llm_confidence}</div>
                                )}
                              </div>

                              {/* Archive only — the withheld rows are the ones
                                  read closely enough to want the underlying
                                  figures, and /showcase/shadow is the only
                                  endpoint that ships them (detail=True). */}
                              {archiveOnly && <ReportedNumbers r={r} />}

                              {/* Prior announcements before this story — builds up over time now
                                  that tier A/B rows outlive the 14-day source prune (most stories
                                  still show nothing until their issuer's history accumulates). */}
                              {(r.prior_news || []).length > 0 && (
                                <div style={{ marginTop: 12, paddingLeft: 4 }}>
                                  <div style={{ fontSize: 10, color: "#64748b", marginBottom: 5 }}>Previous announcements before this story</div>
                                  <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                                    {r.prior_news.map((p, pi) => {
                                      const c = p.sentiment === "positive" ? "#10b981" : p.sentiment === "negative" ? "#ef4444" : "#94a3b8";
                                      const sym = p.sentiment === "positive" ? "▲" : p.sentiment === "negative" ? "▼" : "—";
                                      const inner = (
                                        <>
                                          <span style={{ color: c, fontWeight: 700, width: 14, flexShrink: 0 }}>{sym}</span>
                                          <span style={{ color: "#475569", fontSize: 10, width: 40, flexShrink: 0 }}>{fmtWhen(p.published_at)}</span>
                                          <span style={{ color: "#cbd5e1", fontSize: 11.5 }}>{p.headline}</span>
                                        </>
                                      );
                                      return p.url ? (
                                        <a key={pi} href={p.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} style={{ display: "flex", alignItems: "baseline", gap: 8, textDecoration: "none" }}>
                                          {inner}
                                        </a>
                                      ) : (
                                        <div key={pi} style={{ display: "flex", alignItems: "baseline", gap: 8 }}>{inner}</div>
                                      );
                                    })}
                                  </div>
                                </div>
                              )}

                              {/* Subsequent announcements since tracking began */}
                              {(r.followups || []).length > 0 && (
                                <div style={{ marginTop: 10, paddingLeft: 4 }}>
                                  <div style={{ fontSize: 10, color: "#64748b", marginBottom: 5 }}>Since this story</div>
                                  <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
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
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Deferred until near-viewport so the /news fetch and the panel's
            hydration stay off the critical path; the placeholder matches the
            panel's reserved 520px, so mounting causes no shift. */}
        <LazySection minHeight={520}>
          <NewsPanel
            symbol={selectedNewsSymbol}
            name={sorted.find((r) => r.symbol === selectedNewsSymbol)?.name || (selectedNewsSymbol ? selectedNewsSymbol.replace(".L", "") : "")}
            sideBySide={false}
          />
        </LazySection>
      </div>
    </div>
  );
}
