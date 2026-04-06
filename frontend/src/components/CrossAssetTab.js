import { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, Brush
} from 'recharts';
import { API } from '../utils';

function AssetCard({ label, item, decimals = 2, prefix = '', suffix = '' }) {
  if (!item) return (
    <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:16 }}>
      <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>{label}</div>
      <div style={{ color:'#333', fontSize:18, fontWeight:700, fontFamily:'monospace' }}>—</div>
    </div>
  );

  const { value, pct_change, bias } = item;
  const chgColor = pct_change === null ? '#555' : pct_change > 0 ? '#10b981' : pct_change < 0 ? '#ef4444' : '#f59e0b';
  const arrow = pct_change === null ? '' : pct_change > 0.001 ? ' ↑' : pct_change < -0.001 ? ' ↓' : ' →';

  return (
    <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:16 }}>
      <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>{label}</div>
      <div style={{ color:'#e5e5e5', fontSize:20, fontWeight:700, fontFamily:'monospace' }}>
        {value !== null && value !== undefined ? `${prefix}${value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}` : '—'}
      </div>
      <div style={{ color: chgColor, fontSize:10, marginTop:4 }}>
        {pct_change !== null && pct_change !== undefined
          ? `${pct_change > 0 ? '+' : ''}${(pct_change * 100).toFixed(2)}%${arrow}`
          : '—'}
      </div>
      {bias && <div style={{ color:'#555', fontSize:9, marginTop:4 }}>{bias}</div>}
    </div>
  );
}

function ZScoreCard({ label, item }) {
  if (!item) return <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:16 }}><div style={{ color:'#444', fontSize:9 }}>{label}</div><div style={{ color:'#333' }}>—</div></div>;
  const { zscore, bias } = item;
  const color = zscore === null ? '#555' : zscore < -1 ? '#ef4444' : zscore > 1 ? '#10b981' : '#f59e0b';
  return (
    <div style={{ background: zscore !== null && zscore < -1 ? '#1a0a0a' : '#141414', border:`1px solid ${zscore !== null && zscore < -1 ? '#3a1a1a' : '#2a2a2a'}`, borderRadius:2, padding:16 }}>
      <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>{label}</div>
      <div style={{ color, fontSize:20, fontWeight:700, fontFamily:'monospace' }}>
        {zscore !== null && zscore !== undefined ? `${zscore > 0 ? '+' : ''}${zscore.toFixed(2)}σ` : '—'}
      </div>
      {bias && <div style={{ color:'#555', fontSize:9, marginTop:4 }}>{bias}</div>}
    </div>
  );
}

const MATURITIES = [
  { key: 'y2',  label: '2Y'  },
  { key: 'y5',  label: '5Y'  },
  { key: 'y10', label: '10Y' },
  { key: 'y20', label: '20Y' },
  { key: 'y30', label: '30Y' },
];

const MATURITY_COLORS = {
  y2:  '#f97316',
  y5:  '#f59e0b',
  y10: '#10b981',
  y20: '#60a5fa',
  y30: '#a78bfa',
};

function GiltSnapshotChart({ snapshot }) {
  if (!snapshot || Object.keys(snapshot).length === 0) {
    return <div style={{ color:'#333', fontFamily:'monospace', fontSize:11 }}>No gilt data available</div>;
  }

  const data = MATURITIES.map(({ key, label }) => {
    const maturity = parseInt(key.slice(1));
    return { label, yield: snapshot[maturity] ?? null };
  }).filter(d => d.yield !== null);

  const isInverted = data.length >= 2 && data[0].yield > data[data.length - 1].yield;
  const curveColor = isInverted ? '#ef4444' : '#10b981';
  const curveLabel = isInverted ? 'Inverted' : data[0]?.yield === data[data.length - 1]?.yield ? 'Flat' : 'Normal';

  return (
    <div>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
        <div style={{ color:'#555', fontSize:9, textTransform:'uppercase', letterSpacing:1 }}>Current Curve</div>
        <div style={{ color: curveColor, fontSize:9, fontWeight:700 }}>{curveLabel}</div>
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top:5, right:10, bottom:5, left:0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
          <XAxis dataKey="label" tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }} />
          <YAxis
            tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }}
            tickFormatter={v => `${v.toFixed(1)}%`}
            domain={['auto', 'auto']}
          />
          <Tooltip
            contentStyle={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:11, fontFamily:'monospace' }}
            formatter={v => [`${v.toFixed(2)}%`, 'Yield']}
          />
          <Line type="monotone" dataKey="yield" stroke={curveColor} strokeWidth={2} dot={{ r:4, fill:curveColor }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function GiltHistoryChart({ history }) {
  const [hidden, setHidden] = useState({});

  if (!history || history.length === 0) {
    return <div style={{ color:'#333', fontFamily:'monospace', fontSize:11 }}>No history available</div>;
  }

  const step = Math.max(1, Math.floor(history.length / 260));
  const thinned = history.filter((_, i) => i % step === 0);

  const toggleLine = (key) => setHidden(h => ({ ...h, [key]: !h[key] }));

  return (
    <div>
      <div style={{ color:'#555', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:8 }}>5-Year History</div>
      {/* Custom legend — click to toggle lines */}
      <div style={{ display:'flex', gap:12, marginBottom:8, flexWrap:'wrap' }}>
        {MATURITIES.map(({ key, label }) => (
          <span
            key={key}
            onClick={() => toggleLine(key)}
            style={{
              cursor:'pointer',
              fontSize:9,
              fontFamily:'monospace',
              color: hidden[key] ? '#333' : MATURITY_COLORS[key],
              textDecoration: hidden[key] ? 'line-through' : 'none',
              userSelect:'none',
            }}
          >
            {label}
          </span>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={thinned} margin={{ top:5, right:10, bottom:5, left:0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
          <XAxis
            dataKey="date"
            tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }}
            tickFormatter={d => d.slice(0, 7)}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }}
            tickFormatter={v => `${v.toFixed(1)}%`}
            domain={['auto', 'auto']}
          />
          <Tooltip
            contentStyle={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:10, fontFamily:'monospace' }}
            formatter={(v, name) => [v !== null ? `${v.toFixed(2)}%` : '—', name.toUpperCase()]}
            labelFormatter={l => l}
          />
          <Brush dataKey="date" height={28} stroke="#444" fill="#1a1a1a" travellerWidth={8}
            tickFormatter={d => d.slice(0, 7)}
            style={{ fontSize: 9, fontFamily: 'monospace' }}
          />
          {MATURITIES.map(({ key }) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={hidden[key] ? 'transparent' : MATURITY_COLORS[key]}
              strokeWidth={1.5}
              dot={false}
              connectNulls={false}
              hide={hidden[key]}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function CrossAssetTab({ refreshKey }) {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [giltData, setGiltData] = useState(null);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/market/cross-asset`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  useEffect(() => {
    fetch(`${API}/market/gilt-yields`)
      .then(r => r.json())
      .then(setGiltData)
      .catch(() => {});
  }, [refreshKey]);

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading cross-asset data…</div>;

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Cross-Asset</h2>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12 }}>
        <AssetCard label="GBP / USD"        item={data?.gbpusd}   decimals={4} />
        <AssetCard label="Brent Crude"     item={data?.brent}    decimals={2} prefix="$" />
        <AssetCard label="Gold"            item={data?.gold}     decimals={0} prefix="$" />
        <ZScoreCard label="Gilt vs Utilities (z-score)" item={data?.gilt_vs_utilities} />
      </div>
      {giltData && (
        <div style={{ marginTop:24 }}>
          <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:16 }}>
            UK Gilt Yield Curve
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'2fr 3fr', gap:16 }}>
            <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 }}>
              <GiltSnapshotChart snapshot={giltData.snapshot} />
            </div>
            <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 }}>
              <GiltHistoryChart history={giltData.history} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
