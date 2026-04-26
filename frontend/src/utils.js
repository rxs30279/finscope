export const API = process.env.NODE_ENV === 'production' ? '/api' : 'http://localhost:8000/api';

export const currSym = (code) =>
  code === 'USD' ? '$' : code === 'EUR' ? '\u20AC' : '\u00A3';

export const fmt = (v, type = 'number', currency = 'GBP') => {
  if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return '—';
  if (type === 'currency') {
    const sym = currSym(currency);
    const abs = Math.abs(v);
    const neg = v < 0 ? '-' : '';
    if (abs >= 1e12) return neg + sym + (abs/1e12).toFixed(2) + 'T';
    if (abs >= 1e9)  return neg + sym + (abs/1e9).toFixed(2) + 'B';
    if (abs >= 1e6)  return neg + sym + (abs/1e6).toFixed(2) + 'M';
    return neg + sym + abs.toLocaleString();
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

export const WATCHLIST_KEY = 'stock_screener_watchlist';

export const loadWatchlist = () => {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(WATCHLIST_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
};

export const saveWatchlist = (symbols) => {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(WATCHLIST_KEY, JSON.stringify(symbols)); } catch {}
};

export const TARGETS_KEY = 'stock_screener_target_prices';
const TARGETS_UNIT_V2 = 'stock_screener_targets_unit_v2_pounds';

export const loadTargets = () => {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(TARGETS_KEY);
    let parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== 'object') parsed = {};
    if (!window.localStorage.getItem(TARGETS_UNIT_V2)) {
      const migrated = {};
      for (const [k, v] of Object.entries(parsed)) {
        const n = Number(v);
        if (Number.isFinite(n) && n > 0) migrated[k] = n / 100;
      }
      window.localStorage.setItem(TARGETS_KEY, JSON.stringify(migrated));
      window.localStorage.setItem(TARGETS_UNIT_V2, '1');
      return migrated;
    }
    return parsed;
  } catch { return {}; }
};

export const saveTargets = (targets) => {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(TARGETS_KEY, JSON.stringify(targets)); } catch {}
};
