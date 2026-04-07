import { useState, useEffect } from 'react';
import { API, pctColor } from '../utils';

function fgColor(score) {
  if (score >= 75) return '#10b981';
  if (score >= 55) return '#f59e0b';
  if (score >= 45) return '#666';
  if (score >= 25) return '#f97316';
  return '#ef4444';
}

function fgBg(score) {
  if (score >= 75) return '#0d2318';
  if (score >= 55) return '#1a1400';
  if (score >= 45) return '#1a1a1a';
  if (score >= 25) return '#2a1a00';
  return '#2a0d0d';
}

function PctBadge({ value }) {
  if (value === null || value === undefined) return <span style={{ color:'#444', fontSize:10 }}>—</span>;
  const pct = (value * 100).toFixed(2);
  const color = pctColor(value);
  const bg = value > 0.005 ? '#0d2318' : value < -0.005 ? '#2a0d0d' : '#1a1400';
  return (
    <span style={{ background:bg, color, padding:'1px 5px', borderRadius:2, fontSize:10, fontFamily:'monospace' }}>
      {value > 0 ? '+' : ''}{pct}%
    </span>
  );
}

export default function Sidebar({ refreshKey }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    fetch(`${API}/market/sidebar`)
      .then(r => r.json())
      .then(setData)
      .catch(() => {});
  }, [refreshKey]);

  const labelStyle = { color:'#444', fontSize:9, letterSpacing:'1.5px', textTransform:'uppercase', marginBottom:8 };
  const rowStyle   = { display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:4 };
  const nameStyle  = { color:'#94a3b8', fontSize:10 };

  return (
    <aside style={{ width:185, flexShrink:0, background:'#0d0d0d', borderRight:'1px solid #1e1e1e', padding:'16px 12px', height:'calc(100vh - 52px)', position:'sticky', top:52, overflowY:'auto' }}>

      {/* Benchmarks */}
      <div style={labelStyle}>Benchmarks</div>
      {data?.benchmarks?.map(b => (
        <div key={b.name} style={rowStyle}>
          <span style={nameStyle}>{b.name}</span>
          <PctBadge value={b.pct_change} />
        </div>
      )) ?? <div style={{ color:'#333', fontSize:10 }}>Loading…</div>}

      {/* VIX */}
      {data?.vix !== undefined && data.vix !== null && (
        <div style={{ ...rowStyle, marginTop:12, marginBottom:12, paddingTop:10, borderTop:'1px solid #1e1e1e' }}>
          <span style={nameStyle}>VIX</span>
          <span style={{
            fontFamily:'monospace', fontSize:10, fontWeight:700,
            color: data.vix < 20 ? '#10b981' : data.vix < 30 ? '#f59e0b' : '#ef4444'
          }}>
            {data.vix.toFixed(2)}
          </span>
        </div>
      )}

      {/* CNN Fear & Greed */}
      {data?.cnn_fear_greed?.value !== null && data?.cnn_fear_greed?.value !== undefined && (
        <div style={{ marginBottom:12 }}>
          <div style={rowStyle}>
            <span style={nameStyle}>CNN F&amp;G</span>
            <span style={{ fontFamily:'monospace', fontSize:10, fontWeight:700, color: fgColor(data.cnn_fear_greed.value) }}>
              {data.cnn_fear_greed.value.toFixed(2)}
            </span>
          </div>
          <div style={{ textAlign:'right', fontSize:8, fontWeight:400, color: fgColor(data.cnn_fear_greed.value), opacity:0.7, marginTop:-2 }}>
            {data.cnn_fear_greed.description}
          </div>
        </div>
      )}

      {/* Fear & Greed */}
      {data?.fear_greed && (
        <div style={{ marginTop:12, paddingTop:10, borderTop:'1px solid #1e1e1e' }}>
          <div style={labelStyle}>UK Fear &amp; Greed</div>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:4 }}>
            <span style={{ fontFamily:'monospace', fontSize:22, fontWeight:700, color: fgColor(data.fear_greed.score) }}>
              {data.fear_greed.score}
            </span>
            <span style={{
              background: fgBg(data.fear_greed.score),
              color: fgColor(data.fear_greed.score),
              padding:'2px 6px', borderRadius:2, fontSize:9,
              border:`1px solid ${fgColor(data.fear_greed.score)}33`,
            }}>
              {data.fear_greed.sentiment?.toUpperCase()}
            </span>
          </div>
          <div style={{ background:'#1a1a1a', borderRadius:2, height:4, marginBottom:6 }}>
            <div style={{ background: fgColor(data.fear_greed.score), width:`${data.fear_greed.score}%`, height:4, borderRadius:2 }}/>
          </div>
          {data.fear_greed.suggested_phase && data.fear_greed.suggested_phase !== 'no_change' && (
            <div style={{ color:'#555', fontSize:9 }}>
              Auto phase: <span style={{ color: fgColor(data.fear_greed.score) }}>
                {data.fear_greed.suggested_phase}
                {data.fear_greed.trend === 'rising' ? ' ↑' : data.fear_greed.trend === 'falling' ? ' ↓' : ''}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Sectors */}
      <div style={{ ...labelStyle, marginTop:16 }}>ICB Sectors</div>
      {data?.sectors?.map(s => (
        <div key={s.name} style={rowStyle}>
          <span style={{ ...nameStyle, maxWidth:110, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{s.name}</span>
          <PctBadge value={s.pct_change} />
        </div>
      )) ?? <div style={{ color:'#333', fontSize:10 }}>Loading…</div>}

      {/* Signal Summary */}
      {data?.signal_summary && (
        <div style={{ marginTop:16, borderTop:'1px solid #1e1e1e', paddingTop:12 }}>
          <div style={labelStyle}>Model Signal</div>
          <div style={{ background:'#1a1400', border:'1px solid #333', borderRadius:3, padding:10 }}>
            <div style={{ color:'#f59e0b', fontSize:11, marginBottom:6, fontWeight:700 }}>
              ⚡ {data.signal_summary.cycle_phase?.toUpperCase()}
            </div>
            <div style={{ color:'#666', fontSize:9 }}>
              Above 50MA: <span style={{ color:'#10b981' }}>{data.signal_summary.breadth !== null ? `${(data.signal_summary.breadth*100).toFixed(0)}%` : '—'}</span>
            </div>
            <div style={{ color:'#666', fontSize:9 }}>
              Top RS: <span style={{ color:'#60a5fa' }}>{data.signal_summary.top_rs_sector ?? '—'}</span>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
