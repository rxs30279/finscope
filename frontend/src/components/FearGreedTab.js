"use client";
import { useState, useEffect, useMemo } from 'react';
import dynamic from 'next/dynamic';
import { API } from "@/lib/api";
import { useIsMobile } from "@/hooks/useMediaQuery";

// The Timeline chart is the tab's only recharts consumer — loading it on demand
// keeps the library out of the /markets first-load bundle (the visible gauge is
// hand-rolled SVG). The placeholder matches the chart's 240px plot height.
const FearGreedHistoryChart = dynamic(() => import('@/components/FearGreedHistoryChart'), {
  ssr: false,
  loading: () => <div style={{ minHeight: 240 }} />,
});

// Sentiment → colour, sharing the gauge's FG_BANDS palette so the hub number,
// comparison circles and component scores all match the dial exactly. Greed is
// green (not amber) and Fear a vivid vermillion — both kept clear of the
// burnt-orange page accent (#f97316) used by the section title, which they used
// to collide with.
function fgColor(score) {
  if (score == null) return '#9ca3af';
  if (score >= 75) return '#16d96b'; // Extreme Greed
  if (score >= 55) return '#7ed321'; // Greed
  if (score >= 44) return '#9ca3af'; // Neutral
  if (score >= 25) return '#ff7a14'; // Fear
  return '#ff2e3f';                  // Extreme Fear
}

// fgColor already reads clearly against the dark card (neutral is a light grey),
// so fgInk is now just an alias kept for call-site intent.
const fgInk = fgColor;

function fgSentiment(score) {
  if (score == null) return '—';
  if (score >= 75) return 'Extreme Greed';
  if (score >= 55) return 'Greed';
  if (score >= 44) return 'Neutral';
  if (score >= 25) return 'Fear';
  return 'Extreme Fear';
}

// The five sentiment zones, in ascending order. Boundaries match fgColor / the
// history-chart reference bands so the gauge, bar and chart stay consistent.
const FG_BANDS = [
  { lo: 0,  hi: 25,  color: '#ff2e3f', label: 'EXTREME FEAR' },
  { lo: 25, hi: 44,  color: '#ff7a14', label: 'FEAR' },
  { lo: 44, hi: 55,  color: '#9ca3af', label: 'NEUTRAL' },
  { lo: 55, hi: 75,  color: '#7ed321', label: 'GREED' },
  { lo: 75, hi: 100, color: '#16d96b', label: 'EXTREME GREED' },
];

// CNN-style semicircular dial. 0 sits at the left (180°), 100 at the right (0°);
// the needle swings to `score` and the band it lands in is lit in its colour
// while the rest stay muted — exactly how CNN highlights the active zone.
function FearGreedGauge({ score, color }) {
  const cx = 180, cy = 195, R = 175, r = 115;  // hub centre + outer/inner radii
  const rmid = R - 19;                          // radius the curved labels ride — out near the rim
  const tip  = r + 16;                          // needle tip reaches into the band
  const clamped = Math.max(0, Math.min(100, score ?? 0));

  // value (0–100) → point at `rad` on the dial. Angle 180°…0° as value 0…100.
  const polar = (v, rad) => {
    const t = (180 - 1.8 * v) * Math.PI / 180;
    return [cx + rad * Math.cos(t), cy - rad * Math.sin(t)];
  };
  // Donut-segment path for a band. Each internal edge is shifted a fixed distance
  // *perpendicular to its radius* (a constant tangential offset, not an angular
  // inset), so every gap is the same width with parallel sides — not a wedge.
  const GAP = 5;
  const bandPath = (lo, hi, gapLo, gapHi) => {
    const tLo = (180 - 1.8 * lo) * Math.PI / 180;
    const tHi = (180 - 1.8 * hi) * Math.PI / 180;
    const sLo = gapLo ? GAP / 2 : 0;   // push the low edge toward higher values
    const sHi = gapHi ? GAP / 2 : 0;   // push the high edge toward lower values
    const oLx =  Math.sin(tLo) * sLo, oLy =  Math.cos(tLo) * sLo;
    const oHx = -Math.sin(tHi) * sHi, oHy = -Math.cos(tHi) * sHi;
    const [ox1, oy1] = polar(lo, R), [ox2, oy2] = polar(hi, R);
    const [ix2, iy2] = polar(hi, r), [ix1, iy1] = polar(lo, r);
    return `M ${ox1 + oLx} ${oy1 + oLy} A ${R} ${R} 0 0 1 ${ox2 + oHx} ${oy2 + oHy} L ${ix2 + oHx} ${iy2 + oHy} A ${r} ${r} 0 0 0 ${ix1 + oLx} ${iy1 + oLy} Z`;
  };
  // Open arc through the middle of a band, used as a textPath baseline.
  const labelArc = (lo, hi) => {
    const [x1, y1] = polar(lo, rmid), [x2, y2] = polar(hi, rmid);
    return `M ${x1} ${y1} A ${rmid} ${rmid} 0 0 1 ${x2} ${y2}`;
  };

  const activeIdx = FG_BANDS.findIndex(b => clamped >= b.lo && clamped < (b.hi === 100 ? 101 : b.hi));

  const activeColor = FG_BANDS[activeIdx]?.color || '#9ca3af';

  // Needle as a slim triangle pivoting at the hub centre.
  const tA = (180 - 1.8 * clamped) * Math.PI / 180;
  const tipX = cx + tip * Math.cos(tA), tipY = cy - tip * Math.sin(tA);
  const bw = 7;
  const bx1 = cx + bw * Math.sin(tA), by1 = cy + bw * Math.cos(tA);
  const bx2 = cx - bw * Math.sin(tA), by2 = cy - bw * Math.cos(tA);

  const dots = [];
  for (let v = 0; v <= 100; v += 5) dots.push(v);

  return (
    <svg viewBox="0 0 360 244" width="100%" style={{ maxWidth: 420, display: 'block', margin: '4px 0 0' }}>
      <defs>
        {FG_BANDS.map((b, i) => (
          <path key={i} id={`fg-lbl-${i}`} d={labelArc(b.lo, b.hi)} fill="none" />
        ))}
        {/* Radial gradient backdrop behind the whole dial — brighter at the
            centre, fading to the card colour, giving depth without touching
            the segment fills. Shows through the segment gaps and the hub. */}
        <radialGradient id="fg-dial" cx={cx} cy={cy} r={R} gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#2a2a34" />
          <stop offset="0.6" stopColor="#1a1a20" />
          <stop offset="1" stopColor="#111111" />
        </radialGradient>
        {/* Slight per-segment shading — denser at the inner edge (near the hub),
            easing off toward the rim. Both share the hub centre. */}
        <radialGradient id="fg-seg-on" cx={cx} cy={cy} r={R} gradientUnits="userSpaceOnUse">
          <stop offset="0.6" stopColor={activeColor} stopOpacity="1" />
          <stop offset="1" stopColor={activeColor} stopOpacity="0.62" />
        </radialGradient>
        <radialGradient id="fg-seg-off" cx={cx} cy={cy} r={R} gradientUnits="userSpaceOnUse">
          <stop offset="0.6" stopColor="#2c2c34" />
          <stop offset="1" stopColor="#1a1a1e" />
        </radialGradient>
      </defs>

      {/* Gradient backdrop behind the dial — top half only, ending flush at the
          baseline so it doesn't bleed under the central number */}
      <path d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy} Z`} fill="url(#fg-dial)" />

      {/* Sentiment bands — active one lit in its colour, the rest muted grey */}
      {FG_BANDS.map((b, i) => {
        const active = i === activeIdx;
        return (
          <path
            key={i}
            d={bandPath(b.lo, b.hi, i > 0, i < FG_BANDS.length - 1)}
            fill={active ? 'url(#fg-seg-on)' : 'url(#fg-seg-off)'}
            stroke={active ? b.color : '#2c2c30'}
            strokeWidth={1}
          />
        );
      })}

      {/* Curved zone labels riding the middle of each band */}
      {FG_BANDS.map((b, i) => (
        <text
          key={i}
          fontSize="10.5"
          fontFamily="monospace"
          fontWeight="800"
          letterSpacing="0.5"
          textAnchor="middle"
          fill={i === activeIdx ? '#0b0b0b' : '#71717a'}
        >
          <textPath href={`#fg-lbl-${i}`} startOffset="50%">{b.label}</textPath>
        </text>
      ))}

      {/* Tick ring — dots everywhere except the 0/25/50/75/100 marks, where the
          scale number sits on the ring in the dot's place (as on CNN's gauge). */}
      {dots.filter(v => v % 25 !== 0).map(v => { const [x, y] = polar(v, r - 12); return <circle key={v} cx={x} cy={y} r="1.2" fill="#52525b" />; })}
      {[0, 25, 50, 75, 100].map(v => {
        const [x, y] = polar(v, r - 12);
        // 0 and 100 sit on the baseline; drop the centring offset so their
        // bottom lines up with the segment bottoms (the others stay centred).
        const dy = (v === 0 || v === 100) ? 0 : 4;
        return <text key={v} x={x} y={y + dy} fontSize="11" fontFamily="monospace" fill="#71717a" textAnchor="middle">{v}</text>;
      })}

      {/* Needle */}
      <polygon
        points={`${tipX},${tipY} ${bx1},${by1} ${bx2},${by2}`}
        fill="#e5e5e5"
        stroke="#0b0b0b"
        strokeWidth="0.5"
        strokeLinejoin="round"
      />

      {/* Hub (no outline) + score — a flat-bottomed semicircle so the darker
          lower half of a full circle no longer shows below the dial baseline.
          Neutral grey is lightened to match the band. */}
      <path d={`M ${cx - 44} ${cy} A 44 44 0 0 1 ${cx + 44} ${cy} Z`} fill="#0b0b0b" />
      <text x={cx} y={cy - 6} fontSize="40" fontWeight="700" fontFamily="monospace" fill={color} textAnchor="middle">{score}</text>
    </svg>
  );
}

// Per-component explanations: how each gauge is calculated and what it tells us.
const COMPONENT_INFO = {
  momentum: {
    how: 'Measures how far the FTSE 100 is trading above or below its 125-day (≈6-month) moving average, then ranks that gap against its own trailing two-year range. The most bearish gap of the period scores near 0, the most bullish near 100, and a typical gap sits around 50.',
    means: 'When the index trades unusually far above its medium-term trend, momentum and risk appetite are positive — a greed signal. When the gap is unusually low or negative, price is breaking trend, which tends to accompany fear and pullbacks.',
  },
  breadth: {
    how: 'Counts the share of FTSE 100 stocks trading above their own 50-day moving average, then ranks that figure against its own trailing two-year range — so the score reflects how broad participation is relative to the recent norm (near 0 = the narrowest of the period, near 100 = the broadest).',
    means: 'High breadth signals a broad, healthy advance where most stocks participate — greed. Low breadth warns that gains are narrow or that selling is widespread beneath the surface, a classic fear signal even when the headline index looks calm.',
  },
  currency: {
    how: 'Takes the 60-day percentage change in GBP/USD, inverts it, and ranks it against its own trailing two-year range. A pound near its strongest of the period scores near 0 (fear), near its weakest near 100 (greed).',
    means: 'Around three-quarters of FTSE 100 revenue is earned overseas, so the level of sterling drives reported profits. A weaker pound flatters those overseas earnings once converted back — a tailwind that reads as greed; a stronger pound is an earnings headwind that reads as fear.',
  },
  safe_haven: {
    how: 'Compares the 20-day total return of the FTSE 100 against a UK gilt ETF (all-maturity gilts), then ranks that spread against its own trailing two-year range. Stocks outpacing bonds by an unusual margin scores near 100; gilts winning by an unusual margin scores near 0.',
    means: 'When stocks outpace safe government bonds, money is chasing risk — greed. When gilts win, investors are rotating into safety — fear. It captures the tug-of-war between risk-on and risk-off positioning.',
  },
  realised_vol: {
    how: 'Calculates the actual (realised) 20-day volatility of FTSE 100 daily returns, annualised, then ranks it (inverted) against its own trailing two-year range. The calmest stretches of the period score near 100, the most turbulent near 0.',
    means: 'Unlike the VIX, which is forward-looking, this measures volatility that has already happened. Big daily swings drag the score down and reflect genuine stress; quiet, drifting markets push it toward greed.',
  },
  hl_ratio: {
    how: 'Counts how many FTSE 100 stocks are within 1% of a fresh 52-week high versus a 52-week low, takes the net difference as a share of the universe, then ranks it against its own trailing two-year range (near 100 = the strongest net-new-highs reading of the period, near 0 = the weakest).',
    means: 'A surplus of new highs over new lows shows leadership and conviction — greed. A surge of new lows points to a deteriorating market where damage is spreading, a strong fear signal.',
  },
};

export default function FearGreedTab({ refreshKey }) {
  const [fg, setFg]         = useState(null);
  const [loading, setLoading] = useState(true);
  const [history, setHistory] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [showComponents, setShowComponents] = useState(false);
  const [view, setView] = useState('overview'); // 'overview' (gauge) | 'timeline' (charts)
  const isMobile = useIsMobile();

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/market/fear-greed`)
      .then(r => r.json())
      .then(data => { setFg(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  useEffect(() => {
    setHistoryLoading(true);
    fetch(`${API}/market/fear-greed/history`)
      .then(r => r.json())
      .then(data => { setHistory(Array.isArray(data) ? data : []); setHistoryLoading(false); })
      .catch(() => setHistoryLoading(false));
  }, [refreshKey]);

  const color = fg ? fgColor(fg.score) : '#666';
  const COMPONENT_ORDER = ['momentum', 'breadth', 'currency', 'safe_haven', 'realised_vol', 'hl_ratio'];
  const latestDate = (history && history.length) ? history[history.length - 1].date : null;
  // The headline is an EOD figure stamped with the session it was built from;
  // fall back to the history's latest row if the backend didn't supply one.
  const asOfDate = (fg && fg.as_of) ? fg.as_of : latestDate;
  const fmtDate = (d) => {
    const dt = new Date(d);
    return `${dt.getDate()} ${dt.toLocaleString('default', { month: 'short' })} ${dt.getFullYear()}`;
  };

  // Backward-looking comparisons for the CNN-style side panel, read off the UK
  // history series. valueDaysAgo finds the most recent reading at or before the
  // target date, so weekends/holidays fall back to the prior trading day.
  const ukSeries = useMemo(() => (history || []).filter(d => d.uk != null), [history]);
  const asOfTime = latestDate ? new Date(latestDate).getTime() : Date.now();
  const valueDaysAgo = (days) => {
    if (ukSeries.length === 0) return null;
    const target = asOfTime - days * 86400000;
    let best = null;
    for (const d of ukSeries) {
      const t = new Date(d.date).getTime();
      if (t <= target && (!best || t > new Date(best.date).getTime())) best = d;
    }
    if (!best) best = ukSeries[0]; // history shorter than the lookback
    return Math.round(best.uk);
  };
  const compareRows = [
    { label: 'Previous close', value: ukSeries.length >= 2 ? Math.round(ukSeries[ukSeries.length - 2].uk) : null },
    { label: '1 week ago',     value: valueDaysAgo(7) },
    { label: '1 month ago',    value: valueDaysAgo(30) },
    { label: '1 year ago',     value: valueDaysAgo(365) },
  ];

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, fontWeight:700, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>
        UK Fear &amp; Greed
      </h2>

      {/* ── Today's score / timeline — own box at the top ───────────────────── */}
      {loading ? (
        /* Skeleton mirroring the loaded card's geometry (header row, gauge column,
           compare column) so the fetch→gauge swap causes no layout shift. The
           gauge placeholder's aspect-ratio matches the SVG viewBox (360×244). */
        <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:20, marginBottom:20 }}>
          <div style={{ height:22, marginBottom:14 }} />
          <div style={{ display:'flex', flexDirection: isMobile ? 'column' : 'row', alignItems:'center', gap: isMobile ? 18 : 28 }}>
            <div style={{ flex: isMobile ? 'none' : '0 1 420px', minWidth:0, width: isMobile ? '100%' : 'auto' }}>
              <div style={{ width:'100%', maxWidth:420, aspectRatio:'360 / 244', margin:'4px 0 0', display:'flex', alignItems:'center', justifyContent:'center', color:'#444', fontFamily:'monospace', fontSize:11 }}>
                Loading…
              </div>
            </div>
            <div style={{ flex: isMobile ? 'none' : '1 1 0', width: isMobile ? '100%' : 'auto', display:'flex', justifyContent:'center' }}>
              <div style={{ width: isMobile ? '100%' : 230, display:'flex', flexDirection:'column', gap:16 }}>
                {[0, 1, 2, 3].map(i => <div key={i} style={{ height:46 }} />)}
              </div>
            </div>
          </div>
          <div style={{ height:18, marginTop:8 }} />
        </div>
      ) : !fg ? (
        <div style={{ color:'#444', padding:32, fontFamily:'monospace', background:'#111', border:'1px solid #1e1e1e', borderRadius:3, marginBottom:20 }}>No data available.</div>
      ) : (
      <>
      <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:20, marginBottom:20 }}>
        {/* Header mirrors the body's two columns so the toggle's right edge lines
            up with the right edge of the (centred) history scores below it */}
        <div style={{ display:'flex', alignItems:'center', gap: isMobile ? 12 : 28, marginBottom:14 }}>
          {/* Left — matches the gauge column; holds the current state */}
          <div style={{ flex: isMobile ? '1 1 auto' : '0 1 420px', minWidth:0 }}>
            <div style={{ color, fontSize:13, fontWeight:700, textTransform:'uppercase', letterSpacing:'1.5px' }}>
              {view === 'overview' ? fg.sentiment?.toUpperCase() : ''}
            </div>
          </div>
          {/* Right — matches the history column; the pill rides its right edge */}
          <div style={{ flex: isMobile ? '0 0 auto' : '1 1 0', display:'flex', justifyContent: isMobile ? 'flex-end' : 'center' }}>
            <div style={{ width: isMobile ? 'auto' : 230, display:'flex', justifyContent:'flex-end' }}>
              {/* Overview / Timeline pill switch */}
              <div style={{ display:'flex', border:'1px solid #2a2a2a', borderRadius:20, overflow:'hidden', flexShrink:0 }}>
                {[['overview','Overview'], ['timeline','Timeline']].map(([k, label]) => (
                  <button
                    key={k}
                    onClick={() => setView(k)}
                    style={{
                      background: view === k ? '#3730a3' : 'transparent',
                      color: view === k ? '#e0e7ff' : '#888',
                      border:'none', padding:'3px 11px', cursor:'pointer',
                      fontFamily:'monospace', fontSize:9, textTransform:'uppercase', letterSpacing:'0.5px',
                    }}
                  >{label}</button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {view === 'overview' ? (
        <>
        {/* Gauge on the left, the backward-looking comparisons on the right */}
        <div style={{ display:'flex', flexDirection: isMobile ? 'column' : 'row', alignItems:'center', gap: isMobile ? 18 : 28 }}>
          {/* CNN-style semicircular dial — score in the hub, needle in the zone */}
          <div style={{ flex: isMobile ? 'none' : '0 1 420px', minWidth: 0, width: isMobile ? '100%' : 'auto' }}>
            <FearGreedGauge score={fg.score} color={color} />
          </div>

          {/* Previous close / 1 week / 1 month / 1 year, CNN-style — centred in the
              space left of the gauge (the toggle above rides this block's edge) */}
          <div style={{ flex: isMobile ? 'none' : '1 1 0', width: isMobile ? '100%' : 'auto', display:'flex', justifyContent:'center' }}>
            <div style={{ width: isMobile ? '100%' : 230, display:'flex', flexDirection:'column', gap:16 }}>
              {compareRows.map(row => {
                const c = row.value == null ? '#555' : fgInk(row.value);
                return (
                  <div key={row.label}>
                    <div style={{ color:'#94a3b8', fontSize:10, marginBottom:3 }}>{row.label}</div>
                    <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                      <span style={{ color:'#e5e5e5', fontSize:13, fontWeight:700, whiteSpace:'nowrap' }}>{fgSentiment(row.value)}</span>
                      <span style={{ flex:1, borderBottom:'1px dotted #333', minWidth:12 }}/>
                      <span style={{
                        flexShrink:0, width:30, height:30, borderRadius:'50%',
                        background:c, color:'#0b0b0b', border:'2px solid rgba(0,0,0,0.55)',
                        display:'flex', alignItems:'center', justifyContent:'center',
                        fontFamily:'monospace', fontSize:12, fontWeight:700,
                      }}>{row.value ?? '—'}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Index label + freshness — small and unobtrusive, bottom right */}
        <div style={{ textAlign:'right', marginTop:8, color:'#475569', fontSize:8, textTransform:'uppercase', letterSpacing:'0.5px' }}>
          UK Fear &amp; Greed Index{asOfDate ? ` · as of ${fmtDate(asOfDate)}` : ''}
        </div>
        </>
        ) : (
          <FearGreedHistoryChart history={history} loading={historyLoading} bare />
        )}
      </div>

      {/* ── Component breakdown — overview only ──────────────────────────────── */}
      {view === 'overview' && fg && (
        <div style={{ marginBottom:20 }}>
          <button
            onClick={() => setShowComponents(s => !s)}
            style={{
              width:'100%', textAlign:'left', cursor:'pointer',
              background:'#141414', border:'1px solid #2a2a2a', borderRadius:3,
              color:'#9aa7b5', fontFamily:'monospace', fontSize:11, padding:'10px 14px',
              textTransform:'uppercase', letterSpacing:'0.5px',
              display:'flex', justifyContent:'space-between', alignItems:'center',
            }}
          >
            <span>{showComponents ? '▾ Hide' : '▸ Show'} UK F&amp;G component breakdown</span>
            <span style={{ color:'#555' }}>6 sub-scores</span>
          </button>

          {showComponents && (
            <div style={{ display:'flex', flexDirection:'column', gap:12, marginTop:12 }}>
              {COMPONENT_ORDER.map(key => {
                const c = fg.components?.[key];
                if (!c) return null;
                const cc = fgColor(c.score);
                const info = COMPONENT_INFO[key] || {};
                const band = c.score >= 75 ? 'Ext. Greed' : c.score >= 55 ? 'Greed' : c.score >= 45 ? 'Neutral' : c.score >= 25 ? 'Fear' : 'Ext. Fear';
                return (
                  <div
                    key={key}
                    style={{
                      display:'flex',
                      flexDirection: isMobile ? 'column' : 'row',
                      gap: isMobile ? 10 : 16,
                      background:'#141414',
                      border:'1px solid #2a2a2a',
                      borderRadius:3,
                      padding: isMobile ? 14 : 16,
                      alignItems: isMobile ? 'stretch' : 'flex-start',
                    }}
                  >
                    {/* Metric box */}
                    <div style={{ flexShrink:0, width: isMobile ? 'auto' : 150 }}>
                      <div style={{ color:'#94a3b8', fontSize:10, textTransform:'uppercase', letterSpacing:'0.5px', marginBottom:8 }}>{c.label}</div>
                      <div style={{ display:'flex', alignItems:'baseline', gap:8 }}>
                        <span style={{ color:cc, fontSize:28, fontWeight:700, fontFamily:'monospace', lineHeight:1 }}>{c.score}</span>
                        <span style={{ color:cc, fontSize:10, fontWeight:700 }}>{band}</span>
                      </div>
                      <div style={{ background:'#1a1a1a', borderRadius:2, height:5, margin:'8px 0 0' }}>
                        <div style={{ background:cc, width:`${c.score}%`, height:5, borderRadius:2 }}/>
                      </div>
                    </div>

                    {/* Explanation */}
                    <div style={{ flex:1, fontSize:12, lineHeight:1.6, color:'#9aa7b5' }}>
                      <div style={{ marginBottom:8 }}>
                        <span style={{ color:'#cbd5e1', fontWeight:700, fontSize:10, textTransform:'uppercase', letterSpacing:'0.5px' }}>How it’s calculated&nbsp;</span>
                        {info.how}
                      </div>
                      <div>
                        <span style={{ color:'#cbd5e1', fontWeight:700, fontSize:10, textTransform:'uppercase', letterSpacing:'0.5px' }}>What it tells us&nbsp;</span>
                        {info.means}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

</>
      )}
    </div>
  );
}
