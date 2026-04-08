import { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from 'recharts';
import { API, fmt } from '../utils';

const CONSENSUS_COLORS = {
  Buy:  { bg: '#0d3320', color: '#10b981' },
  Hold: { bg: '#1a1400', color: '#f59e0b' },
  Sell: { bg: '#2a0d0d', color: '#ef4444' },
};

function ConsensusBadge({ value }) {
  if (!value) return <span style={{ color: '#444' }}>—</span>;
  const c = CONSENSUS_COLORS[value] || { bg: '#1a1a1a', color: '#94a3b8' };
  return (
    <span style={{
      ...c, padding: '3px 10px', borderRadius: 2,
      fontSize: 11, fontFamily: 'monospace', fontWeight: 700
    }}>
      {value}
    </span>
  );
}

function ConsensusBar({ row }) {
  const total = row.total_analysts || 0;
  if (!total) return <div style={{ color: '#444', fontSize: 12 }}>No consensus data</div>;
  const segments = [
    { key: 'strong_buy',   label: 'Strong Buy',   color: '#059669' },
    { key: 'buy',          label: 'Buy',           color: '#10b981' },
    { key: 'hold',         label: 'Hold',          color: '#f59e0b' },
    { key: 'sell',         label: 'Sell',          color: '#ef4444' },
    { key: 'strong_sell',  label: 'Strong Sell',   color: '#b91c1c' },
  ];
  return (
    <div>
      <div style={{ display: 'flex', height: 24, borderRadius: 3, overflow: 'hidden', marginBottom: 10 }}>
        {segments.map(({ key, color }) => {
          const pct = total ? ((row[key] || 0) / total * 100) : 0;
          if (pct === 0) return null;
          return (
            <div key={key} style={{ width: `${pct}%`, background: color, transition: 'width 0.3s' }} />
          );
        })}
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {segments.map(({ key, label, color }) => (
          <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, fontFamily: 'monospace' }}>
            <div style={{ width: 8, height: 8, borderRadius: 1, background: color }} />
            <span style={{ color: '#666' }}>{label}</span>
            <span style={{ color: '#e5e5e5', fontWeight: 700 }}>{row[key] || 0}</span>
          </div>
        ))}
        <span style={{ color: '#444', fontSize: 11 }}>({total} analysts)</span>
      </div>
    </div>
  );
}

function PriceTargetRange({ row }) {
  const { price_target_low: low, price_target_high: high,
          price_target_mean: mean, price_target_median: median,
          current_price: current } = row;
  if (!low || !high || !current) return <div style={{ color: '#444', fontSize: 12 }}>No price target data</div>;
  const range = high - low;
  if (range <= 0) return null;
  const pct  = (v) => Math.max(0, Math.min(100, ((v - low) / range * 100)));
  const markers = [
    { val: current, label: 'Current', color: '#6366f1' },
    { val: mean,    label: 'Mean',    color: '#f97316' },
    { val: median,  label: 'Median',  color: '#a855f7' },
  ].filter(m => m.val);

  return (
    <div>
      <div style={{ position: 'relative', height: 28, margin: '16px 0 32px' }}>
        {/* Track */}
        <div style={{
          position: 'absolute', top: '50%', left: 0, right: 0,
          height: 4, background: '#2a2a2a', transform: 'translateY(-50%)', borderRadius: 2
        }} />
        {/* Buy zone (low → mean) */}
        <div style={{
          position: 'absolute', top: '50%',
          left: `${pct(low)}%`, width: `${pct(mean) - pct(low)}%`,
          height: 4, background: '#10b98144', transform: 'translateY(-50%)'
        }} />
        {/* Markers */}
        {markers.map(({ val, label, color }) => (
          <div key={label} style={{
            position: 'absolute', top: '50%', left: `${pct(val)}%`,
            transform: 'translate(-50%, -50%)',
          }}>
            <div style={{ width: 12, height: 12, borderRadius: '50%', background: color, border: '2px solid #0a0a0a' }} />
            <div style={{
              position: 'absolute', top: 16, left: '50%', transform: 'translateX(-50%)',
              fontSize: 9, color, fontFamily: 'monospace', whiteSpace: 'nowrap'
            }}>
              {label}<br />{val?.toFixed(0)}p
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#444', fontFamily: 'monospace' }}>
        <span>Low: {low?.toFixed(0)}p</span>
        {row.upside_pct != null && (
          <span style={{ color: row.upside_pct >= 0 ? '#10b981' : '#ef4444', fontWeight: 700 }}>
            {row.upside_pct >= 0 ? '+' : ''}{row.upside_pct?.toFixed(1)}% to mean target
          </span>
        )}
        <span>High: {high?.toFixed(0)}p</span>
      </div>
    </div>
  );
}

export default function AnalystTab({ symbol }) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/analysts/${encodeURIComponent(symbol)}`)
      .then(r => r.ok ? r.json() : [])
      .then(d => { setHistory(Array.isArray(d) ? d : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [symbol]);

  if (loading) return <div style={{ color: '#444', padding: 32, fontFamily: 'monospace' }}>Loading analyst data…</div>;
  if (!history.length) return <div style={{ color: '#444', padding: 32, fontFamily: 'monospace' }}>No analyst data available for {symbol}</div>;

  // Latest snapshot is last in array (ORDER BY ASC)
  const latest = history[history.length - 1];
  const trendData = history.map(r => ({
    date: r.snapshot_date,
    buy_pct: r.buy_pct,
  }));

  const cardStyle = {
    background: '#141414', border: '1px solid #2a2a2a',
    borderRadius: 3, padding: 20, marginBottom: 16
  };
  const titleStyle = {
    fontSize: 10, color: '#666', textTransform: 'uppercase',
    letterSpacing: 1, fontFamily: 'monospace', marginBottom: 14, marginTop: 0
  };

  return (
    <div>
      {/* Header row: consensus label + key numbers */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 20, flexWrap: 'wrap' }}>
        <ConsensusBadge value={latest.consensus} />
        {latest.buy_pct != null && (
          <span style={{ color: '#94a3b8', fontSize: 12, fontFamily: 'monospace' }}>
            {latest.buy_pct?.toFixed(1)}% bullish
          </span>
        )}
        {latest.total_analysts != null && (
          <span style={{ color: '#555', fontSize: 12, fontFamily: 'monospace' }}>
            {latest.total_analysts} analysts
          </span>
        )}
      </div>

      {/* Panel 1: Consensus bar */}
      <div style={cardStyle}>
        <p style={titleStyle}>Analyst Consensus</p>
        <ConsensusBar row={latest} />
      </div>

      {/* Panel 2: Price target range */}
      <div style={cardStyle}>
        <p style={titleStyle}>Price Target Range</p>
        <PriceTargetRange row={latest} />
      </div>

      {/* Panel 3: Consensus trend (only if ≥2 snapshots) */}
      {trendData.length >= 2 && (
        <div style={cardStyle}>
          <p style={titleStyle}>Consensus Trend — % Bullish</p>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={trendData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#555', fontFamily: 'monospace' }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#555', fontFamily: 'monospace' }} unit="%" />
              <Tooltip
                formatter={v => [`${v?.toFixed(1)}%`, 'Buy%']}
                contentStyle={{ background: '#141414', border: '1px solid #2a2a2a', borderRadius: 2, fontFamily: 'monospace', fontSize: 11 }}
              />
              <Line type="monotone" dataKey="buy_pct" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} name="Buy%" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Panel 4: Estimates & revisions */}
      <div style={cardStyle}>
        <p style={titleStyle}>Estimates & Revisions</p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          <div>
            <div style={{ fontSize: 10, color: '#555', marginBottom: 10, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: 1 }}>EPS Estimates</div>
            {[
              ['Current Year', latest.eps_est_current_yr],
              ['Next Year',    latest.eps_est_next_yr],
              ['Current Q',    latest.eps_est_current_q],
              ['Next Q',       latest.eps_est_next_q],
            ].map(([label, val]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #1a1a1a', fontSize: 12, fontFamily: 'monospace' }}>
                <span style={{ color: '#666' }}>{label}</span>
                <span style={{ color: '#e5e5e5' }}>{val != null ? val.toFixed(2) : '—'}</span>
              </div>
            ))}
          </div>
          <div>
            <div style={{ fontSize: 10, color: '#555', marginBottom: 10, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: 1 }}>Estimate Revisions (30d)</div>
            <div style={{ display: 'flex', gap: 20, marginBottom: 12 }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#10b981', fontFamily: 'monospace' }}>
                  ↑{latest.revisions_up_30d ?? '—'}
                </div>
                <div style={{ fontSize: 10, color: '#444' }}>Up</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#ef4444', fontFamily: 'monospace' }}>
                  ↓{latest.revisions_down_30d ?? '—'}
                </div>
                <div style={{ fontSize: 10, color: '#444' }}>Down</div>
              </div>
            </div>
            {[
              ['Current Year EPS Growth', latest.eps_growth_current_yr],
              ['Next Year EPS Growth',    latest.eps_growth_next_yr],
            ].map(([label, val]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #1a1a1a', fontSize: 12, fontFamily: 'monospace' }}>
                <span style={{ color: '#666' }}>{label}</span>
                <span style={{ color: val >= 0 ? '#10b981' : '#ef4444' }}>
                  {val != null ? `${(val * 100).toFixed(1)}%` : '—'}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
