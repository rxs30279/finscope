import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { API } from '../utils';

function fgColor(score) {
  if (score >= 75) return '#10b981';
  if (score >= 55) return '#f59e0b';
  if (score >= 45) return '#666';
  if (score >= 25) return '#f97316';
  return '#ef4444';
}

function FearGreedCard({ fg }) {
  if (!fg) return null;
  const color = fgColor(fg.score);
  const COMPONENT_ORDER = ['momentum', 'breadth', 'vix', 'safe_haven', 'hl_ratio'];
  return (
    <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16, marginBottom:16 }}>
      <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 }}>
        UK Fear &amp; Greed Index
      </div>

      {/* Score + sentiment */}
      <div style={{ display:'flex', alignItems:'flex-end', gap:16, marginBottom:10 }}>
        <div>
          <span style={{ color, fontSize:36, fontWeight:700, fontFamily:'monospace', lineHeight:1 }}>{fg.score}</span>
          <span style={{ color, fontSize:13, fontWeight:700, marginLeft:8 }}>{fg.sentiment?.toUpperCase()}</span>
        </div>
        <div style={{ color:'#555', fontSize:10, paddingBottom:4 }}>
          Trend: <span style={{ color: fg.trend === 'rising' ? '#10b981' : fg.trend === 'falling' ? '#ef4444' : '#666' }}>
            {fg.trend === 'rising' ? '↑ Rising' : fg.trend === 'falling' ? '↓ Falling' : '—'}
          </span>
          {fg.suggested_phase && fg.suggested_phase !== 'no_change' && (
            <> &nbsp;|&nbsp; Auto-phase: <span style={{ color }}>{fg.suggested_phase}</span>
            &nbsp;|&nbsp; Confirmed: <span style={{ color: fg.confirmed ? '#10b981' : '#555' }}>
              {fg.confirmed ? '2/2 readings' : '1/2 readings'}
            </span></>
          )}
        </div>
      </div>

      {/* Colour-banded progress bar */}
      <div style={{ position:'relative', height:6, borderRadius:3, marginBottom:16, background:'#1a1a1a', overflow:'hidden' }}>
        <div style={{ position:'absolute', left:'0%',  width:'25%', height:'100%', background:'#ef4444', opacity:0.4 }}/>
        <div style={{ position:'absolute', left:'25%', width:'20%', height:'100%', background:'#f97316', opacity:0.4 }}/>
        <div style={{ position:'absolute', left:'45%', width:'10%', height:'100%', background:'#666',    opacity:0.4 }}/>
        <div style={{ position:'absolute', left:'55%', width:'20%', height:'100%', background:'#f59e0b', opacity:0.4 }}/>
        <div style={{ position:'absolute', left:'75%', width:'25%', height:'100%', background:'#10b981', opacity:0.4 }}/>
        <div style={{ position:'absolute', left:`${fg.score}%`, transform:'translateX(-50%)', top:-2, width:3, height:10, background:'white', borderRadius:1 }}/>
      </div>

      {/* Component cards */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:6 }}>
        {COMPONENT_ORDER.map(key => {
          const c = fg.components?.[key];
          if (!c) return null;
          const cc = fgColor(c.score);
          return (
            <div key={key} style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:'8px 6px' }}>
              <div style={{ color:'#555', fontSize:8, marginBottom:4 }}>{c.label}</div>
              <div style={{ color:cc, fontSize:13, fontWeight:700, fontFamily:'monospace' }}>{c.score}</div>
              <div style={{ background:'#1a1a1a', borderRadius:1, height:3, margin:'4px 0' }}>
                <div style={{ background:cc, width:`${c.score}%`, height:3, borderRadius:1 }}/>
              </div>
              <div style={{ color:'#555', fontSize:8 }}>
                {c.score >= 75 ? 'Ext. Greed' : c.score >= 55 ? 'Greed' : c.score >= 45 ? 'Neutral' : c.score >= 25 ? 'Fear' : 'Ext. Fear'}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

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
      <svg width={200} height={115} viewBox="0 0 200 115">
        {/* Background arc */}
        <path d={`M20,100 A80,80 0 0,1 180,100`} fill="none" stroke="#1e1e1e" strokeWidth={14} strokeLinecap="round"/>
        {/* Coloured arc — gradient approximated via 3 segments */}
        <path d={`M20,100 A80,80 0 0,1 100,20`}  fill="none" stroke="#ef4444" strokeWidth={10} strokeLinecap="round" opacity={0.4}/>
        <path d={`M100,20 A80,80 0 0,1 180,100`} fill="none" stroke="#10b981" strokeWidth={10} strokeLinecap="round" opacity={0.4}/>
        {/* Needle */}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth={3} strokeLinecap="round"/>
        <circle cx={cx} cy={cy} r={5} fill={color}/>
        {/* Value */}
        <text x={cx} y={cy-12} textAnchor="middle" fill={color} fontSize={20} fontFamily="monospace" fontWeight={700}>
          {value !== null && value !== undefined ? `${(value*100).toFixed(0)}%` : '—'}
        </text>
      </svg>
      <div style={{ color, fontSize:11, marginTop:2 }}>{label}</div>
    </div>
  );
}

export default function BreadthTab({ refreshKey }) {
  const [data, setData]     = useState(null);
  const [fg, setFg]         = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`${API}/market/breadth`).then(r => r.json()),
      fetch(`${API}/market/fear-greed`).then(r => r.json()),
    ]).then(([breadthData, fgData]) => {
      setData(breadthData);
      setFg(fgData);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [refreshKey]);

  const card  = { background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 };
  const title = { color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 };

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading breadth data…</div>;

  const tooltipStyle = { background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:11, color:'#e5e5e5', fontFamily:'monospace' };

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Market Breadth</h2>
      <FearGreedCard fg={fg} />
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:16, marginBottom:16 }}>

        {/* Gauge */}
        <div style={card}>
          <div style={title}>% Above 50-Day MA</div>
          <BreadthGauge value={data?.pct_above_50ma} />
          <div style={{ display:'flex', justifyContent:'space-around', marginTop:12, fontSize:10, fontFamily:'monospace' }}>
            <span style={{ color:'#555' }}>Adv: <span style={{ color:'#10b981' }}>{data?.advances ?? '—'}</span></span>
            <span style={{ color:'#555' }}>Dec: <span style={{ color:'#ef4444' }}>{data?.declines ?? '—'}</span></span>
            <span style={{ color:'#555' }}>Unch: <span style={{ color:'#555' }}>{data?.unchanged ?? '—'}</span></span>
          </div>
        </div>

        {/* 52-week highs/lows */}
        <div style={card}>
          <div style={title}>52-Week Highs / Lows</div>
          <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {[
              { label:'New Highs', value: data?.new_highs, color:'#10b981', bg:'#0d2318' },
              { label:'New Lows',  value: data?.new_lows,  color:'#ef4444', bg:'#2a0d0d' },
              { label:'H/L Ratio', value: data?.hl_ratio?.toFixed(1) + 'x', color:'#e5e5e5', bg:'#1a1a1a' },
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
          <div style={title}>Advance / Decline</div>
          <div style={{ fontSize:10, color:'#555', lineHeight:1.8 }}>
            <div>Today advancing: <span style={{ color:'#10b981' }}>{data?.advances ?? '—'}</span></div>
            <div>Today declining: <span style={{ color:'#ef4444' }}>{data?.declines ?? '—'}</span></div>
            <div style={{ marginTop:8, color:'#444' }}>A/D line below ↓</div>
          </div>
        </div>
      </div>

      {/* A/D Line chart */}
      {data?.ad_line?.length > 0 && (
        <div style={card}>
          <div style={title}>Cumulative Advance / Decline Line (20 days)</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={data.ad_line} margin={{ top:5, right:10, bottom:5, left:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
              <XAxis dataKey="date" tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }} tickFormatter={d => d.slice(5)} />
              <YAxis tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }} />
              <Tooltip contentStyle={tooltipStyle} />
              <ReferenceLine y={0} stroke="#333" />
              <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={2} dot={false} name="A/D Line" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
