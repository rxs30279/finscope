"use client";
import { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from 'recharts';
import { API } from "@/lib/api";
import { useIsMobile } from "@/hooks/useMediaQuery";

// "2026 JUL" -> "Jul 2026"; "2026 Q1" -> "Q1 2026"; anything else (BoE's
// "30 Jun 2026", GfK's "August 2026") is already human-readable — pass through.
function fmtPeriod(p) {
  if (!p) return '';
  const mon = p.match(/^(\d{4})\s+([A-Z]{3})$/);
  if (mon) return `${mon[2][0]}${mon[2].slice(1).toLowerCase()} ${mon[1]}`;
  const qtr = p.match(/^(\d{4})\s+(Q\d)$/);
  if (qtr) return `${qtr[2]} ${qtr[1]}`;
  return p;
}

function fmtValue(unit, value) {
  if (value === null || value === undefined) return '—';
  if (unit === '%') return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
  if (unit === 'count') return Math.round(value).toLocaleString();
  return `${value > 0 ? '+' : ''}${value.toFixed(0)}`; // 'index' (GfK balance score)
}

// GfK's Overall Index Score is a net balance (% optimists − % pessimists),
// not a 0-100 scale — a bare "-14" has no anchor without knowing that
// convention. These bounds are the series' well-documented historical
// extremes (record low -49, Sep 2022, "worst since records began in 1974";
// record high +8, 2015) — general knowledge about the series, not something
// pulled from our live monthly scrape, so there's no pipeline dependency to
// keep them in sync. Revisit only if a new record is set.
const GFK_TRACK_MIN = -50;
const GFK_TRACK_MAX = 10;

function GfkConfidenceGauge({ card, attribution }) {
  const [showInfo, setShowInfo] = useState(false);
  const cardStyle = { position: 'relative', background: '#141414', border: '1px solid #2a2a2a', borderRadius: 2, padding: 16 };

  if (!card || typeof card.value !== 'number') {
    return (
      <div style={cardStyle}>
        <div style={{ color: '#94a3b8', fontSize: 9, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>{card?.label || 'Consumer Confidence (GfK)'}</div>
        <div style={{ color: '#333', fontSize: 20, fontWeight: 700, fontFamily: 'monospace' }}>—</div>
      </div>
    );
  }

  const { value, prev, period } = card;
  const span = GFK_TRACK_MAX - GFK_TRACK_MIN;
  const pct = ((Math.max(GFK_TRACK_MIN, Math.min(GFK_TRACK_MAX, value)) - GFK_TRACK_MIN) / span) * 100;
  const zeroPct = ((0 - GFK_TRACK_MIN) / span) * 100;

  const valColor = value > 0 ? '#16d96b' : value < 0 ? '#ff2e3f' : '#9ca3af';
  const zoneLabel = value > 0 ? 'Net optimism' : value < 0 ? 'Net pessimism' : 'Balanced';
  const arrow = typeof prev !== 'number' ? '' : value > prev ? ' ↑' : value < prev ? ' ↓' : ' →';

  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ color: '#94a3b8', fontSize: 9, textTransform: 'uppercase', letterSpacing: 1 }}>Consumer Confidence (GfK)</span>
          <span
            onMouseEnter={() => setShowInfo(true)}
            onMouseLeave={() => setShowInfo(false)}
            onClick={() => setShowInfo(v => !v)}
            role="button" tabIndex={0} aria-label="How this is calculated"
            style={{ color: '#667', fontSize: 10, cursor: 'help', userSelect: 'none', lineHeight: 1 }}
          >ⓘ</span>
        </div>
        <div style={{ color: valColor, fontSize: 20, fontWeight: 700, fontFamily: 'monospace' }}>
          {value > 0 ? '+' : ''}{value.toFixed(0)}
        </div>
      </div>

      {showInfo && (
        <div style={{
          position: 'absolute', top: 34, left: 16, right: 16, zIndex: 20,
          background: '#0a0a0a', border: '1px solid #2a2a2a', borderRadius: 4,
          padding: '10px 12px', fontSize: 9, lineHeight: 1.65, color: '#cbd5e1',
          boxShadow: '0 6px 20px rgba(0,0,0,0.6)',
        }}>
          A net balance score (% optimists − % pessimists) across GfK's questions on personal finances, the economy and major purchases. 0 = as many optimists as pessimists — the UK series is negative almost all the time.
        </div>
      )}

      <div style={{ color: valColor, fontSize: 9, marginTop: 8, marginBottom: 10 }}>{zoneLabel}</div>

      <div style={{ position: 'relative', height: 6 }}>
        <div style={{
          position: 'absolute', inset: 0, borderRadius: 3,
          background: `linear-gradient(90deg, #3a1418 0%, #3a1418 ${zeroPct}%, #10331e ${zeroPct}%, #10331e 100%)`,
        }} />
        {/* 0 = neutral reference line */}
        <div style={{ position: 'absolute', top: -2, left: `${zeroPct}%`, transform: 'translateX(-50%)', width: 1, height: 10, background: '#666' }} />
        {/* current-value marker */}
        <div style={{ position: 'absolute', top: -3, left: `${pct}%`, transform: 'translateX(-50%)', width: 2, height: 12, borderRadius: 1, background: valColor }} />
      </div>

      <div style={{ position: 'relative', height: 12, marginTop: 4 }}>
        <span style={{ position: 'absolute', left: 0, color: '#555', fontSize: 8, fontFamily: 'monospace' }}>{GFK_TRACK_MIN}</span>
        <span style={{ position: 'absolute', left: `${zeroPct}%`, transform: 'translateX(-50%)', color: '#555', fontSize: 8, fontFamily: 'monospace' }}>0</span>
        <span style={{ position: 'absolute', right: 0, color: '#555', fontSize: 8, fontFamily: 'monospace' }}>+{GFK_TRACK_MAX}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#444', fontSize: 7, marginTop: 1 }}>
        <span>record low, Sep 2022</span>
        <span>record high, 2015</span>
      </div>

      <div style={{ color: '#94a3b8', fontSize: 9, marginTop: 10 }}>{fmtPeriod(period)}</div>
      {typeof prev === 'number' && (
        <div style={{ color: '#666', fontSize: 9, marginTop: 2 }}>prev {prev > 0 ? '+' : ''}{prev.toFixed(0)}{arrow}</div>
      )}
      {attribution && (
        <div style={{ color: '#555', fontSize: 8, marginTop: 6 }}>{attribution}</div>
      )}
    </div>
  );
}

function ConsumerCard({ card, attribution }) {
  const cardStyle = { background: '#141414', border: '1px solid #2a2a2a', borderRadius: 2, padding: 16 };
  if (!card || card.value === null || card.value === undefined) {
    return (
      <div style={cardStyle}>
        <div style={{ color: '#94a3b8', fontSize: 9, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>{card?.label || '—'}</div>
        <div style={{ color: '#333', fontSize: 20, fontWeight: 700, fontFamily: 'monospace' }}>—</div>
      </div>
    );
  }

  const { value, prev, period, unit } = card;
  const arrow = typeof prev !== 'number' ? '' : value > prev ? ' ↑' : value < prev ? ' ↓' : ' →';
  const valColor = typeof prev !== 'number' ? '#e5e5e5' : value > prev ? '#16d96b' : value < prev ? '#ff2e3f' : '#9ca3af';

  return (
    <div style={cardStyle}>
      <div style={{ color: '#94a3b8', fontSize: 9, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>{card.label}</div>
      <div style={{ color: valColor, fontSize: 20, fontWeight: 700, fontFamily: 'monospace' }}>{fmtValue(unit, value)}</div>
      <div style={{ color: '#94a3b8', fontSize: 9, marginTop: 4 }}>{fmtPeriod(period)}</div>
      {typeof prev === 'number' && (
        <div style={{ color: '#666', fontSize: 9, marginTop: 2 }}>prev {fmtValue(unit, prev)}{arrow}</div>
      )}
      {attribution && (
        <div style={{ color: '#555', fontSize: 8, marginTop: 6 }}>{attribution}</div>
      )}
    </div>
  );
}

// Recharts LineChart for a single history series, matching CrossAssetTab's
// gilt-curve chart styling (dark card, monospace axes, formatted tooltip).
function HistoryChart({ title, subtitle, data, color, decimals, domain }) {
  return (
    <div style={{ background: '#111', border: '1px solid #1e1e1e', borderRadius: 3, padding: 16, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ color: '#ccc', fontSize: 9, textTransform: 'uppercase', letterSpacing: '1.5px', marginBottom: 4 }}>{title}</div>
      {subtitle && <div style={{ color: '#666', fontSize: 8, marginBottom: 12 }}>{subtitle}</div>}
      <div style={{ flex: 1, minHeight: 200 }}>
        {!data || data.length === 0 ? (
          <div style={{ color: '#333', fontFamily: 'monospace', fontSize: 11 }}>No data available</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 9, fill: '#888', fontFamily: 'monospace' }}
                tickFormatter={v => v.slice(0, 4)}
                minTickGap={40}
              />
              <YAxis
                tick={{ fontSize: 9, fill: '#888', fontFamily: 'monospace' }}
                tickFormatter={v => v.toFixed(decimals)}
                domain={domain || ['auto', 'auto']}
              />
              <Tooltip
                contentStyle={{ background: '#141414', border: '1px solid #2a2a2a', borderRadius: 4, fontSize: 11, fontFamily: 'monospace' }}
                labelStyle={{ color: '#e5e5e5' }}
                formatter={v => [v.toFixed(decimals), title]}
              />
              <Line type="monotone" dataKey="value" name={title} stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

export default function ConsumerTab({ refreshKey }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const isMobile = useIsMobile();

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/consumer`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  const cardsBySeries = {};
  (data?.cards || []).forEach(c => { cardsBySeries[c.series] = c; });

  const skelStyle = { background: '#1a1a1a', border: '1px solid #2a2a2a', borderRadius: 3, height: 96 };

  return (
    <div>
      <h2 style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: '#f97316', textTransform: 'uppercase', letterSpacing: 2, marginBottom: 20 }}>Consumer</h2>

      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? 'repeat(2,1fr)' : 'repeat(3,1fr)', gap: 12, marginBottom: 20 }}>
        {loading
          ? Array.from({ length: 6 }).map((_, i) => <div key={i} style={skelStyle} />)
          : <>
              <GfkConfidenceGauge card={cardsBySeries.gfk_confidence} attribution="GfK Consumer Confidence Barometer, powered by NIM" />
              <ConsumerCard card={cardsBySeries.saving_ratio} />
              <ConsumerCard card={cardsBySeries.retail_sales_mom} />
              <ConsumerCard card={cardsBySeries.consumer_credit} />
              <ConsumerCard card={cardsBySeries.mortgage_approvals} />
              <ConsumerCard card={cardsBySeries.household_money} />
            </>
        }
      </div>

      {/* The GfK card above and this chart are the SAME underlying survey on
          different scales (GfK is a balance around 0, OECD is an
          amplitude-adjusted index around 100, and OECD lags GfK by ~2
          months) — they are deliberately not overlaid or implied to be one
          series. See project-consumer-data-tab memory for why. */}
      <div style={{
        display: isMobile ? 'block' : 'grid',
        gridTemplateColumns: isMobile ? undefined : '1fr 1fr',
        gap: 12,
      }}>
        <div style={{ marginBottom: isMobile ? 16 : 0, minHeight: 260 }}>
          {loading
            ? <div style={{ ...skelStyle, height: 260 }} />
            : <HistoryChart
                title="Consumer Confidence — OECD"
                subtitle="Amplitude-adjusted index, long-run mean ≈ 100. Not the same scale as the GfK card above."
                data={data?.history?.oecd_confidence}
                color="#60a5fa"
                decimals={1}
              />}
        </div>
        <div style={{ minHeight: 260 }}>
          {loading
            ? <div style={{ ...skelStyle, height: 260 }} />
            : <HistoryChart
                title="Household Saving Ratio — ONS"
                subtitle="% of household disposable income saved, quarterly."
                data={data?.history?.saving_ratio}
                color="#16d96b"
                decimals={1}
              />}
        </div>
      </div>
    </div>
  );
}
