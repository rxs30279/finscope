"use client";
import { useState, useEffect } from 'react';
import { API } from "@/lib/api";
import { pctColor } from "@/lib/format";
import { lseStatus, nextOpenLabel } from "@/lib/lse";

function fmtCountdown(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`;
}

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

export default function Sidebar({ refreshKey, onNavigate, mobile = false }) {
  const [data, setData] = useState(null);
  // Click-to-reveal: which companies make up each ICB sector basket.
  const [constituents, setConstituents] = useState(null); // { sector: [{symbol,name}] }
  const [expandedSector, setExpandedSector] = useState(null);
  // Auto-refresh tick: the benchmark/sector/VIX figures are live. The backend
  // re-pulls on a fast market-hours cache (~2 min while the LSE is open), so poll
  // every 2 min during the session to surface freshly computed values, and back
  // off to 15 min once closed — prices are static until the next bell.
  const [autoTick, setAutoTick] = useState(0);
  // Per-second tick that drives the live LSE close countdown.
  const [, setClockTick] = useState(0);
  // The LSE clock is time-derived (live countdown), so the server-rendered value
  // and the client's first render differ by however long hydration took, tripping
  // a hydration mismatch. Gate the clock on a post-mount flag so it renders only
  // on the client, where the per-second tick keeps it current.
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    // Self-rescheduling timer that re-reads the LSE status each cycle, so the
    // cadence adapts as the market opens/closes without remounting: 2 min while
    // open, 15 min once closed. A hidden tab skips the bump (no fetch); returning
    // to the tab forces an immediate refresh via the visibility handler.
    let id;
    const schedule = () => {
      const delay = lseStatus().open ? 2 * 60 * 1000 : 15 * 60 * 1000;
      id = setTimeout(() => {
        if (!document.hidden) setAutoTick(t => t + 1);
        schedule();
      }, delay);
    };
    schedule();
    const onVisible = () => { if (!document.hidden) setAutoTick(t => t + 1); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearTimeout(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  useEffect(() => {
    const id = setInterval(() => setClockTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    fetch(`${API}/market/sidebar`)
      .then(r => r.json())
      .then(setData)
      .catch(() => {});
  }, [refreshKey, autoTick]);

  // Refetch constituent prices on every refresh cycle so the per-company
  // colours stay in step with the sector badges rather than the once-only,
  // state-cached copy from first expand.
  useEffect(() => {
    fetch(`${API}/sector-constituents`)
      .then(r => r.json())
      .then(d => setConstituents(d && typeof d === 'object' ? d : {}))
      .catch(() => setConstituents({}));
  }, [refreshKey, autoTick]);

  const toggleSector = (name) => {
    setExpandedSector(prev => (prev === name ? null : name));
  };

  const labelStyle = { color:'#94a3b8', fontSize:11, fontWeight:700, letterSpacing:'1.5px', textTransform:'uppercase', marginBottom:8 };
  const rowStyle   = { display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:4 };
  const nameStyle  = { color:'#94a3b8', fontSize:10 };

  // On mobile the sidebar is rendered inline inside the hamburger drawer, so it
  // drops the fixed width, sticky positioning and own-scroll/borders and just
  // flows with the menu content.
  const asideStyle = mobile
    ? { width:'100%', boxSizing:'border-box', background:'transparent', padding:'4px 20px 16px' }
    : { width:185, flexShrink:0, background:'#0d0d0d', borderRight:'1px solid #1e1e1e', padding:'16px 12px', height:'calc(100vh - 52px)', position:'sticky', top:52, overflowY:'auto', scrollbarWidth:'none', msOverflowStyle:'none' };

  return (
    <aside style={asideStyle}>

      {/* LSE market clock — sits at the very top of the sidebar */}
      {!mounted ? (
        // Placeholder before mount keeps the clock's space so the rest of the
        // sidebar doesn't jump when the live clock appears on the client.
        <div style={{ minHeight: 28 }} />
      ) : (() => {
        const m = lseStatus();
        return (
          <div
            style={{ display:'flex', flexDirection:'column', alignItems:'flex-start', gap:2 }}
            title="London Stock Exchange — 08:00–16:30, Mon–Fri, excl. UK bank holidays"
          >
            <span style={{ display:'flex', alignItems:'center', justifyContent:'space-between', gap:5, width:'100%' }}>
              <span style={{ display:'flex', alignItems:'center', gap:5 }}>
                <span style={{ width:6, height:6, borderRadius:'50%', flexShrink:0, background: m.open ? '#10b981' : '#64748b', boxShadow: m.open ? '0 0 5px #10b981' : 'none' }} />
                <span style={{ color: m.open ? '#10b981' : '#64748b', fontSize:9.5, fontWeight:700, textTransform:'uppercase', letterSpacing:'0.5px' }}>
                  {m.open ? 'Markets open' : 'Markets closed'}
                </span>
              </span>
              {m.open && (
                <span style={{ background:'#0d2318', color:'#10b981', padding:'1px 5px', borderRadius:2, fontSize:10, fontFamily:'monospace', position:'relative', top:1 }}>
                  {fmtCountdown(m.secondsToClose)}
                </span>
              )}
            </span>
            {!m.open && (
              <span style={{ marginLeft:11, color:'#64748b', fontSize:9, fontFamily:'monospace' }}>
                {m.nextOpen}
              </span>
            )}
          </div>
        );
      })()}

      {/* Benchmarks */}
      <div style={{ ...labelStyle, marginTop:12, paddingTop:10, borderTop:'1px solid #1e1e1e' }}>Benchmarks</div>
      {data?.benchmarks?.map(b => (
        <div key={b.name} style={rowStyle}>
          <span style={nameStyle}>{b.name}</span>
          <PctBadge value={b.pct_change} />
        </div>
      )) ?? <div style={{ color:'#333', fontSize:10 }}>Loading…</div>}

      {/* Sectors */}
      <div style={{ ...labelStyle, marginTop:16, paddingTop:10, borderTop:'1px solid #1e1e1e' }}>ICB Sectors</div>
      {data?.sectors?.map(s => {
        const isOpen = expandedSector === s.name;
        const members = constituents?.[s.name];
        return (
          <div key={s.name}>
            <div
              onClick={() => toggleSector(s.name)}
              style={{ ...rowStyle, cursor:'pointer' }}
              title="Show companies in this sector"
            >
              <span style={{ maxWidth:120, overflow:'hidden' }}>
                <span style={{ ...nameStyle, color: isOpen ? '#cbd5e1' : nameStyle.color, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', display:'block' }}>{s.name}</span>
              </span>
              <PctBadge value={s.pct_change} />
            </div>
            {isOpen && (
              <div style={{ margin:'2px 0 8px 10px', paddingLeft:6, borderLeft:'1px solid #1e1e1e' }}>
                {members === undefined ? (
                  <div style={{ color:'#333', fontSize:9 }}>Loading…</div>
                ) : members.length === 0 ? (
                  <div style={{ color:'#333', fontSize:9 }}>No data</div>
                ) : (
                  members.map(c => (
                    <div key={c.symbol} style={{ display:'flex', justifyContent:'space-between', gap:6, marginBottom:2 }}>
                      <span style={{ color:pctColor(c.pct_change), fontSize:9, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{c.name}</span>
                      <span style={{ color:'#475569', fontSize:9, fontFamily:'monospace', flexShrink:0 }}>{c.symbol.replace('.L','')}</span>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        );
      }) ?? <div style={{ color:'#333', fontSize:10 }}>Loading…</div>}

      {/* Heatmap link — sits at the bottom of the sector list */}
      <div
        onClick={() => onNavigate && onNavigate('heatmap')}
        title="Open the market heatmap"
        style={{ color:'#f97316', cursor:'pointer', fontSize:12, letterSpacing:0.5, display:'flex', alignItems:'center', justifyContent:'center', gap:5, marginTop:12, padding:'7px 10px', border:'1px solid #f9731633', borderRadius:4, background:'#f973160d', boxSizing:'border-box' }}
      >
        ▦ Heatmap
      </div>

      {/* UK Fear & Greed */}
      {data?.fear_greed && (
        <div
          onClick={() => onNavigate && onNavigate('markets')}
          title="Open the markets page"
          style={{ marginTop:16, paddingTop:10, borderTop:'1px solid #1e1e1e', cursor:'pointer' }}
        >
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
        </div>
      )}

      {/* US indicators group — VIX and CNN Fear & Greed */}
      {((data?.vix !== undefined && data.vix !== null) ||
        (data?.cnn_fear_greed?.value !== null && data?.cnn_fear_greed?.value !== undefined)) && (
        <div style={{ marginTop:12, paddingTop:10, borderTop:'1px solid #1e1e1e' }}>
          {data?.vix !== undefined && data.vix !== null && (
            <div
              onClick={() => onNavigate && onNavigate('markets')}
              title="Open the markets page"
              style={{ ...rowStyle, marginBottom:12, cursor:'pointer' }}
            >
              <span style={nameStyle}>VIX (US)</span>
              <span style={{
                fontFamily:'monospace', fontSize:10, fontWeight:700,
                color: data.vix < 20 ? '#10b981' : data.vix < 30 ? '#f59e0b' : '#ef4444'
              }}>
                {data.vix.toFixed(2)}
              </span>
            </div>
          )}
          {data?.cnn_fear_greed?.value !== null && data?.cnn_fear_greed?.value !== undefined && (
            <div
              onClick={() => onNavigate && onNavigate('markets')}
              title="Open the markets page"
              style={{ cursor:'pointer' }}
            >
              <div style={rowStyle}>
                <span style={nameStyle}>F&amp;G (US)</span>
                <span style={{ fontFamily:'monospace', fontSize:10, fontWeight:700, color: fgColor(data.cnn_fear_greed.value) }}>
                  {data.cnn_fear_greed.value.toFixed(2)}
                </span>
              </div>
              <div style={{ textAlign:'right', fontSize:8, fontWeight:400, color: fgColor(data.cnn_fear_greed.value), opacity:0.7, marginTop:-2 }}>
                {data.cnn_fear_greed.description}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Support / Feedback — subtle full-width links to the in-app meta pages */}
      <div style={{ marginTop:16, paddingTop:12, borderTop:'1px solid #1e1e1e', display:'flex', flexDirection:'column', gap:8 }}>
        <button
          onClick={() => onNavigate && onNavigate('donate')}
          title="Support Alpha Move AI"
          style={{
            display:'flex', alignItems:'center', justifyContent:'center', gap:6,
            width:'100%', boxSizing:'border-box', background:'none', cursor:'pointer',
            color:'#cbd5e1', fontSize:12, fontFamily:'monospace',
            letterSpacing:0.5, textDecoration:'none',
            border:'1px solid #2a2a2a', borderRadius:4, padding:'7px 10px',
          }}
        >
          <img src="https://storage.ko-fi.com/cdn/cup-border.png" alt="Ko-fi" style={{ height:12, width:18 }} />
          Support
        </button>
        <button
          onClick={() => onNavigate && onNavigate('feedback')}
          title="Send feedback"
          style={{
            display:'flex', alignItems:'center', justifyContent:'center', gap:6,
            width:'100%', boxSizing:'border-box', background:'none', cursor:'pointer',
            color:'#cbd5e1', fontSize:12, fontFamily:'monospace',
            letterSpacing:0.5, textDecoration:'none',
            border:'1px solid #2a2a2a', borderRadius:4, padding:'7px 10px',
          }}
        >
          ✉ Feedback
        </button>
      </div>
      <div style={{ height:24 }} />
    </aside>
  );
}
