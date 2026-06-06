import { useState, useEffect } from 'react';
import { API } from '../utils';
import { useIsMobile } from '../useMediaQuery';

function fgColor(score) {
  if (score >= 75) return '#10b981';
  if (score >= 55) return '#f59e0b';
  if (score >= 45) return '#666';
  if (score >= 25) return '#f97316';
  return '#ef4444';
}

// Per-component explanations: how each gauge is calculated and what it tells us.
const COMPONENT_INFO = {
  momentum: {
    how: 'Measures how far the FTSE 100 is trading above or below its 125-day (≈6-month) moving average. A zero gap (price sitting on its average) scores 50; the score rises as price pulls above the average and falls as it drops below, scaled by how volatile that gap typically is.',
    means: 'When the index trades above its medium-term trend, momentum and risk appetite are positive — a greed signal. When it slips below, price is breaking trend, which tends to accompany fear and pullbacks.',
  },
  breadth: {
    how: 'Counts the share of FTSE 100 stocks trading above their own 50-day moving average. That percentage is the score directly: 50% (half the market above trend) is neutral, higher is greed, lower is fear.',
    means: 'High breadth signals a broad, healthy advance where most stocks participate — greed. Low breadth warns that gains are narrow or that selling is widespread beneath the surface, a classic fear signal even when the headline index looks calm.',
  },
  vix: {
    how: 'Takes the VIX — expected 30-day volatility implied by S&P 500 option prices — and inverts it onto a 0–100 scale relative to its one-year range. Higher VIX produces a lower score. The VIX is US-derived, used here as a global risk-appetite proxy (it tracks the UK’s VFTSE index very closely) because no free UK implied-volatility index is available; UK-specific volatility is captured separately by the Realised Vol gauge below.',
    means: 'The VIX is the original "fear gauge". A low score here means investors are paying up for crash protection (fear); a high score means options are cheap and complacency/greed prevails. Because global equity risk moves in lockstep, it remains a meaningful read on the mood facing UK investors.',
  },
  safe_haven: {
    how: 'Compares the 20-day total return of the FTSE 100 against a UK gilt ETF (all-maturity gilts). A zero spread — stocks and bonds neck-and-neck — scores 50; stocks pulling ahead lifts the score, gilts winning pulls it down, scaled by how much the spread normally swings.',
    means: 'When stocks outpace safe government bonds, money is chasing risk — greed. When gilts win, investors are rotating into safety — fear. It captures the tug-of-war between risk-on and risk-off positioning.',
  },
  realised_vol: {
    how: 'Calculates the actual (realised) 20-day volatility of FTSE 100 daily returns, annualised, then inverts it onto a 0–100 scale. Calm markets score high; turbulent markets score low.',
    means: 'Unlike the VIX, which is forward-looking, this measures volatility that has already happened. Big daily swings drag the score down and reflect genuine stress; quiet, drifting markets push it toward greed.',
  },
  hl_ratio: {
    how: 'Counts how many FTSE 100 stocks are within 1% of a fresh 52-week high versus a 52-week low, and takes the net difference as a share of the universe. Equal highs and lows scores 50; a net ±25% of the index at new highs or lows reaches the extreme greed or fear bands.',
    means: 'A surplus of new highs over new lows shows leadership and conviction — greed. A surge of new lows points to a deteriorating market where damage is spreading, a strong fear signal.',
  },
};

export default function FearGreedTab({ refreshKey }) {
  const [fg, setFg]         = useState(null);
  const [loading, setLoading] = useState(true);
  const isMobile = useIsMobile();

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
        <div style={{ color:'#9aa7b5', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 }}>
          UK Fear &amp; Greed Index
        </div>

        {/* Score + sentiment */}
        <div style={{ display:'flex', alignItems:'flex-end', gap:16, marginBottom:10 }}>
          <div>
            <span style={{ color, fontSize:48, fontWeight:700, fontFamily:'monospace', lineHeight:1 }}>{fg.score}</span>
            <span style={{ color, fontSize:16, fontWeight:700, marginLeft:12 }}>{fg.sentiment?.toUpperCase()}</span>
          </div>
          <div style={{ color:'#94a3b8', fontSize:11, paddingBottom:6 }}>
            Trend: <span style={{ color: fg.trend === 'rising' ? '#10b981' : fg.trend === 'falling' ? '#ef4444' : '#666' }}>
              {fg.trend === 'rising' ? '↑ Rising' : fg.trend === 'falling' ? '↓ Falling' : '—'}
            </span>
            {fg.suggested_phase && fg.suggested_phase !== 'no_change' && (
              <> &nbsp;|&nbsp; Auto-phase: <span style={{ color }}>{fg.suggested_phase}</span>
              &nbsp;|&nbsp; Confirmed: <span style={{ color: fg.confirmed ? '#10b981' : '#94a3b8' }}>
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

        {/* Component breakdown — stacked vertically, each box paired with an explanation */}
        <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
          {COMPONENT_ORDER.map(key => {
            const c = fg.components?.[key];
            if (!c) return null;
            const cc = fgColor(c.score);
            const info = COMPONENT_INFO[key] || {};
            const band = c.score >= 75 ? 'Ext. Greed' : c.score >= 55 ? 'Greed' : c.score >= 45 ? 'Neutral' : c.score >= 25 ? 'Fear' : 'Ext. Fear';
            return (
              <div
                key={key}
                style={{
                  display:'flex',
                  flexDirection: isMobile ? 'column' : 'row',
                  gap: isMobile ? 10 : 16,
                  background:'#141414',
                  border:'1px solid #2a2a2a',
                  borderRadius:3,
                  padding: isMobile ? 14 : 16,
                  alignItems: isMobile ? 'stretch' : 'flex-start',
                }}
              >
                {/* Metric box */}
                <div style={{ flexShrink:0, width: isMobile ? 'auto' : 150 }}>
                  <div style={{ color:'#94a3b8', fontSize:10, textTransform:'uppercase', letterSpacing:'0.5px', marginBottom:8 }}>{c.label}</div>
                  <div style={{ display:'flex', alignItems:'baseline', gap:8 }}>
                    <span style={{ color:cc, fontSize:28, fontWeight:700, fontFamily:'monospace', lineHeight:1 }}>{c.score}</span>
                    <span style={{ color:cc, fontSize:10, fontWeight:700 }}>{band}</span>
                  </div>
                  <div style={{ background:'#1a1a1a', borderRadius:2, height:5, margin:'8px 0 0' }}>
                    <div style={{ background:cc, width:`${c.score}%`, height:5, borderRadius:2 }}/>
                  </div>
                </div>

                {/* Explanation */}
                <div style={{ flex:1, fontSize:12, lineHeight:1.6, color:'#9aa7b5' }}>
                  <div style={{ marginBottom:8 }}>
                    <span style={{ color:'#cbd5e1', fontWeight:700, fontSize:10, textTransform:'uppercase', letterSpacing:'0.5px' }}>How it’s calculated&nbsp;</span>
                    {info.how}
                  </div>
                  <div>
                    <span style={{ color:'#cbd5e1', fontWeight:700, fontSize:10, textTransform:'uppercase', letterSpacing:'0.5px' }}>What it tells us&nbsp;</span>
                    {info.means}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
