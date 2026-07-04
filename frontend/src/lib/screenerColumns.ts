import { gc } from "./format";

// Single source of truth for the Screener's optional "fundamentals" columns.
// Both the Screener table (which cells to render, in what order) and the
// Screener Settings page (which checkboxes to show) import this one list, so
// labels/keys/formatting live in exactly one place. The always-on columns
// (Symbol, Name, Sector, Index, Mkt Cap, and the 4 composite score pills) are
// NOT here — they're hardcoded in Screener.tsx and never toggleable.

export type ColumnFormat = "pct" | "ratio" | "currency" | "x" | "pct_direct";

// Per-column filter, rendered in the Screener's Advanced panel only when the
// column is enabled — so the filter set tracks the visible columns.
export interface ColumnFilterDef {
  dir: "min" | "max"; // min: keep rows with value >= threshold; max: keep value <= threshold.
  positiveOnly?: boolean; // For max-direction valuation ratios: also drop value <= 0 (e.g. loss-making P/E).
  presets: [string, string][]; // [option label, threshold in the column's stored units].
}

export interface ScreenerColumnDef {
  key: string; // API field name — also the sort key used by handleSort/sortCol.
  label: string; // Abbreviated <th> text, reused as the settings-page row label.
  title: string; // Full-name tooltip — feeds COL_TITLES and the settings description.
  group: string; // Thematic heading used to section the Settings page.
  format: ColumnFormat; // Passed to fmt() for the default cell text.
  defaultEnabled: boolean;
  filter: ColumnFilterDef; // Filter presets + direction (every toggleable column is numeric).
  naSectors?: string[]; // Sectors where this metric is not meaningful — blanked to "—" (see blankNaMetrics).
  color?: (v: number | null | undefined) => string; // Cell text colour; omit => plain "#ccc".
  render?: (v: number | null | undefined) => string; // Overrides fmt()-based text (PEGY only).
}

// Divisor to convert a human-typed custom filter value into the column's stored
// units: "pct" columns store fractions (15% → 0.15), everything else is 1:1.
export const filterScale = (format: ColumnFormat): number => (format === "pct" ? 100 : 1);

// P/E: preserves the pre-existing inline behaviour (Screener.tsx:398) where a
// null P/E coerces to 0 and renders green — cosmetic quirk, kept for parity.
const peColor = (v: number | null | undefined) => {
  const n = Number(v);
  return n < 15 ? "#10b981" : n > 40 ? "#ef4444" : "#ccc";
};
const deColor = (v: number | null | undefined) =>
  v != null && v > 2 ? "#ef4444" : "#ccc";
const pegyColor = (v: number | null | undefined) =>
  v == null ? "#444" : v < 1 ? "#10b981" : v <= 2 ? "#f59e0b" : "#ef4444";
const currentRatioColor = (v: number | null | undefined) =>
  v != null && v < 1 ? "#ef4444" : "#ccc";
// Piotroski F-score (0–9): 7+ is strong, 3 or below is weak.
const piotroskiColor = (v: number | null | undefined) =>
  v == null ? "#444" : v >= 7 ? "#10b981" : v <= 3 ? "#ef4444" : "#ccc";
// Altman Z: >3 safe zone, <1.8 distress zone, grey zone between.
const altmanColor = (v: number | null | undefined) =>
  v == null ? "#444" : v > 3 ? "#10b981" : v < 1.8 ? "#ef4444" : "#ccc";

// Fixed master display order, grouped by theme (valuation → returns → margins →
// growth → risk). Screener.tsx filters this by the user's enabled set and
// renders in exactly this order; the Settings page lists it in this order too.
// There is no reordering UI. The default-on columns (P/E, Div Yield, ROE, Rev
// Grwth, D/E, PEGY) render in this array's order — inserting default-off columns
// between them doesn't reorder them.
export const SCREENER_TOGGLE_COLUMNS: ScreenerColumnDef[] = [
  // Valuation & yield
  { key: "price_to_earnings", label: "P/E", title: "Price-to-earnings ratio", group: "Valuation & Yield", format: "ratio", defaultEnabled: true, color: peColor, filter: { dir: "max", positiveOnly: true, presets: [["P/E < 15", "15"], ["P/E < 25", "25"], ["P/E < 40", "40"]] } },
  { key: "price_to_book", label: "P/B", title: "Price-to-book ratio", group: "Valuation & Yield", format: "ratio", defaultEnabled: false, filter: { dir: "max", positiveOnly: true, presets: [["P/B < 1", "1"], ["P/B < 2", "2"], ["P/B < 4", "4"]] } },
  { key: "price_to_sales", label: "P/S", title: "Price-to-sales ratio", group: "Valuation & Yield", format: "ratio", defaultEnabled: false, filter: { dir: "max", positiveOnly: true, presets: [["P/S < 1", "1"], ["P/S < 3", "3"], ["P/S < 6", "6"]] } },
  { key: "dividend_yield", label: "Div Yield", title: "Dividend yield", group: "Valuation & Yield", format: "pct", defaultEnabled: true, filter: { dir: "min", presets: [["Yield > 2%", "0.02"], ["Yield > 4%", "0.04"], ["Yield > 6%", "0.06"]] } },
  // Returns on capital
  { key: "roe", label: "ROE", title: "Return on equity", group: "Returns on Capital", format: "pct", defaultEnabled: true, color: gc, filter: { dir: "min", presets: [["ROE > 10%", "0.1"], ["ROE > 15%", "0.15"], ["ROE > 20%", "0.2"]] } },
  { key: "roic", label: "ROIC", title: "Return on invested capital", group: "Returns on Capital", format: "pct", defaultEnabled: false, color: gc, filter: { dir: "min", presets: [["ROIC > 8%", "0.08"], ["ROIC > 12%", "0.12"], ["ROIC > 20%", "0.2"]] } },
  { key: "roce", label: "ROCE", title: "Return on capital employed", group: "Returns on Capital", format: "pct", defaultEnabled: false, color: gc, filter: { dir: "min", presets: [["ROCE > 8%", "0.08"], ["ROCE > 12%", "0.12"], ["ROCE > 20%", "0.2"]] } },
  { key: "roa", label: "ROA", title: "Return on assets", group: "Returns on Capital", format: "pct", defaultEnabled: false, color: gc, filter: { dir: "min", presets: [["ROA > 5%", "0.05"], ["ROA > 8%", "0.08"], ["ROA > 12%", "0.12"]] } },
  // Margins
  { key: "gross_margin", label: "Gross Mgn", title: "Gross margin", group: "Margins", format: "pct", defaultEnabled: false, color: gc, filter: { dir: "min", presets: [["Gross > 20%", "0.2"], ["Gross > 40%", "0.4"], ["Gross > 60%", "0.6"]] } },
  { key: "operating_margin", label: "Op Mgn", title: "Operating margin", group: "Margins", format: "pct", defaultEnabled: false, color: gc, filter: { dir: "min", presets: [["Op > 10%", "0.1"], ["Op > 20%", "0.2"], ["Op > 30%", "0.3"]] } },
  { key: "net_income_margin", label: "Net Mgn", title: "Net income margin", group: "Margins", format: "pct", defaultEnabled: false, color: gc, filter: { dir: "min", presets: [["Net > 5%", "0.05"], ["Net > 10%", "0.1"], ["Net > 20%", "0.2"]] } },
  { key: "fcf_margin", label: "FCF Mgn", title: "Free cash flow margin", group: "Margins", format: "pct", defaultEnabled: false, color: gc, naSectors: ["Financials"], filter: { dir: "min", presets: [["FCF > 5%", "0.05"], ["FCF > 10%", "0.1"], ["FCF > 15%", "0.15"]] } },
  // Growth
  { key: "revenue_growth", label: "Rev Grwth", title: "Revenue growth (year-on-year)", group: "Growth", format: "pct", defaultEnabled: true, color: gc, filter: { dir: "min", presets: [["Rev > 5%", "0.05"], ["Rev > 10%", "0.1"], ["Rev > 20%", "0.2"]] } },
  { key: "eps_diluted_growth", label: "EPS Grwth", title: "Diluted EPS growth (year-on-year)", group: "Growth", format: "pct", defaultEnabled: false, color: gc, filter: { dir: "min", presets: [["EPS > 5%", "0.05"], ["EPS > 10%", "0.1"], ["EPS > 20%", "0.2"]] } },
  { key: "fcf_growth", label: "FCF Grwth", title: "Free cash flow growth (year-on-year)", group: "Growth", format: "pct", defaultEnabled: false, color: gc, naSectors: ["Financials"], filter: { dir: "min", presets: [["FCF > 5%", "0.05"], ["FCF > 10%", "0.1"], ["FCF > 20%", "0.2"]] } },
  { key: "revenue_cagr_10", label: "Rev 10y", title: "Revenue 10-year CAGR", group: "Growth", format: "pct", defaultEnabled: false, color: gc, filter: { dir: "min", presets: [["10y > 5%", "0.05"], ["10y > 10%", "0.1"], ["10y > 15%", "0.15"]] } },
  { key: "eps_cagr_10", label: "EPS 10y", title: "Diluted EPS 10-year CAGR", group: "Growth", format: "pct", defaultEnabled: false, color: gc, filter: { dir: "min", presets: [["10y > 5%", "0.05"], ["10y > 10%", "0.1"], ["10y > 15%", "0.15"]] } },
  // Leverage & risk
  { key: "debt_to_equity", label: "D/E", title: "Debt-to-equity ratio", group: "Leverage & Risk", format: "ratio", defaultEnabled: true, color: deColor, filter: { dir: "max", presets: [["D/E < 0.5", "0.5"], ["D/E < 1", "1"], ["D/E < 2", "2"]] } },
  { key: "current_ratio", label: "Curr Ratio", title: "Current ratio (current assets ÷ current liabilities)", group: "Leverage & Risk", format: "ratio", defaultEnabled: false, color: currentRatioColor, filter: { dir: "min", presets: [["Curr > 1", "1"], ["Curr > 1.5", "1.5"], ["Curr > 2", "2"]] } },
  { key: "altman_z", label: "Altman Z", title: "Altman Z-score (bankruptcy risk; higher is safer)", group: "Leverage & Risk", format: "ratio", defaultEnabled: false, color: altmanColor, filter: { dir: "min", presets: [["Z > 1.8", "1.8"], ["Z > 3", "3"]] } },
  { key: "piotroski_score", label: "Piotroski", title: "Piotroski F-score (0–9; higher is stronger)", group: "Leverage & Risk", format: "ratio", defaultEnabled: false, color: piotroskiColor, render: (v) => (v == null ? "—" : String(v)), filter: { dir: "min", presets: [["F ≥ 5", "5"], ["F ≥ 7", "7"], ["F ≥ 8", "8"]] } },
  { key: "volatility_annualised", label: "Volatility", title: "Annualised price volatility", group: "Leverage & Risk", format: "pct_direct", defaultEnabled: false, filter: { dir: "max", presets: [["Vol < 20%", "20"], ["Vol < 30%", "30"], ["Vol < 40%", "40"]] } },
  // Composite value (kept last in the array to preserve the default column
  // order in the table; grouped with Valuation on the Settings page).
  { key: "pegy", label: "PEGY", title: "Price/earnings-to-growth-and-yield ratio", group: "Valuation & Yield", format: "ratio", defaultEnabled: true, color: pegyColor, render: (v) => (v == null ? "—" : String(v)), filter: { dir: "max", positiveOnly: true, presets: [["PEGY < 1", "1"], ["PEGY < 1.5", "1.5"], ["PEGY < 2", "2"]] } },
];

// The default view: P/E, Div Yield, ROE, Rev Grwth, D/E, PEGY on; the rest off.
// Merged over any saved prefs so a column added here later gets a sensible
// default instead of undefined for users with an existing saved blob (and so
// users who already customised their columns keep their own choices).
export const DEFAULT_SCREENER_COLUMN_PREFS: Record<string, boolean> =
  Object.fromEntries(SCREENER_TOGGLE_COLUMNS.map((c) => [c.key, c.defaultEnabled]));

// Columns bucketed by their `group`, in group first-appearance order (and array
// order within each group). Used by the Settings page to render subheadings.
// Note: this is presentational only — the table renders enabled columns in the
// master array order above, independent of this grouping.
export const SCREENER_COLUMN_GROUPS: { group: string; columns: ScreenerColumnDef[] }[] =
  SCREENER_TOGGLE_COLUMNS.reduce<{ group: string; columns: ScreenerColumnDef[] }[]>((acc, c) => {
    const bucket = acc.find((g) => g.group === c.group);
    if (bucket) bucket.columns.push(c);
    else acc.push({ group: c.group, columns: [c] });
    return acc;
  }, []);

// Columns that carry a naSectors rule (precomputed so the per-row pass is cheap).
const NA_METRIC_COLUMNS = SCREENER_TOGGLE_COLUMNS.filter((c) => c.naSectors && c.naSectors.length);

// Null out metrics that aren't meaningful for a row's sector (e.g. free-cash-flow
// figures for banks — see the NatWest FCF-growth case). Mutates and returns the
// row. Applied once after fetch so display, sort and filter all treat the value
// as missing ("—"), rather than blanking only the cell and letting a filter/sort
// still act on the junk number. Mirrors Fair Value excluding financials.
export const blankNaMetrics = <T extends { sector?: string | null }>(row: T): T => {
  for (const c of NA_METRIC_COLUMNS) {
    if (row.sector && c.naSectors!.includes(row.sector)) (row as any)[c.key] = null;
  }
  return row;
};
