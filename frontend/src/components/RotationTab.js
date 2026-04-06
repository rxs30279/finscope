import { useState, useEffect } from 'react';
import { API } from '../utils';

const PHASE_ANGLES  = { Recovery: 45, Expansion: 135, Slowdown: 225, Contraction: 315 };
const PHASE_COLOURS = { Recovery:'#10b981', Expansion:'#60a5fa', Slowdown:'#f59e0b', Contraction:'#ef4444' };

const PHASES = ['Recovery', 'Expansion', 'Slowdown', 'Contraction'];

function needleXY(phase, cx, cy, r) {
  const deg = PHASE_ANGLES[phase] || 45;
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function CycleWheel({ phase, onSetPhase }) {
  const cx = 90, cy = 90, r = 65;
  const needle = needleXY(phase, cx, cy, 55);
  const colour = PHASE_COLOURS[phase] || '#f59e0b';

  return (
    <div style={{ textAlign:'center' }}>
      <svg width={180} height={180} viewBox="0 0 180 180">
        {/* Quadrant fills */}
        <path d={`M${cx},${cy} L${cx},${cy-r} A${r},${r} 0 0,1 ${cx+r},${cy} Z`} fill="#0d2318" stroke="#1e4030" strokeWidth={1}/>
        <path d={`M${cx},${cy} L${cx+r},${cy} A${r},${r} 0 0,1 ${cx},${cy+r} Z`} fill="#1a1400" stroke="#3a2800" strokeWidth={1}/>
        <path d={`M${cx},${cy} L${cx},${cy+r} A${r},${r} 0 0,1 ${cx-r},${cy} Z`} fill="#2a0d0d" stroke="#4a1a1a" strokeWidth={1}/>
        <path d={`M${cx},${cy} L${cx-r},${cy} A${r},${r} 0 0,1 ${cx},${cy-r} Z`} fill="#0d1a2a" stroke="#1a3040" strokeWidth={1}/>
        {/* Labels */}
        <text x={cx+42} y={cy-38} fill="#10b981" fontSize={9} fontFamily="monospace" textAnchor="middle">RECOVERY</text>
        <text x={cx+42} y={cy+46} fill="#60a5fa" fontSize={9} fontFamily="monospace" textAnchor="middle">EXPANSION</text>
        <text x={cx-40} y={cy+46} fill="#f59e0b" fontSize={9} fontFamily="monospace" textAnchor="middle">SLOWDOWN</text>
        <text x={cx-38} y={cy-38} fill="#ef4444" fontSize={9} fontFamily="monospace" textAnchor="middle">CONTRACTION</text>
        {/* Center */}
        <circle cx={cx} cy={cy} r={22} fill="#111" stroke="#333" strokeWidth={1}/>
        {/* Needle */}
        <line x1={cx} y1={cy} x2={needle.x} y2={needle.y} stroke={colour} strokeWidth={2.5} strokeLinecap="round"/>
        <circle cx={cx} cy={cy} r={4} fill={colour}/>
      </svg>
      <div style={{ color: colour, fontSize:13, fontWeight:700, marginTop:4 }}>{phase?.toUpperCase()}</div>
      <select
        value={phase}
        onChange={e => onSetPhase(e.target.value)}
        style={{ marginTop:8, background:'#1a1a1a', color:'#666', border:'1px solid #333', padding:'3px 8px', borderRadius:2, fontFamily:'monospace', fontSize:10, cursor:'pointer' }}
      >
        {PHASES.map(p => <option key={p} value={p}>{p}</option>)}
      </select>
    </div>
  );
}

function SectorHeatmap({ sectors }) {
  if (!sectors?.length) return null;
  return (
    <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:6 }}>
      {sectors.map(s => {
        const rank = s.rank;
        const isTop = rank <= 4;
        const isBottom = rank >= 8;
        const bg    = isTop ? `rgba(16,185,129,${0.08 + (4-rank)*0.04})` : isBottom ? `rgba(239,68,68,${0.05 + (rank-8)*0.03})` : '#101010';
        const border= isTop ? '#10b981' : isBottom ? '#ef4444' : '#222';
        const color = isTop ? '#10b981' : isBottom ? '#ef4444' : '#555';
        return (
          <div key={s.sector} style={{ background:bg, border:`1px solid ${border}`, borderRadius:2, padding:'8px 6px', textAlign:'center' }}>
            <div style={{ color, fontSize:9, fontWeight:700 }}>#{rank}</div>
            <div style={{ color:'#e5e5e5', fontSize:10, marginTop:2 }}>{s.sector}</div>
            <div style={{ color, fontSize:9, marginTop:1 }}>{s.rs_score?.toFixed(2)}</div>
          </div>
        );
      })}
    </div>
  );
}

function RSTable({ sectors }) {
  if (!sectors?.length) return null;
  const badgeStyle = (sig) => ({
    background: sig==='BUY' ? '#0d3320' : sig==='AVOID' ? '#2a0d0d' : '#1a1a1a',
    color:      sig==='BUY' ? '#10b981' : sig==='AVOID' ? '#ef4444' : '#555',
    padding:'2px 7px', borderRadius:2, fontSize:9,
  });
  return (
    <table style={{ width:'100%', borderCollapse:'collapse', fontSize:11, fontFamily:'monospace' }}>
      <thead>
        <tr style={{ borderBottom:'1px solid #2a2a2a' }}>
          {['Rank','Sector','RS Score','Trend','Breadth','Signal'].map(h => (
            <th key={h} style={{ padding:'6px 10px', color:'#f97316', fontSize:9, textTransform:'uppercase', letterSpacing:0.5, textAlign: h==='Rank'||h==='RS Score'||h==='Breadth' ? 'right' : 'left' }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sectors.map(s => (
          <tr key={s.sector} style={{ borderBottom:'1px solid #141414' }}>
            <td style={{ padding:'6px 10px', color:'#555', textAlign:'right' }}>#{s.rank}</td>
            <td style={{ padding:'6px 10px', color:'#e5e5e5' }}>{s.sector}</td>
            <td style={{ padding:'6px 10px', color: s.rs_score>1 ? '#10b981' : '#ef4444', textAlign:'right' }}>{s.rs_score?.toFixed(2) ?? '—'}</td>
            <td style={{ padding:'6px 10px', color: s.trend==='rising' ? '#10b981' : s.trend==='falling' ? '#ef4444' : '#555' }}>
              {s.trend==='rising' ? '↑ Rising' : s.trend==='falling' ? '↓ Falling' : '—'}
            </td>
            <td style={{ padding:'6px 10px', color:'#94a3b8', textAlign:'right' }}>
              {s.breadth !== null && s.breadth !== undefined ? `${(s.breadth*100).toFixed(0)}%` : '—'}
            </td>
            <td style={{ padding:'6px 10px' }}><span style={badgeStyle(s.signal)}>{s.signal}</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function RotationTab({ refreshKey }) {
  const [rotation, setRotation] = useState([]);
  const [cycle, setCycle]       = useState(null);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`${API}/market/rotation`).then(r=>r.json()),
      fetch(`${API}/market/cycle`).then(r=>r.json()),
    ]).then(([rot, cyc]) => {
      setRotation(Array.isArray(rot) ? rot : []);
      setCycle(cyc);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [refreshKey]);

  const handleSetPhase = (phase) => {
    fetch(`${API}/market/cycle`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ phase }),
    }).then(r=>r.json()).then(setCycle);
  };

  const card = { background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 };
  const title = { color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 };

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading rotation data…</div>;

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Sector Rotation</h2>
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16, marginBottom:16 }}>
        <div style={card}>
          <div style={title}>Sector Heatmap — RS Rank</div>
          <SectorHeatmap sectors={rotation} />
        </div>
        <div style={card}>
          <div style={title}>Business Cycle</div>
          {cycle && <CycleWheel phase={cycle.phase} onSetPhase={handleSetPhase} />}
          {cycle?.guidance && (
            <div style={{ marginTop:12, fontSize:10 }}>
              <div style={{ color:'#10b981', marginBottom:2 }}>Favour: {cycle.guidance.favour?.join(', ')}</div>
              <div style={{ color:'#ef4444' }}>Avoid: {cycle.guidance.avoid?.join(', ')}</div>
            </div>
          )}
        </div>
      </div>
      <div style={card}>
        <div style={title}>RS Ranking Table</div>
        <RSTable sectors={rotation} />
      </div>
    </div>
  );
}
