"""
FinScope v2 — yfinance Daily Updater
======================================
Fetches financials for 25 stocks/day from Yahoo Finance.
Calculates ROIC, CAGRs, medians, growth rates, valuation ratios.
Upserts results into PostgreSQL.

Run daily:
    python updater.py

All 350 stocks rotate every ~14 days.
"""

import time
import os
import psycopg2
import psycopg2.extras
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, datetime
from dotenv import load_dotenv
import logging
import warnings

import lse_scraper

load_dotenv()

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("updater.log"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

STOCKS_PER_RUN = 25
DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host": os.environ.get("DB_HOST", ""),
    "port": os.environ.get("DB_PORT", "5432"),
    "sslmode": "require",
}


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def db_query(sql, params=None):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_stocks_to_update(n):
    return db_query(
        """
        SELECT symbol, name, financials_updated FROM company_metadata
        ORDER BY financials_updated ASC NULLS FIRST
        LIMIT %s
    """,
        (n,),
    )


def mark_updated(symbol):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE company_metadata SET financials_updated = %s WHERE symbol = %s",
        (date.today(), symbol),
    )
    conn.commit()
    conn.close()


def si(v):
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return int(float(v))
    except:
        return None


def sf(v):
    try:
        if v is None:
            return None
        if isinstance(v, str) and v.lower() in (
            "infinity",
            "-infinity",
            "inf",
            "-inf",
            "nan",
        ):
            return None
        f = float(v)
        return None if np.isnan(f) or np.isinf(f) or abs(f) > 1e15 else f
    except:
        return None


def sg(series, key):
    try:
        if key in series.index:
            return series[key]
        return None
    except:
        return None


def calc_cagr(start, end, years):
    try:
        if not start or not end or years <= 0:
            return None
        if start <= 0 or end <= 0:
            return None
        return (end / start) ** (1 / years) - 1
    except:
        return None


def calc_roic(op_income, tax_rate, total_assets, curr_liab, cash):
    try:
        tax_rate = tax_rate or 0.21
        nopat = op_income * (1 - tax_rate)
        invested_capital = total_assets - curr_liab - (cash or 0)
        if invested_capital <= 0:
            return None
        return nopat / invested_capital
    except:
        return None


def calc_roce(op_income, total_assets, curr_liab):
    try:
        capital_employed = total_assets - curr_liab
        if not capital_employed or capital_employed <= 0:
            return None
        return op_income / capital_employed
    except:
        return None


def calc_medians(rows, field):
    vals = [r[field] for r in rows if r.get(field) is not None]
    return float(np.median(vals)) if vals else None


_SUMMARY_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "updater_summary.log")


def _write_summary(line: str) -> None:
    """Append one summary line per run. Swallows IO errors — never blocks the job."""
    try:
        with open(_SUMMARY_LOG, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception as e:
        log.error(f"Summary log write failed: {e}")


def process_stock(symbol: str):
    log.info(f"  Fetching {symbol} from yfinance...")
    try:
        ticker = yf.Ticker(symbol)

        inc_a = ticker.income_stmt
        bal_a = ticker.balance_sheet
        cf_a = ticker.cashflow
        inc_q = ticker.quarterly_income_stmt
        info = ticker.info or {}

        if inc_a is None or inc_a.empty:
            log.warning(f"  No yfinance income data for {symbol} — will try LSE")
            inc_a = pd.DataFrame()

        yahoo_market_cap = info.get("marketCap")
        yahoo_trailing_pe = info.get("trailingPE")
        yahoo_price_to_sales = info.get("priceToSalesTrailing12Months")
        yahoo_price_to_book = info.get("priceToBook")

        valid_cols = []
        for col in inc_a.columns:
            revenue_check = sg(inc_a[col], "Total Revenue")
            if revenue_check and revenue_check > 0:
                valid_cols.append(col)

        if valid_cols:
            most_recent_col = valid_cols[0]
            log.info(
                f"  Most recent data year: {most_recent_col.year if hasattr(most_recent_col, 'year') else most_recent_col}"
            )
            try:
                hist = ticker.history(period="10y", interval="1mo")
                hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
            except:
                hist = None
        else:
            log.warning(f"  No valid yfinance columns for {symbol} — relying on LSE")
            most_recent_col = None
            hist = None

        def get_price_at_date(target_date):
            if hist is None or hist.empty:
                return None
            try:
                target = pd.Timestamp(target_date)
                diffs = abs(hist.index - target)
                min_diff = diffs.min()
                if min_diff.days > 45:
                    return None
                closest_idx = diffs.argmin()
                price = hist.iloc[closest_idx]["Close"]
                currency = info.get("currency", "GBp")
                if currency == "GBp":
                    price = price / 100
                return float(price) if price and not np.isnan(price) else None
            except:
                return None

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE company_metadata SET
                name = COALESCE(%s, name),
                sector = COALESCE(%s, sector),
                industry = COALESCE(%s, industry),
                full_time_employees = COALESCE(%s, full_time_employees),
                description = COALESCE(%s, description),
                financial_currency = COALESCE(%s, financial_currency)
            WHERE symbol = %s
        """,
            (
                info.get("longName") or info.get("shortName"),
                info.get("sector"),
                info.get("industry"),
                info.get("fullTimeEmployees"),
                (info.get("longBusinessSummary") or "")[:2000] or None,
                info.get("financialCurrency"),
                symbol,
            ),
        )
        conn.commit()
        conn.close()

        annual_rows = []

        for col in valid_cols:
            try:
                period_end = col.date() if hasattr(col, "date") else col
                fiscal_year = period_end.year

                revenue = si(sg(inc_a[col], "Total Revenue"))
                cogs = si(sg(inc_a[col], "Cost Of Revenue"))
                gross_profit = si(sg(inc_a[col], "Gross Profit"))
                rnd = si(sg(inc_a[col], "Research And Development"))
                sga = si(sg(inc_a[col], "Selling General And Administrative"))
                op_income = si(sg(inc_a[col], "Operating Income"))
                ebitda = si(sg(inc_a[col], "EBITDA"))
                interest_exp = si(sg(inc_a[col], "Interest Expense"))
                pretax_income = si(sg(inc_a[col], "Pretax Income"))
                income_tax = si(sg(inc_a[col], "Tax Provision"))
                net_income = si(sg(inc_a[col], "Net Income"))
                eps_basic = sf(sg(inc_a[col], "Basic EPS"))
                eps_diluted = sf(sg(inc_a[col], "Diluted EPS"))
                shares_basic = si(sg(inc_a[col], "Basic Average Shares"))
                shares_diluted = si(sg(inc_a[col], "Diluted Average Shares"))
                da = si(sg(inc_a[col], "Reconciled Depreciation"))

                cash = None
                curr_assets = None
                curr_liab = None
                total_assets = None
                total_equity = None
                st_debt = None
                lt_debt = None
                shares_out = None

                if bal_a is not None and col in bal_a.columns:
                    cash = si(sg(bal_a[col], "Cash And Cash Equivalents"))
                    curr_assets = si(sg(bal_a[col], "Current Assets"))
                    curr_liab = si(sg(bal_a[col], "Current Liabilities"))
                    total_assets = si(sg(bal_a[col], "Total Assets"))
                    total_equity = si(sg(bal_a[col], "Stockholders Equity"))
                    st_debt = si(sg(bal_a[col], "Current Debt"))
                    lt_debt = si(sg(bal_a[col], "Long Term Debt"))
                    shares_out = si(sg(bal_a[col], "Ordinary Shares Number"))

                cfo = None
                capex_raw = None
                if cf_a is not None and col in cf_a.columns:
                    cfo = si(sg(cf_a[col], "Operating Cash Flow"))
                    capex_raw = si(sg(cf_a[col], "Capital Expenditure"))

                capex = abs(capex_raw) if capex_raw is not None else None
                fcf = (cfo - capex) if (cfo is not None and capex is not None) else None
                net_debt = (
                    ((st_debt or 0) + (lt_debt or 0) - (cash or 0))
                    if (st_debt or lt_debt or cash)
                    else None
                )
                working_capital = (
                    ((curr_assets or 0) - (curr_liab or 0))
                    if (curr_assets and curr_liab)
                    else None
                )
                book_value = total_equity
                tax_rate = (
                    (abs(income_tax) / pretax_income)
                    if (income_tax and pretax_income and pretax_income > 0)
                    else 0.21
                )
                nopat = si(op_income * (1 - tax_rate)) if op_income else None

                gross_margin = (
                    sf(gross_profit / revenue)
                    if (gross_profit and revenue and revenue > 0)
                    else None
                )
                op_margin = (
                    sf(op_income / revenue)
                    if (op_income and revenue and revenue > 0)
                    else None
                )
                net_margin = (
                    sf(net_income / revenue)
                    if (net_income and revenue and revenue > 0)
                    else None
                )
                ebitda_margin = (
                    sf(ebitda / revenue)
                    if (ebitda and revenue and revenue > 0)
                    else None
                )
                fcf_margin = (
                    sf(fcf / revenue)
                    if (fcf is not None and revenue and revenue > 0)
                    else None
                )

                roe = (
                    sf(net_income / total_equity)
                    if (net_income and total_equity and total_equity > 0)
                    else None
                )
                roa = (
                    sf(net_income / total_assets)
                    if (net_income and total_assets and total_assets > 0)
                    else None
                )
                roic = (
                    calc_roic(op_income, tax_rate, total_assets, curr_liab, cash)
                    if op_income and total_assets and curr_liab
                    else None
                )
                roce = (
                    calc_roce(op_income, total_assets, curr_liab)
                    if (op_income and total_assets and curr_liab)
                    else None
                )

                de = (
                    sf(((st_debt or 0) + (lt_debt or 0)) / total_equity)
                    if (total_equity and total_equity > 0 and (st_debt or lt_debt))
                    else None
                )
                da_r = (
                    sf(((st_debt or 0) + (lt_debt or 0)) / total_assets)
                    if (total_assets and total_assets > 0)
                    else None
                )
                curr_r = (
                    sf(curr_assets / curr_liab)
                    if (curr_assets and curr_liab and curr_liab > 0)
                    else None
                )
                int_cov = (
                    sf(op_income / abs(interest_exp))
                    if (op_income and interest_exp and interest_exp != 0)
                    else None
                )

                rev_ps = (
                    sf(revenue / shares_diluted)
                    if (revenue and shares_diluted and shares_diluted > 0)
                    else None
                )
                fcf_ps = (
                    sf(fcf / shares_diluted)
                    if (fcf is not None and shares_diluted and shares_diluted > 0)
                    else None
                )
                bvps = (
                    sf(book_value / shares_diluted)
                    if (book_value and shares_diluted and shares_diluted > 0)
                    else None
                )

                period_price = get_price_at_date(period_end)

                if col == most_recent_col and yahoo_market_cap:
                    market_cap_value = si(yahoo_market_cap)
                else:
                    period_shares = shares_diluted or shares_basic or shares_out
                    if period_price and period_shares:
                        market_cap_value = int(period_price * period_shares)
                    else:
                        market_cap_value = None

                if col == most_recent_col and yahoo_trailing_pe:
                    pe_value = sf(yahoo_trailing_pe)
                else:
                    pe_value = (
                        sf(market_cap_value / net_income)
                        if (market_cap_value and net_income and net_income > 0)
                        else None
                    )

                if col == most_recent_col and yahoo_price_to_sales:
                    ps_value = sf(yahoo_price_to_sales)
                else:
                    ps_value = (
                        sf((period_price * (shares_diluted or 1)) / revenue)
                        if (period_price and revenue and revenue > 0)
                        else None
                    )

                if col == most_recent_col and yahoo_price_to_book:
                    pb_value = sf(yahoo_price_to_book)
                elif market_cap_value and total_equity and total_equity > 0:
                    pb_value = sf(market_cap_value / total_equity)
                else:
                    pb_value = None

                row = {
                    "company_symbol": symbol,
                    "fiscal_year": fiscal_year,
                    "period_end_date": period_end,
                    "revenue": revenue,
                    "cogs": cogs,
                    "gross_profit": gross_profit,
                    "rnd": rnd,
                    "sga": sga,
                    "operating_income": op_income,
                    "ebitda": ebitda,
                    "interest_expense": interest_exp,
                    "pretax_income": pretax_income,
                    "income_tax": income_tax,
                    "net_income": net_income,
                    "eps_basic": eps_basic,
                    "eps_diluted": eps_diluted,
                    "shares_basic": shares_basic,
                    "shares_diluted": shares_diluted,
                    "dividends_per_share": None,
                    "cash_and_equiv": cash,
                    "total_current_assets": curr_assets,
                    "total_current_liabilities": curr_liab,
                    "total_assets": total_assets,
                    "total_equity": total_equity,
                    "st_debt": st_debt,
                    "lt_debt": lt_debt,
                    "shares_outstanding": shares_out,
                    "cf_cfo": cfo,
                    "capex": capex,
                    "fcf": fcf,
                    "net_debt": net_debt,
                    "working_capital": working_capital,
                    "book_value": book_value,
                    "gross_margin": gross_margin,
                    "operating_margin": op_margin,
                    "net_income_margin": net_margin,
                    "ebitda_margin": ebitda_margin,
                    "fcf_margin": fcf_margin,
                    "roe": roe,
                    "roa": roa,
                    "roic": roic,
                    "roce": roce,
                    "debt_to_equity": de,
                    "debt_to_assets": da_r,
                    "current_ratio": curr_r,
                    "interest_coverage": int_cov,
                    "revenue_per_share": rev_ps,
                    "fcf_per_share": fcf_ps,
                    "book_value_per_share": bvps,
                    "period_end_price": period_price,
                    "market_cap": market_cap_value,
                    "enterprise_value": (
                        si(info.get("enterpriseValue"))
                        if col == most_recent_col
                        else None
                    ),
                    "price_to_earnings": pe_value,
                    "price_to_book": pb_value,
                    "price_to_sales": ps_value,
                    "price_to_fcf": (
                        sf((period_price * (shares_diluted or 1)) / fcf)
                        if (period_price and fcf and fcf > 0)
                        else None
                    ),
                    "ev_to_ebitda": (
                        sf(info.get("enterpriseToEbitda"))
                        if col == most_recent_col
                        else None
                    ),
                    "ev_to_sales": (
                        sf(info.get("enterpriseToRevenue"))
                        if col == most_recent_col
                        else None
                    ),
                    "revenue_growth": None,
                    "gross_profit_growth": None,
                    "operating_income_growth": None,
                    "net_income_growth": None,
                    "eps_diluted_growth": None,
                    "fcf_growth": None,
                    "total_assets_growth": None,
                    "total_equity_growth": None,
                    "revenue_cagr_10": None,
                    "eps_cagr_10": None,
                    "fcf_cagr_10": None,
                    "equity_cagr_10": None,
                    "gross_margin_median": None,
                    "operating_margin_median": None,
                    "net_margin_median": None,
                    "roe_median": None,
                    "roic_median": None,
                    "debt_to_equity_median": None,
                }

                annual_rows.append(row)
            except Exception as e:
                log.error(f"  Error processing {col} for {symbol}: {e}")
                continue

        if annual_rows:
            annual_rows.sort(key=lambda r: r["period_end_date"])

        # Merge LSE.co.uk fundamentals: fill nulls in yf rows and synthesize
        # rows for fiscal years yf hasn't picked up yet. Best-effort — never
        # fail the yf updater because of LSE issues.
        try:
            lse_data = lse_scraper.fetch_fundamentals(symbol)
            if lse_data:
                before = len(annual_rows)
                annual_rows = lse_scraper.merge(annual_rows, lse_data, symbol)
                annual_rows.sort(key=lambda r: r["period_end_date"])
                added = len(annual_rows) - before
                log.info(f"  LSE merge: {len(lse_data)} FY found, {added} new row(s) added")
        except Exception as e:
            log.warning(f"  LSE merge failed for {symbol}: {e}")

        if not annual_rows:
            log.warning(f"  No data from yfinance or LSE for {symbol}")
            return 0

        for i in range(1, len(annual_rows)):
            cur_r = annual_rows[i]
            prv_r = annual_rows[i - 1]
            for field, col in [
                ("revenue_growth", "revenue"),
                ("gross_profit_growth", "gross_profit"),
                ("operating_income_growth", "operating_income"),
                ("net_income_growth", "net_income"),
                ("eps_diluted_growth", "eps_diluted"),
                ("fcf_growth", "fcf"),
                ("total_assets_growth", "total_assets"),
                ("total_equity_growth", "total_equity"),
            ]:
                try:
                    prev_val = prv_r.get(col)
                    curr_val = cur_r.get(col)
                    if prev_val and curr_val and prev_val != 0:
                        cur_r[field] = sf((curr_val - prev_val) / abs(prev_val))
                except:
                    pass

        if len(annual_rows) >= 2:
            latest = annual_rows[-1]
            oldest = annual_rows[0]
            n_years = latest["fiscal_year"] - oldest["fiscal_year"]
            if n_years > 0:
                latest["revenue_cagr_10"] = calc_cagr(
                    oldest.get("revenue"), latest.get("revenue"), n_years
                )
                latest["eps_cagr_10"] = calc_cagr(
                    oldest.get("eps_diluted"), latest.get("eps_diluted"), n_years
                )
                latest["fcf_cagr_10"] = calc_cagr(
                    oldest.get("fcf"), latest.get("fcf"), n_years
                )
                latest["equity_cagr_10"] = calc_cagr(
                    oldest.get("total_equity"), latest.get("total_equity"), n_years
                )

        if len(annual_rows) >= 3:
            latest = annual_rows[-1]
            for field, col in [
                ("gross_margin_median", "gross_margin"),
                ("operating_margin_median", "operating_margin"),
                ("net_margin_median", "net_income_margin"),
                ("roe_median", "roe"),
                ("roic_median", "roic"),
                ("debt_to_equity_median", "debt_to_equity"),
            ]:
                latest[field] = calc_medians(annual_rows, col)

        conn = get_conn()
        cur = conn.cursor()
        inserted = 0
        for row in annual_rows:
            cols_list = list(row.keys())
            vals_list = [row[c] for c in cols_list]
            placeholders = ", ".join(["%s"] * len(cols_list))
            updates = ", ".join(
                [
                    f"{c} = EXCLUDED.{c}"
                    for c in cols_list
                    if c not in ("company_symbol", "fiscal_year")
                ]
            )
            sql = f"""
                INSERT INTO annual_financials ({', '.join(cols_list)})
                VALUES ({placeholders})
                ON CONFLICT (company_symbol, fiscal_year)
                DO UPDATE SET {updates}
            """
            try:
                cur.execute(sql, vals_list)
                inserted += 1
            except Exception as e:
                conn.rollback()
                log.error(f"  Upsert error for {symbol} FY{row['fiscal_year']}: {e}")
                conn = get_conn()
                cur = conn.cursor()
                continue
        conn.commit()
        conn.close()

        if inc_q is not None and not inc_q.empty:
            conn = get_conn()
            cur = conn.cursor()
            q_cols = inc_q.columns
            for col in q_cols:
                try:
                    q_revenue = si(sg(inc_q[col], "Total Revenue"))
                    if not q_revenue or q_revenue <= 0:
                        continue
                    period_end = col.date() if hasattr(col, "date") else col
                    q_gp = si(sg(inc_q[col], "Gross Profit"))
                    q_op = si(sg(inc_q[col], "Operating Income"))
                    q_ni = si(sg(inc_q[col], "Net Income"))
                    q_ebitda = si(sg(inc_q[col], "EBITDA"))
                    q_eps = sf(sg(inc_q[col], "Diluted EPS"))
                    q_key = f"Q{((period_end.month-1)//3)+1} {period_end.year}"
                    q_gm = (
                        sf(q_gp / q_revenue)
                        if (q_gp and q_revenue and q_revenue > 0)
                        else None
                    )
                    q_om = (
                        sf(q_op / q_revenue)
                        if (q_op and q_revenue and q_revenue > 0)
                        else None
                    )
                    q_nm = (
                        sf(q_ni / q_revenue)
                        if (q_ni and q_revenue and q_revenue > 0)
                        else None
                    )
                    cur.execute(
                        """
                        INSERT INTO quarterly_financials
                            (company_symbol, fiscal_quarter_key, period_end_date,
                             revenue, gross_profit, operating_income, net_income,
                             ebitda, eps_diluted, gross_margin, operating_margin, net_income_margin)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (company_symbol, fiscal_quarter_key)
                        DO UPDATE SET
                            revenue=EXCLUDED.revenue, gross_profit=EXCLUDED.gross_profit,
                            operating_income=EXCLUDED.operating_income, net_income=EXCLUDED.net_income,
                            ebitda=EXCLUDED.ebitda, eps_diluted=EXCLUDED.eps_diluted,
                            gross_margin=EXCLUDED.gross_margin, operating_margin=EXCLUDED.operating_margin,
                            net_income_margin=EXCLUDED.net_income_margin
                    """,
                        (
                            symbol,
                            q_key,
                            period_end,
                            q_revenue,
                            q_gp,
                            q_op,
                            q_ni,
                            q_ebitda,
                            q_eps,
                            q_gm,
                            q_om,
                            q_nm,
                        ),
                    )
                except Exception as e:
                    log.error(f"  Quarterly error for {symbol}: {e}")
            conn.commit()
            conn.close()

        log.info(f"  OK {symbol}: {inserted} annual periods, quarterly done")
        return inserted

    except Exception as e:
        log.error(f"  Fatal error for {symbol}: {e}")
        return 0


if __name__ == "__main__":
    log.info(f"=== FinScope Updater — processing {STOCKS_PER_RUN} stocks ===")
    stocks = get_stocks_to_update(STOCKS_PER_RUN)

    if not stocks:
        log.warning("No stocks found. Run build_company_list.py first!")
        exit(1)

    t0 = time.time()
    started_at = datetime.now().isoformat(timespec="seconds")
    total_periods = 0
    updated_count = 0
    skipped_count = 0
    for stock in stocks:
        sym = stock["symbol"]
        last = stock["financials_updated"] or "never"
        log.info(f"--- {sym} | last updated: {last} ---")
        n = process_stock(sym)
        if n > 0:
            mark_updated(sym)
            total_periods += n
            updated_count += 1
        else:
            skipped_count += 1
        time.sleep(1)

    elapsed = int(time.time() - t0)
    finished_at = datetime.now().isoformat(timespec="seconds")
    log.info(f"\n=== Done! {total_periods} periods updated ===")
    _write_summary(
        f"{finished_at}  started={started_at}  elapsed={elapsed}s  "
        f"total={len(stocks)}  updated={updated_count}  skipped={skipped_count}  "
        f"periods={total_periods}"
    )
