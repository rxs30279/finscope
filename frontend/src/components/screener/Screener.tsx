"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { API } from "@/lib/api";
import { fmt, gc } from "@/lib/format";
import { S } from "@/lib/theme";
import { loadScreenerState, saveScreenerState } from "@/lib/storage";
import { useRefresh } from "@/app/providers";
import HybridSelect from "@/components/company/HybridSelect";
import SectorDropdown from "./SectorDropdown";
import StarButton from "./StarButton";
import ScorePill from "./ScorePill";
import PageHeader from "@/components/layout/PageHeader";

const EMPTY_FILTERS = { sector: "", exclude_sectors: "", ftse_index: "", min_market_cap: "", max_pe: "", min_roe: "", min_revenue_growth: "", consensus: "", min_upside_pct: "" };
const EMPTY_MODES = { min_market_cap: "", max_pe: "", min_roe: "", min_revenue_growth: "" };
const EMPTY_SCORE_FILTERS = { min_momentum: "", min_quality: "", min_value: "", max_risk: "", max_pegy: "" };

const FUND_COLS = [
  ["Symbol", false, "symbol"], ["Name", false, "name"], ["Sector", false, "sector"],
  ["Index", false, "ftse_index"], ["Mkt Cap", true, "market_cap"], ["P/E", true, "price_to_earnings"],
  ["P/B", true, "price_to_book"], ["ROE", true, "roe"], ["Rev Grwth", true, "revenue_growth"],
  ["D/E", true, "debt_to_equity"], ["PEGY", true, "pegy"], ["Mom", true, "momentum_score"],
  ["Qual", true, "quality_score"], ["Value", true, "value_score"], ["Risk", true, "risk_score"],
];
// Full column names, shown as a hover tooltip on the abbreviated headers.
const COL_TITLES: Record<string, string> = {
  symbol: "Ticker symbol",
  name: "Company name",
  sector: "ICB sector",
  ftse_index: "FTSE index membership",
  market_cap: "Market capitalisation",
  price_to_earnings: "Price-to-earnings ratio",
  price_to_book: "Price-to-book ratio",
  roe: "Return on equity",
  revenue_growth: "Revenue growth (year-on-year)",
  debt_to_equity: "Debt-to-equity ratio",
  pegy: "Price/earnings-to-growth-and-yield ratio",
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
const SCORE_COL_WIDTH = 72;

// Display-only shortenings for the widest ICB sector names (full name kept in
// the cell's title tooltip). Sectors not listed render unchanged.
const SECTOR_ABBR: Record<string, string> = {
  "Telecommunications": "Telcomms",
  "Consumer Discretionary": "Consmr Discr",
  "Consumer Staples": "Consmr Stapl",
};
// Analyst view has few columns, so we use a fixed table layout with explicit
// header widths to keep them evenly spaced; Name (no width) absorbs the slack.
const ANALYST_COLS = [
  ["Symbol", false, "symbol", 110], ["Name", false, "name"], ["Sector", false, "sector", 130],
  ["Index", false, "ftse_index", 90], ["Mkt Cap", true, "market_cap", 110], ["Consensus", false, "consensus", 100],
  ["Upside", true, "upside_pct", 95], ["Buy%", true, "buy_pct", 85], ["# Analysts", true, "total_analysts", 100],
  ["Rev Score", true, "revision_score", 100],
];

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
  const [tableView, setTableView] = useState("fundamentals");
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
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
  // Publish the set of symbols passing the current filters so the nav search can
  // flag a result that's been screened out (clicking it would otherwise scroll to
  // a row that isn't there). `matchKeyRef` dedupes so we only push on real change.
  const { setScreenMatches } = useRefresh();
  const matchKeyRef = useRef<string | null>(null);

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
    if (s.tableView) setTableView(s.tableView);
    if (s.sortCol !== undefined) setSortCol(s.sortCol);
    if (s.sortDir) setSortDir(s.sortDir);
    if (s.showAdvanced) setShowAdvanced(s.showAdvanced);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveScreenerState({ filters, selectModes, scoreFilters, tableView, sortCol, sortDir, showAdvanced });
  }, [hydrated, filters, selectModes, scoreFilters, tableView, sortCol, sortDir, showAdvanced]);

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
      setTableMaxH(`${Math.max(220, Math.round(window.innerHeight - top - 16))}px`);
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, [loading, showAdvanced, filters.exclude_sectors, tableView]);

  // Scroll the searched row into view. Deferred to a rAF loop rather than run
  // inline: when the search arrives via router.push("/screener") from another
  // page, Next's App Router resets the new route's scroll to top *after* this
  // effect runs, which would cancel an inline scrollIntoView (the prod-only
  // "search doesn't scroll" bug — masked locally by dev timing). Retrying a few
  // frames also covers the row not being laid out yet on the first frame.
  useEffect(() => {
    if (!highlightSymbol) return;
    let raf = 0;
    let tries = 0;
    const tick = () => {
      const el = document.getElementById("row-" + highlightSymbol);
      if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); return; }
      if (tries++ < 30) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [highlightSymbol, results]);

  // Fetch the full universe once. All filtering is done client-side (below), so
  // this is a single canonical request → one Vercel edge cache key shared by all
  // users, instead of one per filter combination. See backend screener() comment.
  const runScreener = useCallback(() => {
    setLoading(true);
    fetch(`${API}/screener?limit=1000`)
      .then((r) => r.json())
      .then((d) => { setResults(Array.isArray(d) ? d : []); setLoading(false); })
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
  const clearFilters = () => { setFilters(EMPTY_FILTERS); setSelectModes(EMPTY_MODES); setScoreFilters(EMPTY_SCORE_FILTERS); };
  const updateScore = (k: string, v: string) => setScoreFilters((sf) => ({ ...sf, [k]: v }));

  const watchlistSet = watchlist instanceof Set ? watchlist : new Set(watchlist || []);
  const displayed = results.filter((r) => {
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
    if (f.max_pe && (r.price_to_earnings == null || r.price_to_earnings <= 0 || r.price_to_earnings > +f.max_pe)) return false;
    if (f.min_roe && (r.roe == null || r.roe < +f.min_roe)) return false;
    if (f.min_revenue_growth && (r.revenue_growth == null || r.revenue_growth < +f.min_revenue_growth)) return false;
    if (f.consensus && r.consensus !== f.consensus) return false;
    if (f.min_upside_pct && (r.upside_pct == null || r.upside_pct < +f.min_upside_pct)) return false;
    // Score filters (already client-side before this change).
    const sf = scoreFilters;
    if (sf.min_momentum && (r.momentum_score == null || r.momentum_score < +sf.min_momentum)) return false;
    if (sf.min_quality && (r.quality_score == null || r.quality_score < +sf.min_quality)) return false;
    if (sf.min_value && (r.value_score == null || r.value_score < +sf.min_value)) return false;
    if (sf.max_risk && (r.risk_score == null || r.risk_score > +sf.max_risk)) return false;
    if (sf.max_pegy && (r.pegy == null || r.pegy > +sf.max_pegy)) return false;
    return true;
  });

  // Push the passing-symbol set to the shared context whenever it changes. Keyed
  // on the joined symbols and guarded by a ref so we only setState on a genuine
  // change — `displayed` is a fresh array each render, so an unguarded update
  // would loop (the context update re-renders this component). Skip while the
  // universe is still loading so we don't briefly flag every result as excluded.
  useEffect(() => {
    if (loading || results.length === 0) return;
    const syms = displayed.map((r) => r.symbol);
    const key = syms.join("|");
    if (key === matchKeyRef.current) return;
    matchKeyRef.current = key;
    setScreenMatches(new Set(syms));
  });

  const hasActiveFilters = Object.values(filters).some((v) => v !== "") || Object.values(scoreFilters).some((v) => v !== "");
  // Accent a filter control when it has a value, so active filters are obvious.
  const selStyle = (active: boolean) => (active ? { ...S.select, ...S.selectActive } : S.select);
  const hasAdvancedFilters = filters.max_pe || filters.min_roe || filters.min_revenue_growth || scoreFilters.min_momentum || scoreFilters.min_quality || scoreFilters.min_value || scoreFilters.max_risk || scoreFilters.max_pegy;

  const handleSort = (key: string) => {
    if (sortCol === key) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortCol(key); setSortDir("desc"); }
  };

  const sorted = sortCol == null ? displayed : [...displayed].sort((a, b) => {
    const av = a[sortCol], bv = b[sortCol];
    if (av == null && bv == null) return 0;
    if (av == null) return 1; if (bv == null) return -1;
    if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortDir === "asc" ? av - bv : bv - av;
  });

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
        </select>
        <HybridSelect active={!!filters.min_market_cap} selectMode={selectModes.min_market_cap} onSelectChange={(mode) => handleSelectMode("min_market_cap", mode)} onCustomCommit={(v) => handleCustomCommit("min_market_cap", v, (n) => Math.round(n * 1e9))} placeholder="£B" inputWidth={70}>
          <option value="">Any Market Cap</option>
          <option value="1000000000">£1B+</option>
          <option value="10000000000">£10B+</option>
          <option value="50000000000">£50B+</option>
        </HybridSelect>
        <button onClick={() => setShowAdvanced((v) => !v)} style={{ ...S.select, cursor: "pointer", color: showAdvanced || hasAdvancedFilters ? "#f97316" : "#888", borderColor: hasAdvancedFilters ? "#f97316" : "#2a2a2a" }}>
          Advanced {showAdvanced ? "▲" : "▼"}{hasAdvancedFilters ? " ●" : ""}
        </button>
        {hasActiveFilters && (
          <button onClick={clearFilters} style={{ ...S.select, cursor: "pointer", color: "#ef4444", borderColor: "#3a1a1a" }}>Clear filters ✕</button>
        )}
      </div>

      {showAdvanced && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
          {[["min_momentum", "Momentum", [["4","Mom ≥ 4"],["6","Mom ≥ 6"],["8","Mom ≥ 8"]]],["min_quality","Quality",[["4","Quality ≥ 4"],["6","Quality ≥ 6"],["8","Quality ≥ 8"]]],["min_value","Value",[["4","Value ≥ 4"],["6","Value ≥ 6"],["8","Value ≥ 8"]]],["max_risk","Risk",[["3","Risk ≤ 3"],["5","Risk ≤ 5"],["7","Risk ≤ 7"]]],["max_pegy","PEGY",[["1","PEGY ≤ 1"],["1.5","PEGY ≤ 1.5"],["2","PEGY ≤ 2"]]]].map(([k, label, opts]: any) => (
            <select key={k} style={selStyle(!!(scoreFilters as any)[k])} value={(scoreFilters as any)[k]} onChange={(e) => updateScore(k, e.target.value)}>
              <option value="">{label}</option>
              {opts.map(([v, l]: any) => <option key={v} value={v}>{l}</option>)}
            </select>
          ))}
          <HybridSelect active={!!filters.max_pe} selectMode={selectModes.max_pe} onSelectChange={(mode) => handleSelectMode("max_pe", mode)} onCustomCommit={(v) => handleCustomCommit("max_pe", v, (n) => n)} placeholder="P/E" inputWidth={65}>
            <option value="">Any P/E</option><option value="15">P/E &lt; 15</option><option value="25">P/E &lt; 25</option><option value="40">P/E &lt; 40</option>
          </HybridSelect>
          <HybridSelect active={!!filters.min_roe} selectMode={selectModes.min_roe} onSelectChange={(mode) => handleSelectMode("min_roe", mode)} onCustomCommit={(v) => handleCustomCommit("min_roe", v, (n) => n / 100)} placeholder="ROE %" inputWidth={75}>
            <option value="">Any ROE</option><option value="0.1">ROE &gt; 10%</option><option value="0.15">ROE &gt; 15%</option><option value="0.2">ROE &gt; 20%</option>
          </HybridSelect>
          <HybridSelect active={!!filters.min_revenue_growth} selectMode={selectModes.min_revenue_growth} onSelectChange={(mode) => handleSelectMode("min_revenue_growth", mode)} onCustomCommit={(v) => handleCustomCommit("min_revenue_growth", v, (n) => n / 100)} placeholder="Growth %" inputWidth={85}>
            <option value="">Any Rev Growth</option><option value="0.05">Rev Growth &gt; 5%</option><option value="0.1">Rev Growth &gt; 10%</option><option value="0.2">Rev Growth &gt; 20%</option>
          </HybridSelect>
          <select style={selStyle(!!filters.consensus)} value={filters.consensus} onChange={(e) => update("consensus", e.target.value)}>
            <option value="">All Consensus</option><option value="Buy">Buy</option><option value="Hold">Hold</option><option value="Sell">Sell</option>
          </select>
          <select style={selStyle(!!filters.min_upside_pct)} value={filters.min_upside_pct} onChange={(e) => update("min_upside_pct", e.target.value)}>
            <option value="">Any Upside</option><option value="5">Upside &gt; 5%</option><option value="10">Upside &gt; 10%</option><option value="20">Upside &gt; 20%</option>
          </select>
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

      {loading ? <div style={S.loading}>Screening…</div> : (
        <div ref={scrollRef} style={{ overflow: "auto", maxHeight: tableMaxH, scrollbarGutter: "stable", scrollSnapType: "y proximity", scrollPaddingTop: 29 }}>
          <table style={{ ...S.table, minWidth: tableView === "analysts" ? 700 : 900, ...(tableView === "analysts" ? { tableLayout: "fixed" as const } : {}) }}>
            <thead>
              <tr>
                {(tableView === "fundamentals" ? FUND_COLS : ANALYST_COLS).map(([h, num, key, width]: any) => {
                  const isScore = SCORE_KEYS.has(key);
                  return (
                    <th key={h} onClick={() => handleSort(key)} title={COL_TITLES[key] || h} style={{ ...S.th, textAlign: isScore ? "center" : num ? "right" : "left", cursor: "pointer", userSelect: "none", color: sortCol === key ? "#fb923c" : "#f97316", ...(isScore ? { width: SCORE_COL_WIDTH } : {}), ...(width ? { width } : {}), ...(key === "momentum_score" ? { borderLeft: "1px solid #2a2a2a" } : {}) }}>
                      {h}{sortCol === key ? (sortDir === "desc" ? " ▼" : " ▲") : ""}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => {
                const isHighlighted = r.symbol === highlightSymbol;
                const baseBg = isHighlighted ? "#2d1e00" : i % 2 === 0 ? "#1e293b" : "#162032";
                return (
                  <tr key={r.symbol} id={"row-" + r.symbol} onClick={() => onSelect(r.symbol)} style={{ background: baseBg, cursor: "pointer", scrollSnapAlign: "start", boxShadow: isHighlighted ? "inset 3px 0 0 #f97316" : "none" }} onMouseEnter={(e) => (e.currentTarget.style.background = "#334155")} onMouseLeave={(e) => (e.currentTarget.style.background = baseBg)}>
                    <td style={{ ...S.td, fontFamily: "monospace", fontWeight: 700, color: watchlistSet.has(r.symbol) ? "#f59e0b" : "#818cf8" }}>
                      <span style={{ display: "inline-flex", alignItems: "center" }}>
                        <StarButton active={watchlistSet.has(r.symbol)} onClick={(e) => { e.stopPropagation(); onToggleWatchlist && onToggleWatchlist(r.symbol); }} />
                        {r.symbol.replace(".L", "")}
                      </span>
                    </td>
                    {/* maxWidth lives on an inner div, not the td: in the auto-layout
                        fundamentals table a td's max-width is ignored, so a long name
                        would stretch the whole column. The div is respected and truncates. */}
                    <td style={{ ...S.td, color: "#f1f5f9" }} title={r.name}>
                      <div style={{ maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis" }}>{r.name}</div>
                    </td>
                    <td style={{ ...S.td, color: "#64748b" }} title={r.sector}>
                      <div style={{ maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis" }}>{SECTOR_ABBR[r.sector] || r.sector}</div>
                    </td>
                    <td style={{ ...S.td, color: "#64748b" }}>{r.ftse_index?.replace("FTSE ", "")}</td>
                    <td style={{ ...S.tdNum, color: "#ccc" }}>{fmt(r.market_cap, "currency", r.currency)}</td>
                    {tableView === "fundamentals" ? (
                      <>
                        <td style={{ ...S.tdNum, color: r.price_to_earnings < 15 ? "#10b981" : r.price_to_earnings > 40 ? "#ef4444" : "#ccc" }}>{fmt(r.price_to_earnings, "ratio")}</td>
                        <td style={{ ...S.tdNum, color: "#ccc" }}>{fmt(r.price_to_book, "ratio")}</td>
                        <td style={{ ...S.tdNum, color: gc(r.roe) }}>{fmt(r.roe, "pct")}</td>
                        <td style={{ ...S.tdNum, color: gc(r.revenue_growth) }}>{fmt(r.revenue_growth, "pct")}</td>
                        <td style={{ ...S.tdNum, color: r.debt_to_equity > 2 ? "#ef4444" : "#ccc" }}>{fmt(r.debt_to_equity, "ratio")}</td>
                        <td style={{ ...S.tdNum, color: r.pegy == null ? "#444" : r.pegy < 1 ? "#10b981" : r.pegy <= 2 ? "#f59e0b" : "#ef4444" }}>{r.pegy ?? "—"}</td>
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
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
