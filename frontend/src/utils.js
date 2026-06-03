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

// dividenddata.co.uk keys on the LSE EPIC (TIDM). For most stocks that's just the
// Yahoo symbol with the ".L" suffix stripped (GRG.L -> GRG). Two-letter mnemonics
// are the catch: by LSE convention they carry a trailing dot (BP., RR., NG. ...),
// which Yahoo collapses into "XX.L" — so a naive strip yields "BP" when the EPIC
// is "BP.". Re-add the dot for the two-letter case; DIVIDENDDATA_EPIC overrides
// handle any ticker that doesn't follow the convention.
const DIVIDENDDATA_EPIC = {};

export const dividendDataUrl = (symbol) => {
  const s = symbol || '';
  let epic;
  if (DIVIDENDDATA_EPIC[s]) {
    epic = DIVIDENDDATA_EPIC[s];
  } else if (/^[A-Z]{2}\.L$/i.test(s)) {
    epic = s.replace(/\.L$/i, '.'); // BP.L -> BP., RR.L -> RR.
  } else {
    epic = s.replace(/\.L$/i, '');
  }
  return `https://www.dividenddata.co.uk/dividend-yield.py?epic=${encodeURIComponent(epic)}`;
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

// ── Multiple watchlists ───────────────────────────────────────────────────────
// Data model: { lists: [{id, name}], members: { [listId]: [symbol, ...] } }.
// The "default" list is special — the Screener ★ always toggles membership of it,
// and it can never be deleted. Other lists are managed from the Watchlist page.
export const WATCHLISTS_KEY = 'stock_screener_watchlists_v1';
export const DEFAULT_LIST_ID = 'default';
export const DEFAULT_LIST_NAME = 'My Watchlist';

export const genListId = () =>
  'l' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

const normalizeWatchlists = (data) => {
  let lists = Array.isArray(data?.lists)
    ? data.lists.filter((l) => l && typeof l.id === 'string' && typeof l.name === 'string')
    : [];
  const rawMembers = data && typeof data.members === 'object' && data.members ? data.members : {};
  // The default list must exist and lead the order.
  if (!lists.some((l) => l.id === DEFAULT_LIST_ID)) {
    lists = [{ id: DEFAULT_LIST_ID, name: DEFAULT_LIST_NAME }, ...lists];
  } else {
    lists = [
      lists.find((l) => l.id === DEFAULT_LIST_ID),
      ...lists.filter((l) => l.id !== DEFAULT_LIST_ID),
    ];
  }
  const members = {};
  for (const l of lists) {
    const arr = Array.isArray(rawMembers[l.id]) ? rawMembers[l.id] : [];
    members[l.id] = [...new Set(arr.filter((s) => typeof s === 'string'))];
  }
  return { lists, members };
};

export const loadWatchlists = () => {
  if (typeof window === 'undefined') return normalizeWatchlists(null);
  try {
    const raw = window.localStorage.getItem(WATCHLISTS_KEY);
    if (raw) return normalizeWatchlists(JSON.parse(raw));
    // First run on the multi-list model: fold the legacy single list into "My Watchlist".
    const legacy = window.localStorage.getItem(WATCHLIST_KEY);
    const arr = legacy ? JSON.parse(legacy) : [];
    return normalizeWatchlists({
      lists: [{ id: DEFAULT_LIST_ID, name: DEFAULT_LIST_NAME }],
      members: { [DEFAULT_LIST_ID]: Array.isArray(arr) ? arr : [] },
    });
  } catch {
    return normalizeWatchlists(null);
  }
};

export const saveWatchlists = (data) => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(WATCHLISTS_KEY, JSON.stringify(data));
    // Keep the legacy key mirroring the default list for backward compatibility.
    window.localStorage.setItem(
      WATCHLIST_KEY,
      JSON.stringify(data?.members?.[DEFAULT_LIST_ID] || []),
    );
  } catch {}
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

// Price-chart display preferences (range + indicator toggles). Persisted so a
// user's choices — e.g. turning candles off — carry across stocks instead of
// resetting to the presets every time a new company chart mounts.
export const CHART_PREFS_KEY = 'stock_screener_chart_prefs';

const CHART_PREF_DEFAULTS = {
  range: '6M',
  showMA20: true,
  showMA50: false,
  showVolume: true,
  showCandles: true,
  showMACD: false,
  showRSI: false,
};

export const loadChartPrefs = () => {
  if (typeof window === 'undefined') return { ...CHART_PREF_DEFAULTS };
  try {
    const raw = window.localStorage.getItem(CHART_PREFS_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    // Merge over defaults so a newly-added toggle still has a sensible value.
    return { ...CHART_PREF_DEFAULTS, ...(parsed && typeof parsed === 'object' ? parsed : {}) };
  } catch {
    return { ...CHART_PREF_DEFAULTS };
  }
};

export const saveChartPrefs = (prefs) => {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(CHART_PREFS_KEY, JSON.stringify(prefs)); } catch {}
};
