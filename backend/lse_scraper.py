"""
LSE.co.uk fundamentals scraper.

Pulls annual financial data from lse.co.uk's ShareFundamentals page, dedupes
the 5-column restated/as-reported layout into one row per fiscal year, and
returns absolute-unit values matching yfinance conventions (millions → units;
pence → pounds for per-share fields).

The page is behind Cloudflare; curl_cffi with Chrome TLS impersonation
defeats the JS challenge.

Used by updater.py to fill nulls in yfinance-sourced rows and to synthesize
rows for fiscal years yfinance hasn't picked up yet (typically ~20% of the
universe at any given time, decaying as Yahoo catches up).
"""

import re
import logging
from datetime import date
from io import StringIO

import pandas as pd
from curl_cffi import requests as cr

log = logging.getLogger(__name__)

BASE = "https://www.lse.co.uk"
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        1,
    )
}

_MONETARY = {
    "revenue", "operating_income", "interest_expense", "pretax_income",
    "net_income", "intangible_assets", "ppe_net", "total_current_assets",
    "total_assets", "inventories", "receivables", "cash_and_equiv",
    "total_current_liabilities", "total_equity", "retained_earnings",
    "st_debt", "lt_debt",
}
_PERSHARE = {"eps_basic", "eps_diluted", "dividends_per_share"}


def _to_float(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "nan", "n/a", "N/A", "NaN"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").rstrip("p").rstrip("%").strip()
    try:
        f = float(s)
    except ValueError:
        return None
    return -f if neg else f


def _parse_date_col(s: str):
    m = re.match(r"^(\d{1,2}) (\w{3}) '(\d{2})$", str(s).strip())
    if not m:
        return None, None
    day, mon, yr = int(m.group(1)), _MONTHS.get(m.group(2)), 2000 + int(m.group(3))
    if not mon:
        return None, None
    try:
        return yr, date(yr, mon, day)
    except ValueError:
        return None, None


def _fetch(url: str):
    try:
        r = cr.get(url, impersonate="chrome", timeout=20)
        if r.status_code != 200:
            log.debug(f"LSE {r.status_code}: {url}")
            return None
        return r.text
    except Exception as e:
        log.warning(f"LSE fetch error {url}: {e}")
        return None


def fetch_fundamentals(symbol: str) -> dict:
    """Fetch parsed fundamentals for one symbol.

    Returns {fiscal_year: {field: value, period_end_date: 'YYYY-MM-DD'}}.
    Empty dict on any failure (Cloudflare miss, 404, parse error, etc).
    """
    sym = symbol.replace(".L", "").upper()
    sp = _fetch(f"{BASE}/SharePrice.asp?shareprice={sym}")
    if not sp:
        return {}
    slug_m = re.search(
        rf'href="[^"]*ShareFundamentals\.html\?shareprice={sym}&(?:amp;)?share=([^"&]+)"',
        sp,
    )
    slug = slug_m.group(1) if slug_m else sym
    fu = _fetch(f"{BASE}/ShareFundamentals.html?shareprice={sym}&share={slug}")
    if not fu:
        return {}

    try:
        tables = pd.read_html(StringIO(fu))
    except Exception as e:
        log.warning(f"LSE read_html failed {sym}: {e}")
        return {}
    if not tables:
        return {}
    main = max(tables, key=lambda t: t.shape[0])

    date_row_idx = None
    for i in range(min(8, len(main))):
        row_vals = [str(v) for v in main.iloc[i, 1:].tolist()]
        if any(_parse_date_col(v)[0] for v in row_vals):
            date_row_idx = i
            break
    if date_row_idx is None:
        return {}

    cols = []
    for v in main.iloc[date_row_idx, 1:].astype(str).tolist():
        fy, dt = _parse_date_col(v)
        cols.append((fy, dt))

    label_col = main.iloc[:, 0].astype(str)

    def _row_vals(pattern: str):
        mask = label_col.str.contains(pattern, regex=True, na=False, case=False)
        if not mask.any():
            return [None] * len(cols)
        r = main.loc[mask].iloc[0, 1:].tolist()
        return [_to_float(v) for v in r]

    # Two 'Borrowings' rows: first = current, second = non-current
    borrow_mask = label_col == "Borrowings"
    borrow_rows = main.loc[borrow_mask]
    cur_borrow = (
        [_to_float(v) for v in borrow_rows.iloc[0, 1:].tolist()]
        if len(borrow_rows) >= 1
        else [None] * len(cols)
    )
    non_cur_borrow = (
        [_to_float(v) for v in borrow_rows.iloc[1, 1:].tolist()]
        if len(borrow_rows) >= 2
        else [None] * len(cols)
    )

    raw = {
        "revenue":                   _row_vals(r"^Revenue$"),
        "operating_income":          _row_vals(r"^Operating Profit"),
        "interest_expense":          _row_vals(r"^Net Interest$"),
        "pretax_income":             _row_vals(r"^Pre Tax Profit$"),
        "net_income":                _row_vals(r"^Post Tax Profit$"),
        "eps_basic":                 _row_vals(r"^Earnings per Share \(Basic\)$"),
        "eps_diluted":               _row_vals(r"^Earnings per Share \(Diluted\)$"),
        "dividends_per_share":       _row_vals(r"^Dividend per Share$"),
        "intangible_assets":         _row_vals(r"^Intangible Assets$"),
        "ppe_net":                   _row_vals(r"^Property, Plant"),
        "total_current_assets":      _row_vals(r"^Total Current Assets$"),
        "total_assets":              _row_vals(r"^Total Assets$"),
        "inventories":               _row_vals(r"^Inventories$"),
        "receivables":               _row_vals(r"^Trade and Other Re"),
        "cash_and_equiv":            _row_vals(r"^Cash at Bank"),
        "total_current_liabilities": _row_vals(r"^Total Current Liabilities$"),
        "total_equity":              _row_vals(r"^Total Equity$"),
        "retained_earnings":         _row_vals(r"^Retained Earnings$"),
        "st_debt":                   cur_borrow,
        "lt_debt":                   non_cur_borrow,
    }

    # Collapse 5-col layout: one row per fiscal year, leftmost non-null wins.
    by_fy: dict = {}
    for col_idx, (fy, dt) in enumerate(cols):
        if fy is None:
            continue
        if fy not in by_fy:
            by_fy[fy] = {"period_end_date": dt}
        for field, vals in raw.items():
            if by_fy[fy].get(field) is None:
                v = vals[col_idx]
                if v is not None:
                    by_fy[fy][field] = v

    # Convert units. Per-share unit guard: real EPS/DPS in pence rarely
    # exceeds ~5000p (£50/share). Above that = upstream unit bug; drop.
    out = {}
    for fy, data in by_fy.items():
        row = {"period_end_date": data.get("period_end_date")}
        for field, val in data.items():
            if field == "period_end_date" or val is None:
                continue
            if field in _MONETARY:
                row[field] = val * 1_000_000
            elif field in _PERSHARE:
                if abs(val) > 5000:
                    continue
                row[field] = val / 100.0
            else:
                row[field] = val
        # Tax = pretax - net_income (LSE doesn't break it out)
        if row.get("pretax_income") is not None and row.get("net_income") is not None:
            row["income_tax"] = row["pretax_income"] - row["net_income"]
        # Net interest is signed (negative = expense). yf stores interest_expense
        # as a positive value (or negative; both conventions appear). Keep the
        # LSE signed value — downstream callers should use abs() where it matters.
        out[fy] = row

    return out


# ---------------------------------------------------------------------------
# Merge into annual_rows built by updater.py
# ---------------------------------------------------------------------------

# Fields LSE can directly populate. ROIC/ROCE need NOPAT/tax-rate which we
# don't have a clean signal for from LSE alone, so they're left for the case
# where a yf row already exists.
_LSE_FIELDS = [
    "revenue", "operating_income", "interest_expense", "pretax_income",
    "income_tax", "net_income", "eps_basic", "eps_diluted",
    "dividends_per_share", "intangible_assets", "ppe_net",
    "total_current_assets", "total_assets", "inventories", "receivables",
    "cash_and_equiv", "total_current_liabilities", "total_equity",
    "retained_earnings", "st_debt", "lt_debt",
]


def _sf(x):
    """Safe float — pass through, treating None/inf/NaN as None."""
    try:
        if x is None:
            return None
        f = float(x)
        if f != f or abs(f) > 1e18:  # NaN or absurd
            return None
        return f
    except (TypeError, ValueError):
        return None


def _blank_row(symbol: str, fiscal_year: int, period_end) -> dict:
    """Row template with every column annual_financials cares about set to None.
    Mirrors the row dict built inside updater.process_stock."""
    return {
        "company_symbol": symbol,
        "fiscal_year": fiscal_year,
        "period_end_date": period_end,
        "revenue": None, "cogs": None, "gross_profit": None,
        "rnd": None, "sga": None,
        "operating_income": None, "ebitda": None,
        "interest_expense": None, "pretax_income": None,
        "income_tax": None, "net_income": None,
        "eps_basic": None, "eps_diluted": None,
        "shares_basic": None, "shares_diluted": None,
        "dividends_per_share": None,
        "cash_and_equiv": None,
        "total_current_assets": None, "total_current_liabilities": None,
        "total_assets": None, "total_equity": None,
        "st_debt": None, "lt_debt": None,
        "shares_outstanding": None,
        "cf_cfo": None, "capex": None, "fcf": None,
        "net_debt": None, "working_capital": None, "book_value": None,
        "intangible_assets": None, "ppe_net": None,
        "inventories": None, "receivables": None,
        "retained_earnings": None,
        "gross_margin": None, "operating_margin": None,
        "net_income_margin": None, "ebitda_margin": None, "fcf_margin": None,
        "roe": None, "roa": None, "roic": None, "roce": None,
        "debt_to_equity": None, "debt_to_assets": None,
        "current_ratio": None, "interest_coverage": None,
        "revenue_per_share": None, "fcf_per_share": None,
        "book_value_per_share": None,
        "period_end_price": None, "market_cap": None, "enterprise_value": None,
        "price_to_earnings": None, "price_to_book": None,
        "price_to_sales": None, "price_to_fcf": None,
        "ev_to_ebitda": None, "ev_to_sales": None,
        "revenue_growth": None, "gross_profit_growth": None,
        "operating_income_growth": None, "net_income_growth": None,
        "eps_diluted_growth": None, "fcf_growth": None,
        "total_assets_growth": None, "total_equity_growth": None,
        "revenue_cagr_10": None, "eps_cagr_10": None,
        "fcf_cagr_10": None, "equity_cagr_10": None,
        "gross_margin_median": None, "operating_margin_median": None,
        "net_margin_median": None,
        "roe_median": None, "roic_median": None, "debt_to_equity_median": None,
    }


def _recompute_basic_derived(row: dict):
    """Fill margins/ratios that can be computed from whatever's in the row.
    Idempotent — only writes when source fields exist and target is None."""
    rev = row.get("revenue")
    op = row.get("operating_income")
    ni = row.get("net_income")
    ta = row.get("total_assets")
    te = row.get("total_equity")
    cl = row.get("total_current_liabilities")
    ca = row.get("total_current_assets")
    cash = row.get("cash_and_equiv")
    std = row.get("st_debt") or 0
    ltd = row.get("lt_debt") or 0
    iexp = row.get("interest_expense")

    if row.get("operating_margin") is None and rev and op is not None and rev > 0:
        row["operating_margin"] = _sf(op / rev)
    if row.get("net_income_margin") is None and rev and ni is not None and rev > 0:
        row["net_income_margin"] = _sf(ni / rev)
    if row.get("roe") is None and ni is not None and te and te > 0:
        row["roe"] = _sf(ni / te)
    if row.get("roa") is None and ni is not None and ta and ta > 0:
        row["roa"] = _sf(ni / ta)
    if row.get("roce") is None and op is not None and ta and cl is not None:
        ce = ta - cl
        if ce > 0:
            row["roce"] = _sf(op / ce)
    if row.get("debt_to_equity") is None and te and te > 0 and (std or ltd):
        row["debt_to_equity"] = _sf((std + ltd) / te)
    if row.get("debt_to_assets") is None and ta and ta > 0:
        row["debt_to_assets"] = _sf((std + ltd) / ta)
    if row.get("current_ratio") is None and ca and cl and cl > 0:
        row["current_ratio"] = _sf(ca / cl)
    if row.get("interest_coverage") is None and op is not None and iexp and iexp != 0:
        row["interest_coverage"] = _sf(op / abs(iexp))
    if row.get("net_debt") is None and (std or ltd or cash is not None):
        row["net_debt"] = _sf(std + ltd - (cash or 0))
    if row.get("working_capital") is None and ca is not None and cl is not None:
        row["working_capital"] = _sf(ca - cl)
    if row.get("book_value") is None and te is not None:
        row["book_value"] = te


def merge(annual_rows: list, lse_data: dict, symbol: str) -> list:
    """Merge LSE-sourced data into yf-sourced annual_rows.

    For each fiscal year LSE provides:
      - If a yf row exists for that FY, fill any None fields from LSE.
      - Otherwise, synthesize a new row populated from LSE.
    Recomputes basic margins/ratios on every touched row.
    Returns the (possibly grown) row list.
    """
    if not lse_data:
        return annual_rows

    by_fy = {r["fiscal_year"]: r for r in annual_rows}

    for fy, lse_row in lse_data.items():
        existing = by_fy.get(fy)
        if existing is not None:
            for f in _LSE_FIELDS:
                if existing.get(f) is None and lse_row.get(f) is not None:
                    existing[f] = lse_row[f]
            _recompute_basic_derived(existing)
        else:
            period_end = lse_row.get("period_end_date")
            new_row = _blank_row(symbol, fy, period_end)
            for f in _LSE_FIELDS:
                if lse_row.get(f) is not None:
                    new_row[f] = lse_row[f]
            _recompute_basic_derived(new_row)
            annual_rows.append(new_row)
            by_fy[fy] = new_row

    return annual_rows
