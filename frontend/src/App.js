import { useState, useEffect, useCallback } from 'react';
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts';
import { API, fmt, gc } from './utils';
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
  const [tab, setTab]         = useState('overview');
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

  const tabs = ['overview','financials','valuation','health','growth'];

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
          <div style={{ fontSize:30, fontFamily:'DM Serif Display,serif', color:'#f1f5f9' }}>{fmt(snap.market_cap,'currency')}</div>
          <div style={{ fontSize:12, color:'#64748b' }}>Market Cap</div>
          {snap.enterprise_value && <div style={{ fontSize:13, color:'#94a3b8', marginTop:2 }}>EV: {fmt(snap.enterprise_value,'currency')}</div>}
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

      {/* OVERVIEW */}
      {tab==='overview' && (
        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(155px,1fr))', gap:10 }}>
            <MetricCard label="Revenue"       value={fmt(snap.revenue,'currency')} />
            <MetricCard label="Net Income"    value={fmt(snap.net_income,'currency')} color={snap.net_income>0?'#10b981':'#ef4444'} />
            <MetricCard label="EBITDA"        value={fmt(snap.ebitda,'currency')} />
            <MetricCard label="Free Cash Flow"value={fmt(snap.fcf,'currency')} color={snap.fcf>0?'#10b981':'#ef4444'} />
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
            <h3 style={S.cardTitle}>Revenue & Net Income (Annual £B)</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={annualChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
                <XAxis dataKey="year" tick={{ fontSize:11, fill:'#666', fontFamily:'monospace' }} />
                <YAxis tick={{ fontSize:11, fill:'#666', fontFamily:'monospace' }} />
                <Tooltip formatter={v=>'£'+(v?.toFixed(2))+'B'} contentStyle={S.tooltip} />
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
            <h3 style={S.cardTitle}>Revenue, EBITDA & FCF (Annual £B)</h3>
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={annualChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                <defs>
                  <linearGradient id="gR" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#6366f1" stopOpacity={0.3}/><stop offset="95%" stopColor="#6366f1" stopOpacity={0}/></linearGradient>
                  <linearGradient id="gE" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#10b981" stopOpacity={0.25}/><stop offset="95%" stopColor="#10b981" stopOpacity={0}/></linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                <XAxis dataKey="year" tick={{ fontSize:11 }} />
                <YAxis tick={{ fontSize:11 }} />
                <Tooltip formatter={v=>'£'+(v?.toFixed(2))+'B'} contentStyle={S.tooltip} />
                <Area type="monotone" dataKey="revenue"    stroke="#6366f1" fill="url(#gR)" strokeWidth={2} name="Revenue" />
                <Area type="monotone" dataKey="ebitda"     stroke="#10b981" fill="url(#gE)" strokeWidth={2} name="EBITDA" />
                <Line type="monotone" dataKey="fcf"        stroke="#f59e0b" strokeWidth={2} dot={false} name="FCF" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20 }}>
            <div style={S.card}>
              <h3 style={S.cardTitle}>Quarterly Revenue (£B)</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={qChart} margin={{ top:5,right:10,bottom:5,left:0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a5f" />
                  <XAxis dataKey="q" tick={{ fontSize:10 }} />
                  <YAxis tick={{ fontSize:11 }} />
                  <Tooltip formatter={v=>'£'+(v?.toFixed(2))+'B'} contentStyle={S.tooltip} />
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
                  <Tooltip formatter={v=>'£'+(v?.toFixed(2))} contentStyle={S.tooltip} />
                  <ReferenceLine y={0} stroke="#334155" />
                  <Line type="monotone" dataKey="eps" stroke="#6366f1" strokeWidth={2.5} dot={{ r:4, fill:'#6366f1' }} name="EPS" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div style={S.card}>
            <h3 style={S.cardTitle}>Income Statement (£B)</h3>
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
                        <td key={r.period_end_date} style={{ ...S.tdNum, color: r[k]<0?'#ef4444':'inherit' }}>
                          {r[k] ? '£'+(r[k]/1e9).toFixed(2)+'B' : '—'}
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
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(145px,1fr))', gap:10 }}>
            {[['Current Ratio',snap.current_ratio,'ratio'],['Debt/Equity',snap.debt_to_equity,'ratio'],
              ['Debt/Assets',snap.debt_to_assets,'ratio'],['Cash',snap.cash_and_equiv,'currency'],
              ['Net Debt',snap.net_debt,'currency'],['Working Capital',snap.working_capital,'currency'],
              ['Interest Coverage',snap.interest_coverage,'ratio'],['Book Value',snap.book_value,'currency'],
            ].map(([l,v,t])=><MetricCard key={l} label={l} value={fmt(v,t)} />)}
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

// ── Screener ──────────────────────────────────────────────────────────────────
function Screener({ onSelect }) {
  const [filters, setFilters]     = useState({});
  const [filterOpts, setFilterOpts] = useState({ sectors:[], countries:[] });
  const [results, setResults]     = useState([]);
  const [loading, setLoading]     = useState(false);

  useEffect(() => {
    fetch(`${API}/filters`).then(r=>r.json()).then(setFilterOpts);
    runScreener({});
  }, []);

  const runScreener = useCallback((f) => {
    setLoading(true);
    const p = new URLSearchParams();
    if (f.sector)            p.set('sector', f.sector);
    if (f.country)           p.set('country', f.country);
    if (f.ftse_index)        p.set('ftse_index', f.ftse_index);
    if (f.min_market_cap)      p.set('min_market_cap', f.min_market_cap);
    if (f.max_pe)              p.set('max_pe', f.max_pe);
    if (f.min_roe)             p.set('min_roe', f.min_roe);
    if (f.min_revenue_growth)  p.set('min_revenue_growth', f.min_revenue_growth);
    p.set('limit', 350);
    fetch(`${API}/screener?${p}`)
      .then(r=>r.json())
      .then(d=>{ setResults(Array.isArray(d)?d:[]); setLoading(false); })
      .catch(()=>setLoading(false));
  }, []);

  const update = (k,v) => {
    const f = { ...filters, [k]: v };
    setFilters(f);
    runScreener(f);
  };

  return (
    <div>
      <h2 style={{ fontFamily:'DM Serif Display,serif', fontSize:26, color:'#f1f5f9', marginBottom:4 }}>Stock Screener</h2>
      <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:20 }}>
        <div style={{ fontSize:13, color:'#64748b' }}>{filters.ftse_index || 'All indices'}{filters.sector ? ` · ${filters.sector}` : ''}</div>
        <div style={{ background:'#334155', color:'#cbd5e1', borderRadius:20, padding:'2px 12px', fontSize:13, fontWeight:600 }}>{results.length} companies</div>
      </div>

      <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:20 }}>
        <select style={S.select} onChange={e=>update('sector',e.target.value)}>
          <option value="">All Sectors</option>
          {filterOpts.sectors.map(s=><option key={s} value={s}>{s}</option>)}
        </select>
        <select style={S.select} onChange={e=>update('ftse_index',e.target.value)}>
          <option value="">FTSE All-Share</option>
          <option value="FTSE 100">FTSE 100</option>
          <option value="FTSE 250">FTSE 250</option>
          <option value="FTSE 350">FTSE 350</option>
          <option value="FTSE SmallCap">FTSE SmallCap</option>
        </select>
        <select style={S.select} onChange={e=>update('min_market_cap',e.target.value)}>
          <option value="">Any Market Cap</option>
          <option value="1000000000">£1B+</option>
          <option value="10000000000">£10B+</option>
          <option value="50000000000">£50B+</option>
        </select>
        <select style={S.select} onChange={e=>update('max_pe',e.target.value)}>
          <option value="">Any P/E</option>
          <option value="15">P/E &lt; 15</option>
          <option value="25">P/E &lt; 25</option>
          <option value="40">P/E &lt; 40</option>
        </select>
        <select style={S.select} onChange={e=>update('min_roe',e.target.value)}>
          <option value="">Any ROE</option>
          <option value="0.1">ROE &gt; 10%</option>
          <option value="0.15">ROE &gt; 15%</option>
          <option value="0.2">ROE &gt; 20%</option>
        </select>
        <select style={S.select} onChange={e=>update('min_revenue_growth',e.target.value)}>
          <option value="">Any Rev Growth</option>
          <option value="0.05">Rev Growth &gt; 5%</option>
          <option value="0.1">Rev Growth &gt; 10%</option>
          <option value="0.2">Rev Growth &gt; 20%</option>
        </select>
      </div>

      {loading ? <div style={S.loading}>Screening…</div> : (
        <div style={{ overflowX:'auto' }}>
          <table style={S.table}>
            <thead>
              <tr>
                {[['Symbol',false],['Name',false],['Sector',false],['Index',false],['Mkt Cap',true],['Rev',true],['P/E',true],['P/B',true],['ROE',true],['ROIC',true],['Gross Margin',true],['Rev Growth',true],['D/E',true]].map(([h,num])=>(
                  <th key={h} style={{ ...S.th, textAlign: num?'right':'left' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.map((r,i) => (
                <tr key={r.symbol} onClick={()=>onSelect(r.symbol)}
                  style={{ background: i%2===0?'#1e293b':'#162032', cursor:'pointer' }}
                  onMouseEnter={e=>e.currentTarget.style.background='#334155'}
                  onMouseLeave={e=>e.currentTarget.style.background=i%2===0?'#1e293b':'#162032'}>
                  <td style={{ ...S.td, fontFamily:'monospace', fontWeight:700, color:'#818cf8' }}>{r.symbol.replace('.L','')}</td>
                  <td style={S.td}>{r.name?.slice(0,26)}</td>
                  <td style={{ ...S.td, color:'#64748b' }}>{r.sector?.slice(0,18)}</td>
                  <td style={{ ...S.td, color:'#64748b' }}>{r.ftse_index?.replace('FTSE ','')}</td>
                  <td style={S.tdNum}>{fmt(r.market_cap,'currency')}</td>
                  <td style={S.tdNum}>{fmt(r.revenue,'currency')}</td>
                  <td style={{ ...S.tdNum, color: r.price_to_earnings<15?'#10b981':r.price_to_earnings>40?'#ef4444':'inherit' }}>{fmt(r.price_to_earnings,'ratio')}</td>
                  <td style={S.tdNum}>{fmt(r.price_to_book,'ratio')}</td>
                  <td style={{ ...S.tdNum, color:gc(r.roe) }}>{fmt(r.roe,'pct')}</td>
                  <td style={{ ...S.tdNum, color:gc(r.roic) }}>{fmt(r.roic,'pct')}</td>
                  <td style={S.tdNum}>{fmt(r.gross_margin,'pct')}</td>
                  <td style={{ ...S.tdNum, color:gc(r.revenue_growth) }}>{fmt(r.revenue_growth,'pct')}</td>
                  <td style={{ ...S.tdNum, color: r.debt_to_equity>2?'#ef4444':'inherit' }}>{fmt(r.debt_to_equity,'ratio')}</td>
                </tr>
              ))}
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
  const [searchQ, setSearchQ]     = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [showSearch, setShowSearch] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const doSearch = (q) => {
    setSearchQ(q);
    if (q.length < 1) { setSearchResults([]); return; }
    fetch(`${API}/search?q=${encodeURIComponent(q)}`).then(r=>r.json()).then(setSearchResults);
  };

  const selectCompany = (sym) => {
    setSelectedSymbol(sym);
    setPage('company');
    setShowSearch(false);
    setSearchQ('');
    setSearchResults([]);
  };

  const handleRefresh = () => {
    setRefreshKey(k => k + 1);
    setLastUpdated(new Date().toLocaleTimeString('en-GB', { hour:'2-digit', minute:'2-digit' }));
  };

  const NAV_TABS = [
    { id: 'screener',    label: 'Screener'    },
    { id: 'rotation',    label: 'Rotation'    },
    { id: 'breadth',     label: 'Breadth'     },
    { id: 'cross-asset', label: 'Cross-Asset' },
    { id: 'signals',     label: 'Signals'     },
  ];

  const showSidebar = page !== 'company';

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
          <button onClick={handleRefresh} style={{ background:'#1a1a1a', color:'#666', border:'1px solid #2a2a2a', padding:'4px 10px', borderRadius:2, fontFamily:'monospace', fontSize:10, cursor:'pointer' }}>↻</button>
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
                  <div key={r.symbol} onClick={()=>selectCompany(r.symbol)} style={S.dropdownItem}>
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
        {showSidebar && <Sidebar refreshKey={refreshKey} />}
        <main style={{ flex:1, padding:'32px 24px', minWidth:0 }}>
          {page==='screener'    && <Screener onSelect={selectCompany} />}
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
  table:       { width:'100%', borderCollapse:'collapse', fontSize:12, fontFamily:'monospace' },
  th:          { textAlign:'left', padding:'8px 12px', background:'#0a0a0a', color:'#f97316', fontSize:10, fontWeight:700, borderBottom:'1px solid #2a2a2a', whiteSpace:'nowrap', textTransform:'uppercase', letterSpacing:0.5 },
  td:          { padding:'9px 12px', borderBottom:'1px solid #1a1a1a', color:'#ccc', whiteSpace:'nowrap' },
  tdNum:       { padding:'9px 12px', borderBottom:'1px solid #1a1a1a', textAlign:'right', fontFamily:'monospace', fontSize:12, whiteSpace:'nowrap', color:'#e5e5e5' },
  tooltip:     { background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:12, color:'#e5e5e5', fontFamily:'monospace' },
};
