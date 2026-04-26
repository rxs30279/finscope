import { useState, useEffect, useMemo } from 'react';
import { API } from '../utils';

const TIER_COLORS = {
  A: { bg: '#1f1200', color: '#f97316', label: 'Tier A' },
  B: { bg: '#0d1a2a', color: '#60a5fa', label: 'Tier B' },
  C: { bg: '#141414', color: '#555',    label: 'Tier C' },
};

const CATEGORY_LABELS = {
  profit_warning:    'Profit Warning',
  trading_update:    'Trading Update',
  final_results:     'Final Results',
  interim_results:   'Interim Results',
  quarterly:         'Quarterly',
  firm_offer:        'Firm Offer (2.7)',
  possible_offer:    'Possible Offer (2.4)',
  recommended_offer: 'Recommended Offer',
  strategic_review:  'Strategic Review',
  suspension:        'Suspension',
  going_concern:     'Going Concern',
  liquidation:       'Liquidation',
  delisting:         'Delisting',
  response_to:       'Response to Press',
  capital_markets:   'Capital Markets Day',
  capital_raise:     'Capital Raise',
  acquisition:       'Acquisition',
  disposal:          'Disposal',
  contract_win:      'Contract / Partnership',
  board_change:      'Board Change',
  drug_approval:     'Drug Approval',
  clinical_trial:    'Clinical Trial',
  drill_results:     'Drill Results',
  dividend_change:   'Dividend Change',
  update_statement:  'Operational Update',
};

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleString('en-GB', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}

function fmtAgo(iso) {
  if (!iso) return 'never';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1)  return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function TierBadge({ tier }) {
  const c = TIER_COLORS[tier] || TIER_COLORS.C;
  return (
    <span style={{
      background: c.bg, color: c.color,
      padding: '2px 8px', borderRadius: 2,
      fontSize: 10, fontFamily: 'monospace', fontWeight: 700,
      letterSpacing: 1,
    }}>{tier}</span>
  );
}

function ScoreCell({ value }) {
  if (value == null) return <span style={{ color: '#333', fontFamily: 'monospace', fontSize: 12 }}>—</span>;
  const colour =
    value >= 75 ? '#f97316' :
    value >= 50 ? '#60a5fa' :
    value >= 25 ? '#94a3b8' : '#555';
  return <span style={{ color: colour, fontFamily: 'monospace', fontSize: 12 }}>{value}</span>;
}

const ACTION_COLORS = {
  research: { color: '#f97316', bg: '#1f1200' },
  watch:    { color: '#60a5fa', bg: '#0d1a2a' },
  ignore:   { color: '#555',    bg: '#141414' },
};

function ActionPill({ action }) {
  if (!action) return <span style={{ color: '#333', fontFamily: 'monospace', fontSize: 10 }}>—</span>;
  const c = ACTION_COLORS[action] || ACTION_COLORS.ignore;
  return (
    <span style={{
      background: c.bg, color: c.color,
      padding: '2px 8px', borderRadius: 2,
      fontSize: 10, fontFamily: 'monospace', fontWeight: 700,
      letterSpacing: 1, textTransform: 'uppercase',
    }}>{action}</span>
  );
}

function KeywordTags({ hits }) {
  if (!hits || hits.length === 0) return null;
  return (
    <span style={{ marginLeft: 8 }}>
      {hits.map((h, i) => {
        const [kind] = h.split(':');
        const colour = kind === 'neg' ? '#ef4444' : kind === 'pos' ? '#10b981' : '#f59e0b';
        return (
          <span key={i} style={{
            fontSize: 9, color: colour, fontFamily: 'monospace',
            padding: '1px 5px', border: `1px solid ${colour}`,
            borderRadius: 2, marginLeft: 4, opacity: 0.8,
          }}>{h}</span>
        );
      })}
    </span>
  );
}

export default function RnsTab({ refreshKey, onSelect }) {
  const [rows, setRows]         = useState([]);
  const [loading, setLoading]   = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [pipelineStage, setPipelineStage] = useState(null);   // 'ingest' | 'summaries' | 'rank' | null
  const [elapsed, setElapsed]   = useState(0);                // seconds since refresh start
  const [toast, setToast]       = useState(null);
  const [hours, setHours]       = useState(72);
  const [minScore, setMinScore] = useState(20);
  const [tierFilter, setTierFilter] = useState('all');   // all | A | B | C
  const [search, setSearch]     = useState('');
  const [sortMode, setSortMode] = useState('llm');       // 'llm' | 'time'

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/rns/latest?min_score=${minScore}&hours=${hours}&limit=500`)
      .then(r => r.json())
      .then(d => {
        setRows(Array.isArray(d) ? d : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [refreshKey, hours, minScore]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setElapsed(0);
    setPipelineStage('ingest');
    const startedAt = Date.now();
    const elapsedTimer = setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 500);

    try {
      await fetch(`${API}/rns/pipeline?rank_hours=${hours}`, { method: 'POST' });
    } catch {
      clearInterval(elapsedTimer);
      setRefreshing(false);
      setPipelineStage(null);
      setToast('Refresh failed');
      setTimeout(() => setToast(null), 5000);
      return;
    }

    // Poll pipeline status until it reports not running. Timeout at 3 min.
    const startedPollMs = Date.now();
    const poll = setInterval(async () => {
      try {
        const s = await fetch(`${API}/rns/pipeline/status`).then(r => r.json());
        setPipelineStage(s.stage);
        if (!s.running) {
          clearInterval(poll);
          clearInterval(elapsedTimer);
          setRefreshing(false);
          setPipelineStage(null);
          setToast(`Refresh complete in ${Math.round((Date.now() - startedAt) / 1000)}s — reloading…`);
          // reload the feed
          fetch(`${API}/rns/latest?min_score=${minScore}&hours=${hours}&limit=500`)
            .then(r => r.json())
            .then(d => setRows(Array.isArray(d) ? d : []))
            .catch(() => {});
          setTimeout(() => setToast(null), 4000);
        } else if (Date.now() - startedPollMs > 180000) {
          clearInterval(poll);
          clearInterval(elapsedTimer);
          setRefreshing(false);
          setPipelineStage(null);
          setToast('Refresh timed out — check backend logs');
          setTimeout(() => setToast(null), 6000);
        }
      } catch {
        // transient poll failure — keep trying
      }
    }, 2000);
  };

  const filtered = useMemo(() => {
    let r = rows;
    if (tierFilter !== 'all') r = r.filter(x => x.tier === tierFilter);
    if (search) {
      const q = search.toLowerCase();
      r = r.filter(x =>
        x.ticker?.toLowerCase().includes(q) ||
        x.company_name?.toLowerCase().includes(q) ||
        x.headline?.toLowerCase().includes(q)
      );
    }
    if (sortMode === 'llm') {
      // Ranked rows first (by llm_score desc), then unranked (by published_at desc)
      r = [...r].sort((a, b) => {
        const aR = a.llm_score != null, bR = b.llm_score != null;
        if (aR && bR) return b.llm_score - a.llm_score;
        if (aR) return -1;
        if (bR) return 1;
        return new Date(b.published_at) - new Date(a.published_at);
      });
    }
    return r;
  }, [rows, tierFilter, search, sortMode]);

  const tierA = useMemo(() => rows.filter(r => r.tier === 'A'), [rows]);
  const tierB = useMemo(() => rows.filter(r => r.tier === 'B'), [rows]);
  const ranked = useMemo(() => rows.filter(r => r.llm_score != null), [rows]);
  const lastUpdatedAt = useMemo(() => {
    let m = 0;
    for (const r of rows) {
      if (r.fetched_at) {
        const t = new Date(r.fetched_at).getTime();
        if (t > m) m = t;
      }
    }
    return m ? new Date(m).toISOString() : null;
  }, [rows]);

  const S = {
    card: { background: '#141414', border: '1px solid #2a2a2a', borderRadius: 3, padding: 16 },
    th:   { fontSize: 10, color: '#555', textTransform: 'uppercase', letterSpacing: 1, padding: '8px 12px', fontFamily: 'monospace', textAlign: 'left', position: 'sticky', top: 0, background: '#141414', zIndex: 1 },
    td:   { padding: '10px 12px', borderBottom: '1px solid #1a1a1a', fontSize: 12, fontFamily: 'monospace', color: '#e5e5e5', verticalAlign: 'top' },
    pill: (active) => ({
      background: active ? '#1f1200' : 'none', color: active ? '#f97316' : '#666',
      border: '1px solid #2a2a2a', padding: '4px 10px', borderRadius: 2,
      fontFamily: 'monospace', fontSize: 10, cursor: 'pointer',
      letterSpacing: 1, textTransform: 'uppercase',
    }),
  };

  if (loading) return <div style={{ color: '#444', padding: 32, fontFamily: 'monospace' }}>Loading RNS feed…</div>;

  const renderRow = (r) => (
    <tr key={r.id} style={{ borderBottom: '1px solid #141414' }}>
      <td style={{ ...S.td, color: '#666', whiteSpace: 'nowrap' }}>{fmtTime(r.published_at)}</td>
      <td style={S.td}><TierBadge tier={r.tier} /></td>
      <td style={{ ...S.td, fontWeight: 700, whiteSpace: 'nowrap' }}>
        {r.ticker
          ? (r.symbol
              ? <span onClick={() => onSelect?.(r.symbol)}
                      title={`View ${r.symbol}`}
                      style={{ color: '#e5e5e5', cursor: 'pointer', textDecoration: 'none' }}>
                  {r.ticker}
                  <span style={{ color: '#6366f1', marginLeft: 4, fontWeight: 400, fontSize: 10 }}>↗</span>
                </span>
              : r.ticker)
          : '—'}
      </td>
      <td style={{ ...S.td, color: '#94a3b8', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {r.company_name || '—'}
      </td>
      <td style={S.td}>
        <a href={r.url} target="_blank" rel="noopener noreferrer"
           style={{ color: '#e5e5e5', textDecoration: 'none', borderBottom: '1px dotted #3a3a3a' }}>
          {r.headline}
        </a>
        <KeywordTags hits={r.keyword_hits} />
        {r.llm_thesis && (
          <div style={{ marginTop: 6, color: '#888', fontSize: 11, lineHeight: 1.4, maxWidth: 600 }}>
            {r.llm_thesis}
            {r.llm_risks && (
              <div style={{ marginTop: 3, color: '#5a5a5a', fontSize: 10 }}>
                <span style={{ color: '#ef4444' }}>risk:</span> {r.llm_risks}
              </div>
            )}
          </div>
        )}
      </td>
      <td style={{ ...S.td, color: '#666', fontSize: 11, whiteSpace: 'nowrap' }}>
        {CATEGORY_LABELS[r.category] || r.category || '—'}
      </td>
      <td style={{ ...S.td, textAlign: 'right' }}><ScoreCell value={r.score} /></td>
      <td style={{ ...S.td, textAlign: 'right' }}><ScoreCell value={r.llm_score} /></td>
      <td style={{ ...S.td, textAlign: 'center' }}><ActionPill action={r.llm_action} /></td>
    </tr>
  );

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
          <h2 style={{ fontFamily: 'monospace', fontSize: 14, color: '#f97316', textTransform: 'uppercase', letterSpacing: 2, margin: 0 }}>
            RNS News Screener
          </h2>
          <span style={{ fontSize: 10, color: '#555', fontFamily: 'monospace', letterSpacing: 1, textTransform: 'uppercase' }}>
            Last updated: <span style={{ color: '#888' }}>{fmtAgo(lastUpdatedAt)}</span>
            {lastUpdatedAt && (
              <span style={{ color: '#444', marginLeft: 6 }}>({fmtTime(lastUpdatedAt)})</span>
            )}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {toast && <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace' }}>{toast}</span>}
          <button
            onClick={(e) => { if (e.ctrlKey || e.metaKey) handleRefresh(); }}
            disabled={refreshing}
            style={{
              background: refreshing ? '#1f1200' : '#1a1a1a',
              color:      refreshing ? '#f97316' : '#f97316',
              border:     `1px solid ${refreshing ? '#f97316' : '#2a2a2a'}`,
              padding: '4px 12px', borderRadius: 2,
              fontFamily: 'monospace', fontSize: 10,
              cursor: refreshing ? 'default' : 'pointer',
              letterSpacing: 1, textTransform: 'uppercase',
              boxShadow: refreshing ? '0 0 8px rgba(249,115,22,0.4)' : 'none',
              transition: 'background 0.2s, box-shadow 0.2s, border-color 0.2s',
              minWidth: 160,
            }}>
            {refreshing
              ? `⟳ ${pipelineStage || 'starting'}… ${elapsed}s`
              : '↻ Refresh + AI rank'}
          </button>
        </div>
      </div>

      {/* Summary bar */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 20 }}>
        <div style={{ ...S.card, flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: 10, color: '#555', letterSpacing: 1, textTransform: 'uppercase', fontFamily: 'monospace' }}>Tier A — Significant</div>
          <div style={{ fontSize: 28, color: '#f97316', fontFamily: 'monospace', fontWeight: 700, marginTop: 4 }}>{tierA.length}</div>
        </div>
        <div style={{ ...S.card, flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: 10, color: '#555', letterSpacing: 1, textTransform: 'uppercase', fontFamily: 'monospace' }}>Tier B — Noteworthy</div>
          <div style={{ fontSize: 28, color: '#60a5fa', fontFamily: 'monospace', fontWeight: 700, marginTop: 4 }}>{tierB.length}</div>
        </div>
        <div style={{ ...S.card, flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: 10, color: '#555', letterSpacing: 1, textTransform: 'uppercase', fontFamily: 'monospace' }}>AI-Ranked</div>
          <div style={{ fontSize: 28, color: '#10b981', fontFamily: 'monospace', fontWeight: 700, marginTop: 4 }}>{ranked.length}</div>
        </div>
        <div style={{ ...S.card, flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: 10, color: '#555', letterSpacing: 1, textTransform: 'uppercase', fontFamily: 'monospace' }}>Total in feed</div>
          <div style={{ fontSize: 28, color: '#e5e5e5', fontFamily: 'monospace', fontWeight: 700, marginTop: 4 }}>{rows.length}</div>
        </div>
      </div>

      {/* Controls */}
      <div style={{ ...S.card, marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 10, color: '#555', letterSpacing: 1, textTransform: 'uppercase', fontFamily: 'monospace' }}>Window</span>
          <select value={hours} onChange={e => setHours(Number(e.target.value))}
            style={{ background: '#0a0a0a', color: '#e5e5e5', border: '1px solid #2a2a2a', padding: '4px 8px', fontFamily: 'monospace', fontSize: 11, borderRadius: 2 }}>
            <option value={6}>6 hours</option>
            <option value={12}>12 hours</option>
            <option value={24}>24 hours</option>
            <option value={48}>48 hours</option>
            <option value={72}>72 hours</option>
            <option value={168}>1 week</option>
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 10, color: '#555', letterSpacing: 1, textTransform: 'uppercase', fontFamily: 'monospace' }}>Min score</span>
          <select value={minScore} onChange={e => setMinScore(Number(e.target.value))}
            style={{ background: '#0a0a0a', color: '#e5e5e5', border: '1px solid #2a2a2a', padding: '4px 8px', fontFamily: 'monospace', fontSize: 11, borderRadius: 2 }}>
            <option value={0}>0 (all)</option>
            <option value={20}>20</option>
            <option value={40}>40 (Tier B+)</option>
            <option value={60}>60 (Tier A+)</option>
            <option value={75}>75 (high)</option>
          </select>
        </div>

        <div style={{ display: 'flex', gap: 4 }}>
          {['all', 'A', 'B', 'C'].map(t => (
            <button key={t} onClick={() => setTierFilter(t)} style={S.pill(tierFilter === t)}>
              {t === 'all' ? 'All tiers' : `Tier ${t}`}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 4 }}>
          <button onClick={() => setSortMode('llm')} style={S.pill(sortMode === 'llm')}>
            Sort: AI score
          </button>
          <button onClick={() => setSortMode('time')} style={S.pill(sortMode === 'time')}>
            Sort: Time
          </button>
        </div>

        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Filter ticker / company / headline…"
          style={{ background: '#0a0a0a', border: '1px solid #2a2a2a', color: '#e5e5e5', padding: '6px 10px', borderRadius: 2, fontFamily: 'monospace', fontSize: 11, flex: 1, minWidth: 200 }} />
      </div>

      {/* Table */}
      <div style={S.card}>
        <div style={{ maxHeight: 'calc(100vh - 380px)', overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #2a2a2a' }}>
                <th style={S.th}>Time</th>
                <th style={S.th}>Tier</th>
                <th style={S.th}>Ticker</th>
                <th style={S.th}>Company</th>
                <th style={S.th}>Headline / AI Thesis</th>
                <th style={S.th}>Category</th>
                <th style={{ ...S.th, textAlign: 'right' }}>Rules</th>
                <th style={{ ...S.th, textAlign: 'right' }}>AI</th>
                <th style={{ ...S.th, textAlign: 'center' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr><td colSpan={9} style={{ ...S.td, color: '#444', textAlign: 'center', padding: 32 }}>
                  No announcements in this window
                </td></tr>
              )}
              {filtered.map(renderRow)}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
