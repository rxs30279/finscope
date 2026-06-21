"use client";
import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { API } from "@/lib/api";
import { fmtUKDate } from "@/lib/format";
import { useIsMobile } from "@/hooks/useMediaQuery";
import InfoDot from "@/components/InfoDot";


function BreadthGauge({ value }) {
  // value: 0.0–1.0
  const pct    = value !== null && value !== undefined ? value : 0.5;
  const cx = 100, cy = 100, r = 80;
  // Semicircle: 0% → left (180°), 100% → right (0°), 50% → top
  const angleDeg = 180 - pct * 180;
  const rad = angleDeg * Math.PI / 180;
  const nx  = cx + 68 * Math.cos(rad);
  const ny  = cy - 68 * Math.sin(rad);
  const color = pct > 0.60 ? '#10b981' : pct < 0.40 ? '#ef4444' : '#f59e0b';
  const label = pct > 0.60 ? 'Bullish Breadth' : pct < 0.40 ? 'Bearish Breadth' : 'Neutral';

  return (
    <div style={{ textAlign:'center' }}>
      <svg width={200} height={132} viewBox="0 0 200 132">
        {/* Background arc */}
        <path d={`M20,100 A80,80 0 0,1 180,100`} fill="none" stroke="#1e1e1e" strokeWidth={14} strokeLinecap="round"/>
        {/* Coloured arc — gradient approximated via 3 segments */}
        <path d={`M20,100 A80,80 0 0,1 100,20`}  fill="none" stroke="#ef4444" strokeWidth={10} strokeLinecap="round" opacity={0.4}/>
        <path d={`M100,20 A80,80 0 0,1 180,100`} fill="none" stroke="#10b981" strokeWidth={10} strokeLinecap="round" opacity={0.4}/>
        {/* Needle */}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth={3} strokeLinecap="round"/>
        <circle cx={cx} cy={cy} r={5} fill={color}/>
        {/* Value — sits below the pivot so the near-vertical needle (~50%) can't
            overlap it; the needle only ever occupies the upper half. */}
        <text x={cx} y={cy+26} textAnchor="middle" fill={color} fontSize={20} fontFamily="monospace" fontWeight={700}>
          {value !== null && value !== undefined ? `${(value*100).toFixed(0)}%` : '—'}
        </text>
      </svg>
      <div style={{ color, fontSize:11, marginTop:2 }}>{label}</div>
    </div>
  );
}

export default function BreadthTab({ refreshKey }) {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const isMobile = useIsMobile();

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/market/breadth`)
      .then(r => r.json())
      .then(breadthData => { setData(breadthData); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  const card  = { background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 };
  const title = { color:'#9aa7b5', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 };

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

  // H/L Ratio = new highs ÷ new lows. The backend returns null when lows are 0
  // (would divide by zero), so handle the edge cases explicitly: all-highs is a
  // bullish "∞×", all-lows a bearish "0×", and only a truly empty day shows "—".
  const nh = data?.new_highs;
  const nl = data?.new_lows;
  let hl = { value: '—', color: '#e5e5e5', bg: '#1a1a1a' };
  if (nh != null && nl != null) {
    if (nl === 0 && nh > 0)      hl = { value: '∞x',  color: '#10b981', bg: '#0d2318' };
    else if (nh === 0 && nl > 0) hl = { value: '0x',  color: '#ef4444', bg: '#2a0d0d' };
    else if (data?.hl_ratio != null) hl = { value: data.hl_ratio.toFixed(1) + 'x', color: '#e5e5e5', bg: '#1a1a1a' };
  }

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:4 }}>Market Breadth</h2>
      <div style={{ fontFamily:'monospace', fontSize:10, color:'#64748b', marginBottom:20 }}>Across the FTSE 100 constituents</div>
      <div style={{ display:'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 1fr', gap:16, marginBottom:16 }}>

        {/* Gauge */}
        <div style={card}>
          <div style={title}>% Above 50-Day MA</div>
          <BreadthGauge value={data?.pct_above_50ma} />
          <div style={{ display:'flex', justifyContent:'space-around', marginTop:12, fontSize:10, fontFamily:'monospace' }}>
            <span style={{ color:'#94a3b8' }}>Above: <span style={{ color:'#10b981' }}>{data?.above_50ma ?? '—'}</span></span>
            <span style={{ color:'#94a3b8' }}>Below: <span style={{ color:'#ef4444' }}>{data?.below_50ma ?? '—'}</span></span>
          </div>
        </div>

        {/* 52-week highs/lows */}
        <div style={card}>
          <div style={{ ...title, display:'flex', alignItems:'center', gap:6 }}>
            52-Week Highs / Lows
            <InfoDot text="Counts FTSE 100 constituents that touched a new 52-week high or low today. New Highs minus New Lows shows whether leadership is broadening or breaking down; the H/L Ratio (highs ÷ lows) above 1 is bullish, below 1 bearish. A surge in new lows while the index holds up can warn of a narrow, fragile rally." />
          </div>
          <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {[
              { label:'New Highs', value: data?.new_highs, color:'#10b981', bg:'#0d2318' },
              { label:'New Lows',  value: data?.new_lows,  color:'#ef4444', bg:'#2a0d0d' },
              { label:'H/L Ratio', value: hl.value, color: hl.color, bg: hl.bg },
            ].map(({ label, value, color, bg }) => (
              <div key={label} style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <span style={{ color:'#94a3b8', fontSize:11 }}>{label}</span>
                <span style={{ background:bg, color, padding:'2px 10px', borderRadius:2, fontSize:13, fontWeight:700 }}>
                  {value ?? '—'}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* A/D placeholder card — chart is below */}
        <div style={card}>
          <div style={{ ...title, display:'flex', alignItems:'center', gap:6 }}>
            Advance / Decline
            <InfoDot text="Today's split of FTSE 100 constituents that rose (Advancing) versus fell (Declining), with Net = advancing − declining. It gauges how broad-based the day's move is: a rising index on weak net advances means few stocks are doing the lifting. Watch it against price for confirmation or divergence." />
          </div>
          <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {[
              { label:'Advancing', value: data?.advances, color:'#10b981', bg:'#0d2318' },
              { label:'Declining', value: data?.declines, color:'#ef4444', bg:'#2a0d0d' },
              {
                label:'Net',
                value: data?.advances != null && data?.declines != null
                  ? (data.advances - data.declines > 0 ? '+' : '') + (data.advances - data.declines)
                  : '—',
                color:'#e5e5e5', bg:'#1a1a1a',
              },
            ].map(({ label, value, color, bg }) => (
              <div key={label} style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <span style={{ color:'#94a3b8', fontSize:11 }}>{label}</span>
                <span style={{ background:bg, color, padding:'2px 10px', borderRadius:2, fontSize:13, fontWeight:700 }}>
                  {value ?? '—'}
                </span>
              </div>
            ))}
          </div>
          <div style={{ marginTop:10, fontSize:10, color:'#64748b', fontFamily:'monospace' }}>A/D line below ↓</div>
        </div>
      </div>

      {/* A/D Line chart */}
      {data?.ad_line?.length > 0 && (
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
              <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={2} dot={false} name="A/D Line" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
