"use client";
import { useState, useEffect, Fragment } from 'react';
import { API } from "@/lib/api";
import { useIsMobile } from "@/hooks/useMediaQuery";
import InfoDot from "@/components/InfoDot";

// Shared badge palette for both the Signal Log and the RS table's Signal column,
// so the two can't drift apart. BUY/AVOID are common to both; ALERT/INFO are
// signal-log only; NEUTRAL is the RS-table resting state.
const SIGNAL_BADGE_STYLES = {
  BUY:     { background:'#0d3320', color:'#16d96b' },
  AVOID:   { background:'#2a0d0d', color:'#ff2e3f' },
  ALERT:   { background:'#1a1400', color:'#ff7a14' },
  INFO:    { background:'#0d1a2a', color:'#60a5fa' },
  NEUTRAL: { background:'#1a1a1a', color:'#555' },
};

function SignalBadge({ type, block = false }) {
  const style = SIGNAL_BADGE_STYLES[type] || SIGNAL_BADGE_STYLES.INFO;
  // `block` makes the pill fill (and centre within) a fixed grid column so a
  // stack of badges lines up as a tidy vertical column; inline is the default.
  return (
    <span style={{ ...style, padding:'2px 7px', borderRadius:2, fontSize:9, fontFamily:'monospace', whiteSpace:'nowrap', fontWeight:700, textAlign:'center', ...(block ? { display:'block', boxSizing:'border-box' } : {}) }}>
      {type}
    </span>
  );
}

// Split a signal message into a left-hand label (the sector, or the headline for
// non-sector alerts) and a short descriptor, dropping the noisy "RS 1.08 rising"
// middle so the log reads as clean columns rather than one long sentence.
//   "Technology RS 1.08 rising — momentum breakout" → { label:'Technology', detail:'momentum breakout' }
//   "Breadth at 67% — bearish threshold crossed"    → { label:'Breadth at 67%', detail:'bearish threshold crossed' }
function parseSignal(message = '') {
  const rs = message.match(/^(.+?) RS [\d.]+ (?:rising|falling) — (.+)$/);
  if (rs) return { label: rs[1], detail: rs[2] };
  const dash = message.match(/^(.+?) — (.+)$/);
  if (dash) return { label: dash[1], detail: dash[2] };
  return { label: message, detail: '' };
}

function SignalLog({ signals }) {
  // Signals are a snapshot of current conditions (all computed on the same read),
  // not a time-ordered history — so we label them as current and don't show a
  // per-row timestamp (which would be identical on every row).
  // One shared grid (not a grid per row) so the badge / sector / descriptor
  // columns lock to common track widths and line up down the whole log.
  const cell = { borderBottom:'1px solid #141414', padding:'10px 0', fontFamily:'monospace', fontSize:11 };
  return (
    <div>
      {signals.length === 0 ? (
        <div style={{ color:'#64748b', fontSize:12, padding:'24px 0', textAlign:'center' }}>
          No signals triggered yet. Check back after market open.
        </div>
      ) : (
        <div style={{ display:'grid', gridTemplateColumns:'58px max-content 1fr', columnGap:12, alignItems:'center' }}>
          {signals.map((s, i) => {
            const { label, detail } = parseSignal(s.message);
            return (
              <Fragment key={`${s.type}-${s.message}-${i}`}>
                <div style={cell}><SignalBadge type={s.type} block /></div>
                <div style={{ ...cell, color:'#e5e5e5', whiteSpace:'nowrap' }}>{label}</div>
                <div style={{ ...cell, color:'#64748b', minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{detail}</div>
              </Fragment>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Continuous green↔red heat from RS score: 1.0 (in line with the market) is the
// neutral centre, and deviations of ±0.15 saturate the tile. This reads as a
// true heatmap rather than the old discrete top-4/bottom-4 bands.
function rsHeat(rs) {
  if (rs == null) return { bg: '#101010', accent: '#94a3b8' };
  const t = Math.max(-1, Math.min(1, (rs - 1) / 0.15)); // -1..1
  // Green #16d96b / red #ff2e3f — the shared F&G + Breadth dial palette.
  return t >= 0
    ? { bg: `rgba(22,217,107,${0.05 + t * 0.30})`, accent: '#16d96b' }
    : { bg: `rgba(255,46,63,${0.05 + -t * 0.30})`, accent: '#ff2e3f' };
}

function SectorHeatmap({ sectors, isMobile }) {
  if (!sectors?.length) return null;
  // Sectors arrive pre-sorted by RS rank, so the strongest naturally lead.
  return (
    <div style={{ display:'grid', gridTemplateColumns: isMobile ? 'repeat(2,1fr)' : 'repeat(3,1fr)', gap:8 }}>
      {sectors.map(s => {
        const { bg, accent } = rsHeat(s.rs_score);
        const arrow = s.trend === 'rising' ? '↑' : s.trend === 'falling' ? '↓' : '';
        return (
          <div key={s.sector} style={{ position:'relative', background:bg, border:'1px solid rgba(255,255,255,0.06)', borderRadius:6, padding:'10px 11px 9px 13px', overflow:'hidden' }}>
            {/* left accent rail keyed to the sector's strength */}
            <div style={{ position:'absolute', left:0, top:0, bottom:0, width:3, background:accent }} />
            <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', gap:6 }}>
              <span style={{ color:'#e5e5e5', fontSize:11, fontWeight:600, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{s.sector}</span>
              {arrow && <span style={{ color:accent, fontSize:11, lineHeight:1 }}>{arrow}</span>}
            </div>
            <div style={{ display:'flex', alignItems:'baseline', gap:5, marginTop:7 }}>
              <span style={{ color:accent, fontSize:12, fontWeight:700, fontFamily:'monospace', lineHeight:1 }}>{s.rs_score?.toFixed(2) ?? '—'}</span>
              <span style={{ color:'#64748b', fontSize:8, fontWeight:700, letterSpacing:0.8 }}>RS</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RSTable({ sectors }) {
  if (!sectors?.length) return null;
  return (
    <table style={{ width:'100%', minWidth:460, borderCollapse:'collapse', fontSize:11, fontFamily:'monospace', tableLayout:'fixed' }}>
      <thead>
        <tr style={{ borderBottom:'1px solid #2a2a2a' }}>
          {['Rank','Sector','RS Score','Trend','Breadth','Signal'].map(h => (
            <th key={h} style={{ padding:'6px 10px', color:'#f97316', fontSize:9, textTransform:'uppercase', letterSpacing:0.5, textAlign:'center' }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sectors.map(s => (
          <tr key={s.sector} style={{ borderBottom:'1px solid #141414' }}>
            <td style={{ padding:'6px 10px', color:'#94a3b8', textAlign:'center' }}>#{s.rank}</td>
            <td style={{ padding:'6px 10px', color:'#e5e5e5', textAlign:'left' }}>{s.sector}</td>
            <td style={{ padding:'6px 10px', color: s.rs_score>1 ? '#16d96b' : '#ff2e3f', textAlign:'center' }}>{s.rs_score?.toFixed(2) ?? '—'}</td>
            <td style={{ padding:'6px 10px', color: s.trend==='rising' ? '#16d96b' : s.trend==='falling' ? '#ff2e3f' : '#555', textAlign:'center' }}>
              {s.trend==='rising' ? '↑ Rising' : s.trend==='falling' ? '↓ Falling' : '—'}
            </td>
            <td style={{ padding:'6px 10px', color:'#94a3b8', textAlign:'center' }}>
              {s.breadth != null ? `${(s.breadth*100).toFixed(0)}%` : '—'}
            </td>
            <td style={{ padding:'6px 10px', textAlign:'center' }}><SignalBadge type={s.signal} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function RotationTab({ refreshKey }) {
  const [rotation, setRotation] = useState([]);
  const [signals, setSignals]   = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(false);
  const [showTable, setShowTable] = useState(false); // RS table collapsed by default
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
  if (error && !rotation.length) return <div style={{ color:'#ff2e3f', padding:32, fontFamily:'monospace' }}>Couldn’t load rotation data. Try refreshing.</div>;

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, fontWeight:700, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Sector Rotation</h2>
      <div style={{ display:'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap:16, marginBottom:16 }}>
        <div style={card}>
          <div style={{ ...title, display:'flex', alignItems:'center', gap:6 }}>
            Sector Heatmap — RS Rank
            <InfoDot text="Sectors ranked by relative strength (RS) — each basket's 3-month return versus the FTSE All-Share, ordered strongest first. Greener tiles outperform the market (RS above 1); redder tiles lag it. ↑/↓ marks whether RS is rising or falling." />
          </div>
          <SectorHeatmap sectors={rotation} isMobile={isMobile} />
        </div>
        <div style={card}>
          <div style={{ ...title, display:'flex', alignItems:'center', gap:6 }}>
            <span>Signal Log<span style={{ color:'#64748b' }}> — {signals.length} current signal{signals.length !== 1 ? 's' : ''}</span></span>
            <InfoDot text={"A snapshot of today's notable sector conditions (computed on one read, not a time-ordered history).\n\nBUY — sector RS above 1.05 and rising vs 10 days ago (outperforming and strengthening).\nAVOID — RS below 0.95 and falling (underperforming and weakening).\nALERT — overall FTSE 100 breadth crossed a threshold (>65% bullish, <40% bearish).\nNEUTRAL — no active signal."} />
          </div>
          <SignalLog signals={signals} />
        </div>
      </div>
      <div style={card}>
        <div style={{ ...title, display:'flex', alignItems:'center', gap:6, marginBottom: showTable ? 12 : 0 }}>
          <span
            onClick={() => setShowTable(s => !s)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setShowTable(s => !s); } }}
            style={{ display:'flex', alignItems:'center', gap:6, cursor:'pointer', userSelect:'none' }}
          >
            <span style={{ color:'#64748b' }}>{showTable ? '▾' : '▸'}</span>
            RS Ranking Table
          </span>
          <InfoDot text={"RS Score — the sector basket's return over the past 3 months (63 trading days) relative to the All-Share; above 1 means it outperformed.\nTrend — whether RS is rising or falling versus 10 trading days ago.\nBreadth — % of the sector's basket trading above its 50-day MA (curated baskets, not the full FTSE 100).\nSignal — BUY (RS >1.05 & rising), AVOID (RS <0.95 & falling), or NEUTRAL."} />
        </div>
        {showTable && (
          <div style={{ overflowX:'auto' }}>
            <RSTable sectors={rotation} />
          </div>
        )}
      </div>
    </div>
  );
}
