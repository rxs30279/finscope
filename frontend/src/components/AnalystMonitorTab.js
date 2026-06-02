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
// Shrink a raw buy% toward a neutral 50% prior by analyst count.
const shrink = (buyPct, n) => {
  const total = n || 0;
  if (total === 0) return 50;
  return ((buyPct || 0) * total + 50 * SHRINK_K) / (total + SHRINK_K);
};
const shrunkBuyPct = (r) => shrink(r.buy_pct, r.total_analysts);

const compositeScore = (r) =>
  shrunkBuyPct(r) +
  Math.min(Math.max(r.upside_pct || 0, -50), 100) * 0.5 +
  (r.revision_score || 0) * 10;

// ── Biggest Movers (window-delta) ──────────────────────────────────────────────
// Lookback window for the movers panel; mirrors the backend default.
const MOVER_WINDOW_DAYS = 30;

// How much analysts have revised their view over the window. Combines the change in
// coverage-adjusted Buy% (rating) with the % change in mean price target (valuation).
// Both legs are roughly "points"; a row needs at least one leg to qualify.
const moverDeltas = (r) => {
  const hasBuy = r.buy_pct != null && r.base_buy_pct != null;
  const deltaBuy = hasBuy
    ? shrink(r.buy_pct, r.total_analysts) - shrink(r.base_buy_pct, r.base_total_analysts)
    : null;
  const hasTarget = r.price_target_mean != null && r.base_target != null && r.base_target > 0;
  const deltaTargetPct = hasTarget
    ? (r.price_target_mean - r.base_target) / r.base_target * 100
    : null;
  const score = (deltaBuy ?? 0) + (deltaTargetPct ?? 0);
  return { deltaBuy, deltaTargetPct, hasBuy, hasTarget, score };
};

// Ignore tiny wobbles so the lists show genuine moves only.
const MOVER_MIN_SCORE = 3;

export default function AnalystMonitorTab({ refreshKey, onSelect }) {
  const tickerLink = {
    color: '#e5e5e5', fontFamily: 'monospace', fontWeight: 700,
    cursor: 'pointer', textDecoration: 'none',
  };
  const [latest, setLatest]   = useState([]);
  const [movers, setMovers]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast]     = useState(null);
  const [search, setSearch]   = useState('');
  const [consensusFilter, setConsensusFilter] = useState('All');
  const [sortKey, setSortKey] = useState('buy_pct');
  const [sortDir, setSortDir] = useState('desc');

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`${API}/analysts/latest`).then(r => r.json()),
      fetch(`${API}/analysts/movers?window_days=${MOVER_WINDOW_DAYS}`).then(r => r.json()),
    ])
      .then(([l, m]) => {
        setLatest(Array.isArray(l) ? l : []);
        setMovers(Array.isArray(m) ? m : []);
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

  const dataAsOf = useMemo(
    () => stocksWithData.reduce((max, r) => (r.snapshot_date > max ? r.snapshot_date : max), ''),
    [stocksWithData]
  );

  // Movers scored once, then split into ranked upgrade / downgrade lists.
  const scoredMovers = useMemo(
    () => movers
      .map(r => ({ ...r, ...moverDeltas(r) }))
      .filter(r => r.hasBuy || r.hasTarget),
    [movers]
  );

  const topUpgraded = useMemo(
    () => scoredMovers
      .filter(r => r.score >= MOVER_MIN_SCORE)
      .sort((a, b) => b.score - a.score)
      .slice(0, 6),
    [scoredMovers]
  );

  const topDowngraded = useMemo(
    () => scoredMovers
      .filter(r => r.score <= -MOVER_MIN_SCORE)
      .sort((a, b) => a.score - b.score)
      .slice(0, 6),
    [scoredMovers]
  );

  // Most recent baseline date across movers — the "compared against" anchor.
  const moverBaseDate = useMemo(
    () => movers.reduce((max, r) => (r.base_date > max ? r.base_date : max), ''),
    [movers]
  );

  const filtered = useMemo(() => {
    let rows = stocksWithData;
    if (consensusFilter !== 'All') {
      rows = rows.filter(r => r.consensus === consensusFilter);
    }
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
    const getNum =
      sortKey === 'buy_pct' ? shrunkBuyPct :
      sortKey === 'signal'  ? compositeScore :
      (r) => r[sortKey];
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
  }, [stocksWithData, search, consensusFilter, sortKey, sortDir]);

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
          {dataAsOf && (
            <span style={{ fontSize: 10, color: '#555', fontFamily: 'monospace' }}>Data as of {dataAsOf}</span>
          )}
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
            {/* Column headers for the metric columns on the right */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, paddingBottom: 6, marginBottom: 4, borderBottom: '1px solid #2a2a2a' }}>
              <div style={{ flex: 1, fontSize: 9, color: '#555', textTransform: 'uppercase', letterSpacing: 1, fontFamily: 'monospace' }}>Stock</div>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexShrink: 0 }}>
                <span style={{ fontSize: 9, color: '#555', textTransform: 'uppercase', letterSpacing: 0.5, fontFamily: 'monospace', width: 50, textAlign: 'right' }}>Analysts</span>
                <span style={{ fontSize: 9, color: '#555', textTransform: 'uppercase', letterSpacing: 1, fontFamily: 'monospace', width: 60, textAlign: 'right' }}>Upside</span>
                <span style={{ fontSize: 9, color: '#555', textTransform: 'uppercase', letterSpacing: 1, fontFamily: 'monospace', width: 28, textAlign: 'right' }}>Rev</span>
              </div>
            </div>
            {stocks.length === 0 && <div style={{ color: '#444', fontSize: 11 }}>No data yet</div>}
            {stocks.map(r => (
              <div key={r.symbol} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, padding: '6px 0', borderBottom: '1px solid #1a1a1a' }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div>
                    <span
                      onClick={() => onSelect?.(r.symbol, 'analysts')}
                      style={{ ...tickerLink, fontSize: 12 }}
                    >
                      {r.symbol}
                    </span>
                    {r.name && (
                      <span
                        onClick={() => onSelect?.(r.symbol, 'analysts')}
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
                  <span title="Number of analysts" style={{ fontSize: 10, color: '#64748b', fontFamily: 'monospace', display: 'inline-block', width: 50, textAlign: 'right' }}>
                    {r.total_analysts != null ? `${r.total_analysts}a` : ''}
                  </span>
                  <span style={{ display: 'inline-block', width: 60, textAlign: 'right' }}>
                    <UpsideCell value={r.upside_pct} />
                  </span>
                  <span style={{ fontSize: 10, fontFamily: 'monospace', display: 'inline-block', width: 28, textAlign: 'right', color: r.revision_score > 0 ? '#10b981' : r.revision_score < 0 ? '#ef4444' : '#555' }}>
                    {r.revision_score != null ? (r.revision_score > 0 ? `↑${r.revision_score}` : r.revision_score < 0 ? `↓${Math.abs(r.revision_score)}` : '—') : ''}
                  </span>
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
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Filter by symbol, name, sector or market…"
              style={{ background: '#0a0a0a', border: '1px solid #2a2a2a', color: '#e5e5e5', padding: '6px 10px', borderRadius: 2, fontFamily: 'monospace', fontSize: 11, flex: 1, minWidth: 180, boxSizing: 'border-box' }}
            />
            <div style={{ display: 'flex', gap: 4 }}>
              {['All', 'Buy', 'Hold', 'Sell'].map(c => {
                const active = consensusFilter === c;
                const accent = CONSENSUS_COLORS[c]?.color || '#94a3b8';
                return (
                  <button
                    key={c}
                    onClick={() => setConsensusFilter(c)}
                    style={{
                      background: active ? (CONSENSUS_COLORS[c]?.bg || '#1a1a1a') : '#0a0a0a',
                      color: active ? accent : '#555',
                      border: `1px solid ${active ? accent : '#2a2a2a'}`,
                      padding: '5px 10px', borderRadius: 2, fontFamily: 'monospace',
                      fontSize: 10, fontWeight: 700, cursor: 'pointer', textTransform: 'uppercase', letterSpacing: 1,
                    }}
                  >
                    {c}
                  </button>
                );
              })}
            </div>
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
                    style={{ ...colStyle('signal'), textAlign: 'right' }}
                    onClick={() => toggleSort('signal')}
                    title="Composite bullish signal: coverage-adjusted Buy% + upside + revision momentum (drives Top Bullish/Bearish)"
                  >
                    Signal {sortKey === 'signal' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th
                    style={{ ...colStyle('buy_pct'), textAlign: 'right' }}
                    onClick={() => toggleSort('buy_pct')}
                    title={
                      "Buy% (adj) — the share of covering analysts rating the stock a Buy, " +
                      "adjusted for how many analysts actually cover it.\n\n" +
                      "Raw Buy% is unreliable when coverage is thin (one bullish analyst = 100%), " +
                      "so it's shrunk toward a neutral 50% prior with weight k=5: " +
                      "adj = (rawBuy% × analysts + 50 × 5) / (analysts + 5).\n\n" +
                      "Effect — the fewer the analysts, the more it's pulled toward 50%:\n" +
                      "• 1 analyst at 100% Buy → ~58%\n" +
                      "• 5 analysts at 100% Buy → ~75%\n" +
                      "• 10 analysts at 100% Buy → ~83%\n" +
                      "• well-covered names stay close to their raw Buy%.\n\n" +
                      "Hover a row's value to see its raw Buy% and analyst count."
                    }
                  >
                    Buy% (adj) {sortKey === 'buy_pct' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={{ ...colStyle('upside_pct'), textAlign: 'right' }} onClick={() => toggleSort('upside_pct')}>
                    Upside {sortKey === 'upside_pct' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={{ ...colStyle('price_target_mean'), textAlign: 'right' }} onClick={() => toggleSort('price_target_mean')} title="Mean analyst price target">
                    Target {sortKey === 'price_target_mean' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
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
                  <tr><td colSpan={11} style={{ ...S.td, color: '#444', textAlign: 'center', padding: 24 }}>No results</td></tr>
                )}
                {filtered.map(r => (
                  <tr key={r.symbol} style={{ borderBottom: '1px solid #141414' }}>
                    <td style={S.td}>
                      <span onClick={() => onSelect?.(r.symbol, 'analysts')} style={{ ...tickerLink, fontSize: 12 }}>
                        {r.symbol}
                      </span>
                    </td>
                    <td
                      onClick={() => onSelect?.(r.symbol, 'analysts')}
                      style={{ ...S.td, color: '#cbd5e1', cursor: 'pointer' }}
                    >
                      {r.name || '—'}
                    </td>
                    <td style={{ ...S.td, color: '#94a3b8' }}>{r.sector || '—'}</td>
                    <td style={{ ...S.td, color: '#64748b' }}>{r.ftse_index?.replace('FTSE ', '') || '—'}</td>
                    <td style={S.td}><ConsensusBadge value={r.consensus} /></td>
                    {(() => { const sig = compositeScore(r); return (
                      <td style={{ ...S.tdR, color: sig >= 50 ? '#10b981' : sig <= 35 ? '#ef4444' : '#94a3b8', fontWeight: 700 }}>
                        {sig.toFixed(0)}
                      </td>
                    ); })()}
                    <td style={S.tdR} title={r.buy_pct != null ? `Raw: ${r.buy_pct.toFixed(1)}% over ${r.total_analysts ?? 0} analysts` : ''}>
                      {r.buy_pct != null ? `${shrunkBuyPct(r).toFixed(1)}%` : '—'}
                    </td>
                    <td style={S.tdR}><UpsideCell value={r.upside_pct} /></td>
                    <td style={{ ...S.tdR, color: '#94a3b8' }}>{r.price_target_mean != null ? `${r.price_target_mean.toFixed(0)}p` : '—'}</td>
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

        {/* Biggest movers (window-delta) */}
        <div style={S.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
            <span
              style={{ fontSize: 10, color: '#f97316', textTransform: 'uppercase', letterSpacing: 1, fontFamily: 'monospace' }}
              title={`How far analysts have shifted their view over the last ${MOVER_WINDOW_DAYS} days — combines the change in coverage-adjusted Buy% with the % change in mean price target. Ranked, biggest moves first.`}
            >
              Biggest Movers · {MOVER_WINDOW_DAYS}d
            </span>
            <span style={{ fontSize: 9, color: '#555', fontFamily: 'monospace' }}>
              vs {moverBaseDate || `${MOVER_WINDOW_DAYS}d ago`}
            </span>
          </div>

          {scoredMovers.length === 0 && (
            <div style={{ color: '#444', fontSize: 11, fontFamily: 'monospace' }}>
              Not enough history yet — needs ~{MOVER_WINDOW_DAYS} days of snapshots
            </div>
          )}

          {[
            { title: '↑ Upgraded', stocks: topUpgraded, accent: '#10b981' },
            { title: '↓ Downgraded', stocks: topDowngraded, accent: '#ef4444' },
          ].map(({ title, stocks, accent }) => (
            <div key={title} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 9, color: accent, textTransform: 'uppercase', letterSpacing: 1, fontFamily: 'monospace', marginBottom: 4 }}>
                {title}
              </div>
              {scoredMovers.length > 0 && stocks.length === 0 && (
                <div style={{ color: '#444', fontSize: 10, fontFamily: 'monospace', padding: '2px 0' }}>None</div>
              )}
              {stocks.map(r => {
                const flipped = r.base_consensus && r.consensus && r.base_consensus !== r.consensus;
                return (
                  <div key={r.symbol} style={{ padding: '7px 0', borderBottom: '1px solid #1a1a1a' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
                      <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <span onClick={() => onSelect?.(r.symbol, 'analysts')} style={{ ...tickerLink, fontSize: 12 }}>{r.symbol}</span>
                        {r.name && (
                          <span onClick={() => onSelect?.(r.symbol, 'analysts')} style={{ color: '#94a3b8', fontFamily: 'monospace', fontSize: 10, marginLeft: 6, cursor: 'pointer' }}>
                            {r.name}
                          </span>
                        )}
                      </span>
                      {flipped && (
                        <span style={{ fontSize: 10, fontFamily: 'monospace', whiteSpace: 'nowrap', flexShrink: 0 }}>
                          <span style={{ color: '#666' }}>{r.base_consensus}</span>
                          <span style={{ color: '#555' }}>{' → '}</span>
                          <span style={{ color: CONSENSUS_COLORS[r.consensus]?.color || '#94a3b8' }}>{r.consensus}</span>
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, fontFamily: 'monospace', marginTop: 2, color: '#64748b', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                      {r.hasBuy && (
                        <span>
                          Buy% {shrink(r.base_buy_pct, r.base_total_analysts).toFixed(0)}
                          {' → '}
                          {shrink(r.buy_pct, r.total_analysts).toFixed(0)}
                          <span style={{ color: r.deltaBuy >= 0 ? '#10b981' : '#ef4444', marginLeft: 3 }}>
                            ({r.deltaBuy >= 0 ? '+' : ''}{r.deltaBuy.toFixed(0)}pt)
                          </span>
                        </span>
                      )}
                      {r.hasTarget && (
                        <span>
                          Target {r.base_target.toFixed(0)}p
                          {' → '}
                          {r.price_target_mean.toFixed(0)}p
                          <span style={{ color: r.deltaTargetPct >= 0 ? '#10b981' : '#ef4444', marginLeft: 3 }}>
                            ({r.deltaTargetPct >= 0 ? '+' : ''}{r.deltaTargetPct.toFixed(0)}%)
                          </span>
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>

      </div>
    </div>
  );
}
