import { useState, useEffect } from 'react';
import { API, pctColor } from '../utils';

// ── London Stock Exchange trading clock ──────────────────────────────────────
// Regular hours: 08:00–16:30 London, Mon–Fri, excluding England & Wales bank
// holidays (the LSE follows the E&W calendar). Christmas Eve and New Year's Eve
// are half-days with an early 12:30 close when they fall on a weekday.
//
// Holiday/half-day dates are hardcoded and must be refreshed annually from
// gov.uk/bank-holidays (england-and-wales).
const UK_HOLIDAYS = new Set([
  // 2026
  '2026-01-01', '2026-04-03', '2026-04-06', '2026-05-04', '2026-05-25',
  '2026-08-31', '2026-12-25', '2026-12-28',
  // 2027
  '2027-01-01', '2027-03-26', '2027-03-29', '2027-05-03', '2027-05-31',
  '2027-08-30', '2027-12-27', '2027-12-28',
]);
const UK_HALF_DAYS = new Set([
  '2026-12-24', '2026-12-31',
  '2027-12-24', '2027-12-31',
]);

const LSE_OPEN_SEC = 8 * 3600;             // 08:00
const LSE_CLOSE_SEC = 16 * 3600 + 30 * 60; // 16:30
const LSE_HALF_CLOSE_SEC = 12 * 3600 + 30 * 60; // 12:30 (half-days)
const WEEKDAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// Current wall-clock in Europe/London, regardless of the viewer's own timezone.
function londonParts(date = new Date()) {
  const fmt = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false, weekday: 'short',
  });
  const p = {};
  for (const part of fmt.formatToParts(date)) p[part.type] = part.value;
  return p;
}

function isLseTradingDay(iso, weekday) {
  if (weekday === 'Sat' || weekday === 'Sun') return false;
  return !UK_HOLIDAYS.has(iso);
}

// Walk forward from a London calendar date to the label of the next trading day's
// open (e.g. "Opens Mon 08:00"). Steps on a noon-UTC Date so date-only arithmetic
// stays clear of any DST boundary.
function nextOpenLabel(year, month, day) {
  const d = new Date(Date.UTC(year, month - 1, day, 12));
  for (let i = 0; i < 14; i++) {
    d.setUTCDate(d.getUTCDate() + 1);
    const wd = d.getUTCDay();
    const iso = d.toISOString().slice(0, 10);
    if (wd !== 0 && wd !== 6 && !UK_HOLIDAYS.has(iso)) {
      return `Opens ${WEEKDAY_NAMES[wd]} 08:00`;
    }
  }
  return 'Closed';
}

function lseStatus() {
  const p = londonParts();
  let hour = parseInt(p.hour, 10);
  if (hour === 24) hour = 0; // some engines emit "24" at midnight
  const secNow = hour * 3600 + parseInt(p.minute, 10) * 60 + parseInt(p.second, 10);
  const iso = `${p.year}-${p.month}-${p.day}`;
  const trading = isLseTradingDay(iso, p.weekday);
  const closeSec = UK_HALF_DAYS.has(iso) ? LSE_HALF_CLOSE_SEC : LSE_CLOSE_SEC;

  if (trading && secNow >= LSE_OPEN_SEC && secNow < closeSec) {
    return { open: true, secondsToClose: closeSec - secNow };
  }
  if (trading && secNow < LSE_OPEN_SEC) {
    return { open: false, nextOpen: 'Opens today 08:00' };
  }
  return {
    open: false,
    nextOpen: nextOpenLabel(parseInt(p.year, 10), parseInt(p.month, 10), parseInt(p.day, 10)),
  };
}

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

export default function Sidebar({ refreshKey, onNavigate }) {
  const [data, setData] = useState(null);
  // Click-to-reveal: which companies make up each ICB sector basket.
  const [constituents, setConstituents] = useState(null); // { sector: [{symbol,name}] }
  const [expandedSector, setExpandedSector] = useState(null);
  // Auto-refresh tick: the benchmark/sector/VIX figures are live. The backend
  // re-pulls on a 15-minute cache, so poll every 5 minutes to surface a freshly
  // computed value within ~5 min of it landing, keeping an open tab current.
  const [autoTick, setAutoTick] = useState(0);
  // Per-second tick that drives the live LSE close countdown.
  const [, setClockTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setAutoTick(t => t + 1), 5 * 60 * 1000);
    return () => clearInterval(id);
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

  return (
    <aside style={{ width:185, flexShrink:0, background:'#0d0d0d', borderRight:'1px solid #1e1e1e', padding:'16px 12px', height:'calc(100vh - 52px)', position:'sticky', top:52, overflowY:'auto', scrollbarWidth:'none', msOverflowStyle:'none' }}>

      {/* Benchmarks */}
      <div style={labelStyle}>Benchmarks</div>
      {data?.benchmarks?.map(b => (
        <div key={b.name} style={rowStyle}>
          <span style={nameStyle}>{b.name}</span>
          <PctBadge value={b.pct_change} />
        </div>
      )) ?? <div style={{ color:'#333', fontSize:10 }}>Loading…</div>}

      {/* LSE market clock */}
      {(() => {
        const m = lseStatus();
        return (
          <div
            style={{ marginTop:8, paddingTop:8, borderTop:'1px solid #1e1e1e', display:'flex', justifyContent:'space-between', alignItems:'center' }}
            title="London Stock Exchange — 08:00–16:30, Mon–Fri, excl. UK bank holidays"
          >
            <span style={{ display:'flex', alignItems:'center', gap:5 }}>
              <span style={{ width:6, height:6, borderRadius:'50%', flexShrink:0, background: m.open ? '#10b981' : '#64748b', boxShadow: m.open ? '0 0 5px #10b981' : 'none' }} />
              <span style={{ color: m.open ? '#10b981' : '#64748b', fontSize:9.5, fontWeight:700, textTransform:'uppercase', letterSpacing:'0.5px' }}>
                {m.open ? 'Markets open' : 'Markets closed'}
              </span>
            </span>
            <span style={{ color:'#64748b', fontSize:9, fontFamily:'monospace' }}>
              {m.open ? `Closes in ${fmtCountdown(m.secondsToClose)}` : m.nextOpen}
            </span>
          </div>
        );
      })()}

      {/* UK Fear & Greed — sits directly under the market clock */}
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
        </div>
      )}

      {/* US indicators group — VIX and CNN Fear & Greed */}
      {((data?.vix !== undefined && data.vix !== null) ||
        (data?.cnn_fear_greed?.value !== null && data?.cnn_fear_greed?.value !== undefined)) && (
        <div style={{ marginTop:12, paddingTop:10, borderTop:'1px solid #1e1e1e' }}>
          {data?.vix !== undefined && data.vix !== null && (
            <div style={{ ...rowStyle, marginBottom:12 }}>
              <span style={nameStyle}>VIX</span>
              <span style={{
                fontFamily:'monospace', fontSize:10, fontWeight:700,
                color: data.vix < 20 ? '#10b981' : data.vix < 30 ? '#f59e0b' : '#ef4444'
              }}>
                {data.vix.toFixed(2)}
              </span>
            </div>
          )}
          {data?.cnn_fear_greed?.value !== null && data?.cnn_fear_greed?.value !== undefined && (
            <div>
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
        </div>
      )}

      {/* Sectors */}
      <div style={{ ...labelStyle, marginTop:16 }}>ICB Sectors</div>
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
              <span style={{ display:'flex', alignItems:'center', gap:3, maxWidth:120, overflow:'hidden' }}>
                <span style={{ color: isOpen ? '#94a3b8' : '#444', fontSize:7, flexShrink:0 }}>{isOpen ? '▾' : '▸'}</span>
                <span style={{ ...nameStyle, color: isOpen ? '#cbd5e1' : nameStyle.color, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{s.name}</span>
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

      {/* Heatmap link — sits at the foot of the sector list */}
      <div
        onClick={() => onNavigate && onNavigate('heatmap')}
        title="Open the market heatmap"
        style={{ color:'#f97316', cursor:'pointer', fontSize:12, letterSpacing:0.5, display:'flex', alignItems:'center', justifyContent:'center', gap:5, marginTop:16 }}
      >
        ▦ Heatmap
      </div>

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
