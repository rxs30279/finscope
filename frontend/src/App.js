import { useState, useEffect, useCallback, useRef } from 'react';
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts';
import { API, fmt, gc, currSym, loadWatchlist, saveWatchlist, loadTargets, saveTargets } from './utils';
import Sidebar from './components/Sidebar';
import RotationTab from './components/RotationTab';
import BreadthTab from './components/BreadthTab';
import FearGreedTab from './components/FearGreedTab';
import CrossAssetTab from './components/CrossAssetTab';
import SignalsTab from './components/SignalsTab';
import AnalystTab from './components/AnalystTab';
import AnalystMonitorTab from './components/AnalystMonitorTab';
import RnsTab from './components/RnsTab';
import AnalyticsTab from './components/AnalyticsTab';
import NewsTab from './components/NewsTab';


function MetricCard({ label, value, color }) {
  return (
    <div style={{ background:'#141414', borderRadius:2, padding:'14px 18px', border:'1px solid #2a2a2a' }}>
      <div style={{ fontSize:10, color:'#666', marginBottom:6, textTransform:'uppercase', letterSpacing:1, fontFamily:'monospace' }}>{label}</div>
      <div style={{ fontSize:18, fontFamily:'monospace', fontWeight:700, color: color||'#e5e5e5' }}>{value}</div>
    </div>
  );
}

// ── Company Detail ────────────────────────────────────────────────────────────
function CompanyDetail({ symbol, onBack }) {
  const [meta, setMeta]       = useState(null);
  const [snap, setSnap]       = useState(null);
  const [annual, setAnnual]   = useState([]);
  const [quarterly, setQuarterly] = useState([]);
  const [tab, setTab]         = useState('chart');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const enc = encodeURIComponent(symbol);
    Promise.all([
      fetch(`${API}/company?symbol=${enc}`).then(r=>r.json()),
      fetch(`${API}/snapshot?symbol=${enc}`).then(r=>r.json()),
      fetch(`${API}/annual?symbol=${enc}`).then(r=>r.json()),
      fetch(`${API}/quarterly?symbol=${enc}`).then(r=>r.json()),
    ]).then(([m,s,a,q]) => {
      setMeta(m); setSnap(s);
      setAnnual(Array.isArray(a) ? a : []);
      setQuarterly(Array.isArray(q) ? q : []);
      setLoading(false);
    }).catch(()=>setLoading(false));
  }, [symbol]);

  if (loading) return <div style={S.loading}>Loading {symbol}…</div>;
  if (!snap)   return <div style={S.loading}>No data for {symbol}</div>;

  const fcur = meta?.financial_currency || 'GBP';
  const sym  = currSym(fcur);

  const annualChart = annual.map(r => ({
    year:           r.period_end_date?.slice(0,4),
    revenue:        r.revenue     ? r.revenue/1e9     : null,
    net_income:     r.net_income  ? r.net_income/1e9  : null,
    ebitda:         r.ebitda      ? r.ebitda/1e9      : null,
    fcf:            r.fcf         ? r.fcf/1e9         : null,
    gross_margin:   r.gross_margin    ? r.gross_margin*100    : null,
    op_margin:      r.operating_margin? r.operating_margin*100: null,
    net_margin:     r.net_income_margin? r.net_income_margin*100: null,
    roe:            r.roe  ? r.roe*100  : null,
    roic:           r.roic ? r.roic*100 : null,
    roa:            r.roa  ? r.roa*100  : null,
    eps:            r.eps_diluted,
    debt_eq:        r.debt_to_equity,
    curr_ratio:     r.current_ratio,
  }));

  const qChart = quarterly.slice(-8).map(r => ({
    q:          r.fiscal_quarter_key || r.period_end_date?.slice(0,7),
    revenue:    r.revenue   ? r.revenue/1e9   : null,
    net_income: r.net_income? r.net_income/1e9: null,
    eps:        r.eps_diluted,
  }));

  const tabs = ['chart','overview','financials','valuation','health','growth','analysts','news'];

  return (
    <div>
      <button onClick={onBack} style={S.backBtn}>← Back to Screener</button>

      {/* Header */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', flexWrap:'wrap', gap:16, marginBottom:28 }}>
        <div>
          <div style={{ display:'flex', alignItems:'center', gap:14, marginBottom:10 }}>
            <a
              href={`https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}`}
              target="_blank"
              rel="noopener noreferrer"
              title="View on Yahoo Finance"
              style={{ background:'#6366f1', color:'#fff', borderRadius:10, width:50, height:50, display:'flex', alignItems:'center', justifyContent:'center', fontFamily:'DM Serif Display,serif', fontSize:13, fontWeight:700, textDecoration:'none', cursor:'pointer' }}
            >
              {symbol.replace('.L','').slice(0,4)}
            </a>
            <div>
              <h1 style={{ margin:0, fontFamily:'DM Serif Display,serif', fontSize:26, color:'#f1f5f9' }}>{meta?.name || symbol}</h1>
              <div style={{ display:'flex', gap:6, marginTop:5, flexWrap:'wrap' }}>
                {[symbol, meta?.exchange, meta?.sector, meta?.country, meta?.ftse_index].filter(Boolean).map(t => (
                  <span key={t} style={S.badge}>{t}</span>
                ))}
              </div>
            </div>
          </div>
          {meta?.description && (
            <p style={{ color:'#94a3b8', fontSize:13, maxWidth:680, lineHeight:1.7, margin:0 }}>
              {meta.description.slice(0,300)}{meta.description.length>300?'…':''}
            </p>
          )}
        </div>
        <div style={{ textAlign:'right' }}>
          <div style={{ fontSize:30, fontFamily:'DM Serif Display,serif', color:'#f1f5f9' }}>{fmt(snap.market_cap,'currency',fcur)}</div>
          <div style={{ fontSize:12, color:'#64748b' }}>Market Cap</div>
          {snap.enterprise_value && <div style={{ fontSize:13, color:'#94a3b8', marginTop:2 }}>EV: {fmt(snap.enterprise_value,'currency',fcur)}</div>}
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display:'flex', gap:2, borderBottom:'1px solid #334155', marginBottom:24 }}>
        {tabs.map(t => (
          <button key={t} onClick={()=>setTab(t)} style={{ ...S.tab, ...(tab===t?S.tabActive:{}) }}>
            {t.charAt(0).toUpperCase()+t.slice(1)}
          </button>
        ))}
      </div>

      {/* CHART */}
      {tab==='chart' && (
        <div>
          <PriceChart symbol={symbol} />
        </div>
      )}

      {/* OVERVIEW */}
      {tab==='overview' && (
        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(155px,1fr))', gap:10 }}>
            <MetricCard label="Revenue"       value={fmt(snap.revenue,'currency',fcur)} />
            <MetricCard label="Net Income"    value={fmt(snap.net_income,'currency',fcur)} color={snap.net_income>0?'#10b981':'#ef4444'} />
            <MetricCard label="EBITDA"        value={fmt(snap.ebitda,'currency',fcur)} />
            <MetricCard label="Free Cash Flow"value={fmt(snap.fcf,'currency',fcur)} color={snap.fcf>0?'#10b981':'#ef4444'} />
            <MetricCard label="P/E"           value={fmt(snap.price_to_earnings,'ratio')} />
            <MetricCard label="P/B"           value={fmt(snap.price_to_book,'ratio')} />
            <MetricCard label="ROE"           value={fmt(snap.roe,'pct')} color={gc(snap.roe)} />
            <MetricCard label="ROIC"          value={fmt(snap.roic,'pct')} color={gc(snap.roic)} />
            <MetricCard label="Gross Margin"  value={fmt(snap.gross_margin,'pct')} />
            <MetricCard label="Net Margin"    value={fmt(snap.net_income_margin,'pct')} color={gc(snap.net_income_margin)} />
            <MetricCard label="Debt/Equity"   value={fmt(snap.debt_to_equity,'ratio')} color={snap.debt_to_equity>2?'#ef4444':'#e5e5e5'} />
            <MetricCard label="Current Ratio" value={fmt(snap.current_ratio,'ratio')} />
          </div>
          <div style={S.card}>
            <h3 style={S.cardTitle}>{`Revenue & Net Income (Annual ${sym}B)`}</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={annualChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
                <XAxis dataKey="year" tick={{ fontSize:11, fill:'#666', fontFamily:'monospace' }} />
                <YAxis tick={{ fontSize:11, fill:'#666', fontFamily:'monospace' }} />
                <Tooltip formatter={v=>sym+(v?.toFixed(2))+'B'} contentStyle={S.tooltip} />
                <Bar dataKey="revenue"    fill="#f97316" radius={[2,2,0,0]} name="Revenue" />
                <Bar dataKey="net_income" fill="#10b981" radius={[2,2,0,0]} name="Net Income" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* FINANCIALS */}
      {tab==='financials' && (
        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
          <div style={S.card}>
            <h3 style={S.cardTitle}>{`Revenue, EBITDA & FCF (Annual ${sym}B)`}</h3>
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={annualChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                <defs>
                  <linearGradient id="gR" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#6366f1" stopOpacity={0.3}/><stop offset="95%" stopColor="#6366f1" stopOpacity={0}/></linearGradient>
                  <linearGradient id="gE" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#10b981" stopOpacity={0.25}/><stop offset="95%" stopColor="#10b981" stopOpacity={0}/></linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                <XAxis dataKey="year" tick={{ fontSize:11 }} />
                <YAxis tick={{ fontSize:11 }} />
                <Tooltip formatter={v=>sym+(v?.toFixed(2))+'B'} contentStyle={S.tooltip} />
                <Area type="monotone" dataKey="revenue"    stroke="#6366f1" fill="url(#gR)" strokeWidth={2} name="Revenue" />
                <Area type="monotone" dataKey="ebitda"     stroke="#10b981" fill="url(#gE)" strokeWidth={2} name="EBITDA" />
                <Line type="monotone" dataKey="fcf"        stroke="#f59e0b" strokeWidth={2} dot={false} name="FCF" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20 }}>
            <div style={S.card}>
              <h3 style={S.cardTitle}>{`Quarterly Revenue (${sym}B)`}</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={qChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="q" tick={{ fontSize:10 }} />
                  <YAxis tick={{ fontSize:11 }} />
                  <Tooltip formatter={v=>sym+(v?.toFixed(2))+'B'} contentStyle={S.tooltip} />
                  <Bar dataKey="revenue" fill="#6366f1" radius={[4,4,0,0]} name="Revenue" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div style={S.card}>
              <h3 style={S.cardTitle}>EPS Diluted (Annual)</h3>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={annualChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="year" tick={{ fontSize:11 }} />
                  <YAxis tick={{ fontSize:11 }} />
                  <Tooltip formatter={v=>sym+(v?.toFixed(2))} contentStyle={S.tooltip} />
                  <ReferenceLine y={0} stroke="#334155" />
                  <Line type="monotone" dataKey="eps" stroke="#6366f1" strokeWidth={2.5} dot={{ r:4, fill:'#6366f1' }} name="EPS" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div style={S.card}>
            <h3 style={S.cardTitle}>{`Income Statement (${sym}B)`}</h3>
            <div style={{ overflowX:'auto' }}>
              <table style={S.table}>
                <thead>
                  <tr>
                    <th style={S.th}>Metric</th>
                    {annual.slice(-5).map(r=><th key={r.period_end_date} style={{ ...S.th, textAlign:'right' }}>{r.period_end_date?.slice(0,4)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {[['Revenue','revenue'],['Gross Profit','gross_profit'],['Operating Income','operating_income'],['EBITDA','ebitda'],['Net Income','net_income'],['FCF','fcf']].map(([l,k])=>(
                    <tr key={k} style={{ borderBottom:'1px solid #334155' }}>
                      <td style={S.td}>{l}</td>
                      {annual.slice(-5).map(r=>(
                        <td key={r.period_end_date} style={{ ...S.tdNum, color: r[k]<0?'#ef4444':'#ccc' }}>
                          {r[k] ? sym+(r[k]/1e9).toFixed(2)+'B' : '—'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* VALUATION */}
      {tab==='valuation' && (
        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(145px,1fr))', gap:10 }}>
            {[['P/E',snap.price_to_earnings,'ratio'],['P/B',snap.price_to_book,'ratio'],['P/S',snap.price_to_sales,'ratio'],
              ['EV/EBITDA',snap.ev_to_ebitda,'ratio'],['EV/Sales',snap.ev_to_sales,'ratio'],
              ['ROE',snap.roe,'pct'],['ROIC',snap.roic,'pct'],['ROCE',snap.roce,'pct']
            ].map(([l,v,t])=><MetricCard key={l} label={l} value={fmt(v,t)} />)}
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20 }}>
            <div style={S.card}>
              <h3 style={S.cardTitle}>EPS History</h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={annualChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="year" tick={{ fontSize:11 }} />
                  <YAxis tick={{ fontSize:11 }} />
                  <Tooltip contentStyle={S.tooltip} />
                  <ReferenceLine y={0} stroke="#334155" />
                  <Line type="monotone" dataKey="eps" stroke="#6366f1" strokeWidth={2.5} dot={{ r:3 }} name="EPS" />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div style={S.card}>
              <h3 style={S.cardTitle}>Return on Capital (%)</h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={annualChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="year" tick={{ fontSize:11 }} />
                  <YAxis tick={{ fontSize:11 }} unit="%" />
                  <Tooltip formatter={v=>`${v?.toFixed(1)}%`} contentStyle={S.tooltip} />
                  <ReferenceLine y={0} stroke="#334155" />
                  <Line type="monotone" dataKey="roe"  stroke="#6366f1" strokeWidth={2} dot={false} name="ROE" />
                  <Line type="monotone" dataKey="roic" stroke="#10b981" strokeWidth={2} dot={false} name="ROIC" />
                  <Line type="monotone" dataKey="roa"  stroke="#f59e0b" strokeWidth={2} dot={false} name="ROA" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* HEALTH */}
      {tab==='health' && (
        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
          {/* Risk Score card */}
          <div style={{ background:'#141414', borderRadius:2, padding:'18px 22px', border:'1px solid #2a2a2a', display:'flex', alignItems:'center', gap:24 }}>
            <div>
              <div style={{ fontSize:10, color:'#666', marginBottom:8, textTransform:'uppercase', letterSpacing:1, fontFamily:'monospace' }}>Risk Score</div>
              {snap.risk_score == null ? (
                <span style={{ fontSize:28, fontFamily:'monospace', fontWeight:700, color:'#444' }}>—</span>
              ) : (
                <span style={{
                  display: 'inline-block',
                  padding: '4px 14px',
                  borderRadius: 6,
                  fontSize: 28,
                  fontFamily: 'monospace',
                  fontWeight: 700,
                  background: snap.risk_score <= 3 ? '#14532d'
                            : snap.risk_score <= 6 ? '#78350f'
                            :                       '#7f1d1d',
                  color:      snap.risk_score <= 3 ? '#4ade80'
                            : snap.risk_score <= 6 ? '#fbbf24'
                            :                       '#f87171',
                }}>{snap.risk_score}</span>
              )}
            </div>
            <div style={{ display:'flex', flexDirection:'column', gap:6, color:'#888', fontSize:12, fontFamily:'monospace' }}>
              <span>Altman Z: {snap.altman_z != null ? snap.altman_z.toFixed(2) : '—'}</span>
              <span>Volatility: {snap.volatility_annualised != null ? `${snap.volatility_annualised}% ann.` : '—'}</span>
              <span style={{ color:'#555', fontSize:11, marginTop:2 }}>Z &gt; 3.0 safe · 1.8–3.0 grey · &lt; 1.8 distress</span>
            </div>
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(145px,1fr))', gap:10 }}>
            {[['Current Ratio',snap.current_ratio,'ratio'],['Debt/Equity',snap.debt_to_equity,'ratio'],
              ['Debt/Assets',snap.debt_to_assets,'ratio'],['Cash',snap.cash_and_equiv,'currency'],
              ['Net Debt',snap.net_debt,'currency'],['Working Capital',snap.working_capital,'currency'],
              ['Interest Coverage',snap.interest_coverage,'ratio'],['Book Value',snap.book_value,'currency'],
            ].map(([l,v,t])=><MetricCard key={l} label={l} value={fmt(v,t,fcur)} />)}
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20 }}>
            <div style={S.card}>
              <h3 style={S.cardTitle}>Debt / Equity History</h3>
              <ResponsiveContainer width="100%" height={210}>
                <AreaChart data={annualChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                  <defs><linearGradient id="gD" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#ef4444" stopOpacity={0.3}/><stop offset="95%" stopColor="#ef4444" stopOpacity={0}/></linearGradient></defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="year" tick={{ fontSize:11 }} />
                  <YAxis tick={{ fontSize:11 }} />
                  <Tooltip contentStyle={S.tooltip} />
                  <Area type="monotone" dataKey="debt_eq" stroke="#ef4444" fill="url(#gD)" strokeWidth={2} name="D/E" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div style={S.card}>
              <h3 style={S.cardTitle}>Current Ratio History</h3>
              <ResponsiveContainer width="100%" height={210}>
                <LineChart data={annualChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="year" tick={{ fontSize:11 }} />
                  <YAxis tick={{ fontSize:11 }} />
                  <Tooltip contentStyle={S.tooltip} />
                  <ReferenceLine y={1} stroke="#f59e0b" strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="curr_ratio" stroke="#10b981" strokeWidth={2.5} dot={{ r:3 }} name="Current Ratio" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* GROWTH */}
      {tab==='growth' && (
        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(150px,1fr))', gap:10 }}>
            {[['Revenue Growth',snap.revenue_growth,'pct'],['Net Income Growth',snap.net_income_growth,'pct'],
              ['EPS Growth',snap.eps_diluted_growth,'pct'],['FCF Growth',snap.fcf_growth,'pct'],
              ['Revenue CAGR',snap.revenue_cagr_10,'pct'],['EPS CAGR',snap.eps_cagr_10,'pct'],
              ['FCF CAGR',snap.fcf_cagr_10,'pct'],['Equity CAGR',snap.equity_cagr_10,'pct'],
            ].map(([l,v,t])=><MetricCard key={l} label={l} value={fmt(v,t)} color={gc(v)} />)}
          </div>
          <div style={S.card}>
            <h3 style={S.cardTitle}>Profit Margins History (%)</h3>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={annualChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                <XAxis dataKey="year" tick={{ fontSize:11 }} />
                <YAxis tick={{ fontSize:11 }} unit="%" />
                <Tooltip formatter={v=>`${v?.toFixed(1)}%`} contentStyle={S.tooltip} />
                <ReferenceLine y={0} stroke="#334155" />
                <Line type="monotone" dataKey="gross_margin" stroke="#6366f1" strokeWidth={2} dot={false} name="Gross Margin" />
                <Line type="monotone" dataKey="op_margin"    stroke="#10b981" strokeWidth={2} dot={false} name="Op. Margin" />
                <Line type="monotone" dataKey="net_margin"   stroke="#f59e0b" strokeWidth={2} dot={false} name="Net Margin" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ANALYSTS */}
      {tab==='analysts' && (
        <AnalystTab symbol={symbol} />
      )}

      {/* NEWS */}
      {tab==='news' && (
        <NewsTab symbol={symbol} />
      )}
    </div>
  );
}

// ── Hybrid select (presets + custom input) ────────────────────────────────────
function HybridSelect({ selectMode, onSelectChange, onCustomCommit, children, placeholder, inputWidth = 80 }) {
  const [draft, setDraft] = useState('');
  const isCustom = selectMode === 'custom';

  const commit = () => {
    const n = parseFloat(draft);
    if (!isNaN(n)) onCustomCommit(n);
  };

  return (
    <div style={{ display:'flex', gap:4, alignItems:'center' }}>
      <select
        style={S.select}
        value={selectMode}
        onChange={e => {
          setDraft('');
          onSelectChange(e.target.value);
        }}
      >
        {children}
        <option value="custom">Custom…</option>
      </select>
      {isCustom && (
        <input
          type="number"
          placeholder={placeholder}
          value={draft}
          style={{ ...S.select, width:inputWidth, padding:'8px 8px' }}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={e => e.key === 'Enter' && commit()}
          autoFocus
        />
      )}
    </div>
  );
}

// ── PriceChart ────────────────────────────────────────────────────────────────
function PriceChart({ symbol }) {
  const [priceData, setPriceData] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [range, setRange]         = useState('1Y');
  const [showMA20, setShowMA20]   = useState(true);
  const [showMA50, setShowMA50]   = useState(true);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    fetch(`${API}/prices/refresh/${symbol}`, { method: 'POST' })
      .then(() => fetch(`${API}/prices/${symbol}`))
      .then(r => r.json())
      .then(data => { setPriceData(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [symbol]);

  const computeMA = (data, n) =>
    data.map((_, i) => {
      if (i < n - 1) return null;
      const slice = data.slice(i - n + 1, i + 1);
      return Math.round(slice.reduce((s, d) => s + d.close, 0) / n * 100) / 100;
    });

  const ma20 = computeMA(priceData, 20);
  const ma50 = computeMA(priceData, 50);

  const RANGE_DAYS = { '1M': 30, '3M': 90, '6M': 180, '1Y': 365, '3Y': 1095, '5Y': 1825 };
  const cutoffDays = RANGE_DAYS[range];
  const latest = priceData.length ? new Date(priceData[priceData.length - 1].date) : new Date();
  const cutoff  = cutoffDays ? new Date(latest.getTime() - cutoffDays * 86400000) : null;

  const chartData = priceData
    .map((d, i) => ({ date: d.date, close: d.close, ma20: ma20[i], ma50: ma50[i] }))
    .filter(d => !cutoff || new Date(d.date) >= cutoff);

  const tickFormatter = (dateStr) => {
    const d = new Date(dateStr);
    const mon = d.toLocaleString('default', { month: 'short' });
    if (['3Y', '5Y'].includes(range)) return `${mon}${String(d.getFullYear()).slice(2)}`;
    return mon;
  };

  const pillBase = {
    border: '1px solid #2a2a2a', borderRadius: 4, padding: '3px 10px',
    fontSize: 12, cursor: 'pointer', fontFamily: 'monospace', background: 'none',
  };
  const rangePill = active => ({ ...pillBase, ...(active ? { background:'#3730a3', color:'#e0e7ff', borderColor:'#4338ca' } : { color:'#64748b' }) });
  const ma20Pill  = active => ({ ...pillBase, ...(active ? { background:'#78350f', color:'#fde68a', borderColor:'#92400e' } : { color:'#64748b' }) });
  const ma50Pill  = active => ({ ...pillBase, ...(active ? { background:'#4c1d95', color:'#ddd6fe', borderColor:'#5b21b6' } : { color:'#64748b' }) });

  if (loading) return (
    <div style={{ height:400, display:'flex', alignItems:'center', justifyContent:'center', color:'#64748b', fontFamily:'monospace' }}>
      Loading…
    </div>
  );
  if (!priceData.length) return (
    <div style={{ height:400, display:'flex', alignItems:'center', justifyContent:'center', color:'#64748b' }}>
      No price history available
    </div>
  );

  return (
    <div>
      <div style={{ display:'flex', gap:8, marginBottom:12, flexWrap:'wrap', alignItems:'center' }}>
        <div style={{ display:'flex', gap:4 }}>
          {['1M','3M','6M','1Y','3Y','5Y'].map(r => (
            <button key={r} onClick={() => setRange(r)} style={rangePill(r === range)}>{r}</button>
          ))}
        </div>
        <div style={{ display:'flex', gap:4, marginLeft:8 }}>
          <button onClick={() => setShowMA20(v => !v)} style={ma20Pill(showMA20)}>MA20</button>
          <button onClick={() => setShowMA50(v => !v)} style={ma50Pill(showMA50)}>MA50</button>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={380}>
        <ComposedChart data={chartData} margin={{ top:5, right:10, bottom:5, left:0 }}>
          <defs>
            <linearGradient id="gPrice" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.3}/>
              <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
            </linearGradient>
          </defs>
          <XAxis dataKey="date" tick={{ fontSize:10 }} interval="preserveStartEnd" tickFormatter={tickFormatter} />
          <YAxis tick={{ fontSize:10 }} domain={['auto','auto']} width={60} />
          <Tooltip
            contentStyle={S.tooltip}
            labelFormatter={tickFormatter}
            formatter={(val, name) => [val != null ? val.toFixed(2) : '—', name]}
          />
          <Area type="monotone" dataKey="close" stroke="#6366f1" fill="url(#gPrice)" strokeWidth={2} dot={false} name="Close" />
          {showMA20 && <Line type="monotone" dataKey="ma20" stroke="#f59e0b" strokeWidth={1.5} dot={false} strokeDasharray="4 2" name="MA20" connectNulls={false} />}
          {showMA50 && <Line type="monotone" dataKey="ma50" stroke="#a855f7" strokeWidth={1.5} dot={false} name="MA50" connectNulls={false} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Screener ──────────────────────────────────────────────────────────────────
const EMPTY_FILTERS = { sector:'', exclude_sectors:'', ftse_index:'', min_market_cap:'', max_pe:'', min_roe:'', min_revenue_growth:'', consensus:'', min_upside_pct:'' };
const EMPTY_MODES   = { min_market_cap:'', max_pe:'', min_roe:'', min_revenue_growth:'' };
const EMPTY_SCORE_FILTERS = { min_momentum:'', min_quality:'', min_piotroski:'', max_risk:'' };

// [label, rightAlign, sortKey]
const FUND_COLS_BASE = [
  ['Symbol',false,'symbol'],['Name',false,'name'],['Sector',false,'sector'],['Index',false,'ftse_index'],
  ['Mkt Cap',true,'market_cap'],['P/E',true,'price_to_earnings'],['P/B',true,'price_to_book'],
  ['ROE',true,'roe'],['Rev Growth',true,'revenue_growth'],['D/E',true,'debt_to_equity'],
  ['PEGY',true,'pegy'],
];
const FUND_COLS = [
  ...FUND_COLS_BASE,
  ['Momentum',true,'momentum_score'],['Quality',true,'quality_score'],['Value',true,'piotroski_score'],['Risk',true,'risk_score'],
];
const WATCHLIST_FUND_COLS = [
  ...FUND_COLS_BASE,
  ['Price',true,'current_price'],['Target',true,'target_price'],
];
const ANALYST_COLS = [
  ['Symbol',false,'symbol'],['Name',false,'name'],['Sector',false,'sector'],['Index',false,'ftse_index'],
  ['Mkt Cap',true,'market_cap'],['Consensus',false,'consensus'],['Upside',true,'upside_pct'],
  ['Buy%',true,'buy_pct'],['# Analysts',true,'total_analysts'],['Rev Score',true,'revision_score'],
];

function SectorDropdown({ sectors, value, excluded, onSelect, onToggleExclude }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const label = value
    ? value
    : excluded.length ? `All Sectors (−${excluded.length})` : 'All Sectors';

  return (
    <div ref={ref} style={{ position:'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{ ...S.select, minWidth:170, textAlign:'left', cursor:'pointer', display:'flex', alignItems:'center', justifyContent:'space-between', gap:8 }}>
        <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{label}</span>
        <span style={{ fontSize:8, opacity:0.6 }}>▾</span>
      </button>
      {open && (
        <div style={{ position:'absolute', top:'100%', left:0, marginTop:4, background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, minWidth:260, zIndex:200, boxShadow:'0 8px 24px rgba(0,0,0,0.8)', maxHeight:360, overflowY:'auto' }}>
          <div
            onClick={() => { onSelect(''); setOpen(false); }}
            style={{
              padding:'8px 12px', cursor:'pointer', fontFamily:'monospace', fontSize:12,
              color: value === '' ? '#f97316' : '#cbd5e1',
              borderBottom:'1px solid #1f1f1f',
            }}>
            All Sectors
          </div>
          {sectors.map(s => {
            const isExcluded = excluded.includes(s);
            const isSelected = value === s;
            return (
              <div key={s} style={{ display:'flex', alignItems:'stretch', borderBottom:'1px solid #1f1f1f' }}>
                <div
                  onClick={() => { if (!isExcluded) { onSelect(s); setOpen(false); } }}
                  style={{
                    flex:1, padding:'8px 8px 8px 12px',
                    cursor: isExcluded ? 'not-allowed' : 'pointer',
                    fontFamily:'monospace', fontSize:12,
                    color: isSelected ? '#f97316' : isExcluded ? '#555' : '#cbd5e1',
                    textDecoration: isExcluded ? 'line-through' : 'none',
                  }}>
                  {s}
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); onToggleExclude(s); }}
                  title={isExcluded ? 'Stop excluding' : 'Exclude this sector'}
                  style={{
                    background:'none', border:'none', padding:'0 12px',
                    cursor:'pointer', fontSize:13, lineHeight:1,
                    color: isExcluded ? '#ef4444' : '#555',
                  }}>
                  ⊘
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function StarButton({ active, onClick }) {
  return (
    <button
      onClick={onClick}
      title={active ? 'Remove from watchlist' : 'Add to watchlist'}
      style={{
        background:'none', border:'none', cursor:'pointer', padding:'0 6px 0 0',
        color: active ? '#f59e0b' : '#3a3a3a',
        fontSize: 14, lineHeight: 1,
      }}
      onMouseEnter={e => { if (!active) e.currentTarget.style.color = '#7c6a3a'; }}
      onMouseLeave={e => { if (!active) e.currentTarget.style.color = '#3a3a3a'; }}
    >
      {active ? '★' : '☆'}
    </button>
  );
}

function TargetInput({ symbol, target, current, onCommit }) {
  const [draft, setDraft] = useState(target != null ? String(target) : '');
  useEffect(() => { setDraft(target != null ? String(target) : ''); }, [target]);
  let color = '#cbd5e1';
  if (target != null && current != null) {
    color = Number(target) >= Number(current) ? '#10b981' : '#ef4444';
  }
  const commit = () => {
    if (draft === '' && target == null) return;
    if (draft !== (target != null ? String(target) : '')) onCommit(symbol, draft);
  };
  return (
    <input
      type="number"
      step="0.01"
      value={draft}
      placeholder="—"
      onChange={e => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={e => { if (e.key === 'Enter') { commit(); e.currentTarget.blur(); } }}
      onClick={e => e.stopPropagation()}
      style={{
        width: 80, textAlign: 'right',
        background: '#0d0d0d', border: '1px solid #2a2a2a', borderRadius: 2,
        padding: '3px 6px', fontFamily: 'monospace', fontSize: 12, fontWeight: 700,
        color,
        outline: 'none',
      }}
    />
  );
}

function Screener({ onSelect, highlightSymbol, watchlist, onToggleWatchlist, watchlistMode = false }) {
  const [filters, setFilters]       = useState(EMPTY_FILTERS);
  const [selectModes, setSelectModes] = useState(EMPTY_MODES);
  const [filterOpts, setFilterOpts] = useState({ sectors:[], countries:[] });
  const [results, setResults]       = useState([]);
  const [loading, setLoading]       = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [scoreFilters, setScoreFilters] = useState(EMPTY_SCORE_FILTERS);
  const [tableView, setTableView] = useState('fundamentals');
  const [sortCol, setSortCol]     = useState(null);
  const [sortDir, setSortDir]     = useState('desc');
  const [targets, setTargets]     = useState(() => loadTargets());
  const [liveQuotes, setLiveQuotes] = useState({});

  useEffect(() => {
    if (!watchlistMode) return;
    const symbols = [...(watchlist instanceof Set ? watchlist : new Set(watchlist || []))];
    if (symbols.length === 0) { setLiveQuotes({}); return; }
    let cancelled = false;
    const fetchQuotes = () => {
      fetch(`${API}/quotes?symbols=${encodeURIComponent(symbols.join(','))}`)
        .then(r => r.json())
        .then(d => { if (!cancelled && d && typeof d === 'object') setLiveQuotes(d); })
        .catch(() => {});
    };
    fetchQuotes();
    const id = setInterval(fetchQuotes, 60000);
    return () => { cancelled = true; clearInterval(id); };
  }, [watchlistMode, watchlist]);

  const setTarget = (symbol, value) => {
    setTargets(prev => {
      const next = { ...prev };
      const num = parseFloat(value);
      if (!Number.isFinite(num) || num <= 0) delete next[symbol];
      else next[symbol] = num;
      saveTargets(next);
      return next;
    });
  };

  useEffect(() => {
    fetch(`${API}/filters`).then(r=>r.json()).then(setFilterOpts);
    runScreener(EMPTY_FILTERS);
  }, []);

  useEffect(() => {
    if (highlightSymbol) {
      const el = document.getElementById('row-' + highlightSymbol);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [highlightSymbol, results]);

  const runScreener = useCallback((f) => {
    setLoading(true);
    const p = new URLSearchParams();
    if (f.sector)             p.set('sector', f.sector);
    if (f.exclude_sectors)    p.set('exclude_sectors', f.exclude_sectors);
    if (f.country)            p.set('country', f.country);
    if (f.ftse_index)         p.set('ftse_index', f.ftse_index);
    if (f.min_market_cap)     p.set('min_market_cap', f.min_market_cap);
    if (f.max_pe)             p.set('max_pe', f.max_pe);
    if (f.min_roe)            p.set('min_roe', f.min_roe);
    if (f.min_revenue_growth) p.set('min_revenue_growth', f.min_revenue_growth);
    if (f.consensus)          p.set('consensus', f.consensus);
    if (f.min_upside_pct)     p.set('min_upside_pct', f.min_upside_pct);
    p.set('limit', 1000);
    fetch(`${API}/screener?${p}`)
      .then(r=>r.json())
      .then(d=>{ setResults(Array.isArray(d)?d:[]); setLoading(false); })
      .catch(()=>setLoading(false));
  }, []);

  const update = (k, v) => {
    const f = { ...filters, [k]: v };
    setFilters(f);
    runScreener(f);
  };

  const updateMany = (patch) => {
    const f = { ...filters, ...patch };
    setFilters(f);
    runScreener(f);
  };

  const excludedSectors = filters.exclude_sectors ? filters.exclude_sectors.split(',').filter(Boolean) : [];

  const toggleExcludeSector = (s) => {
    const set = new Set(excludedSectors);
    const wasExcluded = set.has(s);
    if (wasExcluded) set.delete(s); else set.add(s);
    const patch = { exclude_sectors: Array.from(set).join(',') };
    if (!wasExcluded && filters.sector === s) patch.sector = '';
    updateMany(patch);
  };

  // Called when a HybridSelect dropdown changes (preset or 'custom')
  const handleSelectMode = (key, mode) => {
    setSelectModes(m => ({ ...m, [key]: mode }));
    if (mode !== 'custom') update(key, mode); // preset value — apply immediately
    // custom: just show the input, don't re-run until user commits a value
  };

  // Called when a custom input value is committed (blur / Enter)
  const handleCustomCommit = (key, rawValue, parse) => {
    const apiValue = String(parse(rawValue));
    update(key, apiValue);
  };

  const clearFilters = () => {
    setFilters(EMPTY_FILTERS);
    setSelectModes(EMPTY_MODES);
    setScoreFilters(EMPTY_SCORE_FILTERS);
    runScreener(EMPTY_FILTERS);
  };

  const updateScore = (k, v) => setScoreFilters(sf => ({ ...sf, [k]: v }));

  const watchlistSet = watchlist instanceof Set ? watchlist : new Set(watchlist || []);
  const displayed = results.filter(r => {
    if (watchlistMode && !watchlistSet.has(r.symbol)) return false;
    const sf = scoreFilters;
    if (sf.min_momentum  && (r.momentum_score  == null || r.momentum_score  < +sf.min_momentum))  return false;
    if (sf.min_quality   && (r.quality_score   == null || r.quality_score   < +sf.min_quality))   return false;
    if (sf.min_piotroski && (r.piotroski_score == null || r.piotroski_score < +sf.min_piotroski)) return false;
    if (sf.max_risk      && (r.risk_score      == null || r.risk_score      > +sf.max_risk))      return false;
    return true;
  });

  const hasActiveFilters = Object.values(filters).some(v => v !== '') || Object.values(scoreFilters).some(v => v !== '');
  const hasAdvancedFilters = filters.max_pe || filters.min_roe || filters.min_revenue_growth
    || scoreFilters.min_momentum || scoreFilters.min_quality || scoreFilters.min_piotroski || scoreFilters.max_risk;

  const handleSort = (key) => {
    if (sortCol === key) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortCol(key); setSortDir('desc'); }
  };

  const lookup = (r, key) => {
    if (key === 'target_price') return targets[r.symbol];
    if (key === 'current_price') return liveQuotes[r.symbol] ?? r.current_price;
    return r[key];
  };
  const sorted = sortCol == null ? displayed : [...displayed].sort((a, b) => {
    const av = lookup(a, sortCol), bv = lookup(b, sortCol);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortDir === 'asc' ? av - bv : bv - av;
  });

  return (
    <div>
      <h2 style={{ fontFamily:'DM Serif Display,serif', fontSize:26, color:'#f1f5f9', marginBottom:4 }}>{watchlistMode ? 'Watchlist' : 'Stock Screener'}</h2>
      <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:20 }}>
        <div style={{ fontSize:13, color:'#64748b' }}>
          {watchlistMode
            ? (watchlistSet.size === 0 ? 'No companies saved yet' : `${watchlistSet.size} saved`)
            : `${filters.ftse_index || 'All indices'}${filters.sector ? ` · ${filters.sector}` : ''}`}
        </div>
        <div style={{ background:'#334155', color:'#cbd5e1', borderRadius:20, padding:'2px 12px', fontSize:13, fontWeight:600 }}>
          {displayed.length !== results.length ? `${displayed.length} / ${results.length}` : displayed.length} companies
        </div>
      </div>

      {!watchlistMode && (
      <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:8, alignItems:'center' }}>
        <SectorDropdown
          sectors={filterOpts.sectors}
          value={filters.sector}
          excluded={excludedSectors}
          onSelect={v => update('sector', v)}
          onToggleExclude={toggleExcludeSector}
        />
        <select style={S.select} value={filters.ftse_index} onChange={e=>update('ftse_index',e.target.value)}>
          <option value="">FTSE Market</option>
          <option value="FTSE 100">FTSE 100</option>
          <option value="FTSE 250">FTSE 250</option>
          <option value="FTSE 350">FTSE 350</option>
          <option value="FTSE SmallCap">FTSE SmallCap</option>
          <option value="FTSE AIM 100">AIM 100</option>
        </select>
        <HybridSelect
          selectMode={selectModes.min_market_cap}
          onSelectChange={mode => handleSelectMode('min_market_cap', mode)}
          onCustomCommit={v => handleCustomCommit('min_market_cap', v, n => Math.round(n * 1e9))}
          placeholder="£B"
          inputWidth={70}
        >
          <option value="">Any Market Cap</option>
          <option value="1000000000">£1B+</option>
          <option value="10000000000">£10B+</option>
          <option value="50000000000">£50B+</option>
        </HybridSelect>
        <button
          onClick={() => setShowAdvanced(v => !v)}
          style={{
            ...S.select,
            cursor:'pointer',
            color: (showAdvanced || hasAdvancedFilters) ? '#f97316' : '#888',
            borderColor: hasAdvancedFilters ? '#f97316' : '#2a2a2a',
          }}
        >
          Advanced {showAdvanced ? '▲' : '▼'}{hasAdvancedFilters ? ' ●' : ''}
        </button>
        {hasActiveFilters && (
          <button onClick={clearFilters} style={{ ...S.select, cursor:'pointer', color:'#ef4444', borderColor:'#3a1a1a' }}>
            Clear filters ✕
          </button>
        )}
      </div>
      )}

      {!watchlistMode && showAdvanced && (
        <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:8 }}>
          <select style={S.select} value={scoreFilters.min_momentum} onChange={e=>updateScore('min_momentum',e.target.value)}>
            <option value="">Momentum</option>
            <option value="4">Mom ≥ 4</option>
            <option value="6">Mom ≥ 6</option>
            <option value="8">Mom ≥ 8</option>
          </select>
          <select style={S.select} value={scoreFilters.min_quality} onChange={e=>updateScore('min_quality',e.target.value)}>
            <option value="">Quality</option>
            <option value="4">Quality ≥ 4</option>
            <option value="6">Quality ≥ 6</option>
            <option value="8">Quality ≥ 8</option>
          </select>
          <select style={S.select} value={scoreFilters.min_piotroski} onChange={e=>updateScore('min_piotroski',e.target.value)}>
            <option value="">Value</option>
            <option value="4">Value ≥ 4</option>
            <option value="6">Value ≥ 6</option>
            <option value="8">Value ≥ 8</option>
          </select>
          <select style={S.select} value={scoreFilters.max_risk} onChange={e=>updateScore('max_risk',e.target.value)}>
            <option value="">Risk</option>
            <option value="3">Risk ≤ 3</option>
            <option value="5">Risk ≤ 5</option>
            <option value="7">Risk ≤ 7</option>
          </select>
          <HybridSelect
            selectMode={selectModes.max_pe}
            onSelectChange={mode => handleSelectMode('max_pe', mode)}
            onCustomCommit={v => handleCustomCommit('max_pe', v, n => n)}
            placeholder="P/E"
            inputWidth={65}
          >
            <option value="">Any P/E</option>
            <option value="15">P/E &lt; 15</option>
            <option value="25">P/E &lt; 25</option>
            <option value="40">P/E &lt; 40</option>
          </HybridSelect>
          <HybridSelect
            selectMode={selectModes.min_roe}
            onSelectChange={mode => handleSelectMode('min_roe', mode)}
            onCustomCommit={v => handleCustomCommit('min_roe', v, n => n / 100)}
            placeholder="ROE %"
            inputWidth={75}
          >
            <option value="">Any ROE</option>
            <option value="0.1">ROE &gt; 10%</option>
            <option value="0.15">ROE &gt; 15%</option>
            <option value="0.2">ROE &gt; 20%</option>
          </HybridSelect>
          <HybridSelect
            selectMode={selectModes.min_revenue_growth}
            onSelectChange={mode => handleSelectMode('min_revenue_growth', mode)}
            onCustomCommit={v => handleCustomCommit('min_revenue_growth', v, n => n / 100)}
            placeholder="Growth %"
            inputWidth={85}
          >
            <option value="">Any Rev Growth</option>
            <option value="0.05">Rev Growth &gt; 5%</option>
            <option value="0.1">Rev Growth &gt; 10%</option>
            <option value="0.2">Rev Growth &gt; 20%</option>
          </HybridSelect>
          <select
            style={S.select}
            value={filters.consensus}
            onChange={e => update('consensus', e.target.value)}
          >
            <option value="">All Consensus</option>
            <option value="Buy">Buy</option>
            <option value="Hold">Hold</option>
            <option value="Sell">Sell</option>
          </select>
          <select
            style={S.select}
            value={filters.min_upside_pct}
            onChange={e => update('min_upside_pct', e.target.value)}
          >
            <option value="">Any Upside</option>
            <option value="5">Upside &gt; 5%</option>
            <option value="10">Upside &gt; 10%</option>
            <option value="20">Upside &gt; 20%</option>
          </select>
        </div>
      )}

      {!watchlistMode && excludedSectors.length > 0 && (
        <div style={{ display:'flex', flexWrap:'wrap', gap:6, alignItems:'center', marginBottom:8 }}>
          <span style={{ fontFamily:'monospace', fontSize:10, color:'#666', textTransform:'uppercase', letterSpacing:1 }}>Excluded:</span>
          {excludedSectors.map(s => (
            <span key={s} style={{
              display:'inline-flex', alignItems:'center', gap:6,
              background:'#2a0d0d', color:'#fca5a5', border:'1px solid #4a1c1c',
              padding:'2px 4px 2px 8px', borderRadius:2, fontSize:11, fontFamily:'monospace',
            }}>
              {s}
              <button
                onClick={() => toggleExcludeSector(s)}
                title="Remove exclusion"
                style={{ background:'none', border:'none', color:'#fca5a5', cursor:'pointer', padding:'0 4px', fontSize:12, lineHeight:1 }}>
                ✕
              </button>
            </span>
          ))}
        </div>
      )}


      {/* View toggle */}
      <div style={{ display:'flex', gap:6, marginBottom:12 }}>
        {['fundamentals','analysts'].map(v => (
          <button key={v} onClick={() => setTableView(v)} style={{
            padding:'5px 14px', borderRadius:2, border:'1px solid',
            fontSize:11, fontFamily:'monospace', cursor:'pointer', textTransform:'uppercase', letterSpacing:0.5,
            background: tableView===v ? '#f97316' : '#141414',
            color:       tableView===v ? '#000'    : '#666',
            borderColor: tableView===v ? '#f97316' : '#2a2a2a',
            fontWeight:  tableView===v ? 700       : 400,
          }}>{v}</button>
        ))}
      </div>

      {loading ? <div style={S.loading}>Screening…</div> : watchlistMode && watchlistSet.size === 0 ? (
        <div style={{ textAlign:'center', padding:64, color:'#64748b', fontFamily:'monospace', fontSize:13, lineHeight:1.8 }}>
          Your watchlist is empty.<br />
          Go to the <span style={{ color:'#f97316' }}>Screener</span> and click the <span style={{ color:'#f59e0b', fontSize:16 }}>☆</span> next to a ticker to add it.
        </div>
      ) : (
        <div style={{ overflow: 'auto', maxHeight: 'calc(100vh - 280px)', scrollbarGutter: 'stable' }}>
          <table style={{ ...S.table, minWidth: tableView==='analysts' ? 700 : 900 }}>
            <thead>
              <tr>
                {(tableView === 'fundamentals' ? (watchlistMode ? WATCHLIST_FUND_COLS : FUND_COLS) : ANALYST_COLS).map(([h,num,key])=>(
                  <th key={h} onClick={() => handleSort(key)} style={{
                    ...S.th, textAlign: num?'right':'left', cursor:'pointer', userSelect:'none',
                    color: sortCol===key ? '#fb923c' : '#f97316',
                  }}>
                    {h}{sortCol===key ? (sortDir==='desc'?' ▼':' ▲') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r,i) => {
                const isHighlighted = r.symbol === highlightSymbol;
                const baseBg = isHighlighted ? '#2d1e00' : i%2===0 ? '#1e293b' : '#162032';
                return (
                <tr key={r.symbol} id={'row-'+r.symbol} onClick={()=>onSelect(r.symbol)}
                  style={{ background: baseBg, cursor:'pointer', boxShadow: isHighlighted ? 'inset 3px 0 0 #f97316' : 'none' }}
                  onMouseEnter={e=>e.currentTarget.style.background='#334155'}
                  onMouseLeave={e=>e.currentTarget.style.background=baseBg}>
                  {/* Shared columns */}
                  <td style={{ ...S.td, fontFamily:'monospace', fontWeight:700, color: watchlistSet.has(r.symbol) ? '#f59e0b' : '#818cf8' }}>
                    <span style={{ display:'inline-flex', alignItems:'center' }}>
                      <StarButton
                        active={watchlistSet.has(r.symbol)}
                        onClick={e => { e.stopPropagation(); onToggleWatchlist && onToggleWatchlist(r.symbol); }}
                      />
                      {r.symbol.replace('.L','')}
                    </span>
                  </td>
                  <td style={S.td}>{r.name?.slice(0,26)}</td>
                  <td style={{ ...S.td, color:'#64748b' }}>{r.sector?.slice(0,18)}</td>
                  <td style={{ ...S.td, color:'#64748b' }}>{r.ftse_index?.replace('FTSE ','')}</td>
                  <td style={S.tdNum}>{fmt(r.market_cap,'currency',r.financial_currency)}</td>
                  {tableView === 'fundamentals' ? (<>
                    <td style={{ ...S.tdNum, color: r.price_to_earnings<15?'#10b981':r.price_to_earnings>40?'#ef4444':'#ccc' }}>{fmt(r.price_to_earnings,'ratio')}</td>
                    <td style={S.tdNum}>{fmt(r.price_to_book,'ratio')}</td>
                    <td style={{ ...S.tdNum, color:gc(r.roe) }}>{fmt(r.roe,'pct')}</td>
                    <td style={{ ...S.tdNum, color:gc(r.revenue_growth) }}>{fmt(r.revenue_growth,'pct')}</td>
                    <td style={{ ...S.tdNum, color: r.debt_to_equity>2?'#ef4444':'#ccc' }}>{fmt(r.debt_to_equity,'ratio')}</td>
                    <td style={{ ...S.tdNum,
                      color: r.pegy == null ? '#444' : r.pegy < 1 ? '#10b981' : r.pegy <= 2 ? '#f59e0b' : '#ef4444',
                    }}>{r.pegy ?? '—'}</td>
                    {watchlistMode ? (() => {
                      const live = liveQuotes[r.symbol];
                      const pence = live != null ? live : r.current_price;
                      const pounds = pence != null ? pence / 100 : null;
                      const isLive = live != null;
                      return (<>
                        <td style={{ ...S.tdNum, color: '#f1f5f9', fontWeight:700 }}
                            title={isLive ? 'Live (yfinance, 60s cache)' : 'Last close'}>
                          {pounds != null ? `£${pounds.toFixed(2)}` : '—'}
                          {isLive && <span style={{ marginLeft:4, fontSize:9, color:'#10b981' }}>●</span>}
                        </td>
                        <td style={{ ...S.tdNum }} onClick={e => e.stopPropagation()}>
                          <TargetInput
                            symbol={r.symbol}
                            target={targets[r.symbol]}
                            current={pounds}
                            onCommit={setTarget}
                          />
                        </td>
                      </>);
                    })() : (<>
                    <td style={{ ...S.tdNum,
                      color: r.momentum_score == null ? '#444' : r.momentum_score >= 7 ? '#10b981' : r.momentum_score >= 4 ? '#f59e0b' : '#ef4444',
                      fontWeight: 700,
                    }}>{r.momentum_score ?? '—'}</td>
                    <td style={{ ...S.tdNum,
                      color: r.quality_score == null ? '#444' : r.quality_score >= 7 ? '#10b981' : r.quality_score >= 4 ? '#f59e0b' : '#ef4444',
                      fontWeight: 700,
                    }}>{r.quality_score ?? '—'}</td>
                    <td style={{ ...S.tdNum,
                      color: r.piotroski_score == null ? '#444' : r.piotroski_score >= 7 ? '#10b981' : r.piotroski_score >= 4 ? '#f59e0b' : '#ef4444',
                      fontWeight: 700,
                    }}>{r.piotroski_score ?? '—'}</td>
                    <td style={{ ...S.tdNum,
                      color: r.risk_score == null ? '#444' : r.risk_score <= 3 ? '#10b981' : r.risk_score <= 6 ? '#f59e0b' : '#ef4444',
                      fontWeight: 700,
                    }}>{r.risk_score ?? '—'}</td>
                    </>)}
                  </>) : (<>
                    <td style={S.td}>
                      {r.consensus
                        ? <span style={{
                            ...({ Buy: { background:'#0d3320', color:'#10b981' }, Hold: { background:'#1a1400', color:'#f59e0b' }, Sell: { background:'#2a0d0d', color:'#ef4444' } }[r.consensus] || {}),
                            padding:'2px 7px', borderRadius:2, fontSize:9, fontFamily:'monospace', fontWeight:700
                          }}>{r.consensus}</span>
                        : <span style={{ color:'#444' }}>—</span>}
                    </td>
                    <td style={{ ...S.tdNum, color: r.upside_pct > 0 ? '#10b981' : r.upside_pct < 0 ? '#ef4444' : '#555' }}>
                      {r.upside_pct != null ? `${r.upside_pct >= 0 ? '+' : ''}${r.upside_pct.toFixed(1)}%` : '—'}
                    </td>
                    <td style={{ ...S.tdNum, color: r.buy_pct != null ? (r.buy_pct >= 60 ? '#10b981' : r.buy_pct >= 40 ? '#f59e0b' : '#ef4444') : '#444' }}>
                      {r.buy_pct != null ? `${r.buy_pct.toFixed(0)}%` : '—'}
                    </td>
                    <td style={{ ...S.tdNum, color: r.total_analysts != null ? '#94a3b8' : '#444' }}>
                      {r.total_analysts ?? '—'}
                    </td>
                    <td style={{ ...S.tdNum,
                      color: r.revision_score == null ? '#444' : r.revision_score > 0 ? '#10b981' : r.revision_score < 0 ? '#ef4444' : '#f59e0b',
                      fontWeight: 700,
                    }}>{r.revision_score != null ? (r.revision_score > 0 ? `+${r.revision_score}` : r.revision_score) : '—'}</td>
                  </>)}
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

    </div>
  );
}

// ── App Shell ─────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage]           = useState('screener'); // screener | watchlist | rotation | breadth | cross-asset | signals | company
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const [watchlist, setWatchlist] = useState(() => new Set(loadWatchlist()));

  useEffect(() => { saveWatchlist([...watchlist]); }, [watchlist]);

  const toggleWatchlist = useCallback((symbol) => {
    setWatchlist(prev => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol); else next.add(symbol);
      return next;
    });
  }, []);
  const [highlightSymbol, setHighlightSymbol] = useState(null);
  const [searchQ, setSearchQ]     = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [showSearch, setShowSearch] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [priceRefreshing, setPriceRefreshing] = useState(false);
  const [priceToast, setPriceToast]           = useState(null);

  const doSearch = (q) => {
    setSearchQ(q);
    if (q.length < 1) { setSearchResults([]); return; }
    fetch(`${API}/search?q=${encodeURIComponent(q)}`).then(r=>r.json()).then(setSearchResults);
  };

  const selectCompany = (sym) => {
    setSelectedSymbol(sym);
    setPage('company');
    setHighlightSymbol(null);
    setShowSearch(false);
    setSearchQ('');
    setSearchResults([]);
    if (typeof window !== 'undefined') {
      window.history.pushState({ page: 'company', symbol: sym }, '', `#company/${encodeURIComponent(sym)}`);
    }
  };

  const goBack = () => {
    setPage('screener');
    if (typeof window !== 'undefined' && window.location.hash) {
      window.history.pushState({ page: 'screener' }, '', window.location.pathname + window.location.search);
    }
  };

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const onPop = (e) => {
      const st = e.state;
      if (st && st.page === 'company' && st.symbol) {
        setSelectedSymbol(st.symbol);
        setPage('company');
      } else {
        setPage('screener');
      }
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const highlightInScreener = (sym) => {
    setHighlightSymbol(sym);
    setPage('screener');
    setShowSearch(false);
    setSearchQ('');
    setSearchResults([]);
  };

  const handleRefresh = () => {
    setRefreshKey(k => k + 1);
    setLastUpdated(new Date().toLocaleTimeString('en-GB', { hour:'2-digit', minute:'2-digit' }));
  };

  const handlePriceRefresh = async () => {
    setPriceRefreshing(true);
    setPriceToast(null);
    try {
      const res = await fetch(`${API}/prices/refresh`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPriceToast({ ok: true, msg: `+${data.rows_added} rows (${data.duration_seconds}s)` });
    } catch {
      setPriceToast({ ok: false, msg: 'Price refresh failed' });
    } finally {
      setPriceRefreshing(false);
      setTimeout(() => setPriceToast(null), 4000);
    }
  };

  const NAV_GROUPS = [
    { id: 'screener',        label: 'Screener' },
    { id: 'watchlist',       label: 'Watchlist' },
    { id: 'analyst-monitor', label: 'Analysts' },
    { id: 'rns',             label: 'RNS News' },
    { id: 'analytics',       label: 'Analytics' },
    { id: 'markets', label: 'Markets', children: [
      { id: 'fear-greed',  label: 'Fear & Greed' },
      { id: 'cross-asset', label: 'Cross-Asset'  },
      { heading: 'Sector Analysis' },
      { id: 'rotation', label: 'Rotation'   },
      { id: 'breadth',  label: 'Breadth'    },
      { id: 'signals',  label: 'Signal Log' },
    ]},
  ];
  const [openMenu, setOpenMenu] = useState(null);

  const showSidebar = page !== 'company';
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div style={{ minHeight:'100vh', background:'#0a0a0a', fontFamily:'monospace' }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />

      {/* Nav */}
      <nav style={{ background:'#0a0a0a', borderBottom:'1px solid #2a2a2a', padding:'0 32px', display:'flex', alignItems:'center', height:52, position:'sticky', top:0, zIndex:100 }}>
        <button onClick={() => setSidebarCollapsed(v => !v)} title="Toggle sidebar"
          style={{ background:'none', border:'none', cursor:'pointer', padding:'4px 8px 4px 0', marginRight:8, marginLeft:-20, display:'flex', alignItems:'center', opacity: sidebarCollapsed ? 0.35 : 0.75, transition:'opacity 0.2s' }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="2" y="2" width="20" height="20" rx="3" stroke="#f1f5f9" strokeWidth="1.5"/>
            <line x1="8" y1="2" x2="8" y2="22" stroke="#f1f5f9" strokeWidth="1.5"/>
            <line x1="11" y1="7" x2="19" y2="7" stroke="#f1f5f9" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="11" y1="12" x2="19" y2="12" stroke="#f1f5f9" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="11" y1="17" x2="16" y2="17" stroke="#f1f5f9" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </button>
        <div
          onClick={()=>setPage('screener')}
          style={{
            fontFamily:'"DM Sans", sans-serif', fontSize:12, fontWeight:600,
            color:'#f97316', letterSpacing:2, textTransform:'uppercase',
            marginRight:32, cursor:'pointer',
            padding:'4px 10px', borderRadius:4,
            background:'linear-gradient(135deg, #2a1a00 0%, #1a1200 100%)',
            boxShadow:'0 0 12px rgba(249, 115, 22, 0.15)',
          }}
        >
          Alpha Move AI
        </div>
        <div style={{ display:'flex', gap:2 }}>
          {NAV_GROUPS.map(g => {
            if (!g.children) {
              return (
                <button key={g.id} style={{ ...S.navBtn, ...(page===g.id ? S.navBtnActive : {}) }} onClick={() => setPage(g.id)}>
                  {g.label}
                </button>
              );
            }
            const groupActive = g.children.some(c => c.id === page);
            return (
              <div key={g.id} style={{ position:'relative' }}
                onMouseEnter={() => setOpenMenu(g.id)}
                onMouseLeave={() => setOpenMenu(null)}>
                <button style={{ ...S.navBtn, ...(groupActive ? S.navBtnActive : {}), display:'flex', alignItems:'center', gap:4 }}>
                  {g.label} <span style={{ fontSize:8, opacity:0.6 }}>▾</span>
                </button>
                {openMenu === g.id && (
                  <div style={{ position:'absolute', top:'100%', left:0, background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, minWidth:160, zIndex:200, boxShadow:'0 8px 24px rgba(0,0,0,0.8)', paddingBottom:4 }}>
                    {g.children.map((c, idx) => {
                      if (c.heading) {
                        return (
                          <div key={'h-'+idx} style={{
                            padding:'10px 16px 4px', color:'#555', fontSize:9,
                            fontFamily:'monospace', textTransform:'uppercase', letterSpacing:1.5,
                            borderTop: idx === 0 ? 'none' : '1px solid #1f1f1f',
                            marginTop: idx === 0 ? 0 : 4,
                          }}>{c.heading}</div>
                        );
                      }
                      return (
                        <button key={c.id}
                          onClick={() => { setPage(c.id); setOpenMenu(null); }}
                          style={{ ...S.navBtn, ...(page===c.id ? S.navBtnActive : {}), display:'block', width:'100%', textAlign:'left', borderRadius:0, padding:'10px 16px' }}>
                          {c.label}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:12 }}>
          {lastUpdated && <span style={{ color:'#444', fontSize:10, fontFamily:'monospace' }}>Updated {lastUpdated}</span>}
          <button onClick={handleRefresh} style={{ background:'#1a1a1a', color:'#666', border:'1px solid #2a2a2a', padding:'4px 10px', borderRadius:2, fontFamily:'monospace', fontSize:10, cursor:'pointer' }}>↻ Market</button>
          <button
            onClick={handlePriceRefresh}
            disabled={priceRefreshing}
            title="Refresh price history"
            style={{
              background: '#1a1a1a', color: priceRefreshing ? '#f97316' : '#666',
              border: '1px solid #2a2a2a', padding: '4px 10px',
              borderRadius: 2, fontFamily: 'monospace', fontSize: 10,
              cursor: priceRefreshing ? 'not-allowed' : 'pointer',
            }}
          >
            <span className={priceRefreshing ? 'spinning' : ''}>↻</span>{priceRefreshing ? ' Refreshing…' : ' Stock Prices'}
          </button>
          {priceToast && (
            <span style={{
              fontSize: 10, fontFamily: 'monospace',
              color: priceToast.ok ? '#10b981' : '#ef4444',
            }}>
              {priceToast.msg}
            </span>
          )}
          <div style={{ position:'relative' }}>
            <input
              placeholder="Search ticker or company…"
              value={searchQ}
              onChange={e=>{ doSearch(e.target.value); setShowSearch(true); }}
              onFocus={()=>setShowSearch(true)}
              onBlur={()=>setTimeout(()=>setShowSearch(false),200)}
              style={S.searchInput}
            />
            {showSearch && searchResults.length>0 && (
              <div style={S.dropdown}>
                {searchResults.map(r=>(
                  <div key={r.symbol} onClick={()=>highlightInScreener(r.symbol)} style={S.dropdownItem}>
                    <span style={{ fontFamily:'monospace', fontWeight:700, color:'#818cf8', minWidth:70 }}>{r.symbol.replace('.L','')}</span>
                    <span style={{ color:'#94a3b8', fontSize:13 }}>{r.name}</span>
                    <span style={{ marginLeft:'auto', fontSize:11, color:'#64748b' }}>{r.exchange}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </nav>

      {/* Body: sidebar + main */}
      <div style={{ display:'flex', maxWidth:1600, margin:'0 auto' }}>
        <div style={{ flexShrink:0, display: showSidebar && !sidebarCollapsed ? 'block' : 'none' }}>
          <Sidebar refreshKey={refreshKey} />
        </div>
        <main style={{ flex:1, padding:'32px 24px', minWidth:0 }}>
          <div style={{ display: page==='screener' ? 'block' : 'none' }}>
            <Screener onSelect={selectCompany} highlightSymbol={highlightSymbol}
              watchlist={watchlist} onToggleWatchlist={toggleWatchlist} />
          </div>
          <div style={{ display: page==='watchlist' ? 'block' : 'none' }}>
            <Screener onSelect={selectCompany}
              watchlist={watchlist} onToggleWatchlist={toggleWatchlist} watchlistMode />
          </div>
          {page==='rotation'    && <RotationTab refreshKey={refreshKey} />}
          {page==='breadth'     && <BreadthTab refreshKey={refreshKey} />}
          {page==='fear-greed'  && <FearGreedTab refreshKey={refreshKey} />}
          {page==='cross-asset' && <CrossAssetTab refreshKey={refreshKey} />}
          {page==='signals'        && <SignalsTab refreshKey={refreshKey} />}
          {page==='analyst-monitor' && <AnalystMonitorTab refreshKey={refreshKey} onSelect={selectCompany} />}
          {page==='rns'             && <RnsTab refreshKey={refreshKey} onSelect={selectCompany} />}
          {page==='analytics'       && <AnalyticsTab refreshKey={refreshKey} onSelect={selectCompany} />}
          {page==='company' && selectedSymbol && (
            <CompanyDetail symbol={selectedSymbol} onBack={goBack} />
          )}
        </main>
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const S = {
  loading:     { textAlign:'center', padding:64, color:'#666', fontSize:16, fontFamily:'monospace' },
  card:        { background:'#141414', borderRadius:4, padding:24, border:'1px solid #2a2a2a' },
  cardTitle:   { margin:'0 0 16px', fontFamily:'monospace', fontSize:13, fontWeight:700, color:'#f97316', textTransform:'uppercase', letterSpacing:1 },
  badge:       { background:'#1f1f1f', color:'#888', fontSize:11, padding:'3px 10px', borderRadius:2, fontFamily:'monospace' },
  tab:         { background:'none', border:'none', padding:'10px 18px', color:'#666', cursor:'pointer', borderBottom:'2px solid transparent', transition:'all 0.15s', fontSize:12, fontFamily:'monospace', textTransform:'uppercase', letterSpacing:0.5 },
  tabActive:   { color:'#f97316', borderBottom:'2px solid #f97316', fontWeight:700 },
  navBtn:      { background:'none', border:'none', padding:'6px 14px', color:'#999', cursor:'pointer', borderRadius:2, fontSize:12, fontFamily:'monospace' },
  navBtnActive:{ color:'#f97316', background:'#1f1200', fontWeight:700 },
  backBtn:     { background:'none', border:'none', color:'#f97316', cursor:'pointer', padding:'0 0 16px', display:'block', fontSize:13, fontFamily:'monospace' },
  searchInput: { width:260, padding:'8px 14px', borderRadius:2, border:'1px solid #2a2a2a', fontSize:13, outline:'none', background:'#0a0a0a', color:'#e5e5e5', fontFamily:'monospace' },
  dropdown:    { position:'absolute', right:0, top:'100%', width:420, background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, boxShadow:'0 8px 24px rgba(0,0,0,0.8)', zIndex:200, maxHeight:320, overflowY:'auto' },
  dropdownItem:{ display:'flex', alignItems:'center', gap:12, padding:'10px 16px', cursor:'pointer', borderBottom:'1px solid #1f1f1f' },
  select:      { padding:'8px 12px', borderRadius:2, border:'1px solid #2a2a2a', fontSize:12, background:'#141414', color:'#ccc', cursor:'pointer', outline:'none', fontFamily:'monospace' },
  table:       { width:'100%', borderCollapse:'separate', borderSpacing:0, fontSize:12, fontFamily:'monospace' },
  th:          { textAlign:'left', padding:'8px 12px', background:'#0a0a0a', color:'#f97316', fontSize:10, fontWeight:700, borderBottom:'1px solid #2a2a2a', whiteSpace:'nowrap', textTransform:'uppercase', letterSpacing:0.5, position:'sticky', top:0, zIndex:1 },
  td:          { padding:'9px 12px', borderBottom:'1px solid #1a1a1a', color:'#ccc', whiteSpace:'nowrap' },
  tdNum:       { padding:'9px 12px', borderBottom:'1px solid #1a1a1a', textAlign:'right', fontFamily:'monospace', fontSize:12, whiteSpace:'nowrap', color:'#e5e5e5' },
  tooltip:     { background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:12, color:'#e5e5e5', fontFamily:'monospace' },
};
