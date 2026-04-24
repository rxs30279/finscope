import { useState, useEffect, useMemo } from 'react';
import { API } from '../utils';

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
      ...c, padding: '2px 8px', borderRadius: 2,
      fontSize: 10, fontFamily: 'monospace', fontWeight: 700
    }}>
      {value}
    </span>
  );
}

function UpsideCell({ value }) {
  if (value == null) return <span style={{ color: '#444' }}>—</span>;
  const color = value >= 0 ? '#10b981' : '#ef4444';
  return <span style={{ color, fontFamily: 'monospace', fontSize: 12 }}>{value >= 0 ? '+' : ''}{value.toFixed(1)}%</span>;
}

// Composite bullish score: shrunk-buy% + upside (capped at 100, halved) + revision_score * 10
// Shrinkage pulls buy_pct toward a neutral 50% prior with weight k=5, so a 1-analyst
// "100% bullish" stock counts as ~58%, while well-covered names stay close to their raw value.
const SHRINK_K = 5;
const shrunkBuyPct = (r) => {
  const n = r.total_analysts || 0;
  const raw = r.buy_pct || 0;
  if (n === 0) return 50;
  return (raw * n + 50 * SHRINK_K) / (n + SHRINK_K);
};

const compositeScore = (r) =>
  shrunkBuyPct(r) +
  Math.min(Math.max(r.upside_pct || 0, -50), 100) * 0.5 +
  (r.revision_score || 0) * 10;

export default function AnalystMonitorTab({ refreshKey, onSelect }) {
  const tickerLink = {
    color: '#e5e5e5', fontFamily: 'monospace', fontWeight: 700,
    cursor: 'pointer', textDecoration: 'none',
  };
  const [latest, setLatest]   = useState([]);
  const [changes, setChanges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast]     = useState(null);
  const [search, setSearch]   = useState('');
  const [sortKey, setSortKey] = useState('buy_pct');
  const [sortDir, setSortDir] = useState('desc');

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`${API}/analysts/latest`).then(r => r.json()),
      fetch(`${API}/analysts/changes`).then(r => r.json()),
    ])
      .then(([l, c]) => {
        setLatest(Array.isArray(l) ? l : []);
        setChanges(Array.isArray(c) ? c : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await fetch(`${API}/analysts/refresh`, { method: 'POST' });
      setToast('Refresh started — this takes a few minutes');
    } catch {
      setToast('Refresh failed');
    } finally {
      setRefreshing(false);
      setTimeout(() => setToast(null), 5000);
    }
  };

  const stocksWithData = useMemo(
    () => latest.filter(r => r.consensus != null),
    [latest]
  );

  const topBullish = useMemo(
    () => [...stocksWithData].sort((a, b) => compositeScore(b) - compositeScore(a)).slice(0, 5),
    [stocksWithData]
  );

  const topBearish = useMemo(
    () => [...stocksWithData].sort((a, b) => compositeScore(a) - compositeScore(b)).slice(0, 5),
    [stocksWithData]
  );

  const filtered = useMemo(() => {
    let rows = stocksWithData;
    if (search) {
      const q = search.toLowerCase();
      rows = rows.filter(r =>
        r.symbol?.toLowerCase().includes(q) ||
        r.name?.toLowerCase().includes(q) ||
        r.sector?.toLowerCase().includes(q) ||
        r.ftse_index?.toLowerCase().includes(q)
      );
    }
    const isStringKey = sortKey === 'name' || sortKey === 'sector' || sortKey === 'ftse_index';
    const getNum = sortKey === 'buy_pct' ? shrunkBuyPct : (r) => r[sortKey];
    return [...rows].sort((a, b) => {
      if (isStringKey) {
        const av = (a[sortKey] || '').toLowerCase();
        const bv = (b[sortKey] || '').toLowerCase();
        if (av === bv) return 0;
        return sortDir === 'desc' ? (av < bv ? 1 : -1) : (av < bv ? -1 : 1);
      }
      const av = getNum(a) ?? -Infinity;
      const bv = getNum(b) ?? -Infinity;
      return sortDir === 'desc' ? bv - av : av - bv;
    });
  }, [stocksWithData, search, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortKey(key); setSortDir('desc'); }
  };

  const colStyle = (key) => ({
    cursor: 'pointer', userSelect: 'none', color: sortKey === key ? '#f97316' : '#555',
    fontSize: 10, textTransform: 'uppercase', letterSpacing: 1,
    padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace',
  });

  const S = {
    card: { background: '#141414', border: '1px solid #2a2a2a', borderRadius: 3, padding: 16 },
    th:   { fontSize: 10, color: '#555', textTransform: 'uppercase', letterSpacing: 1, padding: '8px 12px', fontFamily: 'monospace', textAlign: 'left' },
    td:   { padding: '8px 12px', borderBottom: '1px solid #1a1a1a', fontSize: 12, fontFamily: 'monospace', color: '#e5e5e5' },
    tdR:  { padding: '8px 12px', borderBottom: '1px solid #1a1a1a', fontSize: 12, fontFamily: 'monospace', color: '#e5e5e5', textAlign: 'right' },
  };

  if (loading) return <div style={{ color: '#444', padding: 32, fontFamily: 'monospace' }}>Loading analyst data…</div>;

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ fontFamily: 'monospace', fontSize: 14, color: '#f97316', textTransform: 'uppercase', letterSpacing: 2, margin: 0 }}>
          Analyst Monitor
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {toast && <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace' }}>{toast}</span>}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            style={{ background: '#1a1a1a', color: refreshing ? '#444' : '#666', border: '1px solid #2a2a2a', padding: '4px 12px', borderRadius: 2, fontFamily: 'monospace', fontSize: 10, cursor: refreshing ? 'default' : 'pointer' }}
          >
            {refreshing ? '↻ Starting…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {/* Signals board */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        {[
          { title: 'Top Bullish', stocks: topBullish, accent: '#10b981' },
          { title: 'Top Bearish', stocks: topBearish, accent: '#ef4444' },
        ].map(({ title, stocks, accent }) => (
          <div key={title} style={S.card}>
            <div style={{ fontSize: 10, color: accent, textTransform: 'uppercase', letterSpacing: 1, fontFamily: 'monospace', marginBottom: 12 }}>{title}</div>
            {stocks.length === 0 && <div style={{ color: '#444', fontSize: 11 }}>No data yet</div>}
            {stocks.map(r => (
              <div key={r.symbol} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, padding: '6px 0', borderBottom: '1px solid #1a1a1a' }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div>
                    <span
                      onClick={() => onSelect?.(r.symbol)}
                      style={{ ...tickerLink, fontSize: 12 }}
                    >
                      {r.symbol}
                    </span>
                    {r.name && (
                      <span
                        onClick={() => onSelect?.(r.symbol)}
                        style={{ color: '#cbd5e1', fontFamily: 'monospace', fontSize: 11, marginLeft: 8, cursor: 'pointer' }}
                      >
                        {r.name}
                      </span>
                    )}
                    {' '}
                    <ConsensusBadge value={r.consensus} />
                  </div>
                  {r.sector && (
                    <div style={{ color: '#64748b', fontFamily: 'monospace', fontSize: 10, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.sector}
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexShrink: 0 }}>
                  {r.total_analysts != null && (
                    <span title="Number of analysts" style={{ fontSize: 10, color: '#64748b', fontFamily: 'monospace' }}>
                      {r.total_analysts}a
                    </span>
                  )}
                  <UpsideCell value={r.upside_pct} />
                  {r.revision_score != null && (
                    <span style={{ fontSize: 10, color: r.revision_score > 0 ? '#10b981' : r.revision_score < 0 ? '#ef4444' : '#555', fontFamily: 'monospace' }}>
                      {r.revision_score > 0 ? `↑${r.revision_score}` : r.revision_score < 0 ? `↓${Math.abs(r.revision_score)}` : '—'}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Main layout: table + change feed */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 16, alignItems: 'start' }}>

        {/* Full table */}
        <div style={S.card}>
          <div style={{ marginBottom: 12 }}>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Filter by symbol, name, sector or market…"
              style={{ background: '#0a0a0a', border: '1px solid #2a2a2a', color: '#e5e5e5', padding: '6px 10px', borderRadius: 2, fontFamily: 'monospace', fontSize: 11, width: '100%', boxSizing: 'border-box' }}
            />
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2a2a2a' }}>
                  <th style={S.th}>Symbol</th>
                  <th style={{ ...colStyle('name'), textAlign: 'left' }} onClick={() => toggleSort('name')}>
                    Name {sortKey === 'name' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={{ ...colStyle('sector'), textAlign: 'left' }} onClick={() => toggleSort('sector')}>
                    Sector {sortKey === 'sector' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={{ ...colStyle('ftse_index'), textAlign: 'left' }} onClick={() => toggleSort('ftse_index')}>
                    Market {sortKey === 'ftse_index' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={S.th}>Consensus</th>
                  <th
                    style={{ ...colStyle('buy_pct'), textAlign: 'right' }}
                    onClick={() => toggleSort('buy_pct')}
                    title="Buy % adjusted for analyst coverage (shrunk toward 50% with k=5)"
                  >
                    Buy% (adj) {sortKey === 'buy_pct' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={{ ...colStyle('upside_pct'), textAlign: 'right' }} onClick={() => toggleSort('upside_pct')}>
                    Upside {sortKey === 'upside_pct' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={{ ...colStyle('revision_score'), textAlign: 'right' }} onClick={() => toggleSort('revision_score')}>
                    Revisions {sortKey === 'revision_score' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={{ ...colStyle('total_analysts'), textAlign: 'right' }} onClick={() => toggleSort('total_analysts')}>
                    Analysts {sortKey === 'total_analysts' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr><td colSpan={9} style={{ ...S.td, color: '#444', textAlign: 'center', padding: 24 }}>No results</td></tr>
                )}
                {filtered.map(r => (
                  <tr key={r.symbol} style={{ borderBottom: '1px solid #141414' }}>
                    <td style={S.td}>
                      <span onClick={() => onSelect?.(r.symbol)} style={{ ...tickerLink, fontSize: 12 }}>
                        {r.symbol}
                      </span>
                    </td>
                    <td
                      onClick={() => onSelect?.(r.symbol)}
                      style={{ ...S.td, color: '#cbd5e1', cursor: 'pointer' }}
                    >
                      {r.name || '—'}
                    </td>
                    <td style={{ ...S.td, color: '#94a3b8' }}>{r.sector || '—'}</td>
                    <td style={{ ...S.td, color: '#64748b' }}>{r.ftse_index?.replace('FTSE ', '') || '—'}</td>
                    <td style={S.td}><ConsensusBadge value={r.consensus} /></td>
                    <td style={S.tdR} title={r.buy_pct != null ? `Raw: ${r.buy_pct.toFixed(1)}% over ${r.total_analysts ?? 0} analysts` : ''}>
                      {r.buy_pct != null ? `${shrunkBuyPct(r).toFixed(1)}%` : '—'}
                    </td>
                    <td style={S.tdR}><UpsideCell value={r.upside_pct} /></td>
                    <td style={{ ...S.tdR, color: r.revision_score > 0 ? '#10b981' : r.revision_score < 0 ? '#ef4444' : '#555' }}>
                      {r.revision_score != null ? (r.revision_score > 0 ? `+${r.revision_score}` : r.revision_score) : '—'}
                    </td>
                    <td style={S.tdR}>{r.total_analysts ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Change feed */}
        <div style={S.card}>
          <div style={{ fontSize: 10, color: '#f97316', textTransform: 'uppercase', letterSpacing: 1, fontFamily: 'monospace', marginBottom: 12 }}>
            Recent Changes
          </div>
          {changes.length === 0 && (
            <div style={{ color: '#444', fontSize: 11, fontFamily: 'monospace' }}>
              No significant changes since last refresh
            </div>
          )}
          {changes.map((c, i) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid #1a1a1a' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span onClick={() => onSelect?.(c.symbol)} style={{ ...tickerLink, fontSize: 12 }}>
                  {c.symbol}
                </span>
                <span style={{ color: '#444', fontSize: 10, fontFamily: 'monospace' }}>{c.snapshot_date}</span>
              </div>
              {c.prev_consensus !== c.consensus && (
                <div style={{ fontSize: 11, fontFamily: 'monospace', color: '#94a3b8' }}>
                  <span style={{ color: '#666' }}>{c.prev_consensus || '—'}</span>
                  {' → '}
                  <span style={{ color: CONSENSUS_COLORS[c.consensus]?.color || '#94a3b8' }}>{c.consensus}</span>
                </div>
              )}
              {c.buy_pct != null && c.prev_buy_pct != null &&
               Math.abs(c.buy_pct - c.prev_buy_pct) > 5 && (
                <div style={{ fontSize: 11, fontFamily: 'monospace' }}>
                  <span style={{ color: '#555' }}>Bullish </span>
                  <span style={{ color: '#666' }}>{c.prev_buy_pct.toFixed(0)}%</span>
                  {' → '}
                  <span style={{ color: c.buy_pct >= c.prev_buy_pct ? '#10b981' : '#ef4444' }}>
                    {c.buy_pct.toFixed(0)}%
                  </span>
                  <span style={{ color: c.buy_pct >= c.prev_buy_pct ? '#10b981' : '#ef4444', marginLeft: 4 }}>
                    ({c.buy_pct >= c.prev_buy_pct ? '+' : ''}{(c.buy_pct - c.prev_buy_pct).toFixed(1)}pts)
                  </span>
                </div>
              )}
              {c.upside_pct != null && (
                <div style={{ fontSize: 11, fontFamily: 'monospace' }}>
                  <span style={{ color: '#555' }}>Upside </span>
                  <UpsideCell value={c.upside_pct} />
                </div>
              )}
            </div>
          ))}
        </div>

      </div>
    </div>
  );
}
