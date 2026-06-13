"use client";
import { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from 'recharts';
import { API } from '../utils';
import { useIsMobile } from '../useMediaQuery';

function AssetCard({ label, item, decimals = 2, prefix = '', suffix = '' }) {
  if (!item) return (
    <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:16 }}>
      <div style={{ color:'#94a3b8', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>{label}</div>
      <div style={{ color:'#333', fontSize:18, fontWeight:700, fontFamily:'monospace' }}>—</div>
    </div>
  );

  const { value, pct_change, bias } = item;
  const chgColor = pct_change === null ? '#555' : pct_change > 0 ? '#10b981' : pct_change < 0 ? '#ef4444' : '#f59e0b';
  const arrow = pct_change === null ? '' : pct_change > 0.001 ? ' ↑' : pct_change < -0.001 ? ' ↓' : ' →';

  return (
    <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:16 }}>
      <div style={{ color:'#94a3b8', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>{label}</div>
      <div style={{ color:'#e5e5e5', fontSize:20, fontWeight:700, fontFamily:'monospace' }}>
        {value !== null && value !== undefined ? `${prefix}${value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}` : '—'}
      </div>
      <div style={{ color: chgColor, fontSize:10, marginTop:4 }}>
        {pct_change !== null && pct_change !== undefined
          ? `${pct_change > 0 ? '+' : ''}${(pct_change * 100).toFixed(2)}%${arrow}`
          : '—'}
      </div>
      {bias && <div style={{ color:'#94a3b8', fontSize:9, marginTop:4 }}>{bias}</div>}
    </div>
  );
}

// "2026 APR" -> "Apr 2026"; "2025 Q4" -> "Q4 2025"
function fmtPeriod(p) {
  if (!p) return '';
  const mon = p.match(/^(\d{4})\s+([A-Z]{3})$/);
  if (mon) return `${mon[2][0]}${mon[2].slice(1).toLowerCase()} ${mon[1]}`;
  const qtr = p.match(/^(\d{4})\s+(Q\d)$/);
  if (qtr) return `${qtr[2]} ${qtr[1]}`;
  return p;
}

// ONS macro reading: latest value (%) for the given period, with prior for context.
// `signed` shows +/- and colours the headline (used for GDP growth, which can go negative).
function MacroCard({ label, item, signed = false }) {
  const cardStyle = { background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:16 };
  if (!item || typeof item.value !== 'number') return (
    <div style={cardStyle}>
      <div style={{ color:'#94a3b8', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>{label}</div>
      <div style={{ color:'#333', fontSize:20, fontWeight:700, fontFamily:'monospace' }}>—</div>
    </div>
  );

  const { value, period, prev } = item;
  const valColor = signed ? (value > 0 ? '#10b981' : value < 0 ? '#ef4444' : '#f59e0b') : '#e5e5e5';
  const valText = `${signed && value > 0 ? '+' : ''}${value.toFixed(1)}%`;
  const arrow = typeof prev !== 'number' ? '' : value > prev ? ' ↑' : value < prev ? ' ↓' : ' →';

  return (
    <div style={cardStyle}>
      <div style={{ color:'#94a3b8', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>{label}</div>
      <div style={{ color: valColor, fontSize:20, fontWeight:700, fontFamily:'monospace' }}>{valText}</div>
      <div style={{ color:'#94a3b8', fontSize:9, marginTop:4 }}>{fmtPeriod(period)}</div>
      {typeof prev === 'number' && (
        <div style={{ color:'#666', fontSize:9, marginTop:2 }}>prev {prev.toFixed(1)}%{arrow}</div>
      )}
    </div>
  );
}

// 1-year z-score of the gilt-vs-utilities spread (spread = gilt ETF price −
// utilities basket price), shown as a gauge across a −2.5σ … +2.5σ track.
// High z = gilts expensive vs utilities; low z = gilts cheap.
function GiltUtilitiesGauge({ item }) {
  const [showInfo, setShowInfo] = useState(false);
  const z = item && typeof item.zscore === 'number' ? item.zscore : null;

  // Track spans −2.5σ … +2.5σ. Normal band (−1σ … +1σ) maps to the middle 30–70%.
  const pct = z === null ? 50 : ((Math.max(-2.5, Math.min(2.5, z)) + 2.5) / 5) * 100;

  const zone = z === null ? 'normal' : z <= -1 ? 'cheap' : z >= 1 ? 'expensive' : 'normal';
  const ZONE = {
    cheap:     { color: '#60a5fa', caption: 'Gilts cheap vs utilities' },
    normal:    { color: '#94a3b8', caption: 'Within normal range' },
    expensive: { color: '#f59e0b', caption: 'Gilts expensive vs utilities' },
  };
  const { color, caption } = ZONE[zone];

  return (
    <div style={{ position:'relative', background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:16 }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom:14 }}>
        <div style={{ display:'flex', alignItems:'center', gap:5 }}>
          <span style={{ color:'#94a3b8', fontSize:9, textTransform:'uppercase', letterSpacing:1 }}>Gilt vs Utilities</span>
          <span
            onMouseEnter={() => setShowInfo(true)}
            onMouseLeave={() => setShowInfo(false)}
            onClick={() => setShowInfo(v => !v)}
            role="button" tabIndex={0} aria-label="How this is calculated"
            style={{ color:'#667', fontSize:10, cursor:'help', userSelect:'none', lineHeight:1 }}
          >ⓘ</span>
        </div>
        <div style={{ color, fontSize:14, fontWeight:700, fontFamily:'monospace' }}>
          {z === null ? '—' : `${z > 0 ? '+' : ''}${z.toFixed(2)}σ`}
        </div>
      </div>
      {showInfo && (
        <div style={{
          position:'absolute', top:34, left:16, right:16, zIndex:20,
          background:'#0a0a0a', border:'1px solid #2a2a2a', borderRadius:4,
          padding:'10px 12px', fontSize:9, lineHeight:1.65, color:'#cbd5e1',
          boxShadow:'0 6px 20px rgba(0,0,0,0.6)',
        }}>
          Utilities are rate-sensitive “bond proxies”, so gilts and utilities normally move together — this flags when they diverge.
          <div style={{ marginTop:6 }}>
            <span style={{ color:'#94a3b8' }}>How it's calculated: </span>
            over the last ~252 trading days we take the daily spread between the gilt ETF (IGLT.L) price and the average price of a UK utilities basket, then express today's spread as a z-score against that year's mean.
          </div>
          <div style={{ marginTop:6 }}>
            Within ±1σ is normal; beyond ±2σ is unusual. High = gilts expensive vs utilities; low = gilts cheap.
          </div>
        </div>
      )}

      <div style={{ display:'flex', justifyContent:'space-between', color:'#555', fontSize:9, fontFamily:'monospace', marginBottom:4 }}>
        <span>cheap</span><span>expensive</span>
      </div>

      <div style={{ position:'relative', height:6 }}>
        <div style={{ position:'absolute', inset:0, display:'flex', borderRadius:3, overflow:'hidden' }}>
          <div style={{ flex:'0 0 30%', background:'#1e3a5f' }} />
          <div style={{ flex:'0 0 40%', background:'#2a2a2a' }} />
          <div style={{ flex:'0 0 30%', background:'#4a3a1a' }} />
        </div>
        <div style={{ position:'absolute', top:-3, left:`${pct}%`, transform:'translateX(-50%)', width:2, height:12, borderRadius:1, background: z === null ? '#555' : color }} />
      </div>

      <div style={{ display:'flex', justifyContent:'space-between', color:'#555', fontSize:8, fontFamily:'monospace', marginTop:4 }}>
        <span>−2σ</span><span>0σ</span><span>+2σ</span>
      </div>

      <div style={{ color, fontSize:9, marginTop:10 }}>{caption}</div>
    </div>
  );
}

const MATURITIES = [
  { key: 'y2',  label: '2Y'  },
  { key: 'y5',  label: '5Y'  },
  { key: 'y10', label: '10Y' },
  { key: 'y20', label: '20Y' },
  { key: 'y30', label: '30Y' },
];

// `fill` makes the chart grow to its parent's height (used when it sits beside
// the box grid on desktop); otherwise it falls back to a fixed 180px height.
function GiltSnapshotChart({ snapshot, fill = false }) {
  if (!snapshot || Object.keys(snapshot).length === 0) {
    return <div style={{ color:'#333', fontFamily:'monospace', fontSize:11 }}>No gilt data available</div>;
  }

  const data = MATURITIES.map(({ key, label }) => {
    const maturity = parseInt(key.slice(1));
    return { label, yield: snapshot[maturity] ?? null };
  }).filter(d => d.yield !== null);

  const isInverted = data.length >= 2 && data[0].yield > data[data.length - 1].yield;
  const curveColor = isInverted ? '#ef4444' : '#10b981';
  const curveLabel = isInverted ? 'Inverted' : data[0]?.yield === data[data.length - 1]?.yield ? 'Flat' : 'Normal';

  return (
    <div style={fill ? { height:'100%', display:'flex', flexDirection:'column' } : undefined}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
        <div style={{ color:'#888', fontSize:9, textTransform:'uppercase', letterSpacing:1 }}>Current Curve</div>
        <div style={{ color: curveColor, fontSize:9, fontWeight:700 }}>{curveLabel}</div>
      </div>
      <div style={fill ? { flex:1, minHeight:0 } : undefined}>
        <ResponsiveContainer width="100%" height={fill ? '100%' : 180}>
          <LineChart data={data} margin={{ top:5, right:10, bottom:5, left:0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
            <XAxis dataKey="label" tick={{ fontSize:9, fill:'#888', fontFamily:'monospace' }} />
            <YAxis
              tick={{ fontSize:9, fill:'#888', fontFamily:'monospace' }}
              tickFormatter={v => `${v.toFixed(1)}%`}
              domain={['auto', 'auto']}
            />
            <Tooltip
              contentStyle={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:11, fontFamily:'monospace' }}
              formatter={v => [`${v.toFixed(2)}%`, 'Yield']}
            />
            <Line type="monotone" dataKey="yield" stroke={curveColor} strokeWidth={2} dot={{ r:4, fill:curveColor }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function CrossAssetTab({ refreshKey }) {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [giltData, setGiltData] = useState(null);
  const [macro, setMacro] = useState(null);
  const isMobile = useIsMobile();

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/market/cross-asset`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  useEffect(() => {
    fetch(`${API}/market/gilt-yields`)
      .then(r => r.json())
      .then(setGiltData)
      .catch(() => {});
  }, [refreshKey]);

  useEffect(() => {
    fetch(`${API}/market/uk-macro`)
      .then(r => r.json())
      .then(setMacro)
      .catch(() => {});
  }, [refreshKey]);

  const skelStyle = { background:'#1a1a1a', border:'1px solid #2a2a2a', borderRadius:3 };

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Cross-Asset</h2>
      {/* Six measures as a 2-column block, with the yield-curve chart beside it
          on desktop. The right column (title + chart card) stretches to the box
          block's height, so the chart card bottom lines up with the boxes. */}
      <div style={{
        display: isMobile ? 'block' : 'grid',
        gridTemplateColumns: isMobile ? undefined : 'minmax(0, 500px) 1fr',
        gap: 12,
        alignItems: 'stretch',
      }}>
        <div style={{ display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:12 }}>
          {loading
            ? <div style={{ ...skelStyle, height:96 }} />
            : <AssetCard label="GBP / USD" item={data?.gbpusd} decimals={4} />}
          {loading
            ? <div style={{ ...skelStyle, height:96 }} />
            : <AssetCard label="Brent Crude" item={data?.brent} decimals={2} prefix="$" />}
          {loading
            ? <div style={{ ...skelStyle, height:96 }} />
            : <AssetCard label="Gold" item={data?.gold} decimals={0} prefix="$" />}
          {loading
            ? <div style={{ ...skelStyle, height:96 }} />
            : <GiltUtilitiesGauge item={data?.gilt_vs_utilities} />}
          {macro === null
            ? <div style={{ ...skelStyle, height:96 }} />
            : <MacroCard label="GDP (QoQ)" item={macro.gdp_qoq} signed />}
          {macro === null
            ? <div style={{ ...skelStyle, height:96 }} />
            : <MacroCard label="CPI (YoY)" item={macro.cpi} />}
        </div>
        <div style={{ display:'flex', flexDirection:'column', marginTop: isMobile ? 24 : 0 }}>
          <div style={{ color:'#888', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:16 }}>
            UK Gilt Yield Curve
          </div>
          {giltData ? (
            <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16, flex:1, minHeight: isMobile ? 230 : 0 }}>
              <GiltSnapshotChart snapshot={giltData.snapshot} fill={!isMobile} />
            </div>
          ) : (
            <div style={{ ...skelStyle, flex:1, minHeight: isMobile ? 230 : 0 }} />
          )}
        </div>
      </div>
    </div>
  );
}
