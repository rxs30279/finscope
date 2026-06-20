export const WATCHLIST_KEY = "stock_screener_watchlist";

export const loadWatchlist = (): string[] => {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(WATCHLIST_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
};

export const saveWatchlist = (symbols: string[]): void => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(WATCHLIST_KEY, JSON.stringify(symbols));
  } catch {}
};

// ── Multiple watchlists ───────────────────────────────────────────────────────
// Data model: { lists: [{id, name}], members: { [listId]: [symbol, ...] } }.
// The "default" list is special — the Screener ★ always toggles membership of it,
// and it can never be deleted. Other lists are managed from the Watchlist page.
export const WATCHLISTS_KEY = "stock_screener_watchlists_v1";
export const DEFAULT_LIST_ID = "default";
export const DEFAULT_LIST_NAME = "My Watchlist";

export interface WatchlistEntry {
  id: string;
  name: string;
}

export interface WatchlistsData {
  lists: WatchlistEntry[];
  members: Record<string, string[]>;
}

export const genListId = (): string =>
  "l" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

const normalizeWatchlists = (data: any): WatchlistsData => {
  let lists: WatchlistEntry[] = Array.isArray(data?.lists)
    ? data.lists.filter(
        (l: any) => l && typeof l.id === "string" && typeof l.name === "string",
      )
    : [];
  const rawMembers: Record<string, any> =
    data && typeof data.members === "object" && data.members ? data.members : {};
  if (!lists.some((l) => l.id === DEFAULT_LIST_ID)) {
    lists = [{ id: DEFAULT_LIST_ID, name: DEFAULT_LIST_NAME }, ...lists];
  } else {
    lists = [
      lists.find((l) => l.id === DEFAULT_LIST_ID)!,
      ...lists.filter((l) => l.id !== DEFAULT_LIST_ID),
    ];
  }
  const members: Record<string, string[]> = {};
  for (const l of lists) {
    const arr: any[] = Array.isArray(rawMembers[l.id]) ? rawMembers[l.id] : [];
    members[l.id] = [...new Set(arr.filter((s): s is string => typeof s === "string"))];
  }
  return { lists, members };
};

export const loadWatchlists = (): WatchlistsData => {
  if (typeof window === "undefined") return normalizeWatchlists(null);
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

export const saveWatchlists = (data: WatchlistsData): void => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(WATCHLISTS_KEY, JSON.stringify(data));
    // Keep the legacy key mirroring the default list for backward compatibility.
    window.localStorage.setItem(
      WATCHLIST_KEY,
      JSON.stringify(data?.members?.[DEFAULT_LIST_ID] || []),
    );
  } catch {}
};

export const TARGETS_KEY = "stock_screener_target_prices";
const TARGETS_UNIT_V2 = "stock_screener_targets_unit_v2_pounds";

export const loadTargets = (): Record<string, number> => {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(TARGETS_KEY);
    let parsed: Record<string, number> = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object") parsed = {};
    if (!window.localStorage.getItem(TARGETS_UNIT_V2)) {
      const migrated: Record<string, number> = {};
      for (const [k, v] of Object.entries(parsed)) {
        const n = Number(v);
        if (Number.isFinite(n) && n > 0) migrated[k] = n / 100;
      }
      window.localStorage.setItem(TARGETS_KEY, JSON.stringify(migrated));
      window.localStorage.setItem(TARGETS_UNIT_V2, "1");
      return migrated;
    }
    return parsed;
  } catch {
    return {};
  }
};

export const saveTargets = (targets: Record<string, number>): void => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TARGETS_KEY, JSON.stringify(targets));
  } catch {}
};

// Price-chart display preferences (range + indicator toggles). Persisted so a
// user's choices — e.g. turning candles off — carry across stocks instead of
// resetting to the presets every time a new company chart mounts.
export const CHART_PREFS_KEY = "stock_screener_chart_prefs";

export interface ChartPrefs {
  range: string;
  showMA20: boolean;
  showMA50: boolean;
  showVolume: boolean;
  showCandles: boolean;
  showMACD: boolean;
  showRSI: boolean;
}

const CHART_PREF_DEFAULTS: ChartPrefs = {
  range: "6M",
  showMA20: true,
  showMA50: false,
  showVolume: true,
  showCandles: true,
  showMACD: false,
  showRSI: false,
};

export const loadChartPrefs = (): ChartPrefs => {
  if (typeof window === "undefined") return { ...CHART_PREF_DEFAULTS };
  try {
    const raw = window.localStorage.getItem(CHART_PREFS_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    // Merge over defaults so a newly-added toggle still has a sensible value.
    return {
      ...CHART_PREF_DEFAULTS,
      ...(parsed && typeof parsed === "object" ? parsed : {}),
    };
  } catch {
    return { ...CHART_PREF_DEFAULTS };
  }
};

export const saveChartPrefs = (prefs: ChartPrefs): void => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CHART_PREFS_KEY, JSON.stringify(prefs));
  } catch {}
};

// Screener filter/sort/view state. Persisted so a filter set survives leaving the
// screener (e.g. to inspect a company) and coming back — without it the route
// unmounts and React state resets to the empty defaults on every return visit.
export const SCREENER_STATE_KEY = "stock_screener_screener_state_v1";

export interface ScreenerState {
  filters: Record<string, string>;
  selectModes: Record<string, string>;
  scoreFilters: Record<string, string>;
  tableView: string;
  sortCol: string | null;
  sortDir: "asc" | "desc";
  showAdvanced: boolean;
}

export const loadScreenerState = (): Partial<ScreenerState> => {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(SCREENER_STATE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
};

export const saveScreenerState = (state: ScreenerState): void => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SCREENER_STATE_KEY, JSON.stringify(state));
  } catch {}
};
