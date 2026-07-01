"use client";
import { useState, useEffect, useMemo } from "react";
import { useIsMobile, useIsTablet, useMediaQuery } from "@/hooks/useMediaQuery";
import { API } from "@/lib/api";
import PageHeader from "@/components/layout/PageHeader";

const CATEGORY_LABELS = {
  profit_warning: "Profit Warning",
  trading_update: "Trading Update",
  final_results: "Final Results",
  interim_results: "Interim Results",
  quarterly: "Quarterly",
  firm_offer: "Firm Offer (2.7)",
  possible_offer: "Possible Offer (2.4)",
  recommended_offer: "Recommended Offer",
  strategic_review: "Strategic Review",
  suspension: "Suspension",
  going_concern: "Going Concern",
  liquidation: "Liquidation",
  delisting: "Delisting",
  response_to: "Response to Press",
  capital_markets: "Capital Markets Day",
  capital_raise: "Capital Raise",
  acquisition: "Acquisition",
  disposal: "Disposal",
  contract_win: "Contract / Partnership",
  board_change: "Board Change",
  drug_approval: "Drug Approval",
  clinical_trial: "Clinical Trial",
  drill_results: "Drill Results",
  dividend_change: "Dividend Change",
  update_statement: "Operational Update",
};

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return d.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Same data as fmtTime but split into date/time parts so the table's Time
// column can stack them on two lines (narrower column). Same-day rows have no
// date part — just the time.
function fmtTimeParts(iso) {
  if (!iso) return { date: null, time: "—" };
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  const time = d.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (sameDay) return { date: null, time };
  const date = d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
  });
  return { date, time };
}

function fmtCurrency(v) {
  if (v == null) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e12) return "£" + (v / 1e12).toFixed(2) + "T";
  if (abs >= 1e9) return "£" + (v / 1e9).toFixed(1) + "B";
  if (abs >= 1e6) return "£" + (v / 1e6).toFixed(0) + "M";
  if (abs >= 1e3) return "£" + (v / 1e3).toFixed(0) + "K";
  return "£" + v.toFixed(0);
}

function fmtAgo(iso) {
  if (!iso) return "never";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

const _NEG_CATS = new Set([
  "profit_warning", "going_concern", "liquidation", "delisting", "suspension",
]);
const _POS_CATS = new Set([
  "firm_offer", "recommended_offer", "drug_approval", "contract_win",
]);

const _LLM_POS = ["positive", "upside", "beat", "above expectations", "outperform", "upgrade", "bullish", "boost", "opportunity"];
const _LLM_NEG = ["negative", "pressure", "miss", "below expectations", "concern", "decline", "downgrade", "disappoint", "warning", "bearish", "weak"];

function getSentiment(r) {
  // Layer 1: unambiguous category overrides
  if (_NEG_CATS.has(r.category)) return "negative";
  if (_POS_CATS.has(r.category)) return "positive";

  // Layer 2: LLM thesis — scan for directional language
  if (r.llm_thesis) {
    const text = r.llm_thesis.toLowerCase();
    const pos = _LLM_POS.filter((w) => text.includes(w)).length;
    const neg = _LLM_NEG.filter((w) => text.includes(w)).length;
    if (neg > pos) return "negative";
    if (pos > neg) return "positive";
  }

  // Layer 3: keyword hits fallback
  const hits = r.keyword_hits || [];
  const neg = hits.filter((h) => h.startsWith("neg:")).length;
  const pos = hits.filter((h) => h.startsWith("pos:")).length;
  if (neg > pos) return "negative";
  if (pos > neg) return "positive";
  return "neutral";
}

function SentimentBadge({ row }) {
  const s = getSentiment(row);
  const map = {
    positive: { symbol: "▲", color: "#10b981" },
    negative: { symbol: "▼", color: "#ef4444" },
    neutral:  { symbol: "—", color: "#60a5fa" },
  };
  const { symbol, color } = map[s];
  return (
    <span style={{ color, fontFamily: "monospace", fontSize: 11, fontWeight: 700 }}>
      {symbol}
    </span>
  );
}

function ScoreCell({ value }) {
  if (value == null)
    return (
      <span style={{ color: "#333", fontFamily: "monospace", fontSize: 12 }}>
        —
      </span>
    );
  const colour =
    value >= 75
      ? "#f97316"
      : value >= 50
        ? "#60a5fa"
        : value >= 25
          ? "#94a3b8"
          : "#555";
  return (
    <span style={{ color: colour, fontFamily: "monospace", fontSize: 12 }}>
      {value}
    </span>
  );
}

const ACTION_COLORS = {
  research: { color: "#f97316", bg: "#1f1200" },
  watch: { color: "#60a5fa", bg: "#0d1a2a" },
  ignore: { color: "#555", bg: "#141414" },
};

function ActionPill({ action }) {
  if (!action)
    return (
      <span style={{ color: "#333", fontFamily: "monospace", fontSize: 10 }}>
        —
      </span>
    );
  const c = ACTION_COLORS[action] || ACTION_COLORS.ignore;
  return (
    <span
      style={{
        background: c.bg,
        color: c.color,
        padding: "2px 8px",
        borderRadius: 2,
        fontSize: 10,
        fontFamily: "monospace",
        fontWeight: 700,
        letterSpacing: 1,
        textTransform: "uppercase",
      }}
    >
      {action}
    </span>
  );
}

function KeywordTags({ hits }) {
  if (!hits || hits.length === 0) return null;
  return (
    <span style={{ marginLeft: 8 }}>
      {hits.map((h, i) => {
        const [kind] = h.split(":");
        const colour =
          kind === "neg" ? "#ef4444" : kind === "pos" ? "#10b981" : "#f59e0b";
        return (
          <span
            key={i}
            style={{
              fontSize: 9,
              color: colour,
              fontFamily: "monospace",
              padding: "1px 5px",
              border: `1px solid ${colour}`,
              borderRadius: 2,
              marginLeft: 4,
              opacity: 0.8,
            }}
          >
            {h}
          </span>
        );
      })}
    </span>
  );
}

export default function RnsTab({ refreshKey, onSelect }) {
  // Use the stacked single-column layout on phones AND tablet-width screens
  // (e.g. a Surface Pro in portrait, ~912px). The full desktop table has too
  // many columns to fit those widths and otherwise spills off the page.
  // Call both hooks unconditionally — `||` would short-circuit useIsTablet()
  // when useIsMobile() is true, changing the hook count across a resize and
  // crashing React (Rules of Hooks).
  const isMobileWidth = useIsMobile();
  const isTablet = useIsTablet();
  // The full multi-column table needs ~1080px just for its fixed columns, and
  // on a 1024-wide laptop the sidebar + card padding eat further into that —
  // cramping the headline into a narrow sliver. Treat anything up to ~1200px as
  // "small" and use the fluid stacked single-column layout there too.
  const isCramped = useMediaQuery("(max-width: 1199px)");
  const isMobile = isMobileWidth || isTablet || isCramped;
  // On the narrowest (phone) widths the action pill won't fit beside the score
  // on the meta line, so drop it down next to the market cap and leave just the
  // score pinned top-right.
  const isNarrow = useMediaQuery("(max-width: 640px)");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [hours, setHours] = useState(72);
  const [minLlmScore, setMinLlmScore] = useState(50);
  const [search, setSearch] = useState("");
  // Bumped by the manual refresh button or the auto-poll to force a re-fetch.
  const [manualRefresh, setManualRefresh] = useState(0);

  // Auto-poll: fire 90s after each 15-min UTC boundary (synced to the backend cron,
  // staggered to give the pipeline time to finish). Then every 15 min. Pauses when the tab is hidden; re-syncs and optionally
  // fires immediately when the tab becomes visible again after >15 min away.
  useEffect(() => {
    const INTERVAL = 15 * 60 * 1000;
    const STAGGER = 30 * 1000; // wait 30s after the boundary for the cron to finish
    const poll = () => setManualRefresh((n) => n + 1);
    let timeout = null;
    let interval = null;
    let hiddenAt = null;

    const stop = () => { clearTimeout(timeout); clearInterval(interval); };

    const schedule = () => {
      stop();
      const msUntilNext = INTERVAL - (Date.now() % INTERVAL) + STAGGER;
      timeout = setTimeout(() => {
        poll();
        interval = setInterval(poll, INTERVAL);
      }, msUntilNext);
    };

    const onVisibility = () => {
      if (document.hidden) {
        hiddenAt = Date.now();
        stop();
      } else {
        if (hiddenAt && Date.now() - hiddenAt > INTERVAL) poll();
        schedule();
      }
    };

    document.addEventListener("visibilitychange", onVisibility);
    if (!document.hidden) schedule();
    return () => { stop(); document.removeEventListener("visibilitychange", onVisibility); };
  }, []);

  useEffect(() => {
    setLoading(true);
    const bust = manualRefresh > 0 ? `&_t=${Date.now()}` : "";
    fetch(`${API}/rns/latest?min_score=0&hours=${hours}&limit=500${bust}`)
      .then((r) => r.json())
      .then((d) => {
        const data = Array.isArray(d) ? d : [];
        setRows(data);
        setLoading(false);
        // After initial render, try to fill in market caps for rows that
        // don't have one in the DB. The backend returns {} if no Yahoo
        // Finance API key is configured — the column shows "—" in that case.
        fetch(`${API}/rns/market-caps?min_score=0&hours=${hours}`)
          .then((r) => r.json())
          .then((mcMap) => {
            if (Object.keys(mcMap).length === 0) return;
            setRows((prev) =>
              prev.map((r) => {
                if (r.market_cap != null) return r;
                const key = r.symbol || r.ticker;
                return key && mcMap[key] != null
                  ? { ...r, market_cap: mcMap[key] }
                  : r;
              }),
            );
          })
          .catch(() => {});
      })
      .catch(() => setLoading(false));
  }, [refreshKey, hours, manualRefresh]);

  const filtered = useMemo(() => {
    let r = rows;
    if (search) {
      const q = search.toLowerCase();
      r = r.filter(
        (x) =>
          x.ticker?.toLowerCase().includes(q) ||
          x.company_name?.toLowerCase().includes(q) ||
          x.headline?.toLowerCase().includes(q),
      );
    }
    if (minLlmScore > 0) {
      r = r.filter((x) => x.llm_score != null && x.llm_score >= minLlmScore);
    }
    // Ranked rows first (by llm_score desc), then unranked (by published_at desc)
    r = [...r].sort((a, b) => {
      const aR = a.llm_score != null,
        bR = b.llm_score != null;
      if (aR && bR) return b.llm_score - a.llm_score;
      if (aR) return -1;
      if (bR) return 1;
      return new Date(b.published_at) - new Date(a.published_at);
    });
    return r;
  }, [rows, search, minLlmScore]);

  const ranked = useMemo(() => rows.filter((r) => r.llm_score != null), [rows]);

  // Bucket filtered rows by FTSE index — same logic as the digest email.
  // Anything not explicitly FTSE 100 / 250 falls into "small" (SmallCap, AIM,
  // unlisted, or NULL ftse_index).
  const buckets = useMemo(() => {
    const out = { large: [], mid: [], small: [] };
    for (const r of filtered) {
      const idx = r.ftse_index;
      if (idx === "FTSE 100") out.large.push(r);
      else if (idx === "FTSE 250") out.mid.push(r);
      else out.small.push(r);
    }
    return out;
  }, [filtered]);
  const lastUpdatedAt = useMemo(() => {
    let m = 0;
    for (const r of rows) {
      if (r.fetched_at) {
        const t = new Date(r.fetched_at).getTime();
        if (t > m) m = t;
      }
    }
    return m ? new Date(m).toISOString() : null;
  }, [rows]);

  const S = {
    card: {
      background: "#141414",
      border: "1px solid #2a2a2a",
      borderRadius: 3,
      padding: 16,
    },
    th: {
      fontSize: 10,
      color: "#555",
      textTransform: "uppercase",
      letterSpacing: 1,
      padding: "8px 12px",
      fontFamily: "monospace",
      textAlign: "left",
      position: "sticky",
      top: 0,
      background: "#141414",
      zIndex: 1,
    },
    td: {
      padding: "10px 12px",
      borderBottom: "1px solid #1a1a1a",
      fontSize: 12,
      fontFamily: "monospace",
      color: "#e5e5e5",
      verticalAlign: "top",
    },
    pill: (active) => ({
      background: active ? "#1f1200" : "none",
      color: active ? "#f97316" : "#666",
      border: "1px solid #2a2a2a",
      padding: "4px 10px",
      borderRadius: 2,
      fontFamily: "monospace",
      fontSize: 10,
      cursor: "pointer",
      letterSpacing: 1,
      textTransform: "uppercase",
    }),
  };

  if (loading)
    return (
      <div style={{ color: "#444", padding: 32, fontFamily: "monospace" }}>
        Loading RNS feed…
      </div>
    );

  // On mobile the full multi-column row is wider than the screen and the
  // headline spills off the right. Stack it instead: a compact meta line
  // (time · tier · ticker · company) with the headline and AI thesis beneath.
  const renderMobileRow = (r) => {
    const { date, time } = fmtTimeParts(r.published_at);
    return (
      <tr key={r.id} style={{ borderBottom: "1px solid #1a1a1a" }}>
        <td style={{ ...S.td, padding: "10px 8px" }}>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: 8,
              marginBottom: 6,
            }}
          >
            <span style={{ color: "#666", fontSize: 11 }}>
              {date ? `${date} ` : ""}
              {time}
            </span>
            <SentimentBadge row={r} />
            {r.ticker &&
              (r.symbol ? (
                <span
                  onClick={() => onSelect?.(r.symbol)}
                  title={`View ${r.symbol}`}
                  style={{ color: "#e5e5e5", fontWeight: 700, cursor: "pointer" }}
                >
                  {r.ticker}
                  <span
                    style={{
                      color: "#818cf8",
                      marginLeft: 4,
                      fontWeight: 400,
                      fontSize: 10,
                    }}
                  >
                    ↗
                  </span>
                </span>
              ) : (
                <span style={{ color: "#e5e5e5", fontWeight: 700 }}>
                  {r.ticker}
                </span>
              ))}
            {r.company_name && (
              <span style={{ color: "#94a3b8", fontSize: 11, overflowWrap: "anywhere" }}>
                {r.company_name}
              </span>
            )}
            {/* Action + AI score — pinned to the top-right of the card, as in
                the email digest. Action sits to the left of the score, but on
                narrow widths it drops to the market-cap line (below) so the
                score keeps its top-right slot. */}
            {((!isNarrow && r.llm_action) || r.llm_score != null) && (
              <span
                style={{
                  marginLeft: "auto",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                {!isNarrow && r.llm_action && <ActionPill action={r.llm_action} />}
                {r.llm_score != null && <ScoreCell value={r.llm_score} />}
              </span>
            )}
          </div>
          {/* Market cap on its own line beneath the meta row. On narrow widths
              this line also hosts the action pill (dropped from the meta row). */}
          {(r.market_cap != null || (isNarrow && r.llm_action)) && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                marginBottom: 6,
              }}
            >
              {r.market_cap != null && (
                <span
                  style={{ color: "#666", fontSize: 11, fontFamily: "monospace" }}
                >
                  Mkt cap{" "}
                  <span style={{ color: "#94a3b8" }}>
                    {fmtCurrency(r.market_cap)}
                  </span>
                </span>
              )}
              {isNarrow && r.llm_action && <ActionPill action={r.llm_action} />}
            </div>
          )}
          <a
            href={r.url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: "#e5e5e5",
              textDecoration: "none",
              borderBottom: "1px dotted #3a3a3a",
              overflowWrap: "anywhere",
            }}
          >
            {r.headline}
          </a>
          <KeywordTags hits={r.keyword_hits} />
          {r.llm_thesis && (
            <div
              style={{ marginTop: 6, color: "#888", fontSize: 11, lineHeight: 1.4 }}
            >
              {r.llm_thesis}
              {r.llm_risks && (
                <div style={{ marginTop: 3, color: "#5a5a5a", fontSize: 10 }}>
                  <span style={{ color: "#ef4444" }}>risk:</span> {r.llm_risks}
                </div>
              )}
            </div>
          )}
        </td>
      </tr>
    );
  };

  const renderRow = (r) =>
    isMobile ? (
      renderMobileRow(r)
    ) : (
    <tr key={r.id} style={{ borderBottom: "1px solid #141414" }}>
      <td style={{ ...S.td, color: "#666", whiteSpace: "nowrap" }}>
        {(() => {
          const { date, time } = fmtTimeParts(r.published_at);
          return (
            <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.35 }}>
              {date && <span style={{ color: "#555" }}>{date}</span>}
              <span>{time}</span>
            </div>
          );
        })()}
      </td>
      <td style={{ ...S.td, textAlign: "center", paddingLeft: 4, paddingRight: 4 }}>
        <SentimentBadge row={r} />
      </td>
      <td
        style={{
          ...S.td,
          textAlign: "right",
          whiteSpace: "nowrap",
          display: isMobile ? "none" : undefined,
        }}
      >
        {r.market_cap != null ? fmtCurrency(r.market_cap) : "—"}
      </td>
      <td style={{ ...S.td, fontWeight: 700, whiteSpace: "nowrap" }}>
        {r.ticker ? (
          r.symbol ? (
            <span
              onClick={() => onSelect?.(r.symbol)}
              title={`View ${r.symbol}`}
              style={{
                color: "#e5e5e5",
                cursor: "pointer",
                textDecoration: "none",
              }}
            >
              {r.ticker}
              <span
                style={{
                  color: "#818cf8",
                  marginLeft: 4,
                  fontWeight: 400,
                  fontSize: 10,
                }}
              >
                ↗
              </span>
            </span>
          ) : (
            r.ticker
          )
        ) : (
          "—"
        )}
      </td>
      <td
        style={{
          ...S.td,
          color: "#94a3b8",
          maxWidth: isMobile ? 80 : 120,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {r.company_name || "—"}
      </td>
      <td
        style={{
          ...S.td,
          maxWidth: isMobile ? "none" : 400,
          minWidth: isMobile ? 180 : 250,
        }}
      >
        <a
          href={r.url}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            color: "#e5e5e5",
            textDecoration: "none",
            borderBottom: "1px dotted #3a3a3a",
          }}
        >
          {r.headline}
        </a>
        <KeywordTags hits={r.keyword_hits} />
        {r.llm_thesis && (
          <div
            style={{
              marginTop: 6,
              color: "#888",
              fontSize: 11,
              lineHeight: 1.4,
              maxWidth: 600,
            }}
          >
            {r.llm_thesis}
            {r.llm_risks && (
              <div style={{ marginTop: 3, color: "#5a5a5a", fontSize: 10 }}>
                <span style={{ color: "#ef4444" }}>risk:</span> {r.llm_risks}
              </div>
            )}
          </div>
        )}
      </td>
      <td
        style={{
          ...S.td,
          color: "#666",
          fontSize: 11,
          whiteSpace: "nowrap",
          display: isMobile ? "none" : undefined,
        }}
      >
        {CATEGORY_LABELS[r.category] || r.category || "—"}
      </td>
      <td
        style={{
          ...S.td,
          textAlign: "right",
          display: isMobile ? "none" : undefined,
        }}
      >
        <ScoreCell value={r.score} />
      </td>
      <td
        style={{
          ...S.td,
          textAlign: "right",
          display: isMobile ? "none" : undefined,
        }}
      >
        <ScoreCell value={r.llm_score} />
      </td>
      <td
        style={{
          ...S.td,
          textAlign: "center",
          display: isMobile ? "none" : undefined,
        }}
      >
        <ActionPill action={r.llm_action} />
      </td>
    </tr>
    );

  return (
    <div>
      {/* Header */}
      <PageHeader
        title="RNS Daily News Screener"
        subtitle="London Stock Exchange regulatory announcements, filtered and AI-ranked by significance."
        right={
          <span
            style={{
              fontSize: 10,
              color: "#555",
              fontFamily: "monospace",
              letterSpacing: 1,
              textTransform: "uppercase",
              display: "flex",
              flexWrap: "wrap",
              alignItems: "baseline",
              gap: 14,
            }}
          >
            <span style={{ display: "inline-flex", alignItems: "baseline", gap: 8 }}>
              Last available update:{" "}
              {lastUpdatedAt && (
                <span style={{ color: "#888" }}>{fmtTime(lastUpdatedAt)}</span>
              )}
              <button
                type="button"
                onClick={() => setManualRefresh((n) => n + 1)}
                disabled={loading}
                title="Reload data from server — new announcements ingest automatically every ~15 min"
                style={{
                  background: "#0a0a0a",
                  color: loading ? "#444" : "#f97316",
                  border: "1px solid #2a2a2a",
                  borderRadius: 2,
                  padding: "2px 8px",
                  fontFamily: "monospace",
                  fontSize: 10,
                  letterSpacing: 1,
                  textTransform: "uppercase",
                  cursor: loading ? "default" : "pointer",
                }}
              >
                {loading ? "Refreshing…" : "↻ Refresh"}
              </button>
            </span>
            <span style={{ color: "#444" }}>·</span>
            <span>
              AI Ranked: <span style={{ color: "#10b981" }}>{ranked.length}</span>
              {"  "}Total: <span style={{ color: "#e5e5e5" }}>{rows.length}</span>
            </span>
            <span style={{ color: "#444" }}>·</span>
            <a
              href="/subscribe"
              style={{
                color: "#f97316",
                textDecoration: "none",
                letterSpacing: 1,
              }}
            >
              Subscribe →
            </a>
          </span>
        }
      />

      {/* Controls */}
      {(() => {
        const windowDropdown = (
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            <span style={{ fontSize: 10, color: "#555", letterSpacing: 1, textTransform: "uppercase", fontFamily: "monospace" }}>
              Window
            </span>
            <select
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
              style={{ background: "#0a0a0a", color: "#e5e5e5", border: "1px solid #2a2a2a", padding: "4px 8px", fontFamily: "monospace", fontSize: 11, borderRadius: 2 }}
            >
              <option value={6}>6 hours</option>
              <option value={12}>12 hours</option>
              <option value={24}>24 hours</option>
              <option value={48}>48 hours</option>
              <option value={72}>72 hours</option>
              <option value={168}>1 week</option>
            </select>
          </div>
        );
        const scoreCount = (
          <span style={{ fontFamily: "monospace", whiteSpace: "nowrap", textAlign: "right" }}>
            <span style={{ fontSize: 11, color: "#888" }}>AI </span>
            <span style={{ fontSize: 11, color: minLlmScore >= 75 ? "#f97316" : minLlmScore >= 50 ? "#60a5fa" : minLlmScore >= 25 ? "#94a3b8" : "#888" }}>
              {minLlmScore > 0 ? `${minLlmScore}+` : "All"}
            </span>
            <span style={{ fontSize: 11, color: "#888" }}>{" "}({filtered.length} news items)</span>
          </span>
        );
        const sliderLabel = (
          <span style={{ fontSize: 10, color: "#555", letterSpacing: 1, textTransform: "uppercase", fontFamily: "monospace" }}>
            AI Score
          </span>
        );
        const sliderInput = (
          <input
            type="range"
            min={0} max={100} step={5}
            value={minLlmScore}
            onChange={(e) => setMinLlmScore(Number(e.target.value))}
            style={{ flex: 1, width: "100%", accentColor: "#f97316", cursor: "pointer" }}
          />
        );
        const searchInput = (
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter ticker / company / headline…"
            style={{ background: "#0a0a0a", border: "1px solid #2a2a2a", color: "#e5e5e5", padding: "6px 10px", borderRadius: 2, fontFamily: "monospace", fontSize: 11, width: "100%", boxSizing: "border-box" }}
          />
        );
        return isMobile ? (
          <div style={{ ...S.card, marginBottom: 16, display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {windowDropdown}
              <span style={{ marginLeft: "auto" }}>{scoreCount}</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {sliderLabel}
              {sliderInput}
            </div>
            {searchInput}
          </div>
        ) : (
          <div style={{ ...S.card, marginBottom: 16, display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
            {windowDropdown}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "1 1 220px", minWidth: 160 }}>
              {sliderLabel}
              {sliderInput}
              {scoreCount}
            </div>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter ticker / company / headline…"
              style={{ background: "#0a0a0a", border: "1px solid #2a2a2a", color: "#e5e5e5", padding: "6px 10px", borderRadius: 2, fontFamily: "monospace", fontSize: 11, flex: 1, minWidth: 200 }}
            />
          </div>
        );
      })()}

      {/* Bucketed tables — one section per FTSE cap bucket. */}
      {filtered.length === 0 && (
        <div
          style={{
            ...S.card,
            textAlign: "center",
            color: "#444",
            padding: 32,
            fontFamily: "monospace",
            fontSize: 12,
          }}
        >
          No announcements in this window
        </div>
      )}

      {[
        { key: "large", label: "Large Cap", sub: "FTSE 100",                       color: "#f97316" },
        { key: "mid",   label: "Mid Cap",   sub: "FTSE 250",                       color: "#60a5fa" },
        { key: "small", label: "Small Cap", sub: "SmallCap / AIM / other",         color: "#6b7280" },
      ].map(({ key, label, sub, color }) => {
        const items = buckets[key];
        if (!items || items.length === 0) return null;
        return (
          <div key={key} style={{ marginBottom: 18 }}>
            {/* Section heading bar */}
            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                flexWrap: "wrap",
                gap: 12,
                padding: "8px 12px",
                marginBottom: 6,
                background: `${color}15`,
                borderLeft: `3px solid ${color}`,
                borderRadius: 2,
              }}
            >
              <span
                style={{
                  fontFamily: "monospace",
                  fontWeight: 700,
                  color,
                  fontSize: 12,
                  letterSpacing: 2,
                  textTransform: "uppercase",
                }}
              >
                {label}
              </span>
              <span style={{ fontFamily: "monospace", color: "#666", fontSize: 10 }}>
                {sub}
              </span>
              <span
                style={{
                  marginLeft: "auto",
                  fontFamily: "monospace",
                  color: "#666",
                  fontSize: 10,
                }}
              >
                {items.length} item{items.length === 1 ? "" : "s"}
              </span>
            </div>

            {/* Section table */}
            <div style={{ ...S.card, overflowX: "auto" }}>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: 12,
                  // Fixed layout + a shared colgroup so all three cap-bucket
                  // tables share identical column widths and line up vertically.
                  // (Default auto-layout sizes each table to its own content,
                  // which is why the columns drifted out of alignment.)
                  tableLayout: isMobile ? undefined : "fixed",
                  // The 9 fixed columns total ~760px; reserve enough headroom so
                  // the flexible Headline column stays readable. Below this the
                  // card (overflowX:auto) scrolls horizontally rather than
                  // squeezing the headline into a narrow sliver — which is what
                  // happened at ~1024px-wide viewports (content area < table).
                  minWidth: isMobile ? undefined : 1080,
                }}
              >
                {!isMobile && (
                  <colgroup>
                    <col style={{ width: 64 }} />{/* Time */}
                    <col style={{ width: 80 }} />{/* Sentiment */}
                    <col style={{ width: 80 }} />{/* Mkt Cap */}
                    <col style={{ width: 96 }} />{/* Ticker */}
                    <col style={{ width: 130 }} />{/* Company */}
                    <col />{/* Headline / AI Thesis — takes remaining space */}
                    <col style={{ width: 140 }} />{/* Category */}
                    <col style={{ width: 56 }} />{/* Rules */}
                    <col style={{ width: 48 }} />{/* AI */}
                    <col style={{ width: 90 }} />{/* Action */}
                  </colgroup>
                )}
                {!isMobile && (
                <thead>
                  <tr style={{ borderBottom: "1px solid #2a2a2a" }}>
                    <th style={S.th}>Time</th>
                    <th style={{ ...S.th, textAlign: "center" }}>Sentiment</th>
                    <th
                      style={{
                        ...S.th,
                        textAlign: "right",
                        display: isMobile ? "none" : undefined,
                      }}
                    >
                      Mkt Cap
                    </th>
                    <th style={S.th}>Ticker</th>
                    <th style={S.th}>Company</th>
                    <th style={S.th}>Headline / AI Thesis</th>
                    <th style={{ ...S.th, display: isMobile ? "none" : undefined }}>
                      Category
                    </th>
                    <th
                      style={{
                        ...S.th,
                        textAlign: "right",
                        display: isMobile ? "none" : undefined,
                      }}
                    >
                      Rules
                    </th>
                    <th
                      style={{
                        ...S.th,
                        textAlign: "right",
                        display: isMobile ? "none" : undefined,
                      }}
                    >
                      AI
                    </th>
                    <th
                      style={{
                        ...S.th,
                        textAlign: "center",
                        display: isMobile ? "none" : undefined,
                      }}
                    >
                      Action
                    </th>
                  </tr>
                </thead>
                )}
                <tbody>{items.map(renderRow)}</tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
