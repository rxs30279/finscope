import { useState, useEffect, useRef, useLayoutEffect, useCallback } from "react";
import { API } from "../utils";

// ── Colour scale ──────────────────────────────────────────────────────────────
// finviz-style red→grey→green ramp, clamped at ±3% daily move. No data → neutral.
const NEUTRAL = [58, 63, 75]; // #3a3f4b slate grey centre
const GREEN = [38, 161, 90]; // #26a15a
const RED = [192, 57, 43]; // #c0392b
const CLAMP = 0.03;

const lerp = (a, b, t) => Math.round(a + (b - a) * t);
const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;

function heatColor(pct) {
  if (pct === null || pct === undefined) return "#2a2a2a";
  const t = Math.min(Math.abs(pct), CLAMP) / CLAMP; // 0..1 intensity
  const target = pct >= 0 ? GREEN : RED;
  return rgb([
    lerp(NEUTRAL[0], target[0], t),
    lerp(NEUTRAL[1], target[1], t),
    lerp(NEUTRAL[2], target[2], t),
  ]);
}

// ── Squarified treemap (Bruls, Huizing & van Wijk) ─────────────────────────────
// Lays out `items` ([{value, ...}]) into the rectangle (x, y, w, h), returning
// each item with absolute {x, y, w, h}. Produces near-square tiles ordered by
// value, which keeps the largest names readable.
function squarify(items, x, y, w, h) {
  const total = items.reduce((s, i) => s + i.value, 0);
  if (total <= 0 || w <= 0 || h <= 0) return [];

  const nodes = items.map((i) => ({ ...i, area: (i.value / total) * (w * h) }));
  const rects = [];
  let rect = { x, y, w, h };
  let row = [];

  const worst = (areas, side) => {
    if (!areas.length) return Infinity;
    const sum = areas.reduce((a, b) => a + b, 0);
    const max = Math.max(...areas);
    const min = Math.min(...areas);
    const s2 = sum * sum;
    const side2 = side * side;
    return Math.max((side2 * max) / s2, s2 / (side2 * min));
  };

  const layoutRow = (rowNodes, r) => {
    const rowArea = rowNodes.reduce((s, n) => s + n.area, 0);
    if (r.w >= r.h) {
      const rw = rowArea / r.h;
      let ry = r.y;
      rowNodes.forEach((n) => {
        const rh = n.area / rw;
        rects.push({ ...n, x: r.x, y: ry, w: rw, h: rh });
        ry += rh;
      });
      return { x: r.x + rw, y: r.y, w: r.w - rw, h: r.h };
    }
    const rh = rowArea / r.w;
    let rx = r.x;
    rowNodes.forEach((n) => {
      const rw = n.area / rh;
      rects.push({ ...n, x: rx, y: r.y, w: rw, h: rh });
      rx += rw;
    });
    return { x: r.x, y: r.y + rh, w: r.w, h: r.h - rh };
  };

  const queue = nodes.slice();
  while (queue.length) {
    const node = queue[0];
    const side = Math.min(rect.w, rect.h);
    const cur = row.map((n) => n.area);
    const next = cur.concat(node.area);
    if (row.length === 0 || worst(next, side) <= worst(cur, side)) {
      row.push(node);
      queue.shift();
    } else {
      rect = layoutRow(row, rect);
      row = [];
    }
  }
  if (row.length) layoutRow(row, rect);
  return rects;
}

const fmtCap = (v) => {
  if (v == null) return "—";
  if (v >= 1e12) return `£${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `£${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `£${(v / 1e6).toFixed(0)}M`;
  return `£${v.toFixed(0)}`;
};
const fmtPct = (p) => (p == null ? "—" : `${p >= 0 ? "+" : ""}${(p * 100).toFixed(2)}%`);

// LSE regular hours: 08:00–16:30 London time, Mon–Fri. Uses the Europe/London
// zone so BST/GMT is handled automatically. (Bank holidays aren't checked — on
// one the button would show but a live fetch just returns the last close.)
function isLseOpen(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const get = (t) => parts.find((p) => p.type === t)?.value;
  const wd = get("weekday");
  if (wd === "Sat" || wd === "Sun") return false;
  let hh = parseInt(get("hour"), 10);
  if (hh === 24) hh = 0;
  const mins = hh * 60 + parseInt(get("minute"), 10);
  return mins >= 8 * 60 && mins <= 16 * 60 + 30;
}

// Company metadata stores GICS/yfinance sector names; the rest of the app (and
// the sidebar) uses ICB names. Map them so the grid matches and "Consumer
// Staples" etc. appear under the expected label.
const SECTOR_LABELS = {
  "Basic Materials": "Materials",
  "Communication Services": "Telecommunications",
  "Consumer Cyclical": "Consumer Discretionary",
  "Consumer Defensive": "Consumer Staples",
  "Financial Services": "Financials",
  Healthcare: "Health Care",
};
const icbSector = (s) => SECTOR_LABELS[s] || s || "Other";

const INDEX_OPTIONS = [
  ["FTSE 100", "FTSE 100"],
  ["FTSE 250", "FTSE 250"],
  ["FTSE 350", "FTSE 350"],
  ["All-Share", "FTSE All-Share"],
];

const HEADER_H = 16; // sector label strip

export default function HeatmapTab({ refreshKey, onSelect }) {
  const [data, setData] = useState(null);
  const [index, setIndex] = useState("FTSE 100");
  const [live, setLive] = useState(true);
  const [marketOpen, setMarketOpen] = useState(() => isLseOpen());
  const [loading, setLoading] = useState(true);
  const [updated, setUpdated] = useState(null);
  const [dataIsLive, setDataIsLive] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const wrapRef = useRef(null);
  const [width, setWidth] = useState(0);

  // Live only makes sense while the market is open — otherwise intraday prices
  // don't move and the live fetch just echoes the last close.
  const effLive = marketOpen && live;

  // Re-check the open/closed state every minute so the Live control appears at
  // the open and disappears at the close without a reload.
  useEffect(() => {
    const id = setInterval(() => setMarketOpen(isLseOpen()), 60000);
    return () => clearInterval(id);
  }, []);

  const fetchData = useCallback(
    (liveFlag, showSpinner) => {
      if (showSpinner) setLoading(true);
      if (liveFlag) setSyncing(true);
      const params = new URLSearchParams();
      if (index) params.set("ftse_index", index);
      if (liveFlag) params.set("live", "true");
      return fetch(`${API}/heatmap?${params.toString()}`)
        .then((r) => r.json())
        .then((d) => {
          setData(Array.isArray(d) ? d : []);
          setUpdated(new Date());
          setDataIsLive(liveFlag);
        })
        .catch(() => setData((prev) => prev ?? []))
        .finally(() => {
          setLoading(false);
          if (liveFlag) setSyncing(false);
        });
    },
    [index],
  );

  // On mount / index / refresh: paint instantly from the DB (close-to-close),
  // then upgrade to live quotes in the background when Live is on.
  useEffect(() => {
    let cancelled = false;
    // Paint the DB close-to-close instantly, then always overlay live quotes —
    // even when the market is closed, where yfinance returns the last completed
    // session's move. This keeps the grid in step with the sidebar instead of
    // lagging a session behind the once-a-day DB price refresh. Only the
    // recurring poll (below) is gated to market hours.
    fetchData(false, true).then(() => {
      if (!cancelled && live) fetchData(true, false);
    });
    return () => {
      cancelled = true;
    };
  }, [fetchData, live, refreshKey]);

  // Live mode: silently refresh the live overlay every 5 minutes while open.
  useEffect(() => {
    if (!effLive) return;
    const id = setInterval(() => fetchData(true, false), 5 * 60000);
    return () => clearInterval(id);
  }, [effLive, fetchData]);

  // Track container width so the treemap can lay out in pixel space.
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const W = width || 960;
  const H = Math.max(460, Math.min(820, W * 0.62));

  // Build the two-level layout: sectors first, then stocks within each sector.
  const tiles = [];
  const sectorLabels = [];
  if (data && data.length) {
    const bySector = {};
    data.forEach((d) => {
      if (!d.market_cap || d.market_cap <= 0) return;
      const sec = icbSector(d.sector);
      (bySector[sec] = bySector[sec] || []).push(d);
    });
    const sectors = Object.entries(bySector)
      .map(([name, members]) => ({
        name,
        members,
        value: members.reduce((s, m) => s + m.market_cap, 0),
      }))
      .sort((a, b) => b.value - a.value);

    const sectorRects = squarify(sectors, 0, 0, W, H);
    sectorRects.forEach((sr) => {
      sectorLabels.push({ name: sr.name, x: sr.x, y: sr.y, w: sr.w });
      const innerY = sr.y + HEADER_H;
      const innerH = sr.h - HEADER_H;
      if (innerH <= 4 || sr.w <= 4) return;
      const members = sr.members
        .map((m) => ({ ...m, value: m.market_cap }))
        .sort((a, b) => b.value - a.value);
      squarify(members, sr.x, innerY, sr.w, innerH).forEach((t) => tiles.push(t));
    });
  }

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
          marginBottom: 14,
        }}
      >
        <div>
          <h2
            style={{
              fontFamily: "DM Serif Display,serif",
              fontSize: 22,
              color: "#f1f5f9",
              margin: 0,
            }}
          >
            Market Heatmap
          </h2>
          <div style={{ color: "#64748b", fontSize: 11, marginTop: 3 }}>
            Tiles sized by market cap, grouped by ICB sector, coloured by{" "}
            {dataIsLive && marketOpen
              ? "today's move so far"
              : "the latest session's move"}
            .
            {syncing ? (
              <span style={{ color: "#22c55e", marginLeft: 8 }}>· syncing live…</span>
            ) : (
              updated && (
                <span style={{ color: "#475569", marginLeft: 8 }}>
                  · updated{" "}
                  {updated.toLocaleTimeString("en-GB", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              )
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
          {marketOpen ? (
            <button
              onClick={() => setLive((v) => !v)}
              title="Toggle near-real-time intraday prices (refreshes every 5 minutes)"
              style={{
                border: "1px solid",
                borderColor: live ? "#166534" : "#2a2a2a",
                borderRadius: 4,
                padding: "3px 10px",
                fontSize: 12,
                fontFamily: "monospace",
                cursor: "pointer",
                background: live ? "#14532d" : "none",
                color: live ? "#bbf7d0" : "#64748b",
                display: "flex",
                alignItems: "center",
                gap: 5,
              }}
            >
              <span
                className={live ? "spinning" : ""}
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: live ? "#22c55e" : "#475569",
                  display: "inline-block",
                }}
              />
              {live ? "LIVE" : "Live"}
            </button>
          ) : (
            <span
              title="LSE is closed (08:00–16:30 London, Mon–Fri) — showing the last close"
              style={{
                border: "1px solid #2a2a2a",
                borderRadius: 4,
                padding: "3px 10px",
                fontSize: 12,
                fontFamily: "monospace",
                color: "#64748b",
                display: "flex",
                alignItems: "center",
                gap: 5,
              }}
            >
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: "#475569",
                  display: "inline-block",
                }}
              />
              Market closed
            </span>
          )}
          <span style={{ width: 8 }} />
          {INDEX_OPTIONS.map(([label, val]) => {
            const active = index === val;
            return (
              <button
                key={val}
                onClick={() => setIndex(val)}
                style={{
                  border: "1px solid #2a2a2a",
                  borderRadius: 4,
                  padding: "3px 10px",
                  fontSize: 12,
                  fontFamily: "monospace",
                  cursor: "pointer",
                  background: active ? "#3730a3" : "none",
                  color: active ? "#e0e7ff" : "#64748b",
                  borderColor: active ? "#4338ca" : "#2a2a2a",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 10,
          fontFamily: "monospace",
          fontSize: 10,
          color: "#64748b",
        }}
      >
        <span>-3%</span>
        {[-0.03, -0.018, -0.007, 0, 0.007, 0.018, 0.03].map((p) => (
          <span
            key={p}
            style={{
              width: 26,
              height: 12,
              background: heatColor(p),
              display: "inline-block",
              borderRadius: 2,
            }}
          />
        ))}
        <span>+3%</span>
      </div>

      <div
        ref={wrapRef}
        style={{
          position: "relative",
          width: "100%",
          height: H,
          background: "#0a0a0a",
          border: "1px solid #1e1e1e",
          borderRadius: 4,
          overflow: "hidden",
        }}
      >
        {loading ? (
          <div style={{ ...centered, color: "#64748b" }}>Loading…</div>
        ) : !tiles.length ? (
          <div style={{ ...centered, color: "#64748b" }}>No data</div>
        ) : (
          <>
            {sectorLabels.map((s) => (
              <div
                key={`lbl-${s.name}`}
                style={{
                  position: "absolute",
                  left: s.x,
                  top: s.y,
                  width: s.w,
                  height: HEADER_H,
                  display: "flex",
                  alignItems: "center",
                  padding: "0 5px",
                  color: "#94a3b8",
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: 0.5,
                  textTransform: "uppercase",
                  fontFamily: "monospace",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  pointerEvents: "none",
                }}
              >
                {s.w > 60 ? s.name : ""}
              </div>
            ))}
            {tiles.map((t) => {
              const showText = t.w > 30 && t.h > 20;
              const big = t.w > 64 && t.h > 44;
              const ticker = t.symbol.replace(".L", "");
              return (
                <div
                  key={t.symbol}
                  onClick={() => onSelect && onSelect(t.symbol)}
                  title={`${t.name} · ${fmtCap(t.market_cap)} · ${fmtPct(t.pct_change)}`}
                  style={{
                    position: "absolute",
                    left: t.x,
                    top: t.y,
                    width: t.w,
                    height: t.h,
                    background: heatColor(t.pct_change),
                    border: "1px solid rgba(0,0,0,0.45)",
                    boxSizing: "border-box",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    overflow: "hidden",
                    cursor: "pointer",
                    color: "#fff",
                    fontFamily: "monospace",
                    lineHeight: 1.1,
                  }}
                >
                  {showText && (
                    <>
                      <span
                        style={{
                          fontWeight: 700,
                          fontSize: big ? 13 : 10,
                          textShadow: "0 1px 2px rgba(0,0,0,0.6)",
                        }}
                      >
                        {ticker}
                      </span>
                      {big && (
                        <span
                          style={{
                            fontSize: 10,
                            opacity: 0.95,
                            textShadow: "0 1px 2px rgba(0,0,0,0.6)",
                          }}
                        >
                          {fmtPct(t.pct_change)}
                        </span>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}

const centered = {
  position: "absolute",
  inset: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontFamily: "monospace",
};
