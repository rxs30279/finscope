"use client";
import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { API } from "@/lib/api";
import { fmtUKDate } from "@/lib/format";
import { useIsMobile } from "@/hooks/useMediaQuery";
import InfoDot from "@/components/InfoDot";


// Breadth gauge styled to match the CNN-style Fear & Greed dial: two thin donut
// zones (red ≤50, green ≥50) with a gap between them, a gradient backdrop, a
// slim triangle needle and a hub holding the percentage. Same footprint as
// before — only the look changes. value: 0.0–1.0.
function BreadthGauge({ value }) {
  const has = value !== null && value !== undefined;
  const pct = has ? value * 100 : 50;           // 0–100
  const clamped = Math.max(0, Math.min(100, pct));

  const cx = 100, cy = 104, R = 82, r = 68;     // hub centre + outer/inner radii
  const tip = r - 2;                            // needle tip sits just inside the band
  // Shares the F&G dial's FG_BANDS palette (green #16d96b / red #ff2e3f, neutral
  // grey #9ca3af) so the two gauges on the page read as one family — no amber.
  const color = pct > 60 ? '#16d96b' : pct < 40 ? '#ff2e3f' : '#9ca3af';
  const label = pct > 60 ? 'Bullish Breadth' : pct < 40 ? 'Bearish Breadth' : 'Neutral';

  // value (0–100) → point at `rad` on the dial. Angle 180°…0° as value 0…100.
  const polar = (v, rad) => {
    const t = (180 - 1.8 * v) * Math.PI / 180;
    return [cx + rad * Math.cos(t), cy - rad * Math.sin(t)];
  };
  // Donut-segment path; the shared edge is pushed back a constant tangential
  // offset so the gap has parallel sides — same trick as the F&G gauge.
  const GAP = 4;
  const bandPath = (lo, hi, gapLo, gapHi) => {
    const tLo = (180 - 1.8 * lo) * Math.PI / 180;
    const tHi = (180 - 1.8 * hi) * Math.PI / 180;
    const sLo = gapLo ? GAP / 2 : 0;
    const sHi = gapHi ? GAP / 2 : 0;
    const oLx =  Math.sin(tLo) * sLo, oLy =  Math.cos(tLo) * sLo;
    const oHx = -Math.sin(tHi) * sHi, oHy = -Math.cos(tHi) * sHi;
    const [ox1, oy1] = polar(lo, R), [ox2, oy2] = polar(hi, R);
    const [ix2, iy2] = polar(hi, r), [ix1, iy1] = polar(lo, r);
    return `M ${ox1 + oLx} ${oy1 + oLy} A ${R} ${R} 0 0 1 ${ox2 + oHx} ${oy2 + oHy} L ${ix2 + oHx} ${iy2 + oHy} A ${r} ${r} 0 0 0 ${ix1 + oLx} ${iy1 + oLy} Z`;
  };

  const BANDS = [
    { lo: 0,  hi: 50,  color: '#ff2e3f' },
    { lo: 50, hi: 100, color: '#16d96b' },
  ];
  const activeIdx = clamped < 50 ? 0 : 1;

  // Needle as a slim triangle pivoting at the hub centre.
  const tA = (180 - 1.8 * clamped) * Math.PI / 180;
  const tipX = cx + tip * Math.cos(tA), tipY = cy - tip * Math.sin(tA);
  const bw = 5;
  const bx1 = cx + bw * Math.sin(tA), by1 = cy + bw * Math.cos(tA);
  const bx2 = cx - bw * Math.sin(tA), by2 = cy - bw * Math.cos(tA);

  const dots = [];
  for (let v = 0; v <= 100; v += 10) dots.push(v);

  return (
    <div style={{ textAlign:'center' }}>
      <svg width={200} height={132} viewBox="0 0 200 132" style={{ display:'block', margin:'0 auto' }}>
        <defs>
          {/* Radial backdrop — brighter at the hub, fading to the card colour */}
          <radialGradient id="bg-dial" cx={cx} cy={cy} r={R} gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#2a2a34" />
            <stop offset="0.6" stopColor="#1a1a20" />
            <stop offset="1" stopColor="#111111" />
          </radialGradient>
          {/* Per-zone shading — denser at the inner edge, easing off to the rim */}
          <radialGradient id="bg-seg-red" cx={cx} cy={cy} r={R} gradientUnits="userSpaceOnUse">
            <stop offset="0.55" stopColor="#ff2e3f" stopOpacity="1" />
            <stop offset="1" stopColor="#ff2e3f" stopOpacity="0.62" />
          </radialGradient>
          <radialGradient id="bg-seg-green" cx={cx} cy={cy} r={R} gradientUnits="userSpaceOnUse">
            <stop offset="0.55" stopColor="#16d96b" stopOpacity="1" />
            <stop offset="1" stopColor="#16d96b" stopOpacity="0.62" />
          </radialGradient>
        </defs>

        {/* Gradient backdrop — top half only, flush at the baseline */}
        <path d={`M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy} Z`} fill="url(#bg-dial)" />

        {/* Two zones — the side the needle lands in is lit, the other dimmed */}
        {BANDS.map((b, i) => (
          <path
            key={i}
            d={bandPath(b.lo, b.hi, i > 0, i < BANDS.length - 1)}
            fill={`url(#bg-seg-${i === 0 ? 'red' : 'green'})`}
            fillOpacity={i === activeIdx ? 1 : 0.4}
            stroke={i === activeIdx ? b.color : '#2c2c30'}
            strokeWidth={1}
          />
        ))}

        {/* Tick dots + 0 / 50 / 100 scale figures, as on the F&G ring */}
        {dots.filter(v => v % 50 !== 0).map(v => { const [x, y] = polar(v, r - 9); return <circle key={v} cx={x} cy={y} r="1" fill="#52525b" />; })}
        {[0, 50, 100].map(v => {
          const [x, y] = polar(v, r - 9);
          const dy = (v === 0 || v === 100) ? 0 : 3;
          return <text key={v} x={x} y={y + dy} fontSize="8" fontFamily="monospace" fill="#71717a" textAnchor="middle">{v}</text>;
        })}

        {/* Needle */}
        <polygon points={`${tipX},${tipY} ${bx1},${by1} ${bx2},${by2}`} fill="#e5e5e5" stroke="#0b0b0b" strokeWidth="0.5" strokeLinejoin="round" />

        {/* Hub + percentage — a flat-bottomed semicircle so nothing shows below
            the dial baseline (a full circle's darker lower half was visible) */}
        <path d={`M ${cx - 27} ${cy} A 27 27 0 0 1 ${cx + 27} ${cy} Z`} fill="#0b0b0b" />
        <text x={cx} y={cy - 4} fontSize="20" fontWeight="700" fontFamily="monospace" fill={color} textAnchor="middle">
          {has ? `${Math.round(pct)}%` : '—'}
        </text>
      </svg>
      <div style={{ color, fontSize:11, marginTop:2 }}>{label}</div>
    </div>
  );
}

// Back-to-back bar on a single axis: the left value grows leftward from the
// centre, the right value rightward. Each half is scaled independently to `max`
// (the FTSE 100 universe) so the full span represents 2 × max.
const STRIPE = 'repeating-linear-gradient(-45deg, #222, #222 5px, #161616 5px, #161616 10px)';
function DivergingBar({ leftLabel, leftValue, leftColor, rightLabel, rightValue, rightColor, max = 100 }) {
  const lp = (leftValue != null && leftValue > 0) ? Math.min(100, (leftValue / max) * 100) : 0;
  const rp = (rightValue != null && rightValue > 0) ? Math.min(100, (rightValue / max) * 100) : 0;
  // Read "No" rather than "0" for an empty count (e.g. "No New Lows").
  const fmt = (v) => v == null ? '—' : v === 0 ? 'No' : v;
  return (
    <div>
      <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6, fontSize:9, fontFamily:'monospace', color:'#94a3b8' }}>
        <span><span style={{ fontWeight:700, color: leftValue > 0 ? leftColor : undefined }}>{fmt(leftValue)}</span> {leftLabel}</span>
        <span>{rightLabel} <span style={{ fontWeight:700, color: rightValue > 0 ? rightColor : undefined }}>{fmt(rightValue)}</span></span>
      </div>
      <div style={{ display:'flex', height:26, gap:8 }}>
        {/* left bar — fill anchored to the centre, growing left */}
        <div style={{ flex:1, background:STRIPE, border:'1px solid rgba(91,33,182,0.45)', boxSizing:'border-box', borderRadius:3, display:'flex', justifyContent:'flex-end', overflow:'hidden' }}>
          <div style={{ width:`${lp}%`, height:'100%', background:leftColor, transition:'width .3s ease' }} />
        </div>
        {/* right bar — fill anchored to the centre, growing right */}
        <div style={{ flex:1, background:STRIPE, border:'1px solid rgba(91,33,182,0.45)', boxSizing:'border-box', borderRadius:3, overflow:'hidden' }}>
          <div style={{ width:`${rp}%`, height:'100%', background:rightColor, transition:'width .3s ease' }} />
        </div>
      </div>
    </div>
  );
}

// Small sliding on/off switch with a label.
function Toggle({ on, onChange, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      style={{ display:'flex', alignItems:'center', gap:8, background:'none', border:'none', cursor:'pointer', padding:0, fontFamily:'monospace', fontSize:10, color:'#94a3b8' }}
    >
      <span style={{ position:'relative', width:32, height:18, borderRadius:9, boxSizing:'border-box', background: on ? '#3730a3' : '#2a2a2a', border:`1px solid ${on ? '#4338ca' : '#3a3a3a'}`, transition:'background .2s, border-color .2s', flexShrink:0 }}>
        <span style={{ position:'absolute', top:1, left: on ? 15 : 1, width:14, height:14, borderRadius:'50%', background:'#e5e5e5', transition:'left .2s' }} />
      </span>
      {label}
    </button>
  );
}

// Small freshness stamp pinned to a card's bottom-right corner: "Current" for
// the live MA dial, "Last close · <date>" for the EOD-anchored cards.
function CornerStamp({ children }) {
  return (
    <div style={{ position:'absolute', bottom:8, right:12, fontSize:8, color:'#475569', fontFamily:'monospace', textTransform:'uppercase', letterSpacing:'0.5px' }}>
      {children}
    </div>
  );
}

export default function BreadthTab({ refreshKey }) {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAdLine, setShowAdLine] = useState(false); // A/D line chart hidden by default
  const isMobile = useIsMobile();

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/market/breadth`)
      .then(r => r.json())
      .then(breadthData => { setData(breadthData); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  const card  = { background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:'16px 16px 26px', position:'relative' };
  const title = { color:'#9aa7b5', fontSize:9, fontFamily:'monospace', textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 };

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading breadth data…</div>;

  const tooltipStyle = { background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:11, color:'#e5e5e5', fontFamily:'monospace' };

  // A/D line x-axis: with ~20 points Recharts crowds the date labels (and they
  // overlap badly on mobile). Pick a fixed number of evenly-spaced ticks pulled
  // from the actual data — fewer on mobile — so labels stay legible at any width.
  const adLine = data?.ad_line || [];
  const TICK_COUNT = isMobile ? 4 : 7;
  const adTicks =
    adLine.length <= TICK_COUNT
      ? adLine.map(d => d.date)
      : Array.from({ length: TICK_COUNT }, (_, i) =>
          adLine[Math.round((i * (adLine.length - 1)) / (TICK_COUNT - 1))].date
        );
  const fmtAdTick = (d) => {
    const dt = new Date(d);
    return isNaN(dt) ? d : dt.toLocaleDateString('en-GB', { day:'numeric', month:'short' });
  };

  const nh = data?.new_highs;
  const nl = data?.new_lows;

  // Both diverging bars scale dynamically off their larger count (with headroom,
  // rounded to a tidy step) so even a quiet/lopsided day fills the bars — capped
  // at the 100-stock ceiling each side could in theory reach.
  const scaleFor = (peak) => Math.min(100, Math.max(5, Math.ceil((peak * 1.25) / 5) * 5));
  const hlScaleMax = scaleFor(Math.max(nh || 0, nl || 0));
  const adScaleMax = scaleFor(Math.max(data?.advances || 0, data?.declines || 0));

  // Freshness stamp — the endpoint carries no explicit timestamp, so use the
  // latest trading day present in the A/D line (the session these figures cover).
  const lastDate = adLine.length ? adLine[adLine.length - 1].date : null;
  const lastUpdated = (() => {
    if (!lastDate) return null;
    const dt = new Date(lastDate);
    return isNaN(dt.getTime()) ? null : `${dt.getDate()} ${dt.toLocaleString('default', { month: 'short' })} ${dt.getFullYear()}`;
  })();

  return (
    <div>
      <div style={{ display:'flex', alignItems:'baseline', gap:10, flexWrap:'wrap', marginBottom:20 }}>
        <h2 style={{ fontFamily:'monospace', fontSize:14, fontWeight:700, color:'#f97316', textTransform:'uppercase', letterSpacing:2, margin:0 }}>Market Breadth</h2>
        <span style={{ fontFamily:'monospace', fontSize:10, color:'#64748b' }}>Across the FTSE 100 constituents</span>
      </div>
      <div style={{ display:'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 1fr', gap:16, marginBottom:16 }}>

        {/* Gauge */}
        <div style={card}>
          <div style={title}>% Above 50-Day MA</div>
          <BreadthGauge value={data?.pct_above_50ma} />
          <div style={{ display:'flex', justifyContent:'space-around', marginTop:12, fontSize:10, fontFamily:'monospace' }}>
            <span style={{ color:'#94a3b8' }}>Below: <span style={{ color:'#ff2e3f' }}>{data?.below_50ma ?? '—'}</span></span>
            <span style={{ color:'#94a3b8' }}>Above: <span style={{ color:'#16d96b' }}>{data?.above_50ma ?? '—'}</span></span>
          </div>
          <CornerStamp>Current</CornerStamp>
        </div>

        {/* 52-week highs/lows */}
        <div style={{ ...card, display:'flex', flexDirection:'column' }}>
          <div style={{ ...title, display:'flex', alignItems:'center', gap:6 }}>
            52-Week Highs / Lows
            <InfoDot text="Counts FTSE 100 constituents that touched a new 52-week high or low today. New Highs minus New Lows shows whether leadership is broadening or breaking down; the H/L Ratio (highs ÷ lows) above 1 is bullish, below 1 bearish. A surge in new lows while the index holds up can warn of a narrow, fragile rally." />
          </div>
          <div style={{ flex:1, display:'flex', flexDirection:'column', justifyContent:'center', transform:'translateY(-10px)' }}>
            <DivergingBar
              leftLabel="New Lows"   leftValue={data?.new_lows}   leftColor="#ff2e3f"
              rightLabel="New Highs" rightValue={data?.new_highs} rightColor="#16d96b"
              max={hlScaleMax}
            />
          </div>
          <CornerStamp>Last close{lastUpdated ? ` · ${lastUpdated}` : ''}</CornerStamp>
        </div>

        {/* A/D placeholder card — chart is below */}
        <div style={{ ...card, display:'flex', flexDirection:'column' }}>
          <div style={{ ...title, display:'flex', alignItems:'center', gap:6 }}>
            Advance / Decline
            <InfoDot text="Today's split of FTSE 100 constituents that rose (Advancing) versus fell (Declining), with Net = advancing − declining. It gauges how broad-based the day's move is: a rising index on weak net advances means few stocks are doing the lifting. Watch it against price for confirmation or divergence." />
          </div>
          <div style={{ flex:1, display:'flex', flexDirection:'column', justifyContent:'center', transform:'translateY(-10px)' }}>
            <DivergingBar
              leftLabel="Declining"  leftValue={data?.declines}  leftColor="#ff2e3f"
              rightLabel="Advancing" rightValue={data?.advances} rightColor="#16d96b"
              max={adScaleMax}
            />
          </div>
          {/* Absolute so it doesn't shrink the bar's centring region — keeps this
              bar vertically aligned with the highs/lows bar in the next card. */}
          <div style={{ position:'absolute', left:16, bottom:40 }}>
            <Toggle on={showAdLine} onChange={setShowAdLine} label={`${showAdLine ? 'Hide' : 'Show'} A/D line`} />
          </div>
          <CornerStamp>Last close{lastUpdated ? ` · ${lastUpdated}` : ''}</CornerStamp>
        </div>
      </div>

      {/* A/D Line chart — toggled from the Advance/Decline card, hidden by default */}
      {showAdLine && data?.ad_line?.length > 0 && (
        <div style={card}>
          <div style={{ ...title, display:'flex', alignItems:'center', gap:6 }}>
            Cumulative Advance / Decline Line (20 days)
            <InfoDot text="A running total of each day's net advances (advancing − declining) over the last 20 trading days. A rising line means breadth is steadily improving; a falling line means more stocks are declining than advancing. When the A/D line diverges from the index — index up but line down — it can signal an underlying weakening before price reflects it." />
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={data.ad_line} margin={{ top:5, right:10, bottom:5, left:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
              <XAxis dataKey="date" ticks={adTicks} interval={0} tickFormatter={fmtAdTick} tick={{ fontSize:9, fill:'#64748b', fontFamily:'monospace' }} />
              <YAxis tick={{ fontSize:9, fill:'#64748b', fontFamily:'monospace' }} />
              <Tooltip contentStyle={tooltipStyle} labelStyle={{ color:'#e5e5e5' }} labelFormatter={fmtUKDate} />
              <ReferenceLine y={0} stroke="#333" />
              <Line type="monotone" dataKey="value" stroke="#16d96b" strokeWidth={2} dot={false} name="A/D Line" />
            </LineChart>
          </ResponsiveContainer>
          <CornerStamp>Last close{lastUpdated ? ` · ${lastUpdated}` : ''}</CornerStamp>
        </div>
      )}
    </div>
  );
}
