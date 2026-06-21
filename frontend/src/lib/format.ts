export const currSym = (code: string): string =>
  code === "USD" ? "$" : code === "EUR" ? "€" : "£";

export const fmt = (
  v: number | null | undefined,
  type: string = "number",
  currency: string = "GBP",
): string => {
  if (v === null || v === undefined || (typeof v === "number" && isNaN(v)))
    return "—";
  if (type === "currency") {
    const sym = currSym(currency);
    const abs = Math.abs(v);
    const neg = v < 0 ? "-" : "";
    if (abs >= 1e12) return neg + sym + (abs / 1e12).toFixed(2) + "T";
    if (abs >= 1e9) return neg + sym + (abs / 1e9).toFixed(2) + "B";
    if (abs >= 1e6) return neg + sym + (abs / 1e6).toFixed(2) + "M";
    return neg + sym + abs.toLocaleString();
  }
  if (type === "pct") return `${(v * 100).toFixed(1)}%`;
  if (type === "pct_direct") return `${v.toFixed(1)}%`;
  if (type === "x") return `${v.toFixed(2)}x`;
  if (type === "ratio") return v.toFixed(2);
  return v.toLocaleString();
};

// British date format (dd/mm/yyyy) for chart tooltip labels. Falls back to the
// raw value if it isn't a parseable date.
export const fmtUKDate = (d: string | number | Date): string => {
  const dt = new Date(d);
  return isNaN(dt.getTime()) ? String(d) : dt.toLocaleDateString("en-GB");
};

export const gc = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return "#94a3b8";
  return v >= 0 ? "#10b981" : "#ef4444";
};

// dividenddata.co.uk keys on the LSE EPIC (TIDM). For most stocks that's just the
// Yahoo symbol with the ".L" suffix stripped (GRG.L -> GRG). Two-letter mnemonics
// are the catch: by LSE convention they carry a trailing dot (BP., RR., NG. ...),
// which Yahoo collapses into "XX.L" — so a naive strip yields "BP" when the EPIC
// is "BP.". Re-add the dot for the two-letter case; DIVIDENDDATA_EPIC overrides
// handle any ticker that doesn't follow the convention.
const DIVIDENDDATA_EPIC: Record<string, string> = {};

export const dividendDataUrl = (symbol: string): string => {
  const s = symbol || "";
  let epic: string;
  if (DIVIDENDDATA_EPIC[s]) {
    epic = DIVIDENDDATA_EPIC[s];
  } else if (/^[A-Z]{2}\.L$/i.test(s)) {
    epic = s.replace(/\.L$/i, ".");
  } else {
    epic = s.replace(/\.L$/i, "");
  }
  return `https://www.dividenddata.co.uk/dividend-yield.py?epic=${encodeURIComponent(epic)}`;
};

export const pctColor = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return "#94a3b8";
  if (v > 0.005) return "#10b981";
  if (v < -0.005) return "#ef4444";
  return "#f59e0b";
};
