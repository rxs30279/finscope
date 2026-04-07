import { useState, useEffect, useCallback } from 'react';
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts';
import { API, fmt, gc, currSym } from './utils';
import Sidebar from './components/Sidebar';
import RotationTab from './components/RotationTab';
import BreadthTab from './components/BreadthTab';
import CrossAssetTab from './components/CrossAssetTab';
import SignalsTab from './components/SignalsTab';


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

  const tabs = ['chart','overview','financials','valuation','health','growth'];

  return (
    <div>
      <button onClick={onBack} style={S.backBtn}>← Back to Screener</button>

      {/* Header */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', flexWrap:'wrap', gap:16, marginBottom:28 }}>
        <div>
          <div style={{ display:'flex', alignItems:'center', gap:14, marginBottom:10 }}>
            <div style={{ background:'#6366f1', color:'#fff', borderRadius:10, width:50, height:50, display:'flex', alignItems:'center', justifyContent:'center', fontFamily:'DM Serif Display,serif', fontSize:13, fontWeight:700 }}>
              {symbol.replace('.L','').slice(0,4)}
            </div>
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
                    {annual.slice(-5).map(r=><th key={r.period_end_date} style={S.th}>{r.period_end_date?.slice(0,4)}</th>)}
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
const EMPTY_FILTERS = { sector:'', ftse_index:'', min_market_cap:'', max_pe:'', min_roe:'', min_revenue_growth:'' };
const EMPTY_MODES   = { min_market_cap:'', max_pe:'', min_roe:'', min_revenue_growth:'' };
const EMPTY_SCORE_FILTERS = { min_momentum:'', min_quality:'', min_piotroski:'', max_risk:'' };

function Screener({ onSelect, highlightSymbol }) {
  const [filters, setFilters]       = useState(EMPTY_FILTERS);
  const [selectModes, setSelectModes] = useState(EMPTY_MODES);
  const [filterOpts, setFilterOpts] = useState({ sectors:[], countries:[] });
  const [results, setResults]       = useState([]);
  const [loading, setLoading]       = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [scoreFilters, setScoreFilters] = useState(EMPTY_SCORE_FILTERS);

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
    if (f.country)            p.set('country', f.country);
    if (f.ftse_index)         p.set('ftse_index', f.ftse_index);
    if (f.min_market_cap)     p.set('min_market_cap', f.min_market_cap);
    if (f.max_pe)             p.set('max_pe', f.max_pe);
    if (f.min_roe)            p.set('min_roe', f.min_roe);
    if (f.min_revenue_growth) p.set('min_revenue_growth', f.min_revenue_growth);
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

  const displayed = results.filter(r => {
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

  return (
    <div>
      <h2 style={{ fontFamily:'DM Serif Display,serif', fontSize:26, color:'#f1f5f9', marginBottom:4 }}>Stock Screener</h2>
      <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:20 }}>
        <div style={{ fontSize:13, color:'#64748b' }}>{filters.ftse_index || 'All indices'}{filters.sector ? ` · ${filters.sector}` : ''}</div>
        <div style={{ background:'#334155', color:'#cbd5e1', borderRadius:20, padding:'2px 12px', fontSize:13, fontWeight:600 }}>
          {displayed.length !== results.length ? `${displayed.length} / ${results.length}` : displayed.length} companies
        </div>
      </div>

      <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:8, alignItems:'center' }}>
        <select style={S.select} value={filters.sector} onChange={e=>update('sector',e.target.value)}>
          <option value="">All Sectors</option>
          {filterOpts.sectors.map(s=><option key={s} value={s}>{s}</option>)}
        </select>
        <select style={S.select} value={filters.ftse_index} onChange={e=>update('ftse_index',e.target.value)}>
          <option value="">FTSE All-Share</option>
          <option value="FTSE 100">FTSE 100</option>
          <option value="FTSE 250">FTSE 250</option>
          <option value="FTSE 350">FTSE 350</option>
          <option value="FTSE SmallCap">FTSE SmallCap</option>
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

      {showAdvanced && (
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
        </div>
      )}


      {loading ? <div style={S.loading}>Screening…</div> : (
        <div>
          <table style={S.table}>
            <thead>
              <tr>
                {[['Symbol',false],['Name',false],['Sector',false],['Index',false],['Mkt Cap',true],['P/E',true],['P/B',true],['ROE',true],['Rev Growth',true],['D/E',true],['Momentum',true],['Quality',true],['Value',true],['Risk',true]].map(([h,num])=>(
                  <th key={h} style={{ ...S.th, textAlign: num?'right':'left' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayed.map((r,i) => {
                const isHighlighted = r.symbol === highlightSymbol;
                const baseBg = isHighlighted ? '#2d1e00' : i%2===0 ? '#1e293b' : '#162032';
                return (
                <tr key={r.symbol} id={'row-'+r.symbol} onClick={()=>onSelect(r.symbol)}
                  style={{ background: baseBg, cursor:'pointer', boxShadow: isHighlighted ? 'inset 3px 0 0 #f97316' : 'none' }}
                  onMouseEnter={e=>e.currentTarget.style.background='#334155'}
                  onMouseLeave={e=>e.currentTarget.style.background=baseBg}>
                  <td style={{ ...S.td, fontFamily:'monospace', fontWeight:700, color:'#818cf8' }}>{r.symbol.replace('.L','')}</td>
                  <td style={S.td}>{r.name?.slice(0,26)}</td>
                  <td style={{ ...S.td, color:'#64748b' }}>{r.sector?.slice(0,18)}</td>
                  <td style={{ ...S.td, color:'#64748b' }}>{r.ftse_index?.replace('FTSE ','')}</td>
                  <td style={S.tdNum}>{fmt(r.market_cap,'currency',r.financial_currency)}</td>
                  <td style={{ ...S.tdNum, color: r.price_to_earnings<15?'#10b981':r.price_to_earnings>40?'#ef4444':'#ccc' }}>{fmt(r.price_to_earnings,'ratio')}</td>
                  <td style={S.tdNum}>{fmt(r.price_to_book,'ratio')}</td>
                  <td style={{ ...S.tdNum, color:gc(r.roe) }}>{fmt(r.roe,'pct')}</td>
                  <td style={{ ...S.tdNum, color:gc(r.revenue_growth) }}>{fmt(r.revenue_growth,'pct')}</td>
                  <td style={{ ...S.tdNum, color: r.debt_to_equity>2?'#ef4444':'#ccc' }}>{fmt(r.debt_to_equity,'ratio')}</td>
                  <td style={{ ...S.tdNum,
                    color: r.momentum_score == null ? '#444'
                         : r.momentum_score >= 7    ? '#10b981'
                         : r.momentum_score >= 4    ? '#f59e0b'
                         :                            '#ef4444',
                    fontWeight: 700,
                  }}>{r.momentum_score ?? '—'}</td>
                  <td style={{ ...S.tdNum,
                    color: r.quality_score == null ? '#444'
                         : r.quality_score >= 7    ? '#10b981'
                         : r.quality_score >= 4    ? '#f59e0b'
                         :                           '#ef4444',
                    fontWeight: 700,
                  }}>{r.quality_score ?? '—'}</td>
                  <td style={{ ...S.tdNum,
                    color: r.piotroski_score == null ? '#444'
                         : r.piotroski_score >= 7   ? '#10b981'
                         : r.piotroski_score >= 4   ? '#f59e0b'
                         :                            '#ef4444',
                    fontWeight: 700,
                  }}>{r.piotroski_score ?? '—'}</td>
                  <td style={{ ...S.tdNum,
                    color: r.risk_score == null ? '#444'
                         : r.risk_score <= 3    ? '#10b981'
                         : r.risk_score <= 6    ? '#f59e0b'
                         :                        '#ef4444',
                    fontWeight: 700,
                  }}>{r.risk_score ?? '—'}</td>
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
  const [page, setPage]           = useState('screener'); // screener | rotation | breadth | cross-asset | signals | company
  const [selectedSymbol, setSelectedSymbol] = useState(null);
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
  };

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

  const NAV_TABS = [
    { id: 'screener',    label: 'Screener'    },
    { id: 'rotation',    label: 'Rotation'    },
    { id: 'breadth',     label: 'Breadth'     },
    { id: 'cross-asset', label: 'Cross-Asset' },
    { id: 'signals',     label: 'Signals'     },
  ];

  const showSidebar = page !== 'company';
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div style={{ minHeight:'100vh', background:'#0a0a0a', fontFamily:'monospace' }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />

      {/* Nav */}
      <nav style={{ background:'#0a0a0a', borderBottom:'1px solid #2a2a2a', padding:'0 32px', display:'flex', alignItems:'center', height:52, position:'sticky', top:0, zIndex:100 }}>
        <div style={{ fontFamily:'monospace', fontSize:16, fontWeight:700, color:'#f97316', marginRight:32, cursor:'pointer', letterSpacing:2, textTransform:'uppercase' }} onClick={()=>setPage('screener')}>
          Egg Basket
        </div>
        <div style={{ display:'flex', gap:2 }}>
          {NAV_TABS.map(t => (
            <button key={t.id} style={{ ...S.navBtn, ...(page===t.id ? S.navBtnActive : {}) }} onClick={()=>setPage(t.id)}>
              {t.label}
            </button>
          ))}
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
      <div style={{ display:'flex', maxWidth:1400, margin:'0 auto' }}>
        {showSidebar && sidebarCollapsed && (
          <button onClick={() => setSidebarCollapsed(false)} title="Expand sidebar"
            style={{ position:'fixed', left:0, top:80, zIndex:200, background:'#141414', border:'1px solid #2a2a2a', borderLeft:'none', borderRadius:'0 4px 4px 0', color:'#555', fontSize:14, cursor:'pointer', padding:'8px 4px', lineHeight:1 }}>›</button>
        )}
        {showSidebar && !sidebarCollapsed && (
          <div style={{ position:'relative', flexShrink:0 }}>
            <Sidebar refreshKey={refreshKey} onCollapse={() => setSidebarCollapsed(true)} />
          </div>
        )}
        <main style={{ flex:1, padding:'32px 24px', minWidth:0 }}>
          <div style={{ display: page==='screener' ? 'block' : 'none' }}>
            <Screener onSelect={selectCompany} highlightSymbol={highlightSymbol} />
          </div>
          {page==='rotation'    && <RotationTab refreshKey={refreshKey} />}
          {page==='breadth'     && <BreadthTab refreshKey={refreshKey} />}
          {page==='cross-asset' && <CrossAssetTab refreshKey={refreshKey} />}
          {page==='signals'     && <SignalsTab refreshKey={refreshKey} />}
          {page==='company' && selectedSymbol && (
            <CompanyDetail symbol={selectedSymbol} onBack={()=>setPage('screener')} />
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
  navBtn:      { background:'none', border:'none', padding:'6px 14px', color:'#666', cursor:'pointer', borderRadius:2, fontSize:12, fontFamily:'monospace' },
  navBtnActive:{ color:'#f97316', background:'#1f1200', fontWeight:700 },
  backBtn:     { background:'none', border:'none', color:'#f97316', cursor:'pointer', padding:'0 0 16px', display:'block', fontSize:13, fontFamily:'monospace' },
  searchInput: { width:260, padding:'8px 14px', borderRadius:2, border:'1px solid #2a2a2a', fontSize:13, outline:'none', background:'#0a0a0a', color:'#e5e5e5', fontFamily:'monospace' },
  dropdown:    { position:'absolute', right:0, top:'100%', width:420, background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, boxShadow:'0 8px 24px rgba(0,0,0,0.8)', zIndex:200, maxHeight:320, overflowY:'auto' },
  dropdownItem:{ display:'flex', alignItems:'center', gap:12, padding:'10px 16px', cursor:'pointer', borderBottom:'1px solid #1f1f1f' },
  select:      { padding:'8px 12px', borderRadius:2, border:'1px solid #2a2a2a', fontSize:12, background:'#141414', color:'#ccc', cursor:'pointer', outline:'none', fontFamily:'monospace' },
  table:       { width:'100%', borderCollapse:'separate', borderSpacing:0, fontSize:12, fontFamily:'monospace' },
  th:          { textAlign:'left', padding:'8px 12px', background:'#0a0a0a', color:'#f97316', fontSize:10, fontWeight:700, borderBottom:'1px solid #2a2a2a', whiteSpace:'nowrap', textTransform:'uppercase', letterSpacing:0.5, position:'sticky', top:52, zIndex:1 },
  td:          { padding:'9px 12px', borderBottom:'1px solid #1a1a1a', color:'#ccc', whiteSpace:'nowrap' },
  tdNum:       { padding:'9px 12px', borderBottom:'1px solid #1a1a1a', textAlign:'right', fontFamily:'monospace', fontSize:12, whiteSpace:'nowrap', color:'#e5e5e5' },
  tooltip:     { background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:12, color:'#e5e5e5', fontFamily:'monospace' },
};
