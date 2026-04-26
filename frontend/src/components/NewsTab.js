import { useState, useEffect } from 'react';
import { API } from '../utils';

const TIER_STYLE = {
  A: { bg:'#0d3320', color:'#10b981', label:'A' },
  B: { bg:'#1a1400', color:'#f59e0b', label:'B' },
  C: { bg:'#1a1a1a', color:'#666',    label:'C' },
};

const ACTION_STYLE = {
  buy:     { bg:'#0d3320', color:'#10b981' },
  watch:   { bg:'#1a1400', color:'#f59e0b' },
  avoid:   { bg:'#2a0d0d', color:'#ef4444' },
  neutral: { bg:'#1a1a1a', color:'#888'    },
};

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now - d;
  const diffH = diffMs / (1000 * 60 * 60);
  if (diffH < 24) return `${Math.max(1, Math.round(diffH))}h ago`;
  const diffD = diffH / 24;
  if (diffD < 30) return `${Math.round(diffD)}d ago`;
  return d.toLocaleDateString('en-GB', { day:'2-digit', month:'short', year:'2-digit' });
}

function RnsRow({ r }) {
  const tier = TIER_STYLE[r.tier] || TIER_STYLE.C;
  const action = (r.llm_action || '').toLowerCase();
  const actStyle = ACTION_STYLE[action];
  return (
    <div style={{ padding:'12px 14px', borderBottom:'1px solid #1a1a1a', display:'flex', gap:14, alignItems:'flex-start' }}>
      <div style={{ flexShrink:0, width:72, fontSize:10, color:'#666', fontFamily:'monospace', paddingTop:3 }}>
        {fmtTime(r.published_at)}
      </div>
      <span style={{
        background:tier.bg, color:tier.color, flexShrink:0,
        padding:'2px 7px', borderRadius:2, fontSize:9, fontFamily:'monospace', fontWeight:700,
        marginTop:2,
      }}>{tier.label}</span>
      <div style={{ flex:1, minWidth:0 }}>
        <a href={r.url} target="_blank" rel="noopener noreferrer" style={{ color:'#e5e5e5', fontSize:13, textDecoration:'none', fontFamily:'monospace', display:'block', lineHeight:1.5 }}>
          {r.headline}
        </a>
        {r.llm_thesis && (
          <div style={{ color:'#94a3b8', fontSize:11, marginTop:4, lineHeight:1.5 }}>
            {r.llm_thesis}
          </div>
        )}
        <div style={{ display:'flex', gap:10, marginTop:5, alignItems:'center', flexWrap:'wrap' }}>
          {r.wire && <span style={{ fontSize:9, color:'#555', fontFamily:'monospace' }}>{r.wire}</span>}
          {r.category && <span style={{ fontSize:9, color:'#666', fontFamily:'monospace' }}>· {r.category.replace(/_/g,' ')}</span>}
          {r.llm_score != null && <span style={{ fontSize:9, color:'#60a5fa', fontFamily:'monospace' }}>· AI {r.llm_score}</span>}
          {actStyle && (
            <span style={{ background:actStyle.bg, color:actStyle.color, padding:'1px 6px', borderRadius:2, fontSize:9, fontFamily:'monospace', fontWeight:700, textTransform:'uppercase' }}>
              {action}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function GoogleRow({ r }) {
  return (
    <div style={{ padding:'10px 14px', borderBottom:'1px solid #1a1a1a', display:'flex', gap:14, alignItems:'flex-start' }}>
      <div style={{ flexShrink:0, width:72, fontSize:10, color:'#666', fontFamily:'monospace', paddingTop:3 }}>
        {fmtTime(r.published_at)}
      </div>
      <div style={{ flex:1, minWidth:0 }}>
        <a href={r.link} target="_blank" rel="noopener noreferrer" style={{ color:'#e5e5e5', fontSize:13, textDecoration:'none', display:'block', lineHeight:1.5 }}>
          {r.title}
        </a>
        {r.source && (
          <div style={{ color:'#64748b', fontSize:10, marginTop:3, fontFamily:'monospace' }}>{r.source}</div>
        )}
      </div>
    </div>
  );
}

export default function NewsTab({ symbol }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [summary, setSummary] = useState(null);
  const [summarising, setSummarising] = useState(false);
  const [summaryError, setSummaryError] = useState(null);

  const load = (force = false) => {
    if (force) setRefreshing(true); else setLoading(true);
    const url = `${API}/news/${encodeURIComponent(symbol)}${force ? '?refresh=true' : ''}`;
    fetch(url)
      .then(r => r.json())
      .then(d => {
        setData(d);
        setSummary(d.summary || null);
        setLoading(false); setRefreshing(false);
      })
      .catch(() => { setLoading(false); setRefreshing(false); });
  };

  const generateSummary = () => {
    setSummarising(true);
    setSummaryError(null);
    fetch(`${API}/news/${encodeURIComponent(symbol)}/summary`, { method: 'POST' })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(d => { setSummary(d); setSummarising(false); })
      .catch(err => { setSummaryError(err.message); setSummarising(false); });
  };

  useEffect(() => {
    setSummary(null); setSummaryError(null);
    load(false);
    /* eslint-disable-next-line */
  }, [symbol]);

  if (loading) {
    return <div style={{ color:'#666', fontFamily:'monospace', padding:32, textAlign:'center' }}>Loading news…</div>;
  }
  if (!data) {
    return <div style={{ color:'#666', fontFamily:'monospace', padding:32, textAlign:'center' }}>No news available</div>;
  }

  const rns = Array.isArray(data.rns) ? data.rns : [];
  const google = Array.isArray(data.google) ? data.google : [];

  const themes = Array.isArray(summary?.themes) ? summary.themes : [];

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
        <div style={{ color:'#64748b', fontSize:11, fontFamily:'monospace' }}>
          Last 6 months · {rns.length} RNS · {google.length} press
          {data.google_fetched_at && <> · Google updated {fmtTime(data.google_fetched_at)}</>}
        </div>
        <button
          onClick={() => load(true)}
          disabled={refreshing}
          style={{
            background:'#1a1a1a', color: refreshing ? '#f97316' : '#666',
            border:'1px solid #2a2a2a', padding:'4px 10px', borderRadius:2,
            fontFamily:'monospace', fontSize:10, cursor: refreshing ? 'not-allowed' : 'pointer',
          }}
        >
          {refreshing ? '↻ Refreshing…' : '↻ Refresh news'}
        </button>
      </div>

      {/* AI Summary card */}
      <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4 }}>
        <div style={{ padding:'10px 14px', borderBottom:'1px solid #2a2a2a', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
          <div style={{ color:'#a78bfa', fontSize:11, fontFamily:'monospace', textTransform:'uppercase', letterSpacing:1, fontWeight:700 }}>
            ✦ AI Summary — Last 60 Days
          </div>
          <div style={{ display:'flex', gap:10, alignItems:'center' }}>
            {summary?.generated_at && (
              <span style={{ color:'#555', fontSize:10, fontFamily:'monospace' }}>
                Generated {fmtTime(summary.generated_at)}
              </span>
            )}
            <button
              onClick={(e) => { if (e.ctrlKey || e.metaKey) generateSummary(); }}
              disabled={summarising}
              style={{
                background: summarising ? '#2e1065' : '#1a1a1a',
                color:      summarising ? '#c4b5fd' : '#a78bfa',
                border: '1px solid #4c1d95',
                padding: '4px 10px', borderRadius: 2,
                fontFamily: 'monospace', fontSize: 10,
                cursor: summarising ? 'not-allowed' : 'pointer',
              }}
            >
              {summarising ? '✦ Summarising…' : (summary ? '↻ Regenerate' : '✦ Generate summary')}
            </button>
          </div>
        </div>
        <div style={{ padding:'14px 16px' }}>
          {summaryError && (
            <div style={{ color:'#ef4444', fontSize:12, fontFamily:'monospace', marginBottom:10 }}>
              {summaryError}
            </div>
          )}
          {!summary && !summaryError && (
            <div style={{ color:'#666', fontSize:12, fontFamily:'monospace', lineHeight:1.7 }}>
              Press <span style={{ color:'#a78bfa' }}>✦ Generate summary</span> to have DeepSeek read the last 60 days of RNS + press coverage and produce a short summary.
            </div>
          )}
          {summary && (
            <div>
              <div style={{ color:'#e5e5e5', fontSize:13, lineHeight:1.7, marginBottom: themes.length ? 14 : 0 }}>
                {summary.summary}
              </div>
              {themes.length > 0 && (
                <div style={{ display:'flex', flexDirection:'column', gap:8, marginBottom:14 }}>
                  {themes.map((t, i) => (
                    <div key={i} style={{ borderLeft:'2px solid #4c1d95', paddingLeft:12 }}>
                      <div style={{ color:'#c4b5fd', fontSize:12, fontFamily:'monospace', fontWeight:700, marginBottom:2 }}>
                        {t.title}
                      </div>
                      <div style={{ color:'#cbd5e1', fontSize:12, lineHeight:1.6 }}>
                        {t.detail}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {summary.outlook && (
                <div style={{ background:'#0d0d0d', border:'1px solid #2a2a2a', borderRadius:3, padding:'10px 12px' }}>
                  <div style={{ color:'#666', fontSize:9, fontFamily:'monospace', textTransform:'uppercase', letterSpacing:1, marginBottom:4 }}>
                    Watch Next
                  </div>
                  <div style={{ color:'#e5e5e5', fontSize:12, lineHeight:1.6 }}>
                    {summary.outlook}
                  </div>
                </div>
              )}
              <div style={{ color:'#555', fontSize:10, fontFamily:'monospace', marginTop:10 }}>
                Based on {summary.rns_count ?? 0} RNS · {summary.google_count ?? 0} press · {summary.model}
              </div>
            </div>
          )}
        </div>
      </div>

      <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4 }}>
        <div style={{ padding:'10px 14px', borderBottom:'1px solid #2a2a2a', color:'#f97316', fontSize:11, fontFamily:'monospace', textTransform:'uppercase', letterSpacing:1, fontWeight:700 }}>
          Regulatory (RNS)
        </div>
        {rns.length === 0 ? (
          <div style={{ padding:20, color:'#555', fontSize:12, fontFamily:'monospace', textAlign:'center' }}>
            No RNS announcements in the last 6 months
          </div>
        ) : rns.map(r => <RnsRow key={r.id} r={r} />)}
      </div>

      <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4 }}>
        <div style={{ padding:'10px 14px', borderBottom:'1px solid #2a2a2a', color:'#f97316', fontSize:11, fontFamily:'monospace', textTransform:'uppercase', letterSpacing:1, fontWeight:700 }}>
          Press / Google News
        </div>
        {google.length === 0 ? (
          <div style={{ padding:20, color:'#555', fontSize:12, fontFamily:'monospace', textAlign:'center' }}>
            No press articles yet — try ↻ Refresh news above
          </div>
        ) : google.map(r => <GoogleRow key={r.id} r={r} />)}
      </div>
    </div>
  );
}
