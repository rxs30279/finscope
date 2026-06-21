"use client";
import { useState, useEffect, useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceArea, ReferenceLine
} from 'recharts';
import { API } from "@/lib/api";
import { fmtUKDate } from "@/lib/format";
import { useIsMobile } from "@/hooks/useMediaQuery";

const RANGE_DAYS = { '1M': 31, '3M': 92, '6M': 183, '1Y': 366 };
const UK_COLOR = '#f97316'; // orange — matches the page accent
const US_COLOR = '#38bdf8'; // sky blue — CNN US index
const VIX_COLOR = '#a78bfa'; // violet — VIX overlay (off by default)

function fgColor(score) {
  if (score >= 75) return '#10b981';
  if (score >= 55) return '#f59e0b';
  if (score >= 45) return '#666';
  if (score >= 25) return '#f97316';
  return '#ef4444';
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
    means: 'Around three-quarters of FTSE 100 revenue is earned overseas, so the level of sterling drives reported profits. A weaker pound flatters those overseas earnings once converted back — a tailwind that reads as greed; a stronger pound is an earnings headwind that reads as fear. The US VIX, previously used here, now sits in its own panel as a standalone cross-check.',
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

// Percentile rank (0–100) of `v` within a pre-sorted reference array, using the
// Hazen convention (strictly-less + half-equal) so ties land mid-band and the
// median maps to ~50. Returns null for missing values / empty reference.
function pctRank(sortedRef, v) {
  if (v == null || sortedRef.length === 0) return null;
  let lo = 0, eq = 0;
  for (const x of sortedRef) {
    if (x < v) lo++;
    else if (x === v) eq++;
    else break;
  }
  return Math.round(((lo + 0.5 * eq) / sortedRef.length) * 100);
}

function FearGreedHistoryChart({ history, loading }) {
  const [range, setRange] = useState('1Y');
  const [mode, setMode]   = useState('raw'); // 'raw' | 'pct'
  // Which series are drawn — UK and US, each independently toggleable.
  const [show, setShow]   = useState({ uk: true, us: true });
  const toggle = (k) => setShow(s => ({ ...s, [k]: !s[k] }));

  const filtered = useMemo(() => {
    if (!history || history.length === 0) return [];
    const cutoff = Date.now() - RANGE_DAYS[range] * 86400000;
    return history.filter(d => new Date(d.date).getTime() >= cutoff);
  }, [history, range]);

  // Reference distributions are the FULL fetched history (≈ trailing year), not
  // the range-filtered slice — so a point's percentile is stable regardless of
  // which range pill is active, and each index is ranked only against itself.
  const refs = useMemo(() => {
    const h = history || [];
    return {
      uk: h.map(d => d.uk).filter(v => v != null).sort((a, b) => a - b),
      us: h.map(d => d.us).filter(v => v != null).sort((a, b) => a - b),
    };
  }, [history]);

  // Data fed to the chart: raw scores, or each point re-expressed as its
  // percentile within its own series so the two are comparable like-for-like.
  const chartData = useMemo(() => {
    if (mode === 'raw') return filtered;
    return filtered.map(d => ({
      date: d.date,
      uk: pctRank(refs.uk, d.uk),
      us: pctRank(refs.us, d.us),
    }));
  }, [filtered, mode, refs]);

  // Explicit, evenly-spaced ticks that always include the first and last data
  // point. Letting recharts auto-pick (preserveStartEnd + minTickGap) dropped
  // the final date's label when it sat within minTickGap of the prior tick, so
  // the axis appeared to stop a few days short of the latest reading.
  const ticks = useMemo(() => {
    const n = filtered.length;
    if (n === 0) return [];
    if (n <= 2) return filtered.map(d => d.date);
    const count = Math.min(7, n);
    const out = [];
    for (let i = 0; i < count; i++) {
      out.push(filtered[Math.round((i * (n - 1)) / (count - 1))].date);
    }
    return [...new Set(out)];
  }, [filtered]);

  const pillBase = { borderWidth:1, borderStyle:'solid', borderColor:'#2a2a2a', borderRadius:3, padding:'2px 8px', fontSize:9, cursor:'pointer', fontFamily:'monospace', background:'none' };
  const pillActive = { ...pillBase, background:'#3730a3', color:'#e0e7ff', borderColor:'#4338ca' };
  const pillInactive = { ...pillBase, color:'#555' };

  const tickFormatter = (d) => {
    const date = new Date(d);
    const mon = date.toLocaleString('default', { month: 'short' });
    // Short ranges: day + month (e.g. "5 Jun"). Longer ranges: month + 2-digit
    // year (e.g. "Jun '25") so the year boundary is clear without crowding.
    if (range === '1M' || range === '3M') return `${date.getDate()} ${mon}`;
    return `${mon} '${String(date.getFullYear()).slice(2)}`;
  };

  return (
    <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:20, marginBottom:20 }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:14, flexWrap:'wrap', gap:10 }}>
        <div style={{ color:'#9aa7b5', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px' }}>
          UK vs US Fear &amp; Greed — rolling year
        </div>
        <div style={{ display:'flex', gap:14, alignItems:'center', flexWrap:'wrap' }}>
          <div style={{ display:'flex', gap:10 }}>
            {[['uk', UK_COLOR, 'UK'], ['us', US_COLOR, 'US (CNN)']].map(([k, c, label]) => (
              <button
                key={k}
                onClick={() => toggle(k)}
                title={`${show[k] ? 'Hide' : 'Show'} ${label}`}
                style={{
                  background:'none', border:'none', padding:0, cursor:'pointer',
                  color: show[k] ? c : '#555', fontSize:10, fontFamily:'monospace',
                  display:'flex', alignItems:'center', gap:5,
                  textDecoration: show[k] ? 'none' : 'line-through',
                }}
              >
                <span style={{ width:10, height:2, background: show[k] ? c : '#555', display:'inline-block' }}/> {label}
              </button>
            ))}
          </div>
          <div style={{ display:'flex', gap:4 }}>
            {[['raw','Raw'], ['pct','%ile']].map(([m, label]) => (
              <button key={m} onClick={() => setMode(m)} title={m === 'pct' ? 'Show each index as its percentile within its own trailing-year history' : 'Show the raw 0–100 score'} style={m === mode ? pillActive : pillInactive}>{label}</button>
            ))}
          </div>
          <div style={{ display:'flex', gap:4 }}>
            {Object.keys(RANGE_DAYS).map(r => (
              <button key={r} onClick={() => setRange(r)} style={r === range ? pillActive : pillInactive}>{r}</button>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ color:'#444', fontFamily:'monospace', fontSize:11, padding:'40px 0', textAlign:'center' }}>Loading history…</div>
      ) : filtered.length === 0 ? (
        <div style={{ color:'#444', fontFamily:'monospace', fontSize:11, padding:'40px 0', textAlign:'center' }}>No history available yet.</div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={chartData} margin={{ top:5, right:34, bottom:5, left:0 }}>
            {/* Sentiment bands behind the lines */}
            <ReferenceArea yAxisId="left" y1={0}  y2={25}  fill="#ef4444" fillOpacity={0.06} />
            <ReferenceArea yAxisId="left" y1={25} y2={45}  fill="#f97316" fillOpacity={0.05} />
            <ReferenceArea yAxisId="left" y1={55} y2={75}  fill="#f59e0b" fillOpacity={0.05} />
            <ReferenceArea yAxisId="left" y1={75} y2={100} fill="#10b981" fillOpacity={0.06} />
            <ReferenceLine yAxisId="left" y={50} stroke="#2a2a2a" strokeDasharray="3 3" />
            <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
            <XAxis dataKey="date" tick={{ fontSize:9, fill:'#888', fontFamily:'monospace' }} ticks={ticks} interval={0} tickMargin={8} tickFormatter={tickFormatter} />
            <YAxis yAxisId="left" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} width={40} tick={{ fontSize:9, fill:'#888', fontFamily:'monospace' }} />
            <Tooltip
              contentStyle={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:10, fontFamily:'monospace' }}
              labelStyle={{ color:'#e5e5e5' }}
              formatter={(v, name) => [v != null ? `${Math.round(v)}${mode === 'pct' ? ' %ile' : ''}` : '—', name]}
              labelFormatter={fmtUKDate}
            />
            {show.uk && <Line yAxisId="left" type="monotone" dataKey="uk" name="UK" stroke={UK_COLOR} strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />}
            {show.us && <Line yAxisId="left" type="monotone" dataKey="us" name="US (CNN)" stroke={US_COLOR} strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />}
          </LineChart>
        </ResponsiveContainer>
      )}
      <div style={{ color:'#555', fontSize:9, fontFamily:'monospace', marginTop:8, lineHeight:1.6 }}>
        {mode === 'pct'
          ? 'Each index shown as its percentile within its own trailing-year history (0 = lowest reading of the period, 100 = highest). Puts the lower-variance UK index on a like-for-like scale with the US for comparing relative extremes.'
          : 'UK index reconstructed daily from our six price-derived components, each percentile-ranked against its own trailing two-year range and then averaged; US is CNN’s published Fear & Greed Index. 0 = extreme fear, 100 = extreme greed.'}
      </div>
    </div>
  );
}

function VixHistoryChart({ history, loading }) {
  const [range, setRange] = useState('1Y');

  const filtered = useMemo(() => {
    if (!history || history.length === 0) return [];
    const cutoff = Date.now() - RANGE_DAYS[range] * 86400000;
    return history.filter(d => d.vix != null && new Date(d.date).getTime() >= cutoff);
  }, [history, range]);

  const ticks = useMemo(() => {
    const n = filtered.length;
    if (n === 0) return [];
    if (n <= 2) return filtered.map(d => d.date);
    const count = Math.min(7, n);
    const out = [];
    for (let i = 0; i < count; i++) {
      out.push(filtered[Math.round((i * (n - 1)) / (count - 1))].date);
    }
    return [...new Set(out)];
  }, [filtered]);

  const pillBase = { borderWidth:1, borderStyle:'solid', borderColor:'#2a2a2a', borderRadius:3, padding:'2px 8px', fontSize:9, cursor:'pointer', fontFamily:'monospace', background:'none' };
  const pillActive = { ...pillBase, background:'#3730a3', color:'#e0e7ff', borderColor:'#4338ca' };
  const pillInactive = { ...pillBase, color:'#555' };

  const tickFormatter = (d) => {
    const date = new Date(d);
    const mon = date.toLocaleString('default', { month: 'short' });
    if (range === '1M' || range === '3M') return `${date.getDate()} ${mon}`;
    return `${mon} '${String(date.getFullYear()).slice(2)}`;
  };

  return (
    <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:20, marginBottom:20 }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:14, flexWrap:'wrap', gap:10 }}>
        <div style={{ color:'#9aa7b5', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px' }}>
          US VIX — rolling year
        </div>
        <div style={{ display:'flex', gap:14, alignItems:'center', flexWrap:'wrap' }}>
          <span style={{ color: VIX_COLOR, fontSize:10, fontFamily:'monospace', display:'flex', alignItems:'center', gap:5 }}>
            <span style={{ width:10, height:2, background: VIX_COLOR, display:'inline-block' }}/> US VIX
          </span>
          <div style={{ display:'flex', gap:4 }}>
            {Object.keys(RANGE_DAYS).map(r => (
              <button key={r} onClick={() => setRange(r)} style={r === range ? pillActive : pillInactive}>{r}</button>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ color:'#444', fontFamily:'monospace', fontSize:11, padding:'40px 0', textAlign:'center' }}>Loading history…</div>
      ) : filtered.length === 0 ? (
        <div style={{ color:'#444', fontFamily:'monospace', fontSize:11, padding:'40px 0', textAlign:'center' }}>No VIX history available yet.</div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={filtered} margin={{ top:5, right:34, bottom:5, left:0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
            {/* 20 ≈ the VIX long-run average — a rough fear/calm divider. */}
            <ReferenceLine y={20} stroke="#2a2a2a" strokeDasharray="3 3" label={{ value:'20', position:'right', fill:'#555', fontSize:9, fontFamily:'monospace' }} />
            <XAxis dataKey="date" tick={{ fontSize:9, fill:'#888', fontFamily:'monospace' }} ticks={ticks} interval={0} tickMargin={8} tickFormatter={tickFormatter} />
            <YAxis domain={['auto', 'auto']} width={40} tick={{ fontSize:9, fill:'#888', fontFamily:'monospace' }} />
            <Tooltip
              contentStyle={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:10, fontFamily:'monospace' }}
              labelStyle={{ color:'#e5e5e5' }}
              formatter={(v) => [v != null ? v.toFixed(2) : '—', 'US VIX']}
              labelFormatter={fmtUKDate}
            />
            <Line type="monotone" dataKey="vix" name="US VIX" stroke={VIX_COLOR} strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
      <div style={{ color:'#555', fontSize:9, fontFamily:'monospace', marginTop:8, lineHeight:1.6 }}>
        The CBOE Volatility Index (VIX) — the market’s expected 30-day volatility implied by S&P 500 option prices. The original US “fear gauge”: higher = more fear (crash protection in demand), lower = calm/complacency. Shown here as the raw level; used globally as a risk-appetite proxy because equity risk moves in lockstep across markets.
      </div>
    </div>
  );
}

export default function FearGreedTab({ refreshKey }) {
  const [fg, setFg]         = useState(null);
  const [loading, setLoading] = useState(true);
  const [history, setHistory] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [showComponents, setShowComponents] = useState(false);
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

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>
        Fear &amp; Greed
      </h2>

      {/* ── Today's score — own box at the top ─────────────────────────────── */}
      {loading ? (
        <div style={{ color:'#444', padding:32, fontFamily:'monospace', background:'#111', border:'1px solid #1e1e1e', borderRadius:3, marginBottom:20 }}>Loading…</div>
      ) : !fg ? (
        <div style={{ color:'#444', padding:32, fontFamily:'monospace', background:'#111', border:'1px solid #1e1e1e', borderRadius:3, marginBottom:20 }}>No data available.</div>
      ) : (
      <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:20, marginBottom:20 }}>
        {/* Header: make it unmistakable this is today's reading */}
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'baseline', flexWrap:'wrap', gap:6, marginBottom:14 }}>
          <div style={{ color:'#f97316', fontSize:11, fontWeight:700, textTransform:'uppercase', letterSpacing:'1.5px' }}>
            Latest Close
          </div>
          <div style={{ color:'#94a3b8', fontSize:9, textTransform:'uppercase', letterSpacing:'1px' }}>
            UK Fear &amp; Greed Index{asOfDate ? ` · as of ${fmtDate(asOfDate)}` : ''}
          </div>
        </div>

        {/* Score + sentiment */}
        <div style={{ display:'flex', alignItems:'flex-end', gap:16, marginBottom:14 }}>
          <div>
            <span style={{ color, fontSize:56, fontWeight:700, fontFamily:'monospace', lineHeight:1 }}>{fg.score}</span>
            <span style={{ color, fontSize:18, fontWeight:700, marginLeft:14 }}>{fg.sentiment?.toUpperCase()}</span>
          </div>
          <div style={{ color:'#94a3b8', fontSize:11, paddingBottom:8 }}>
            Trend: <span style={{ color: fg.trend === 'rising' ? '#10b981' : fg.trend === 'falling' ? '#ef4444' : '#666' }}>
              {fg.trend === 'rising' ? '↑ Rising' : fg.trend === 'falling' ? '↓ Falling' : '—'}
            </span>
          </div>
        </div>

        {/* Colour-banded progress bar (the gauge graphic). Outer wrapper is not
            clipped so the current-reading marker can stand proud of the bar. */}
        <div style={{ position:'relative', height:10 }}>
          <div style={{ position:'absolute', inset:0, borderRadius:5, background:'#1a1a1a', overflow:'hidden' }}>
            <div style={{ position:'absolute', left:'0%',  width:'25%', height:'100%', background:'#ef4444', opacity:0.9 }}/>
            <div style={{ position:'absolute', left:'25%', width:'20%', height:'100%', background:'#f97316', opacity:0.9 }}/>
            <div style={{ position:'absolute', left:'45%', width:'10%', height:'100%', background:'#9ca3af', opacity:0.9 }}/>
            <div style={{ position:'absolute', left:'55%', width:'20%', height:'100%', background:'#f59e0b', opacity:0.9 }}/>
            <div style={{ position:'absolute', left:'75%', width:'25%', height:'100%', background:'#10b981', opacity:0.9 }}/>
          </div>
          {/* Current reading — a bold outlined marker that overhangs the bar */}
          <div style={{ position:'absolute', left:`${fg.score}%`, top:'50%', transform:'translate(-50%,-50%)', zIndex:2, width:6, height:22, background:'#fff', border:'2px solid #0b0b0b', borderRadius:3, boxShadow:'0 0 7px rgba(0,0,0,0.95)' }}/>
        </div>
        <div style={{ display:'flex', justifyContent:'space-between', color:'#555', fontSize:8, fontFamily:'monospace', marginTop:5, textTransform:'uppercase', letterSpacing:'0.5px' }}>
          <span>Extreme Fear</span><span>Neutral</span><span>Extreme Greed</span>
        </div>
      </div>
      )}

      {/* ── Component breakdown — collapsed behind a toggle ──────────────────── */}
      {fg && (
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

      {/* ── History chart ───────────────────────────────────────────────────── */}
      <FearGreedHistoryChart history={history} loading={historyLoading} />

      {/* ── US VIX — its own panel below ────────────────────────────────────── */}
      <VixHistoryChart history={history} loading={historyLoading} />
    </div>
  );
}
