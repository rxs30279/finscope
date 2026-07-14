"use client";
import { useState, useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceArea, ReferenceLine
} from 'recharts';
import { fmtUKDate } from "@/lib/format";

// Split out of FearGreedTab.js so recharts stays out of the /markets first-load
// bundle — the chart sits behind the Timeline toggle and is loaded on demand
// via next/dynamic in FearGreedTab.

const RANGE_DAYS = { '1M': 31, '3M': 92, '6M': 183, '1Y': 366 };
const UK_COLOR = '#f97316'; // orange — matches the page accent
const US_COLOR = '#38bdf8'; // sky blue — CNN US index

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

export default function FearGreedHistoryChart({ history, loading, bare = false }) {
  const [range, setRange] = useState('1Y');
  const [mode, setMode]   = useState('raw'); // 'raw' | 'pct'
  // Which series are drawn — UK and US, each independently toggleable.
  const [show, setShow]   = useState({ uk: true, us: false });
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
    <div style={bare ? {} : { background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:20, marginBottom:20 }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:14, flexWrap:'wrap', gap:10 }}>
        <div style={{ color:'#9aa7b5', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px' }}>
          UK and US Fear &amp; Greed — rolling year
        </div>
        <div style={{ display:'flex', gap:14, alignItems:'center', flexWrap:'wrap' }}>
          <div style={{ display:'flex', gap:10 }}>
            {[['uk', UK_COLOR, 'UK'], ['us', US_COLOR, 'US']].map(([k, c, label]) => (
              <button
                key={k}
                onClick={() => toggle(k)}
                title={`${show[k] ? 'Hide' : 'Show'} ${label}`}
                style={{
                  background:'none', border:'none', padding:0, cursor:'pointer',
                  color: show[k] ? c : '#555', fontSize:10, fontFamily:'monospace',
                  display:'flex', alignItems:'center', gap:5,
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
            <ReferenceArea yAxisId="left" y1={0}  y2={25}  fill="#ff2e3f" fillOpacity={0.06} />
            <ReferenceArea yAxisId="left" y1={25} y2={44}  fill="#ff7a14" fillOpacity={0.05} />
            <ReferenceArea yAxisId="left" y1={55} y2={75}  fill="#7ed321" fillOpacity={0.05} />
            <ReferenceArea yAxisId="left" y1={75} y2={100} fill="#16d96b" fillOpacity={0.06} />
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
            {show.us && <Line yAxisId="left" type="monotone" dataKey="us" name="US" stroke={US_COLOR} strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />}
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
