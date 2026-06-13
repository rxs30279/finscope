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
  genListId,
  loadWatchlists,
  saveWatchlists,
  type WatchlistsData,
} from "@/lib/storage";

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
  const [watchlists, setWatchlists] = useState<WatchlistsData>(() =>
    loadWatchlists(),
  );

  useEffect(() => {
    saveWatchlists(watchlists);
  }, [watchlists]);

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
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);
  return (
    <RefreshContext.Provider value={{ refreshKey, refresh, highlightSymbol, setHighlightSymbol }}>
      {children}
    </RefreshContext.Provider>
  );
}
