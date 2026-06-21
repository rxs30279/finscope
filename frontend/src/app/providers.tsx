"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  DEFAULT_LIST_ID,
  DEFAULT_LIST_NAME,
  genListId,
  loadWatchlists,
  saveWatchlists,
  type WatchlistsData,
} from "@/lib/storage";

// SSR-deterministic default — matches loadWatchlists() when there's no window,
// so the server HTML and the client's first render agree before localStorage
// is read in an effect (see WatchlistProvider).
const EMPTY_WATCHLISTS: WatchlistsData = {
  lists: [{ id: DEFAULT_LIST_ID, name: DEFAULT_LIST_NAME }],
  members: { [DEFAULT_LIST_ID]: [] },
};

interface WatchlistContextValue {
  watchlists: WatchlistsData;
  defaultMembers: Set<string>;
  toggleWatchlist: (symbol: string) => void;
  createWatchlist: (name: string) => string;
  renameWatchlist: (id: string, name: string) => void;
  deleteWatchlist: (id: string) => void;
  addToWatchlist: (id: string, symbol: string) => void;
  removeFromWatchlist: (id: string, symbol: string) => void;
}

const WatchlistContext = createContext<WatchlistContextValue | null>(null);

export function useWatchlist(): WatchlistContextValue {
  const ctx = useContext(WatchlistContext);
  if (!ctx) throw new Error("useWatchlist must be used within WatchlistProvider");
  return ctx;
}

export function WatchlistProvider({ children }: { children: React.ReactNode }) {
  // Start from the empty default (matches SSR) and load the real localStorage
  // data only after mount. Reading localStorage in the useState initializer
  // would make the first client render diverge from the server-rendered HTML,
  // which is exactly the watchlist-page hydration mismatch. `hydrated` then gates
  // the save effect so the empty default isn't written back over real data.
  const [watchlists, setWatchlists] = useState<WatchlistsData>(EMPTY_WATCHLISTS);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setWatchlists(loadWatchlists());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated) saveWatchlists(watchlists);
  }, [hydrated, watchlists]);

  const defaultMembers = useMemo(
    () => new Set(watchlists.members[DEFAULT_LIST_ID] || []),
    [watchlists],
  );

  const toggleWatchlist = useCallback((symbol: string) => {
    setWatchlists((prev) => {
      const cur = prev.members[DEFAULT_LIST_ID] || [];
      const next = cur.includes(symbol)
        ? cur.filter((s) => s !== symbol)
        : [...cur, symbol];
      return { ...prev, members: { ...prev.members, [DEFAULT_LIST_ID]: next } };
    });
  }, []);

  const createWatchlist = useCallback((name: string): string => {
    const id = genListId();
    setWatchlists((prev) => ({
      lists: [...prev.lists, { id, name }],
      members: { ...prev.members, [id]: [] },
    }));
    return id;
  }, []);

  const renameWatchlist = useCallback((id: string, name: string) => {
    setWatchlists((prev) => ({
      ...prev,
      lists: prev.lists.map((l) => (l.id === id ? { ...l, name } : l)),
    }));
  }, []);

  const deleteWatchlist = useCallback((id: string) => {
    if (id === DEFAULT_LIST_ID) return;
    setWatchlists((prev) => {
      const members = { ...prev.members };
      delete members[id];
      return { lists: prev.lists.filter((l) => l.id !== id), members };
    });
  }, []);

  const addToWatchlist = useCallback((id: string, symbol: string) => {
    setWatchlists((prev) => {
      const cur = prev.members[id] || [];
      if (cur.includes(symbol)) return prev;
      return { ...prev, members: { ...prev.members, [id]: [...cur, symbol] } };
    });
  }, []);

  const removeFromWatchlist = useCallback((id: string, symbol: string) => {
    setWatchlists((prev) => {
      const cur = prev.members[id] || [];
      return {
        ...prev,
        members: { ...prev.members, [id]: cur.filter((s) => s !== symbol) },
      };
    });
  }, []);

  return (
    <WatchlistContext.Provider
      value={{
        watchlists,
        defaultMembers,
        toggleWatchlist,
        createWatchlist,
        renameWatchlist,
        deleteWatchlist,
        addToWatchlist,
        removeFromWatchlist,
      }}
    >
      {children}
    </WatchlistContext.Provider>
  );
}

// ── Refresh context ───────────────────────────────────────────────────────────

interface RefreshContextValue {
  refreshKey: number;
  refresh: () => void;
  highlightSymbol: string | null;
  setHighlightSymbol: (sym: string | null) => void;
  // Symbols that pass the screener's current filters, published by the Screener
  // so the nav search can flag results that have been screened out. `null` means
  // "unknown" (screener not visited yet this session) — flag nothing in that case.
  screenMatches: Set<string> | null;
  setScreenMatches: (s: Set<string> | null) => void;
}

const RefreshContext = createContext<RefreshContextValue | null>(null);

export function useRefresh(): RefreshContextValue {
  const ctx = useContext(RefreshContext);
  if (!ctx) throw new Error("useRefresh must be used within RefreshProvider");
  return ctx;
}

export function RefreshProvider({ children }: { children: ReactNode }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const [highlightSymbol, setHighlightSymbol] = useState<string | null>(null);
  const [screenMatches, setScreenMatches] = useState<Set<string> | null>(null);
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);
  return (
    <RefreshContext.Provider value={{ refreshKey, refresh, highlightSymbol, setHighlightSymbol, screenMatches, setScreenMatches }}>
      {children}
    </RefreshContext.Provider>
  );
}
