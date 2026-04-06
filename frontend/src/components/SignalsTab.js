import { useState, useEffect } from 'react';
import { API } from '../utils';

const BADGE_STYLES = {
  BUY:   { background:'#0d3320', color:'#10b981' },
  AVOID: { background:'#2a0d0d', color:'#ef4444' },
  ALERT: { background:'#1a1400', color:'#f59e0b' },
  INFO:  { background:'#0d1a2a', color:'#60a5fa' },
};

function SignalBadge({ type }) {
  const style = BADGE_STYLES[type] || BADGE_STYLES.INFO;
  return (
    <span style={{ ...style, padding:'2px 7px', borderRadius:2, fontSize:9, fontFamily:'monospace', whiteSpace:'nowrap', fontWeight:700 }}>
      {type}
    </span>
  );
}

export default function SignalsTab({ refreshKey }) {
  const [signals, setSignals]   = useState([]);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/market/signals`)
      .then(r => r.json())
      .then(d => { setSignals(Array.isArray(d) ? d : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading signals…</div>;

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Signal Log</h2>
      <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 }}>
        <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 }}>
          {signals.length} signal{signals.length !== 1 ? 's' : ''} — newest first
        </div>
        {signals.length === 0 && (
          <div style={{ color:'#333', fontSize:12, padding:'24px 0', textAlign:'center' }}>
            No signals triggered yet. Check back after market open.
          </div>
        )}
        {signals.map((s, i) => (
          <div key={i} style={{ display:'flex', gap:12, alignItems:'flex-start', borderBottom:'1px solid #141414', padding:'10px 0', fontFamily:'monospace' }}>
            <span style={{ color:'#444', fontSize:9, whiteSpace:'nowrap', marginTop:2 }}>{s.timestamp}</span>
            <SignalBadge type={s.type} />
            <span style={{ color:'#e5e5e5', fontSize:11 }}>{s.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
