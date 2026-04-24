import { useState, useEffect, useMemo } from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { API } from '../utils';

const MODES = {
  'quality-pegy': {
    label: 'Quality × PEGY',
    xKey: 'pegy',         xLabel: 'PEGY (lower = cheaper)',
    yKey: 'quality_score', yLabel: 'Quality (1–10)',
    xMin: 0,  xMax: 5,  xMid: 1,
    yMin: 0,  yMax: 10, yMid: 5,
    invertX: true,   // low PEGY is "good"
    tooltipX: v => v?.toFixed?.(2) ?? '—',
    tooltipY: v => v ?? '—',
    quadrants: {
      tl: 'Cheap quality',    // high Y, low X
      tr: 'Expensive quality',// high Y, high X
      bl: 'Cheap low-quality',// low Y, low X
      br: 'Avoid',            // low Y, high X
    },
  },
  'momentum-risk': {
    label: 'Momentum × Risk',
    xKey: 'risk_score',     xLabel: 'Risk (1–10, lower = safer)',
    yKey: 'momentum_score', yLabel: 'Momentum (1–10)',
    xMin: 0, xMax: 10, xMid: 5,
    yMin: 0, yMax: 10, yMid: 5,
    invertX: true,
    tooltipX: v => v ?? '—',
    tooltipY: v => v ?? '—',
    quadrants: {
      tl: 'Strong + safe',
      tr: 'Strong + risky',
      bl: 'Weak + safe',
      br: 'Weak + risky',
    },
  },
};

function dotColor(d, mode) {
  const x = d[mode.xKey], y = d[mode.yKey];
  if (x == null || y == null) return '#555';
  const xGood = mode.invertX ? x < mode.xMid : x > mode.xMid;
  const yGood = y > mode.yMid;
  if (xGood && yGood) return '#10b981';  // ideal quadrant
  if (!xGood && !yGood) return '#ef4444'; // avoid quadrant
  return '#f59e0b';                        // mixed
}

function CustomTooltip({ active, payload, mode }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, padding:'8px 10px', fontSize:12, fontFamily:'monospace', color:'#f1f5f9' }}>
      <div style={{ color:'#a5b4fc', fontWeight:700, marginBottom:2, fontSize:13 }}>{d.symbol?.replace('.L','')}</div>
      <div style={{ color:'#cbd5e1', marginBottom:4, fontSize:11 }}>{d.name?.slice(0,32)}</div>
      <div style={{ color:'#94a3b8', fontSize:10, marginBottom:4 }}>{d.sector}</div>
      <div>{mode.xLabel.split(' ')[0]}: <span style={{ color:'#f1f5f9', fontWeight:600 }}>{mode.tooltipX(d[mode.xKey])}</span></div>
      <div>{mode.yLabel.split(' ')[0]}: <span style={{ color:'#f1f5f9', fontWeight:600 }}>{mode.tooltipY(d[mode.yKey])}</span></div>
    </div>
  );
}

export default function AnalyticsTab({ refreshKey, onSelect }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modeKey, setModeKey] = useState('quality-pegy');
  const [ftseFilter, setFtseFilter] = useState('all');
  const [xZoom, setXZoom] = useState(MODES['quality-pegy'].xMax);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/screener?limit=1000`)
      .then(r => r.json())
      .then(data => { setRows(data || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  const mode = MODES[modeKey];

  // Reset zoom when mode changes — each axis has different natural scale.
  useEffect(() => { setXZoom(mode.xMax); }, [modeKey, mode.xMax]);

  const filteredRows = useMemo(() => {
    let data = rows;
    if (ftseFilter !== 'all') {
      if (ftseFilter === 'FTSE 350') {
        data = data.filter(r => r.ftse_index === 'FTSE 100' || r.ftse_index === 'FTSE 250');
      } else {
        data = data.filter(r => r.ftse_index === ftseFilter);
      }
    }
    return data.filter(r => r[mode.xKey] != null && r[mode.yKey] != null);
  }, [rows, mode, ftseFilter]);

  // True data max across filtered rows — caps the zoom slider so you can pull back to see outliers.
  const dataXMax = useMemo(() => {
    if (filteredRows.length === 0) return mode.xMax;
    const max = Math.max(...filteredRows.map(r => r[mode.xKey] || 0));
    return Math.max(mode.xMax, Math.ceil(max));
  }, [filteredRows, mode]);

  const hiddenCount = filteredRows.filter(r => r[mode.xKey] > xZoom).length;

  const card = { background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 };

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading analytics…</div>;

  const btn = (active) => ({
    background: active ? '#1e293b' : '#141414',
    color: active ? '#a5b4fc' : '#cbd5e1',
    border: `1px solid ${active ? '#475569' : '#2a2a2a'}`,
    padding:'6px 14px', fontFamily:'monospace', fontSize:11, fontWeight: active ? 600 : 500,
    cursor:'pointer', borderRadius:3,
  });

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>
        Analytics
      </h2>

      <div style={{ display:'flex', gap:8, marginBottom:16, flexWrap:'wrap', alignItems:'center' }}>
        {Object.entries(MODES).map(([key, m]) => (
          <button key={key} onClick={() => setModeKey(key)} style={btn(modeKey === key)}>
            {m.label}
          </button>
        ))}
        <div style={{ width:1, height:20, background:'#2a2a2a', margin:'0 6px' }} />
        {['all', 'FTSE 100', 'FTSE 250', 'FTSE 350'].map(f => (
          <button key={f} onClick={() => setFtseFilter(f)} style={btn(ftseFilter === f)}>
            {f === 'all' ? 'All' : f}
          </button>
        ))}
        <span style={{ color:'#94a3b8', fontSize:11, fontFamily:'monospace', marginLeft:'auto' }}>
          {filteredRows.length} of {rows.length} plotted
        </span>
      </div>

      <div style={card}>
        <ResponsiveContainer width="100%" height={560}>
          <ScatterChart margin={{ top:20, right:30, bottom:50, left:40 }}>
            <CartesianGrid stroke="#1e1e1e" />
            <XAxis
              type="number" dataKey={mode.xKey} name={mode.xLabel}
              domain={[mode.xMin, xZoom]}
              allowDataOverflow
              tick={{ fill:'#cbd5e1', fontSize:11, fontFamily:'monospace' }}
              stroke="#475569"
              label={{ value: mode.xLabel, position:'insideBottom', offset:-10, fill:'#e2e8f0', fontSize:12, fontFamily:'monospace' }}
            />
            <YAxis
              type="number" dataKey={mode.yKey} name={mode.yLabel}
              domain={[mode.yMin, mode.yMax]}
              tick={{ fill:'#cbd5e1', fontSize:11, fontFamily:'monospace' }}
              stroke="#475569"
              label={{ value: mode.yLabel, angle:-90, position:'insideLeft', fill:'#e2e8f0', fontSize:12, fontFamily:'monospace' }}
            />
            <ReferenceLine x={mode.xMid} stroke="#333" strokeDasharray="3 3" />
            <ReferenceLine y={mode.yMid} stroke="#333" strokeDasharray="3 3" />
            <Tooltip content={<CustomTooltip mode={mode} />} cursor={{ strokeDasharray:'3 3', stroke:'#333' }} />
            <Scatter
              data={filteredRows}
              shape={(props) => {
                const { cx, cy, payload } = props;
                const mc = payload.market_cap || 0;
                const r = mc > 0 ? Math.max(3, Math.min(12, Math.log10(mc) - 5)) : 3;
                return (
                  <circle
                    cx={cx} cy={cy} r={r}
                    fill={dotColor(payload, mode)}
                    fillOpacity={0.55}
                    stroke={dotColor(payload, mode)}
                    strokeOpacity={0.9}
                    style={{ cursor:'pointer' }}
                    onClick={() => onSelect?.(payload.symbol)}
                  />
                );
              }}
            />
          </ScatterChart>
        </ResponsiveContainer>

        {/* X-axis zoom slider — pull left to zoom into the dense region */}
        <div style={{ marginTop:4, padding:'8px 6px 0' }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:4, fontSize:10, fontFamily:'monospace', color:'#94a3b8' }}>
            <span>X range: {mode.xMin.toFixed(1)} → {xZoom.toFixed(1)}</span>
            <span style={{ color: hiddenCount > 0 ? '#f59e0b' : '#64748b' }}>
              {hiddenCount > 0 ? `${hiddenCount} points beyond ${xZoom.toFixed(1)}` : 'All points in view'}
            </span>
            <button
              onClick={() => setXZoom(dataXMax)}
              style={{ background:'none', border:'1px solid #2a2a2a', color:'#94a3b8', fontSize:9, fontFamily:'monospace', padding:'2px 8px', borderRadius:2, cursor:'pointer' }}
            >
              Fit all
            </button>
          </div>
          <input
            type="range"
            min={Math.max(mode.xMin + 0.5, 1)}
            max={dataXMax}
            step={dataXMax > 20 ? 0.5 : 0.1}
            value={xZoom}
            onChange={e => setXZoom(parseFloat(e.target.value))}
            style={{ width:'100%', accentColor:'#f97316', cursor:'pointer' }}
          />
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginTop:16, fontSize:11, fontFamily:'monospace', color:'#cbd5e1' }}>
          <div><span style={{ color:'#10b981' }}>●</span> {mode.quadrants.tl}</div>
          <div style={{ textAlign:'right' }}><span style={{ color:'#f59e0b' }}>●</span> {mode.quadrants.tr}</div>
          <div><span style={{ color:'#f59e0b' }}>●</span> {mode.quadrants.bl}</div>
          <div style={{ textAlign:'right' }}><span style={{ color:'#ef4444' }}>●</span> {mode.quadrants.br}</div>
        </div>
        <div style={{ marginTop:10, fontSize:10, color:'#94a3b8', fontFamily:'monospace' }}>
          Dot size ∝ market cap · click a dot to open the company
        </div>
      </div>
    </div>
  );
}
