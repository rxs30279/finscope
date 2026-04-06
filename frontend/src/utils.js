export const API = process.env.NODE_ENV === 'production' ? '/api' : 'http://localhost:8000/api';

export const fmt = (v, type = 'number') => {
  if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return '—';
  if (type === 'currency') {
    const abs = Math.abs(v);
    const neg = v < 0 ? '-' : '';
    if (abs >= 1e12) return neg + '\u00A3' + (abs/1e12).toFixed(2) + 'T';
    if (abs >= 1e9)  return neg + '\u00A3' + (abs/1e9).toFixed(2) + 'B';
    if (abs >= 1e6)  return neg + '\u00A3' + (abs/1e6).toFixed(2) + 'M';
    return neg + '\u00A3' + abs.toLocaleString();
  }
  if (type === 'pct') return `${(v*100).toFixed(1)}%`;
  if (type === 'pct_direct') return `${v.toFixed(1)}%`;
  if (type === 'x')   return `${v.toFixed(2)}x`;
  if (type === 'ratio') return v.toFixed(2);
  return v.toLocaleString();
};

export const gc = (v) => {
  if (v === null || v === undefined) return '#94a3b8';
  return v >= 0 ? '#10b981' : '#ef4444';
};

export const pctColor = (v) => {
  if (v === null || v === undefined) return '#94a3b8';
  if (v > 0.005) return '#10b981';
  if (v < -0.005) return '#ef4444';
  return '#f59e0b';
};
