-- Adds a clean, currency-safe dividend yield to the financials.
--
-- Background: ttm_financials.dividends_per_share was effectively unusable as a
-- yield source. The yfinance updater hard-coded dividends_per_share = None on
-- every run (so ~43% of stocks, incl. AZN/BP/SHEL/HSBA, showed NULL), and even
-- where present it sat in the reporting currency (USD for many FTSE names) while
-- price is quoted in GBp — so dividends_per_share / period_end_price was
-- cross-currency and wrong. Deriving from dividends_paid also blew up on
-- depressed-earnings cyclicals (BP).
--
-- yfinance's own trailingAnnualDividendYield is broken for .L tickers (it divides
-- a £ rate by a pence price → ~0.0002). But info['dividendYield'] is correct and
-- currency-free (a percentage, e.g. 5.35 for BATS). The updater now stores that,
-- normalised to a fraction (0.0535), on the most-recent annual row, and PEGY uses
-- it directly. See backend/updater.py and _attach_pegy in backend/main.py.

ALTER TABLE annual_financials
    ADD COLUMN IF NOT EXISTS dividend_yield double precision;

-- ttm_financials is a passthrough view (latest annual row per company); recreate
-- it with the new column appended so the screener/PEGY can read it.
CREATE OR REPLACE VIEW ttm_financials AS
 SELECT DISTINCT ON (company_symbol) id,
    company_symbol,
    fiscal_year,
    period_end_date,
    revenue,
    cogs,
    gross_profit,
    rnd,
    sga,
    operating_income,
    ebitda,
    interest_expense,
    pretax_income,
    income_tax,
    net_income,
    eps_basic,
    eps_diluted,
    shares_basic,
    shares_diluted,
    dividends_per_share,
    cash_and_equiv,
    st_investments,
    receivables,
    inventories,
    total_current_assets,
    ppe_net,
    intangible_assets,
    goodwill,
    total_assets,
    accounts_payable,
    st_debt,
    total_current_liabilities,
    lt_debt,
    total_liabilities,
    total_equity,
    retained_earnings,
    shares_outstanding,
    cf_cfo,
    capex,
    cf_cfi,
    cf_cff,
    dividends_paid,
    stock_buybacks,
    da,
    fcf,
    net_debt,
    invested_capital,
    nopat,
    working_capital,
    book_value,
    tangible_book_value,
    gross_margin,
    operating_margin,
    net_income_margin,
    ebitda_margin,
    fcf_margin,
    roe,
    roa,
    roic,
    roce,
    debt_to_equity,
    debt_to_assets,
    current_ratio,
    interest_coverage,
    revenue_per_share,
    fcf_per_share,
    book_value_per_share,
    period_end_price,
    market_cap,
    enterprise_value,
    price_to_earnings,
    price_to_book,
    price_to_sales,
    price_to_fcf,
    ev_to_ebitda,
    ev_to_sales,
    revenue_growth,
    gross_profit_growth,
    operating_income_growth,
    net_income_growth,
    eps_diluted_growth,
    fcf_growth,
    total_assets_growth,
    total_equity_growth,
    revenue_cagr_10,
    eps_cagr_10,
    fcf_cagr_10,
    equity_cagr_10,
    dividends_cagr_10,
    gross_margin_median,
    operating_margin_median,
    net_margin_median,
    roe_median,
    roic_median,
    debt_to_equity_median,
    dividend_yield
   FROM annual_financials
  ORDER BY company_symbol, period_end_date DESC;
