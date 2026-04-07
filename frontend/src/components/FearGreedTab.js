import { useState, useEffect } from 'react';
import { API } from '../utils';

function fgColor(score) {
  if (score >= 75) return '#10b981';
  if (score >= 55) return '#f59e0b';
  if (score >= 45) return '#666';
  if (score >= 25) return '#f97316';
  return '#ef4444';
}

export default function FearGreedTab({ refreshKey }) {
  const [fg, setFg]         = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/market/fear-greed`)
      .then(r => r.json())
      .then(data => { setFg(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading…</div>;
  if (!fg)     return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>No data available.</div>;

  const color = fgColor(fg.score);
  const COMPONENT_ORDER = ['momentum', 'breadth', 'vix', 'safe_haven', 'realised_vol', 'hl_ratio'];

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>
        Fear &amp; Greed
      </h2>

      <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:20 }}>
        {/* Header label */}
        <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 }}>
          UK Fear &amp; Greed Index
        </div>

        {/* Score + sentiment */}
        <div style={{ display:'flex', alignItems:'flex-end', gap:16, marginBottom:10 }}>
          <div>
            <span style={{ color, fontSize:48, fontWeight:700, fontFamily:'monospace', lineHeight:1 }}>{fg.score}</span>
            <span style={{ color, fontSize:16, fontWeight:700, marginLeft:12 }}>{fg.sentiment?.toUpperCase()}</span>
          </div>
          <div style={{ color:'#555', fontSize:11, paddingBottom:6 }}>
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
        <div style={{ position:'relative', height:8, borderRadius:4, marginBottom:24, background:'#1a1a1a', overflow:'hidden' }}>
          <div style={{ position:'absolute', left:'0%',  width:'25%', height:'100%', background:'#ef4444', opacity:0.4 }}/>
          <div style={{ position:'absolute', left:'25%', width:'20%', height:'100%', background:'#f97316', opacity:0.4 }}/>
          <div style={{ position:'absolute', left:'45%', width:'10%', height:'100%', background:'#666',    opacity:0.4 }}/>
          <div style={{ position:'absolute', left:'55%', width:'20%', height:'100%', background:'#f59e0b', opacity:0.4 }}/>
          <div style={{ position:'absolute', left:'75%', width:'25%', height:'100%', background:'#10b981', opacity:0.4 }}/>
          <div style={{ position:'absolute', left:`${fg.score}%`, transform:'translateX(-50%)', top:-3, width:4, height:14, background:'white', borderRadius:2 }}/>
        </div>

        {/* Component cards */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(6,1fr)', gap:8 }}>
          {COMPONENT_ORDER.map(key => {
            const c = fg.components?.[key];
            if (!c) return null;
            const cc = fgColor(c.score);
            return (
              <div key={key} style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:3, padding:'12px 10px' }}>
                <div style={{ color:'#555', fontSize:9, marginBottom:6 }}>{c.label}</div>
                <div style={{ color:cc, fontSize:18, fontWeight:700, fontFamily:'monospace' }}>{c.score}</div>
                <div style={{ background:'#1a1a1a', borderRadius:2, height:4, margin:'6px 0' }}>
                  <div style={{ background:cc, width:`${c.score}%`, height:4, borderRadius:2 }}/>
                </div>
                <div style={{ color:'#555', fontSize:9 }}>
                  {c.score >= 75 ? 'Ext. Greed' : c.score >= 55 ? 'Greed' : c.score >= 45 ? 'Neutral' : c.score >= 25 ? 'Fear' : 'Ext. Fear'}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
