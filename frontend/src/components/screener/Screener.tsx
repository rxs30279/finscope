"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import Link from "next/link";
import { API } from "@/lib/api";
import { companyHref } from "@/lib/company";
import { fmt, gc } from "@/lib/format";
import { S } from "@/lib/theme";
import { loadScreenerState, saveScreenerState, loadScreenerColumns } from "@/lib/storage";
import { useScrollRestore } from "@/hooks/useScrollRestore";
import { SCREENER_TOGGLE_COLUMNS, DEFAULT_SCREENER_COLUMN_PREFS, filterScale } from "@/lib/screenerColumns";
import { useRefresh } from "@/app/providers";
import HybridSelect from "@/components/company/HybridSelect";
import SectorDropdown from "./SectorDropdown";
import StarButton from "./StarButton";
import ScorePill from "./ScorePill";
import PageHeader from "@/components/layout/PageHeader";

// P/E, ROE, Rev Growth and PEGY are no longer fixed filters here — they're
// generated per-column in the Advanced panel from the enabled table columns
// (see colFilters). What remains are the non-column filters: sector/index/market
// cap (always-on columns).
const EMPTY_FILTERS = { sector: "", exclude_sectors: "", ftse_index: "", min_market_cap: "" };
const EMPTY_MODES = { min_market_cap: "" };
const EMPTY_SCORE_FILTERS = { min_momentum: "", min_quality: "", min_value: "", max_risk: "" };

// FUND_COLS is now built per-render inside the component (it depends on the
// user's chosen columns). See `fundCols` useMemo below.
// Full column names, shown as a hover tooltip on the abbreviated headers. The
// toggleable-column titles are spread from the shared config so labels/tooltips
// live in one place; the always-on columns stay literal here.
const COL_TITLES: Record<string, string> = {
  symbol: "Ticker symbol",
  name: "Company name",
  sector: "ICB sector",
  ftse_index: "FTSE index membership",
  market_cap: "Market capitalisation",
  ...Object.fromEntries(SCREENER_TOGGLE_COLUMNS.map((c) => [c.key, c.title])),
  momentum_score: "Momentum score (0–10)",
  quality_score: "Quality score (0–10)",
  value_score: "Value score (0–10, higher = cheaper)",
  risk_score: "Risk score (0–10, lower is safer)",
  consensus: "Analyst consensus rating",
  upside_pct: "Upside to mean analyst price target",
  buy_pct: "Percentage of analysts rating Buy",
  total_analysts: "Number of covering analysts",
  revision_score: "Earnings estimate revision score",
};
// Composite-score columns — rendered as graded pills and visually grouped.
// Pinned to one equal width so the columns stay even regardless of header text.
const SCORE_KEYS = new Set(["momentum_score", "quality_score", "value_score", "risk_score"]);
const SCORE_COL_WIDTH = 56;

// Row virtualization: only the rows in (and just around) the viewport are
// mounted. The universe is >700 rows and grows, so rendering them all built a
// ~10k-node table and re-reconciled every one on each sort/filter (the INP
// cost). Windowing decouples DOM/render cost from universe size. Rows are all
// single-line (`whiteSpace: nowrap`), so height is uniform — a fixed-height
// window is safe. ROW_H is a fallback; the real height is measured on mount.
const ROW_H = 36;
const OVERSCAN = 8; // rows rendered beyond each edge, so fast scrolls don't flash blank
// Windowing needs stable column widths — with auto table-layout the browser
// sizes columns from the *rendered* cells, so widths would jitter as different
// rows scroll into the window. Fixed layout + explicit widths keeps them still.
const FUND_COL_WIDTH: Record<string, number> = { symbol: 90, name: 170, sector: 112, ftse_index: 82, market_cap: 94 };
const fundColWidth = (key: string): number =>
  SCORE_KEYS.has(key) ? SCORE_COL_WIDTH : FUND_COL_WIDTH[key] ?? 82;

// Display-only shortenings for the widest ICB sector names (full name kept in
// the cell's title tooltip). Sectors not listed render unchanged.
const SECTOR_ABBR: Record<string, string> = {
  "Telecommunications": "Telcomms",
  "Consumer Discretionary": "Consmr Discr",
  "Consumer Staples": "Consmr Stapl",
};
// Compact display for the Index cell (full value kept in the title tooltip). The
// FTSE-prefixed indices collapse to their number/tier via the `.replace` below;
// these two are the long, un-prefixed values that would otherwise overflow the
// narrow Index column — "Main (non-index)" especially.
const INDEX_ABBR: Record<string, string> = {
  "Main (non-index)": "Main",
  "FTSE SmallCap": "SmallCap",
};
const indexLabel = (v: string | null | undefined): string =>
  v == null ? "" : INDEX_ABBR[v] ?? v.replace("FTSE ", "");
// Analyst view has few columns, so we use a fixed table layout with explicit
// header widths to keep them evenly spaced; Name (no width) absorbs the slack.
const ANALYST_COLS = [
  ["Symbol", false, "symbol", 110], ["Name", false, "name"], ["Sector", false, "sector", 130],
  ["Index", false, "ftse_index", 90], ["Mkt Cap", true, "market_cap", 110], ["Consensus", false, "consensus", 100],
  ["Upside", true, "upside_pct", 95], ["Buy%", true, "buy_pct", 85], ["# Analysts", true, "total_analysts", 100],
  ["Rev Score", true, "revision_score", 100],
];

// Human label for a committed custom column-filter value, matching the preset
// option style (e.g. "FCF Mgn > 12%"), so the dropdown keeps the metric's
// identity instead of collapsing to a bare "Custom…".
const fmtColFilterLabel = (c: (typeof SCREENER_TOGGLE_COLUMNS)[number], raw: string): string => {
  const n = parseFloat(raw);
  if (isNaN(n)) return "";
  const disp = c.format === "pct" ? `${+(n * 100).toFixed(2)}%` : c.format === "pct_direct" ? `${n}%` : `${n}`;
  return `${c.label} ${c.filter.dir === "min" ? ">" : "<"} ${disp}`;
};

interface Props {
  onSelect: (symbol: string, tab?: string) => void;
  highlightSymbol?: string | null;
  watchlist?: Set<string>;
  onToggleWatchlist?: (symbol: string) => void;
}

export default function Screener({ onSelect, highlightSymbol, watchlist, onToggleWatchlist }: Props) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [selectModes, setSelectModes] = useState(EMPTY_MODES);
  const [filterOpts, setFilterOpts] = useState<{ sectors: string[]; countries: string[] }>({ sectors: [], countries: [] });
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [scoreFilters, setScoreFilters] = useState(EMPTY_SCORE_FILTERS);
  // Per-column metric filters, keyed by column key. `colFilters` holds the chosen
  // threshold (in the column's stored units); `colFilterModes` holds the dropdown
  // mode ("" | preset value | "custom"). Only applied for currently-enabled
  // columns, so disabling a column removes its filter.
  const [colFilters, setColFilters] = useState<Record<string, string>>({});
  const [colFilterModes, setColFilterModes] = useState<Record<string, string>>({});
  const [tableView, setTableView] = useState("fundamentals");
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  // Which optional fundamental columns are shown (chosen on the Settings page).
  // Initialised to the defaults — not `{}` — so SSR and the first client paint
  // both show the default 6-column view before hydration reads localStorage.
  const [enabledCols, setEnabledCols] = useState<Record<string, boolean>>(DEFAULT_SCREENER_COLUMN_PREFS);
  // Hydrate persisted filters/sort/view on mount (in an effect, not a lazy
  // initializer, so SSR and first client render agree). `hydrated` then gates the
  // save effect so the empty defaults don't overwrite saved state before load.
  const [hydrated, setHydrated] = useState(false);
  // Scroll container height is measured rather than a fixed `100vh - 245px`
  // guess: the filter controls wrap onto several rows on mobile, so the header
  // above the table is much taller there. A fixed offset overflows the viewport
  // and scrolls the whole page (pushing the title off-screen). Measuring the
  // table's actual top offset sizes it to exactly fill the rest of the viewport.
  const scrollRef = useRef<HTMLDivElement>(null);
  const [tableMaxH, setTableMaxH] = useState("calc(100vh - 245px)");
  // Row-virtualization state. `scrollTop`/`viewportH` drive which slice of the
  // sorted rows is mounted; `rowH` is measured from a real row (see effect) so
  // the spacer math is pixel-accurate across zoom/DPI. viewportH seeds to a
  // screenful so the very first paint renders a window, not the whole list.
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(800);
  const [rowH, setRowH] = useState(ROW_H);
  const scrollRaf = useRef(0);
  // Publish the set of symbols passing the current filters so the nav search can
  // flag a result that's been screened out (clicking it would otherwise scroll to
  // a row that isn't there). `matchKeyRef` dedupes so we only push on real change.
  const { setScreenMatches, setHighlightSymbol } = useRefresh();
  const matchKeyRef = useRef<string | null>(null);
  // Local copy of the searched symbol, kept for row styling after the context
  // value is consumed (cleared) by the scroll effect below.
  const [highlighted, setHighlighted] = useState<string | null>(null);

  useEffect(() => {
    const s = loadScreenerState();
    if (s.filters) setFilters((f) => ({ ...f, ...s.filters }));
    if (s.selectModes) setSelectModes((m) => ({ ...m, ...s.selectModes }));
    // Merge only known score-filter keys so a stale key from an older build
    // (e.g. the former `min_piotroski` Value filter) is dropped rather than
    // lingering as a phantom active filter.
    if (s.scoreFilters) setScoreFilters((sf) => {
      const saved = s.scoreFilters as Record<string, string>;
      const next = { ...sf };
      for (const k of Object.keys(sf)) if (k in saved) (next as any)[k] = saved[k];
      return next;
    });
    if (s.colFilters) setColFilters(s.colFilters);
    if (s.colFilterModes) setColFilterModes(s.colFilterModes);
    if (s.tableView) setTableView(s.tableView);
    if (s.sortCol !== undefined) setSortCol(s.sortCol);
    if (s.sortDir) setSortDir(s.sortDir);
    if (s.showAdvanced) setShowAdvanced(s.showAdvanced);
    setEnabledCols(loadScreenerColumns());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveScreenerState({ filters, selectModes, scoreFilters, colFilters, colFilterModes, tableView, sortCol, sortDir, showAdvanced });
  }, [hydrated, filters, selectModes, scoreFilters, colFilters, colFilterModes, tableView, sortCol, sortDir, showAdvanced]);

  useEffect(() => {
    fetch(`${API}/filters`).then((r) => r.json()).then(setFilterOpts);
    runScreener();
  }, []);

  // Size the table's scroll area to fill the viewport below it, so the page
  // itself never scrolls and the header stays put. `getBoundingClientRect().top`
  // is the live distance from the viewport top; we recompute whenever the header
  // height can change (advanced panel, excluded chips, loading) and on resize/
  // orientation change (which is what re-wraps the filters on mobile).
  useEffect(() => {
    const compute = () => {
      const el = scrollRef.current;
      if (!el) return;
      const top = el.getBoundingClientRect().top;
      const h = Math.max(220, Math.round(window.innerHeight - top - 16));
      setTableMaxH(`${h}px`);
      setViewportH(h); // == the container's visible height once the list overflows
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, [loading, showAdvanced, filters.exclude_sectors, tableView]);

  // (The searched-row scroll effect lives after `sorted` is computed — it needs
  // the row's index in the sorted order to position the virtualized window.)

  // Fetch the full universe once. All filtering is done client-side (below), so
  // this is a single canonical request → one Vercel edge cache key shared by all
  // users, instead of one per filter combination. See backend screener() comment.
  const runScreener = useCallback(() => {
    setLoading(true);
    fetch(`${API}/screener?limit=1000`)
      .then((r) => r.json())
      .then((d) => {
        // Metrics that aren't meaningful for a row (FCF for banks, revenue
        // ratios for trusts, …) arrive already nulled by the server, so they
        // show "—" and never sort/filter on junk.
        const arr = Array.isArray(d) ? d : [];
        setResults(arr);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const update = (k: string, v: string) => setFilters((f) => ({ ...f, [k]: v }));
  const updateMany = (patch: Partial<typeof EMPTY_FILTERS>) => setFilters((f) => ({ ...f, ...patch }));
  // `sector` and `exclude_sectors` are both comma-separated lists so multiple
  // sectors can be included/excluded. A sector can't be in both lists at once.
  const includedSectors = filters.sector ? filters.sector.split(",").filter(Boolean) : [];
  const excludedSectors = filters.exclude_sectors ? filters.exclude_sectors.split(",").filter(Boolean) : [];
  const toggleIncludeSector = (s: string) => {
    const set = new Set(includedSectors);
    const nowIncluded = !set.has(s);
    if (nowIncluded) set.add(s); else set.delete(s);
    const patch: any = { sector: Array.from(set).join(",") };
    // Including a sector lifts any exclusion on it.
    if (nowIncluded && excludedSectors.includes(s)) patch.exclude_sectors = excludedSectors.filter((x) => x !== s).join(",");
    updateMany(patch);
  };
  const toggleExcludeSector = (s: string) => {
    const set = new Set(excludedSectors);
    const wasExcluded = set.has(s);
    if (wasExcluded) set.delete(s); else set.add(s);
    const patch: any = { exclude_sectors: Array.from(set).join(",") };
    // Excluding a sector removes it from the include list.
    if (!wasExcluded && includedSectors.includes(s)) patch.sector = includedSectors.filter((x) => x !== s).join(",");
    updateMany(patch);
  };
  const handleSelectMode = (key: string, mode: string) => {
    setSelectModes((m) => ({ ...m, [key]: mode }));
    if (mode !== "custom") update(key, mode);
  };
  const handleCustomCommit = (key: string, rawValue: number, parse: (n: number) => number) => {
    update(key, String(parse(rawValue)));
  };
  // Per-column filter handlers. Presets store the option value directly; custom
  // input is scaled into the column's stored units (pct columns: 15 → 0.15).
  const handleColSelect = (key: string, mode: string) => {
    setColFilterModes((m) => ({ ...m, [key]: mode }));
    if (mode !== "custom") setColFilters((f) => ({ ...f, [key]: mode }));
  };
  const handleColCustom = (key: string, rawValue: number, scale: number) => {
    setColFilters((f) => ({ ...f, [key]: String(rawValue / scale) }));
  };
  const clearFilters = () => {
    setFilters(EMPTY_FILTERS); setSelectModes(EMPTY_MODES); setScoreFilters(EMPTY_SCORE_FILTERS);
    setColFilters({}); setColFilterModes({});
  };
  const updateScore = (k: string, v: string) => setScoreFilters((sf) => ({ ...sf, [k]: v }));

  // The user's enabled optional columns, in the fixed master order. Declared
  // before `displayed` because the per-column filters apply only to enabled
  // columns (disabling a column drops its filter).
  const visibleToggleCols = useMemo(
    () => SCREENER_TOGGLE_COLUMNS.filter((c) => enabledCols[c.key] ?? c.defaultEnabled),
    [enabledCols],
  );

  const watchlistSet = watchlist instanceof Set ? watchlist : new Set(watchlist || []);
  // Memoized so filtering the ~700-row universe only re-runs when an input that
  // actually affects the result set changes — not on every unrelated re-render
  // (scroll, hover, watchlist toggle). `includedSectors`/`excludedSectors` derive
  // purely from `filters`, so they're covered by the `filters` dependency.
  const displayed = useMemo(() => results.filter((r) => {
    // Fundamental filters — applied client-side (mirrors backend screener() WHERE clause).
    const f = filters;
    if (includedSectors.length && !includedSectors.includes(r.sector)) return false;
    if (f.exclude_sectors && excludedSectors.includes(r.sector)) return false;
    if (f.ftse_index) {
      if (f.ftse_index === "FTSE 350") { if (r.ftse_index !== "FTSE 100" && r.ftse_index !== "FTSE 250") return false; }
      else if (f.ftse_index === "FTSE All-Share") { if (r.ftse_index !== "FTSE 100" && r.ftse_index !== "FTSE 250" && r.ftse_index !== "FTSE SmallCap") return false; }
      else if (r.ftse_index !== f.ftse_index) return false;
    }
    if (f.min_market_cap && (r.market_cap == null || r.market_cap < +f.min_market_cap)) return false;
    // Per-column metric filters — applied only for currently-enabled columns, so
    // a filter disappears (stops filtering) when its column is turned off.
    for (const c of visibleToggleCols) {
      const raw = colFilters[c.key];
      if (!raw) continue;
      const t = parseFloat(raw);
      if (isNaN(t)) continue;
      const v = r[c.key];
      if (v == null) return false;
      if (c.filter.dir === "min") { if (v < t) return false; }
      else if (v > t || (c.filter.positiveOnly && v <= 0)) return false;
    }
    // Score filters (always-on columns).
    const sf = scoreFilters;
    if (sf.min_momentum && (r.momentum_score == null || r.momentum_score < +sf.min_momentum)) return false;
    if (sf.min_quality && (r.quality_score == null || r.quality_score < +sf.min_quality)) return false;
    if (sf.min_value && (r.value_score == null || r.value_score < +sf.min_value)) return false;
    if (sf.max_risk && (r.risk_score == null || r.risk_score > +sf.max_risk)) return false;
    return true;
  }), [results, filters, scoreFilters, colFilters, visibleToggleCols]);

  // Push the passing-symbol set to the shared context whenever it changes. Keyed
  // on the joined symbols and guarded by a ref so we only setState on a genuine
  // change (the context update re-renders this component, which would otherwise
  // loop). Now that `displayed` is memoized, this effect only fires when the
  // filtered set actually changes. Skip while the universe is still loading so
  // we don't briefly flag every result as excluded.
  useEffect(() => {
    if (loading || results.length === 0) return;
    const syms = displayed.map((r) => r.symbol);
    const key = syms.join("|");
    if (key === matchKeyRef.current) return;
    matchKeyRef.current = key;
    setScreenMatches(new Set(syms));
  }, [displayed, loading, results.length, setScreenMatches]);

  // Only enabled columns' filters count as active (a lingering filter on a
  // now-hidden column shouldn't light up "Clear" or the Advanced dot).
  const activeColFilters = visibleToggleCols.some((c) => colFilters[c.key]);
  const hasActiveFilters = Object.values(filters).some((v) => v !== "") || Object.values(scoreFilters).some((v) => v !== "") || activeColFilters;
  // Accent a filter control when it has a value, so active filters are obvious.
  const selStyle = (active: boolean) => (active ? { ...S.select, ...S.selectActive } : S.select);
  const hasAdvancedFilters = activeColFilters || scoreFilters.min_momentum || scoreFilters.min_quality || scoreFilters.min_value || scoreFilters.max_risk;

  const handleSort = (key: string) => {
    if (sortCol === key) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortCol(key); setSortDir("desc"); }
  };

  // Memoized so the ~700-row copy-and-sort only runs when the order can actually
  // change (new data, or a change of sort column/direction) — not on every
  // scroll frame the virtualized window triggers.
  const sorted = useMemo(() => sortCol == null ? displayed : [...displayed].sort((a, b) => {
    const av = a[sortCol], bv = b[sortCol];
    if (av == null && bv == null) return 0;
    if (av == null) return 1; if (bv == null) return -1;
    if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortDir === "asc" ? av - bv : bv - av;
  }), [displayed, sortCol, sortDir]);

  // Restore where the user was reading when they last left. The table scrolls in
  // its own overflow container, not the window, so nothing else can do this for
  // us. Setting scrollTop fires onScroll, which re-renders the virtualized window
  // at the new offset. It applies from a rAF callback, so it lands after the
  // whole effect phase and can't be undone by the snap-to-top below even if the
  // two ever land in one commit — in practice they don't, since the filters that
  // one keys off settle on mount while this waits for the fetch.
  const forgetScroll = useScrollRestore(
    "screener",
    !loading && sorted.length > 0,
    () => scrollRef.current,
  );

  // Reset the scroll position to the top whenever the filtered/sorted set
  // changes. With virtualization the container's scrollHeight comes from spacer
  // rows sized to the full list; if the list shrinks under a stale scrollTop the
  // window would point past the end (blank view), so snap back to the top —
  // which is also the expected UX when a filter or sort is applied. A search
  // jump (below) doesn't touch these deps, so it isn't clobbered.
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    setScrollTop(0);
    // ...and drop any remembered offset with it: it indexed into the list the
    // user just replaced. Ignored during the mount-time settle — see forget().
    forgetScroll();
  }, [forgetScroll, filters, scoreFilters, colFilters, tableView, sortCol, sortDir, visibleToggleCols]);

  // Scroll the searched row into view. Placed here because it needs the row's
  // index in `sorted` to position the virtualized window: the target row may not
  // be mounted yet, but the spacer rows give the container its full scroll height
  // immediately, so scrolling to `index * rowH` always lands and the row mounts
  // as the window catches up. The context value is one-shot (it lives in the
  // root-layout provider and survives navigation), so it's cleared once consumed
  // — after the jump, or once the universe is loaded and the row provably isn't
  // in the filtered set. Not cleared while results are still loading: the re-run
  // on `sorted` arrival does the scroll.
  useEffect(() => {
    if (!highlightSymbol) return;
    const el = scrollRef.current;
    const idx = sorted.findIndex((r) => r.symbol === highlightSymbol);
    if (idx < 0) {
      if (results.length > 0) setHighlightSymbol(null); // loaded, but screened out — stop waiting
      return;
    }
    if (!el) return;
    setHighlighted(highlightSymbol);
    // Measure a real row *now* rather than trusting the rowH state, which may
    // still be the fallback on this first render. For a row far down the list a
    // 1-2px per-row estimate error compounds into hundreds of px, landing the
    // approximate jump outside the mounted window (so the exact scroll below
    // never finds its row). A live measurement makes phase 1 land close enough.
    const sample = el.querySelector("tr[data-vrow]") as HTMLElement | null;
    const rh = sample?.offsetHeight || rowH;
    // Phase 1 — approximate jump so the target row mounts into the virtualized
    // window. Instant (not smooth) so it doesn't fight the exact scroll below.
    const approx = Math.max(0, idx * rh - el.clientHeight / 2 + rh / 2);
    el.scrollTop = approx;
    setScrollTop(approx);
    // Phase 2 — once the row is actually in the DOM, centre it exactly; this
    // self-corrects any residual estimate error regardless of rowH. Retry across
    // frames because the row only mounts after the phase-1 scroll re-renders the
    // window (and to cover layout not being settled on the first frame).
    let raf = 0, tries = 0;
    const settle = () => {
      const row = document.getElementById("row-" + highlightSymbol);
      if (row) {
        row.scrollIntoView({ behavior: "smooth", block: "center" });
        setHighlightSymbol(null);
        return;
      }
      if (tries++ < 30) raf = requestAnimationFrame(settle);
      else setHighlightSymbol(null);
    };
    raf = requestAnimationFrame(settle);
    return () => cancelAnimationFrame(raf);
  }, [highlightSymbol, sorted, results, rowH, setHighlightSymbol]);

  // Header column spec for the fundamentals view: the always-on left columns,
  // then the chosen optional columns, then the 4 always-on score pills.
  const fundCols = useMemo(
    () => [
      ["Symbol", false, "symbol"], ["Name", false, "name"], ["Sector", false, "sector"],
      ["Index", false, "ftse_index"], ["Mkt Cap", true, "market_cap"],
      ...visibleToggleCols.map((c) => [c.label, true, c.key]),
      ["Mom", true, "momentum_score"], ["Qual", true, "quality_score"],
      ["Value", true, "value_score"], ["Risk", true, "risk_score"],
    ],
    [visibleToggleCols],
  );

  // The columns actually rendered for the active view (drives the colgroup and
  // the spacer-row colSpan). Analysts view carries its own widths (4th tuple
  // slot); fundamentals derives them from `fundColWidth`.
  const activeCols = tableView === "fundamentals" ? fundCols : ANALYST_COLS;
  const colCount = activeCols.length;
  // Fixed-layout tables need a definite width; sum the fundamentals column
  // widths so the table scrolls horizontally on narrow screens and stretches
  // uniformly (never per-row) on wide ones.
  const fundMinWidth = fundCols.reduce((s, [, , key]: any) => s + fundColWidth(key), 0);

  // rAF-coalesced scroll tracking, so we re-render the window at most once per
  // frame rather than on every scroll event.
  const onScroll = useCallback(() => {
    if (scrollRaf.current) return;
    scrollRaf.current = requestAnimationFrame(() => {
      scrollRaf.current = 0;
      if (scrollRef.current) setScrollTop(scrollRef.current.scrollTop);
    });
  }, []);
  useEffect(() => () => { if (scrollRaf.current) cancelAnimationFrame(scrollRaf.current); }, []);

  // Measure a real row's height once it's on screen so the spacer math is exact
  // (font metrics vary with zoom/DPI). Guarded so it settles after one update.
  useEffect(() => {
    const el = scrollRef.current?.querySelector("tr[data-vrow]") as HTMLElement | null;
    if (el && el.offsetHeight && Math.abs(el.offsetHeight - rowH) > 0.5) setRowH(el.offsetHeight);
  }, [tableView, sorted.length, rowH, loading]);

  // The mounted window: rows in view plus an overscan margin, with spacer rows
  // above and below standing in for the un-mounted rows so the scrollbar and
  // row striping stay correct.
  const total = sorted.length;
  const startIndex = Math.max(0, Math.floor(scrollTop / rowH) - OVERSCAN);
  const endIndex = Math.min(total, startIndex + Math.ceil(viewportH / rowH) + OVERSCAN * 2);
  const windowRows = sorted.slice(startIndex, endIndex);
  const padTop = startIndex * rowH;
  const padBottom = Math.max(0, (total - endIndex) * rowH);

  return (
    <div>
      <PageHeader
        title="UK Stock Screener"
        inlineSubtitle
        subtitle={`${filters.ftse_index || "All indices"}${includedSectors.length === 1 ? ` · ${includedSectors[0]}` : includedSectors.length > 1 ? ` · ${includedSectors.length} sectors` : ""}`}
        right={
          <span style={{ flexShrink: 0, background: "rgba(249,115,22,0.1)", color: "#fb923c", border: "1px solid rgba(249,115,22,0.28)", borderRadius: 100, padding: "3px 11px", fontSize: 12, fontWeight: 600 }}>
            {displayed.length !== results.length ? `${displayed.length} / ${results.length}` : displayed.length} companies
          </span>
        }
      />

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 8, alignItems: "center" }}>
        <SectorDropdown sectors={filterOpts.sectors} selected={includedSectors} excluded={excludedSectors} onToggleInclude={toggleIncludeSector} onClear={() => update("sector", "")} onToggleExclude={toggleExcludeSector} />
        <select style={selStyle(!!filters.ftse_index)} value={filters.ftse_index} onChange={(e) => update("ftse_index", e.target.value)}>
          <option value="">FTSE Market</option>
          <option value="FTSE 100">FTSE 100</option>
          <option value="FTSE 250">FTSE 250</option>
          <option value="FTSE 350">FTSE 350</option>
          <option value="FTSE SmallCap">FTSE SmallCap</option>
          <option value="FTSE AIM 100">AIM 100</option>
          <option value="AIM">AIM (other)</option>
          <option value="Main (non-index)">Main (non-index)</option>
        </select>
        <HybridSelect active={!!filters.min_market_cap} selectMode={selectModes.min_market_cap} onSelectChange={(mode) => handleSelectMode("min_market_cap", mode)} onCustomCommit={(v) => handleCustomCommit("min_market_cap", v, (n) => Math.round(n * 1e9))} placeholder="£B" inputWidth={70}>
          <option value="">Any Market Cap</option>
          <option value="1000000000">£1B+</option>
          <option value="10000000000">£10B+</option>
          <option value="50000000000">£50B+</option>
        </HybridSelect>
        <button
          onClick={() => setShowAdvanced((v) => !v)}
          style={{
            ...S.select,
            cursor: "pointer",
            fontWeight: 600,
            // Always wear an orange accent so it reads as the primary way in to
            // richer filtering, not just another dropdown. Fill solid once the
            // panel is open or filters are set.
            ...(showAdvanced || hasAdvancedFilters
              ? { background: "#f97316", border: "1px solid #f97316", color: "#0a0a0a" }
              : { background: "rgba(249,115,22,0.1)", border: "1px solid rgba(249,115,22,0.4)", color: "#fb923c" }),
          }}
        >
          ⚙ Advanced {showAdvanced ? "▲" : "▼"}{hasAdvancedFilters ? " ●" : ""}
        </button>
        {hasActiveFilters && (
          <button onClick={clearFilters} style={{ ...S.select, cursor: "pointer", color: "#ef4444", borderColor: "#3a1a1a" }}>Clear filters ✕</button>
        )}
      </div>

      {showAdvanced && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
          {/* One metric filter per enabled table column, in master order. */}
          {visibleToggleCols.map((c) => (
            <HybridSelect
              key={c.key}
              active={!!colFilters[c.key]}
              selectMode={colFilterModes[c.key] || ""}
              onSelectChange={(mode) => handleColSelect(c.key, mode)}
              onCustomCommit={(v) => handleColCustom(c.key, v, filterScale(c.format))}
              placeholder={c.label}
              inputWidth={75}
              customLabel={colFilterModes[c.key] === "custom" ? fmtColFilterLabel(c, colFilters[c.key] || "") : undefined}
            >
              <option value="">Any {c.label}</option>
              {c.filter.presets.map(([lbl, val]) => <option key={val} value={val}>{lbl}</option>)}
            </HybridSelect>
          ))}
          {/* Always-on composite score filters. */}
          {[["min_momentum", "Momentum", [["4","Mom ≥ 4"],["6","Mom ≥ 6"],["8","Mom ≥ 8"]]],["min_quality","Quality",[["4","Quality ≥ 4"],["6","Quality ≥ 6"],["8","Quality ≥ 8"]]],["min_value","Value",[["4","Value ≥ 4"],["6","Value ≥ 6"],["8","Value ≥ 8"]]],["max_risk","Risk",[["3","Risk ≤ 3"],["5","Risk ≤ 5"],["7","Risk ≤ 7"]]]].map(([k, label, opts]: any) => (
            <select key={k} style={selStyle(!!(scoreFilters as any)[k])} value={(scoreFilters as any)[k]} onChange={(e) => updateScore(k, e.target.value)}>
              <option value="">{label}</option>
              {opts.map(([v, l]: any) => <option key={v} value={v}>{l}</option>)}
            </select>
          ))}
        </div>
      )}

      {excludedSectors.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginBottom: 8 }}>
          <span style={{ fontFamily: "monospace", fontSize: 10, color: "#666", textTransform: "uppercase", letterSpacing: 1 }}>Excluded:</span>
          {excludedSectors.map((s) => (
            <span key={s} style={{ display: "inline-flex", alignItems: "center", gap: 6, background: "#2a0d0d", color: "#fca5a5", border: "1px solid #4a1c1c", padding: "2px 4px 2px 8px", borderRadius: 2, fontSize: 11, fontFamily: "monospace" }}>
              {s}
              <button onClick={() => toggleExcludeSector(s)} title="Remove exclusion" style={{ background: "none", border: "none", color: "#fca5a5", cursor: "pointer", padding: "0 4px", fontSize: 12, lineHeight: 1 }}>✕</button>
            </span>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {["fundamentals", "analysts"].map((v) => (
          <button key={v} onClick={() => setTableView(v)} style={{ padding: "5px 14px", borderRadius: 2, border: "1px solid", fontSize: 11, fontFamily: "monospace", cursor: "pointer", textTransform: "uppercase", letterSpacing: 0.5, background: tableView === v ? "#f97316" : "#141414", color: tableView === v ? "#000" : "#666", borderColor: tableView === v ? "#f97316" : "#2a2a2a", fontWeight: tableView === v ? 700 : 400 }}>
            {v}
          </button>
        ))}
      </div>

      {loading ? <div style={{ ...S.loading, minHeight: tableMaxH, boxSizing: "border-box" }}>Screening…</div> : (
        <div ref={scrollRef} onScroll={onScroll} style={{ overflow: "auto", maxHeight: tableMaxH, scrollbarGutter: "stable", scrollSnapType: "y proximity", scrollPaddingTop: 29 }}>
          {/* tableLayout:fixed keeps column widths stable as rows scroll into and
              out of the virtualized window (auto-layout would resize columns to
              whatever slice is currently mounted). The colgroup pins the widths. */}
          <table style={{ ...S.table, tableLayout: "fixed" as const, minWidth: tableView === "analysts" ? 700 : fundMinWidth }}>
            <colgroup>
              {activeCols.map(([, , key, width]: any) => (
                <col key={key} style={width ? { width } : tableView === "fundamentals" ? { width: fundColWidth(key) } : undefined} />
              ))}
            </colgroup>
            <thead>
              <tr>
                {(tableView === "fundamentals" ? fundCols : ANALYST_COLS).map(([h, num, key, width]: any) => {
                  const isScore = SCORE_KEYS.has(key);
                  return (
                    <th key={key} onClick={() => handleSort(key)} title={COL_TITLES[key] || h} style={{ ...S.th, textAlign: isScore ? "center" : num ? "right" : "left", cursor: "pointer", userSelect: "none", color: sortCol === key ? "#fb923c" : "#f97316", ...(isScore ? { width: SCORE_COL_WIDTH } : {}), ...(width ? { width } : {}), ...(key === "momentum_score" ? { borderLeft: "1px solid #2a2a2a" } : {}) }}>
                      {h}{sortCol === key ? (sortDir === "desc" ? " ▼" : " ▲") : ""}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {/* Spacer rows stand in for the un-mounted rows above/below the
                  window so the scrollbar length and striping stay correct. */}
              {padTop > 0 && (
                <tr aria-hidden="true"><td colSpan={colCount} style={{ height: padTop, padding: 0, border: 0 }} /></tr>
              )}
              {windowRows.map((r, wi) => {
                const i = startIndex + wi; // absolute index — keeps zebra striping stable while scrolling
                const isHighlighted = r.symbol === highlighted;
                const baseBg = isHighlighted ? "#2d1e00" : i % 2 === 0 ? "#1e293b" : "#162032";
                return (
                  <tr key={r.symbol} data-vrow id={"row-" + r.symbol} onClick={() => onSelect(r.symbol)} style={{ background: baseBg, cursor: "pointer", scrollSnapAlign: "start", boxShadow: isHighlighted ? "inset 3px 0 0 #f97316" : "none" }} onMouseEnter={(e) => (e.currentTarget.style.background = "#334155")} onMouseLeave={(e) => (e.currentTarget.style.background = baseBg)}>
                    <td style={{ ...S.td, fontFamily: "monospace", fontWeight: 700, color: watchlistSet.has(r.symbol) ? "#f59e0b" : "#818cf8" }}>
                      <span style={{ display: "inline-flex", alignItems: "center" }}>
                        <StarButton active={watchlistSet.has(r.symbol)} onClick={(e) => { e.stopPropagation(); onToggleWatchlist && onToggleWatchlist(r.symbol); }} />
                        <Link prefetch={false} href={companyHref(r.symbol)} onClick={(e) => e.stopPropagation()} style={{ color: "inherit", textDecoration: "none" }}>
                          {r.symbol.replace(".L", "")}
                        </Link>
                      </span>
                    </td>
                    {/* Truncation lives on an inner div (max-width + ellipsis): the
                        fixed column width caps the cell, and the div clips a long name
                        to the visible width rather than letting it force a horizontal scroll. */}
                    <td style={{ ...S.td, color: "#f1f5f9" }} title={r.name}>
                      <Link prefetch={false} href={companyHref(r.symbol)} onClick={(e) => e.stopPropagation()} style={{ color: "inherit", textDecoration: "none" }}>
                        <div style={{ maxWidth: 152, overflow: "hidden", textOverflow: "ellipsis" }}>{r.name}</div>
                      </Link>
                    </td>
                    <td style={{ ...S.td, color: "#64748b" }} title={r.sector}>
                      <div style={{ maxWidth: 104, overflow: "hidden", textOverflow: "ellipsis" }}>{SECTOR_ABBR[r.sector] || r.sector}</div>
                    </td>
                    <td style={{ ...S.td, color: "#64748b" }} title={r.ftse_index}>{indexLabel(r.ftse_index)}</td>
                    <td style={{ ...S.tdNum, color: "#ccc" }}>{fmt(r.market_cap, "currency", r.currency)}</td>
                    {tableView === "fundamentals" ? (
                      <>
                        {visibleToggleCols.map((c) => (
                          <td key={c.key} style={{ ...S.tdNum, color: c.color ? c.color(r[c.key]) : "#ccc" }}>
                            {c.render ? c.render(r[c.key]) : fmt(r[c.key], c.format)}
                          </td>
                        ))}
                        {[["momentum_score", false], ["quality_score", false], ["value_score", false], ["risk_score", true]].map(([k, invert]: any) => (
                          <td key={k} style={{ ...S.tdNum, textAlign: "center", width: SCORE_COL_WIDTH, ...(k === "momentum_score" ? { borderLeft: "1px solid #2a2a2a" } : {}) }}>
                            <ScorePill value={r[k]} invert={invert} />
                          </td>
                        ))}
                      </>
                    ) : (
                      <>
                        <td style={S.td}>
                          {r.consensus ? (
                            <span style={{ ...({ Buy: { background: "#0d3320", color: "#10b981" }, Hold: { background: "#1a1400", color: "#f59e0b" }, Sell: { background: "#2a0d0d", color: "#ef4444" } }[r.consensus as string] || {}), padding: "2px 7px", borderRadius: 2, fontSize: 9, fontFamily: "monospace", fontWeight: 700 }}>{r.consensus}</span>
                          ) : <span style={{ color: "#444" }}>—</span>}
                        </td>
                        <td style={{ ...S.tdNum, color: r.upside_pct > 0 ? "#10b981" : r.upside_pct < 0 ? "#ef4444" : "#555" }}>{r.upside_pct != null ? `${r.upside_pct >= 0 ? "+" : ""}${r.upside_pct.toFixed(1)}%` : "—"}</td>
                        <td style={{ ...S.tdNum, color: r.buy_pct != null ? r.buy_pct >= 60 ? "#10b981" : r.buy_pct >= 40 ? "#f59e0b" : "#ef4444" : "#444" }}>{r.buy_pct != null ? `${r.buy_pct.toFixed(0)}%` : "—"}</td>
                        <td style={{ ...S.tdNum, color: r.total_analysts != null ? "#94a3b8" : "#444" }}>{r.total_analysts ?? "—"}</td>
                        <td style={{ ...S.tdNum, color: r.revision_score == null ? "#444" : r.revision_score > 0 ? "#10b981" : r.revision_score < 0 ? "#ef4444" : "#f59e0b", fontWeight: 700 }}>{r.revision_score != null ? r.revision_score > 0 ? `+${r.revision_score}` : r.revision_score : "—"}</td>
                      </>
                    )}
                  </tr>
                );
              })}
              {padBottom > 0 && (
                <tr aria-hidden="true"><td colSpan={colCount} style={{ height: padBottom, padding: 0, border: 0 }} /></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
