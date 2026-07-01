"use client";
import { useState, useEffect, useRef } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer
} from 'recharts';
import { API } from "@/lib/api";
import { fmt, fmtUKDate } from "@/lib/format";
import { useIsMobile } from "@/hooks/useMediaQuery";
import InfoDot from "@/components/InfoDot";

// Text colour for the consensus label in the caption line.
const CONSENSUS_TEXT = { Buy: '#10b981', Hold: '#94a3b8', Sell: '#ef4444' };

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// "2026-06-01" → "1 Jun" (axis tick); falls back to the raw value if unparseable.
const fmtTickDate = (s) => {
  if (typeof s !== 'string') return s;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return s;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`;
};

// Rating buckets rendered outward from the neutral spine: mild (sell/buy) sit
// inside next to Hold, strong ratings sit on the outer edges.
const RATING_COLORS = {
  strong_sell: '#b91c1c', sell: '#ef4444', hold: '#4b5563',
  buy: '#10b981', strong_buy: '#059669',
};
const RATING_LABELS = {
  strong_sell: 'Strong Sell', sell: 'Sell', hold: 'Hold',
  buy: 'Buy', strong_buy: 'Strong Buy',
};
// Brighter, roughly luminance-matched tints for the labels — mild and strong
// variants share a tint so the text reads at equal brightness (the block fills
// still distinguish strong vs mild). More legible than the dark fill colours.
const LABEL_COLORS = {
  strong_sell: '#f87171', sell: '#f87171', hold: '#cbd5e1',
  buy: '#34d399', strong_buy: '#34d399',
};

// Diverging consensus bar: Hold straddles a fixed centre spine, buys grow right,
// sells grow left. Each analyst-share maps to half the container width, so an
// all-one-side book fills exactly to that edge and the spine stays put at 50%.
function ConsensusDivergingBar({ row, isMobile }) {
  const [hover, setHover] = useState(null);
  const [staggered, setStaggered] = useState(false);
  const labelWrapRef = useRef(null);
  const segsRef = useRef([]);

  const total = row.total_analysts || 0;
  const counts = {
    strong_sell: row.strong_sell || 0, sell: row.sell || 0, hold: row.hold || 0,
    buy: row.buy || 0, strong_buy: row.strong_buy || 0,
  };

  // Lay non-empty blocks left→right (bearish→bullish), each sized to its share
  // of the total, with a small gap between them, filling a target fraction of
  // the card. Fill nearly the whole width on mobile so blocks don't get squished.
  const ORDER = ['strong_sell', 'sell', 'hold', 'buy', 'strong_buy'];
  const active = total ? ORDER.filter((k) => counts[k] > 0) : [];
  const GAP = 1.2;                                   // container %
  const fill = isMobile ? 98 : 52;                   // target width of the run
  const scale = (fill - Math.max(0, active.length - 1) * GAP) / 100;
  let x = 50 - fill / 2;                             // left edge, centred
  const segs = active.map((k) => {
    const width = (counts[k] / total) * 100 * scale;
    const seg = { k, left: x, width };
    x += width + GAP;
    return seg;
  });
  segsRef.current = segs;

  // Stagger the labels onto two rows only when they'd actually overlap on one
  // line — measure each label's real width against its block-centre position.
  // Re-checks on resize so it un-staggers when there's room.
  const staggerKey = segs.map((s) => `${s.k}${s.width.toFixed(1)}`).join('|');
  useEffect(() => {
    const wrap = labelWrapRef.current;
    if (!wrap) return;
    const measure = () => {
      const cw = wrap.offsetWidth;
      const s = segsRef.current;
      const kids = Array.from(wrap.children);
      if (!cw || kids.length !== s.length || kids.length < 2) { setStaggered(false); return; }
      let overlap = false, prevRight = -Infinity;
      for (let i = 0; i < kids.length; i++) {
        const center = ((s[i].left + s[i].width / 2) / 100) * cw;
        const half = kids[i].offsetWidth / 2;
        if (center - half < prevRight + 4) { overlap = true; break; }
        prevRight = center + half;
      }
      setStaggered(overlap);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [staggerKey]);

  if (!total) return <div style={{ color: '#444', fontSize: 12 }}>No consensus data</div>;

  const lowCoverage = total < 3;

  return (
    <div>
      {/* Segment labels above the bar — every rating shown, each centred over
          its block. Single line by default; staggered onto two rows only when
          the labels would actually overlap (measured, see effect above). */}
      <div ref={labelWrapRef} style={{ position: 'relative', height: staggered ? 30 : 16, marginBottom: 2 }}>
        {segs.map(({ k, left, width }, i) => (
          <div
            key={k}
            style={{
              position: 'absolute', left: `${left + width / 2}%`, top: staggered && i % 2 ? 15 : 0,
              transform: 'translateX(-50%)', whiteSpace: 'nowrap',
              fontSize: 10, fontFamily: 'monospace', fontWeight: 700, color: LABEL_COLORS[k],
              opacity: hover && hover !== k ? 0.35 : 1, transition: 'opacity 0.15s',
            }}
          >
            {counts[k]} {RATING_LABELS[k]}
          </div>
        ))}
      </div>

      {/* Bar */}
      <div style={{ position: 'relative', height: 34, marginBottom: 16 }}>
        {/* Baseline track — grounds the centred blocks on a full-width rail. */}
        <div style={{
          position: 'absolute', top: '50%', left: 0, right: 0, height: 8,
          transform: 'translateY(-50%)', background: '#1c1c1c',
          border: '1px solid #262626', borderRadius: 4,
        }} />
        {segs.map(({ k, left, width }) => (
          <div
            key={k}
            onMouseEnter={() => setHover(k)}
            onMouseLeave={() => setHover(null)}
            style={{
              position: 'absolute', top: 0, bottom: 0, left: `${left}%`, width: `${width}%`,
              // Top highlight → base colour → bottom shade for a raised, glossy block.
              background: 'linear-gradient(to bottom, rgba(255,255,255,0.32), rgba(255,255,255,0.04) 42%, rgba(0,0,0,0.32))',
              backgroundColor: RATING_COLORS[k],
              borderRadius: 2,
              // Coloured glow + drop shadow + inset top highlight (constant, no hover change).
              boxShadow: `0 0 9px ${RATING_COLORS[k]}66, 0 2px 5px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.35)`,
              transition: 'left 0.3s, width 0.3s',
              cursor: 'default',
              filter: 'brightness(0.82)',
            }}
          />
        ))}
      </div>

      {/* Caption */}
      <div style={{ fontSize: 12, fontFamily: 'monospace', color: '#555' }}>
        <span style={{ color: CONSENSUS_TEXT[row.consensus] || '#94a3b8', fontWeight: 700 }}>
          {row.consensus || '—'}
        </span>
        {row.buy_pct != null && <> · {row.buy_pct.toFixed(1)}% bullish</>}
        {' · '}{total} analysts
        {lowCoverage && <span style={{ color: '#444' }}> · thin coverage</span>}
      </div>
    </div>
  );
}

// Zoned range band: the analyst low→high range as a band split at the current
// price into a red downside zone (low→current) and a green upside zone
// (current→high), so the share of the range above/below today's price reads at
// a glance. Mean & median are marked; their labels splay so they don't collide.
function PriceTargetRange({ row, isMobile }) {
  const { price_target_low: low, price_target_high: high,
          price_target_mean: mean, price_target_median: median,
          current_price: current, upside_pct: upside } = row;
  if (!low || !high || !current || high <= low) {
    return <div style={{ color: '#444', fontSize: 12 }}>No price target data</div>;
  }
  const span = high - low;
  const pos = (v) => Math.max(0, Math.min(100, ((v - low) / span) * 100));
  // Constrain the band to a centred 75% of the card on desktop; use the full
  // width on mobile where horizontal space is scarce.
  const INSET = isMobile ? 0 : 12.5;
  const X = (p) => INSET + p * (100 - 2 * INSET) / 100;   // 0..100 → 12.5..87.5
  const cur = pos(current);
  const upColor = upside == null ? '#94a3b8' : upside >= 0 ? '#10b981' : '#ef4444';

  // Zone fill: colour brightest at the current-price edge, fading toward the
  // outer edge — but the fade is over a FIXED distance (D, in container %), not
  // the zone's own width. So a narrow zone (price near an end) stays coloured
  // instead of cramming the whole gradient into a few px and going black.
  const D = 28;
  const peak = isMobile ? 0.72 : 0.55;            // colour intensity at the price
  const shadeMax = isMobile ? 0.30 : 0.55;        // max darkening at the outer edge
  const outFloor = isMobile ? 0.30 : 0;           // min colour kept at the outer edge
  const zoneBg = (rgb, w, currentLeft) => {
    const lift = Math.max(0, 1 - w / D);          // 0 for wide zones → ~1 for tiny
    const cOut = Math.max(peak * lift, outFloor).toFixed(3); // outer colour alpha (floored on mobile)
    const dark = (shadeMax * (1 - lift)).toFixed(3); // outer shade, eased off when narrow
    const color = currentLeft
      ? `linear-gradient(to right, rgba(${rgb},${peak}), rgba(${rgb},${cOut}))`
      : `linear-gradient(to right, rgba(${rgb},${cOut}), rgba(${rgb},${peak}))`;
    const shade = currentLeft
      ? `linear-gradient(to right, rgba(255,255,255,0.18), rgba(0,0,0,${dark}))`
      : `linear-gradient(to right, rgba(0,0,0,${dark}), rgba(255,255,255,0.18))`;
    return `${color}, ${shade}, linear-gradient(#0a0a0a, #0a0a0a)`;
  };

  // Mean & median markers; splay their labels outward so near-equal values don't overlap.
  const marks = [
    median != null && { name: 'Median', val: median },
    mean   != null && { name: 'Mean',   val: mean },
  ].filter(Boolean).sort((a, b) => a.val - b.val);

  const AX = 42;                                   // band centre (px)
  const mono = { fontFamily: 'monospace', whiteSpace: 'nowrap', lineHeight: 1.5 };
  const zone = { position: 'absolute', top: AX - 18, height: 36 };
  const endLabel = { position: 'absolute', top: AX + 30, fontSize: 10, color: '#999', ...mono };

  return (
    <div style={{ position: 'relative', height: 112, marginTop: 12 }}>
      {/* Downside / upside zones (split at current) */}
      <div style={{ ...zone, left: `${X(0)}%`, width: `${X(cur) - X(0)}%`, background: zoneBg('185,28,28', X(cur) - X(0), false), borderRadius: '2px 0 0 2px', boxShadow: '0 0 8px #b91c1c55, 0 2px 5px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.3)' }} />
      <div style={{ ...zone, left: `${X(cur)}%`, width: `${X(100) - X(cur)}%`, background: zoneBg('5,150,105', X(100) - X(cur), true), borderRadius: '0 2px 2px 0', boxShadow: '0 0 8px #05966955, 0 2px 5px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.3)' }} />

      {/* Mean & median ticks + splayed labels */}
      {marks.map((m, i) => (
        <div key={m.name}>
          <div style={{ position: 'absolute', top: AX - 18, height: 36, left: `${X(pos(m.val))}%`, width: 2, transform: 'translateX(-50%)', background: '#f59e0b', boxShadow: '0 0 6px #f59e0baa', zIndex: 2 }} />
          <div style={{
            position: 'absolute', top: 4, left: `${X(pos(m.val))}%`, fontSize: 10, color: '#f59e0b', fontWeight: 700, ...mono,
            transform: marks.length > 1 && i === 0 ? 'translateX(-100%)' : 'none',
            paddingRight: marks.length > 1 && i === 0 ? 5 : 0,
            paddingLeft:  marks.length > 1 && i === 0 ? 0 : 5,
            textAlign:    marks.length > 1 && i === 0 ? 'right' : 'left',
          }}>
            {m.name} {m.val.toFixed(0)}p
          </div>
        </div>
      ))}

      {/* Current price marker */}
      <div style={{ position: 'absolute', top: AX - 22, height: 44, left: `${X(cur)}%`, width: 2, transform: 'translateX(-50%)', background: upColor, borderRadius: 1, boxShadow: `0 0 8px ${upColor}`, zIndex: 3 }} />
      <div style={{ position: 'absolute', top: AX + 20, left: `${X(cur)}%`, transform: 'translateX(-50%)', borderLeft: '4px solid transparent', borderRight: '4px solid transparent', borderBottom: `5px solid ${upColor}`, zIndex: 3 }} />
      {/* Current readout under the marker */}
      <div style={{
        position: 'absolute', top: AX + 30, left: `${X(cur)}%`, fontSize: 10, ...mono,
        // Anchor left/right when the price is near an edge so the label stays on-screen.
        transform: cur < 15 ? 'none' : cur > 85 ? 'translateX(-100%)' : 'translateX(-50%)',
        textAlign: cur < 15 ? 'left' : cur > 85 ? 'right' : 'center',
      }}>
        <span style={{ color: '#999' }}>Last close {current.toFixed(0)}p</span>
        {upside != null && (
          <><br /><span style={{ color: upColor, fontWeight: 700 }}>{upside >= 0 ? '+' : ''}{upside.toFixed(1)}% to mean</span></>
        )}
      </div>

      {/* Range endpoints — desktop only (crowds the current label on mobile).
          Also dropped when the current marker sits too near that end to collide. */}
      {!isMobile && cur > 22 && <span style={{ ...endLabel, left: `${INSET}%` }}>Low {low.toFixed(0)}p</span>}
      {!isMobile && cur < 78 && <span style={{ ...endLabel, right: `${INSET}%`, textAlign: 'right' }}>High {high.toFixed(0)}p</span>}
    </div>
  );
}

// Shared sub-section header + stat row so every block in the Estimates panel
// has the same rhythm.
const subHeadStyle = {
  fontSize: 10, color: '#555', fontFamily: 'monospace',
  textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8,
};
function StatRow({ label, value, color = '#e5e5e5' }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      padding: '5px 0', borderBottom: '1px solid #1a1a1a',
      fontSize: 12, fontFamily: 'monospace',
    }}>
      <span style={{ color: '#666' }}>{label}</span>
      <span style={{ color }}>{value}</span>
    </div>
  );
}
function RevisionPair({ up, down }) {
  return (
    <span>
      <span style={{ color: '#10b981' }}>↑{up ?? 0}</span>
      {'   '}
      <span style={{ color: '#ef4444' }}>↓{down ?? 0}</span>
    </span>
  );
}

export default function AnalystTab({ symbol }) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const isMobile = useIsMobile();

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/analysts/${encodeURIComponent(symbol)}`)
      .then(r => r.ok ? r.json() : [])
      .then(d => { setHistory(Array.isArray(d) ? d : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [symbol]);

  if (loading) return <div style={{ color: '#444', padding: 32, fontFamily: 'monospace' }}>Loading analyst data…</div>;
  if (!history.length) return <div style={{ color: '#444', padding: 32, fontFamily: 'monospace' }}>No analyst data available for {symbol}</div>;

  // Latest snapshot is last in array (ORDER BY ASC)
  const latest = history[history.length - 1];
  const trendData = history.map(r => ({
    date: r.snapshot_date,
    buy_pct: r.buy_pct,
  }));
  const targetTrend = history.map(r => ({
    date: r.snapshot_date,
    target: r.price_target_mean,
    price: r.current_price,
  }));
  const hasTargetTrend = targetTrend.filter(d => d.target != null).length >= 2;

  const cardStyle = {
    background: '#141414', border: '1px solid #2a2a2a',
    borderRadius: 3, padding: 20, marginBottom: 16
  };
  const titleStyle = {
    fontSize: 10, color: '#666', textTransform: 'uppercase',
    letterSpacing: 1, fontFamily: 'monospace', marginBottom: 14, marginTop: 0
  };

  return (
    <div>
      {/* Panel 1: Consensus bar */}
      <div style={cardStyle}>
        <p style={titleStyle}>Analyst Consensus</p>
        <ConsensusDivergingBar row={latest} isMobile={isMobile} />
      </div>

      {/* Panel 2: Price target range */}
      <div style={cardStyle}>
        <p style={titleStyle}>Price Target Range</p>
        <PriceTargetRange row={latest} isMobile={isMobile} />
      </div>

      {/* Panels 3 + 3b: trend charts side by side (stack on mobile) */}
      {(trendData.length >= 2 || hasTargetTrend) && (
      <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 16, marginBottom: 16 }}>
      {/* Panel 3: Consensus trend (only if ≥2 snapshots) */}
      {trendData.length >= 2 && (
        <div style={{ ...cardStyle, flex: 1, minWidth: 0, marginBottom: 0 }}>
          <p style={{ ...titleStyle, display: 'flex', alignItems: 'center', gap: 6 }}>
            Consensus Trend — % Bullish
            <InfoDot text="Share of covering analysts with a Buy (or Strong Buy) rating, tracked over time. A rising line means sentiment is improving. Uses a coverage-adjusted Buy% so thinly-covered names aren't over-weighted." />
          </p>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={trendData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
              <XAxis dataKey="date" tickFormatter={fmtTickDate} minTickGap={24} tick={{ fontSize: 10, fill: '#555', fontFamily: 'monospace' }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#555', fontFamily: 'monospace' }} unit="%" />
              <Tooltip
                formatter={v => [`${v?.toFixed(1)}%`, 'Buy%']}
                labelFormatter={fmtUKDate}
                contentStyle={{ background: '#141414', border: '1px solid #2a2a2a', borderRadius: 2, fontFamily: 'monospace', fontSize: 11 }}
                labelStyle={{ color: '#e5e5e5' }}
                itemStyle={{ color: '#10b981' }}
              />
              <Line type="monotone" dataKey="buy_pct" stroke="#10b981" strokeWidth={2} dot={false} name="Buy%" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Panel 3b: Price target vs price trend (only if ≥2 snapshots with targets) */}
      {hasTargetTrend && (
        <div style={{ ...cardStyle, flex: 1, minWidth: 0, marginBottom: 0 }}>
          <p style={titleStyle}>Mean Target vs Price</p>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={targetTrend} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
              <XAxis dataKey="date" tickFormatter={fmtTickDate} minTickGap={24} tick={{ fontSize: 10, fill: '#555', fontFamily: 'monospace' }} />
              <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10, fill: '#555', fontFamily: 'monospace' }} unit="p" />
              <Tooltip
                formatter={(v, name) => [v != null ? `${v.toFixed(0)}p` : '—', name]}
                labelFormatter={fmtUKDate}
                contentStyle={{ background: '#141414', border: '1px solid #2a2a2a', borderRadius: 2, fontFamily: 'monospace', fontSize: 11 }}
                labelStyle={{ color: '#e5e5e5' }}
              />
              <Legend wrapperStyle={{ fontSize: 10, fontFamily: 'monospace' }} />
              <Line type="monotone" dataKey="target" stroke="#f97316" strokeWidth={2} dot={false} name="Mean Target" connectNulls />
              <Line type="monotone" dataKey="price" stroke="#6366f1" strokeWidth={2} dot={false} name="Price" connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      </div>
      )}

      {/* Panel 4: Estimates & revisions — two cards side by side (stack on mobile) */}
      <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 16 }}>
        {/* Card A: everything EPS */}
        <div style={{ ...cardStyle, flex: 1, minWidth: 0, marginBottom: 0, display: 'flex', flexDirection: 'column' }}>
          <p style={titleStyle}>EPS Forecasts</p>
          <div style={subHeadStyle}>Estimates</div>
          {[
            ['Current Year', latest.eps_est_current_yr],
            ['Next Year',    latest.eps_est_next_yr],
            ['Current Q',    latest.eps_est_current_q],
            ['Next Q',       latest.eps_est_next_q],
          ].map(([label, val]) => (
            <StatRow key={label} label={label} value={val != null ? val.toFixed(2) : '—'} />
          ))}

          <div style={{ ...subHeadStyle, marginTop: 'auto', paddingTop: 16 }}>Growth</div>
          {[
            ['Current Year', latest.eps_growth_current_yr],
            ['Next Year',    latest.eps_growth_next_yr],
          ].map(([label, val]) => (
            <StatRow
              key={label}
              label={label}
              value={val != null ? `${(val * 100).toFixed(1)}%` : '—'}
              color={val == null ? '#e5e5e5' : val >= 0 ? '#10b981' : '#ef4444'}
            />
          ))}
        </div>

        {/* Card B: revenue + revision activity */}
        <div style={{ ...cardStyle, flex: 1, minWidth: 0, marginBottom: 0, display: 'flex', flexDirection: 'column' }}>
          <p style={titleStyle}>Revenue & Revisions</p>
          <div style={subHeadStyle}>Estimates</div>
          {[
            ['Current Year', latest.rev_est_current_yr],
            ['Next Year',    latest.rev_est_next_yr],
          ].map(([label, val]) => (
            <StatRow key={label} label={label} value={val != null ? fmt(val, 'currency') : '—'} />
          ))}

          <div style={{ ...subHeadStyle, marginTop: 'auto', paddingTop: 16 }}>Revisions</div>
          <StatRow label="Last 30 days" value={<RevisionPair up={latest.revisions_up_30d} down={latest.revisions_down_30d} />} />
          <StatRow label="Last 7 days"  value={<RevisionPair up={latest.revisions_up_7d}  down={latest.revisions_down_7d} />} />
        </div>
      </div>
    </div>
  );
}
