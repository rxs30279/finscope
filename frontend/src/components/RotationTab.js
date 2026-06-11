import { useState, useEffect } from 'react';
import { API } from '../utils';
import { useIsMobile } from '../useMediaQuery';

// Shared badge palette for both the Signal Log and the RS table's Signal column,
// so the two can't drift apart. BUY/AVOID are common to both; ALERT/INFO are
// signal-log only; NEUTRAL is the RS-table resting state.
const SIGNAL_BADGE_STYLES = {
  BUY:     { background:'#0d3320', color:'#10b981' },
  AVOID:   { background:'#2a0d0d', color:'#ef4444' },
  ALERT:   { background:'#1a1400', color:'#f59e0b' },
  INFO:    { background:'#0d1a2a', color:'#60a5fa' },
  NEUTRAL: { background:'#1a1a1a', color:'#555' },
};

function SignalBadge({ type }) {
  const style = SIGNAL_BADGE_STYLES[type] || SIGNAL_BADGE_STYLES.INFO;
  return (
    <span style={{ ...style, padding:'2px 7px', borderRadius:2, fontSize:9, fontFamily:'monospace', whiteSpace:'nowrap', fontWeight:700 }}>
      {type}
    </span>
  );
}

function SignalLog({ signals }) {
  // Signals are a snapshot of current conditions (all computed on the same read),
  // not a time-ordered history — so we label them as current and don't show a
  // per-row timestamp (which would be identical on every row).
  return (
    <div>
      <div style={{ color:'#9aa7b5', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 }}>
        {signals.length} current signal{signals.length !== 1 ? 's' : ''}
      </div>
      {signals.length === 0 && (
        <div style={{ color:'#64748b', fontSize:12, padding:'24px 0', textAlign:'center' }}>
          No signals triggered yet. Check back after market open.
        </div>
      )}
      {signals.map((s, i) => (
        <div key={`${s.type}-${s.message}-${i}`} style={{ display:'flex', gap:12, alignItems:'flex-start', borderBottom:'1px solid #141414', padding:'10px 0', fontFamily:'monospace' }}>
          <SignalBadge type={s.type} />
          <span style={{ color:'#e5e5e5', fontSize:11 }}>{s.message}</span>
        </div>
      ))}
    </div>
  );
}

function SectorHeatmap({ sectors, isMobile }) {
  if (!sectors?.length) return null;
  // Top 4 and bottom 4 by RS rank are highlighted; the bottom band is derived
  // from the sector count so it stays correct if SECTOR_TICKERS gains/loses one.
  const n = sectors.length;
  const bottomFrom = n - 3; // rank at which the bottom-4 band begins
  return (
    <div style={{ display:'grid', gridTemplateColumns: isMobile ? 'repeat(2,1fr)' : 'repeat(3,1fr)', gap:6 }}>
      {sectors.map(s => {
        const rank = s.rank;
        const isTop = rank <= 4;
        const isBottom = rank >= bottomFrom;
        const bg    = isTop ? `rgba(16,185,129,${0.08 + (4-rank)*0.04})` : isBottom ? `rgba(239,68,68,${0.05 + (rank-bottomFrom)*0.03})` : '#101010';
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
  return (
    <>
    <table style={{ width:'100%', minWidth:460, borderCollapse:'collapse', fontSize:11, fontFamily:'monospace' }}>
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
            <td style={{ padding:'6px 10px', color:'#94a3b8', textAlign:'right' }}>#{s.rank}</td>
            <td style={{ padding:'6px 10px', color:'#e5e5e5' }}>{s.sector}</td>
            <td style={{ padding:'6px 10px', color: s.rs_score>1 ? '#10b981' : '#ef4444', textAlign:'right' }}>{s.rs_score?.toFixed(2) ?? '—'}</td>
            <td style={{ padding:'6px 10px', color: s.trend==='rising' ? '#10b981' : s.trend==='falling' ? '#ef4444' : '#555' }}>
              {s.trend==='rising' ? '↑ Rising' : s.trend==='falling' ? '↓ Falling' : '—'}
            </td>
            <td style={{ padding:'6px 10px', color:'#94a3b8', textAlign:'right' }}>
              {s.breadth != null ? `${(s.breadth*100).toFixed(0)}%` : '—'}
            </td>
            <td style={{ padding:'6px 10px' }}><SignalBadge type={s.signal} /></td>
          </tr>
        ))}
      </tbody>
    </table>
    <div style={{ color:'#64748b', fontSize:9, fontFamily:'monospace', marginTop:8, lineHeight:1.5 }}>
      RS Score = the basket's return over the past 3 months (63 trading days) relative to the All-Share; &gt;1 means it outperformed.<br/>
      Breadth = % of each sector's basket trading above its 50-day MA, measured over the curated sector baskets (not the full FTSE 100).
    </div>
    </>
  );
}

export default function RotationTab({ refreshKey }) {
  const [rotation, setRotation] = useState([]);
  const [signals, setSignals]   = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(false);
  const isMobile = useIsMobile();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    Promise.all([
      fetch(`${API}/market/rotation`).then(r=>r.json()),
      fetch(`${API}/market/signals`).then(r=>r.json()),
    ]).then(([rot, sig]) => {
      if (cancelled) return;
      setRotation(Array.isArray(rot) ? rot : []);
      setSignals(Array.isArray(sig) ? sig : []);
      setLoading(false);
    }).catch(() => {
      if (cancelled) return;
      setError(true);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [refreshKey]);

  const card = { background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 };
  const title = { color:'#9aa7b5', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 };

  // Only blank the page on the very first load; later refreshes swap data in
  // underneath the existing view rather than flashing the whole tab.
  if (loading && !rotation.length) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading rotation data…</div>;
  if (error && !rotation.length) return <div style={{ color:'#ef4444', padding:32, fontFamily:'monospace' }}>Couldn’t load rotation data. Try refreshing.</div>;

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Sector Rotation</h2>
      <div style={{ display:'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap:16, marginBottom:16 }}>
        <div style={card}>
          <div style={title}>Sector Heatmap — RS Rank</div>
          <SectorHeatmap sectors={rotation} isMobile={isMobile} />
        </div>
        <div style={card}>
          <div style={title}>Signal Log</div>
          <SignalLog signals={signals} />
        </div>
      </div>
      <div style={card}>
        <div style={title}>RS Ranking Table</div>
        <div style={{ overflowX:'auto' }}>
          <RSTable sectors={rotation} />
        </div>
      </div>
    </div>
  );
}
