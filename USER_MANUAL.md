# Egg Basket — UK Stock Screener: User Manual

---

## Contents

1. [Overview](#1-overview)
2. [Layout & Navigation](#2-layout--navigation)
3. [The Screener](#3-the-screener)
4. [Company Detail](#4-company-detail)
5. [Analyst Monitor](#5-analyst-monitor)
6. [Sector Analysis](#6-sector-analysis)
7. [Markets](#7-markets)
8. [Signal Log](#8-signal-log)
9. [Scores Explained](#9-scores-explained)
10. [Data Sources](#10-data-sources)

---

## 1. Overview

Egg Basket is a single-page web application for screening and analysing UK-listed stocks. It provides:

- A filterable screener across all FTSE-indexed stocks with composite scoring
- Detailed company financials, price charts, and health metrics
- Sector rotation analysis and a proprietary UK Fear & Greed index
- Cross-asset views including gilt yield curves and macro indicators

All market data is cached for 15 minutes; company fundamental data is stored in a local database.

---

## 2. Layout & Navigation

### Top Navigation Bar

The sticky navbar appears on every page.

| Element | Action |
|---|---|
| **Egg Basket** logo | Return to the Screener from anywhere |
| **Screener** link | Go to the main stock screener table |
| **Sector Analysis** dropdown | Rotation, Breadth, Signal Log |
| **Markets** dropdown | Fear & Greed, Cross-Asset |
| **↻ Market** button | Refresh sidebar data and all live market feeds |
| **↻ Stock Prices** button | Bulk-update the price history database for all stocks |
| **Search box** | Live search by ticker (e.g. `AZN`) or company name |

After clicking **↻ Market**, a timestamp ("Updated HH:MM") confirms when data was last fetched.

After clicking **↻ Stock Prices**, a toast notification shows the result, e.g. `+120 rows (8.3s)`.

### Search

Start typing in the search box (minimum 1 character) to see a dropdown of up to 20 matching companies, showing ticker, name, and exchange. Clicking a result:

- On the Screener page: scrolls to and highlights that row with an orange left border.
- On any other page: navigates to that company's detail page.

### Left Sidebar

The sidebar is visible on all pages except Company Detail. It shows a live market overview and refreshes when you press **↻ Market**.

| Section | What it shows |
|---|---|
| **Benchmarks** | Today's % change for FTSE 100, FTSE 250, FTSE All-Share (green/red) |
| **VIX** | Current VIX level — green (<20), amber (<30), red (≥30) |
| **CNN F&G** | CNN Fear & Greed index value and label |
| **UK Fear & Greed** | App's own composite score (0–100), label, trend direction, and suggested cycle phase |
| **ICB Sectors** | Today's % change for each tracked sector basket |
| **Model Signal** | Current business cycle phase, % of FTSE 100 stocks above their 50-day MA, top RS sector |

The sidebar can be collapsed using the panel-icon button at the top left of the navbar.

---

## 3. The Screener

The screener table lists all UK-listed companies in the database with their key metrics.

### Filters

All filters are live — the table updates instantly as you change them.

| Filter | Options |
|---|---|
| **Sector** | All Sectors, or any specific ICB sector |
| **FTSE Market** | All (default), FTSE 100, FTSE 250, FTSE 350, FTSE SmallCap, AIM 100 |
| **Market Cap** | Any / £1B+ / £10B+ / £50B+ / Custom (enter a £B value) |
| **Consensus** | All Consensus / Buy / Hold / Sell |
| **Upside** | Any Upside / >5% / >10% / >20% |

Click **Advanced ▼** to reveal additional filters (the button turns orange with a dot when any are active):

| Filter | Options |
|---|---|
| **Momentum** | Any / ≥4 / ≥6 / ≥8 |
| **Quality** | Any / ≥4 / ≥6 / ≥8 |
| **Value** | Any / ≥4 / ≥6 / ≥8 (Piotroski F-Score) |
| **Risk** | Any / ≤3 / ≤5 / ≤7 |
| **Max P/E** | Any / <15 / <25 / <40 / Custom |
| **Min ROE** | Any / >10% / >15% / >20% / Custom |
| **Min Revenue Growth** | Any / >5% / >10% / >20% / Custom |

A **"Clear filters ✕"** button appears when any filter is active and resets all filters at once.

A **company count badge** (e.g. "47 / 312 companies") above the table shows how many pass the current filters.

### View Toggle: Fundamentals / Analysts

Two buttons above the table switch between views. The selected view is highlighted in orange.

#### Fundamentals View

Columns: Symbol, Name, Sector, Index, Mkt Cap, P/E, P/B, ROE, Rev Growth, D/E, Momentum, Quality, Value, Risk.

| Column | Colour rule |
|---|---|
| P/E | Green if <15; red if >40 |
| ROE, Rev Growth | Green if positive; red if negative |
| D/E | Red if >2 |
| Momentum, Quality, Value | Green ≥7; amber ≥4; red <4 |
| Risk | Green ≤3; amber ≤6; red >6 |

#### Analysts View

Columns: Symbol, Name, Sector, Index, Mkt Cap, Consensus, Upside, Buy%, # Analysts, Rev Score.

| Column | Colour rule |
|---|---|
| Consensus | Green badge = Buy; amber = Hold; red = Sell |
| Upside | Green if positive; red if negative |
| Buy% | Green ≥60%; amber ≥40%; red <40% |
| Rev Score | Green if positive; red if negative |

### Sticky Headers

The column header row stays pinned at the top of the table as you scroll down through results. Click any header to sort by that column; click again to reverse direction. The active sort column is highlighted in orange.

### Opening a Company

Click any row to open the Company Detail page for that stock.

---

## 4. Company Detail

### Header

Shows the company's avatar (with ticker abbreviation), full name, ticker, exchange, sector, country, FTSE index membership, market cap, and enterprise value. A short company description is shown where available.

Use **← Back to Screener** to return to your previous filtered screener view.

### Tabs

**Chart** is the default tab when you open a company.

#### Chart

An interactive price chart with gradient fill.

- **Time range**: 1M, 3M, 6M, 1Y, 3Y, 5Y
- **MA20** (amber dashed pill) — toggle a 20-day moving average overlay
- **MA50** (purple solid pill) — toggle a 50-day moving average overlay

Price data is refreshed to the current date automatically when the chart loads.

#### Overview

A grid of 12 metric cards (Revenue, Net Income, EBITDA, Free Cash Flow, P/E, P/B, ROE, ROIC, Gross Margin, Net Margin, Debt/Equity, Current Ratio) with colour coding, plus a bar chart of annual Revenue and Net Income.

#### Financials

- Area chart of annual Revenue, EBITDA, and FCF
- Bar chart of the last 8 quarters' Revenue
- Line chart of annual EPS Diluted
- 5-year Income Statement table (Revenue, Gross Profit, Operating Income, EBITDA, Net Income, FCF — negative values in red)

#### Valuation

- Grid of 8 cards: P/E, P/B, P/S, EV/EBITDA, EV/Sales, ROE, ROIC, ROCE
- Line chart of EPS history
- Line chart of ROE, ROIC, and ROA over time

#### Health

- **Risk Score card** (1–10): large coloured number — green ≤3, amber ≤6, red >6
- **Altman Z-Score**: >3.0 = safe; 1.8–3.0 = grey zone; <1.8 = distress
- **Annualised Volatility** (%)
- Grid of 8 cards: Current Ratio, Debt/Equity, Debt/Assets, Cash, Net Debt, Working Capital, Interest Coverage, Book Value
- Area chart of Debt/Equity history
- Line chart of Current Ratio history (reference line at y=1)

#### Growth

- Grid of 8 cards: Revenue Growth, Net Income Growth, EPS Growth, FCF Growth, and 10-year CAGRs for Revenue, EPS, FCF, and Equity — all colour-coded by sign
- Line chart of Gross Margin, Operating Margin, and Net Margin history

#### Analysts

Displays the latest analyst coverage data for the stock.

**Header row:** Consensus badge (Buy / Hold / Sell), % bullish, and analyst count.

**Analyst Consensus card:** A stacked bar showing the breakdown across Strong Buy, Buy, Hold, Sell, and Strong Sell, with a legend showing individual counts.

**Price Target Range card:** A horizontal range bar from the lowest to highest analyst price target. Three markers are plotted:
- **Current** (indigo) — today's price
- **Mean** (orange) — consensus mean target
- **Median** (purple) — consensus median target

The upside/downside to the mean target is shown as a green or red percentage.

**Consensus Trend card** (shown when 2+ historical snapshots exist): A line chart of % bullish over time.

**Estimates & Revisions card:**
- EPS estimates for Current Year, Next Year, Current Quarter, and Next Quarter
- 30-day estimate revisions: count of upward (↑) and downward (↓) EPS changes
- EPS growth forecasts for Current Year and Next Year (colour-coded by sign)

---

## 5. Analyst Monitor

Accessible via **Analysts** in the top navigation bar.

A cross-portfolio view of analyst sentiment across all stocks in the database that have coverage data.

### Top Bullish / Top Bearish

Two side-by-side cards showing the 5 most bullish and 5 most bearish stocks by composite score. The composite score blends Buy%, Upside, and Revision Score.

Each row shows the ticker, consensus badge, upside %, and revision direction (↑/↓).

### Full Analyst Table

A sortable table of all stocks with analyst data. Columns:

| Column | Description |
|---|---|
| Symbol | Ticker |
| Consensus | Buy / Hold / Sell badge |
| Buy% | Percentage of analysts rating the stock Buy or Strong Buy |
| Upside | % upside to the mean analyst price target (green/red) |
| Revisions | Net 30-day estimate revisions (+/−) |
| Analysts | Total number of analysts covering the stock |

Click any column header to sort; click again to reverse. Use the search box to filter by ticker or company name.

### Recent Changes

A sidebar feed listing stocks where consensus or upside has changed since the previous data refresh, showing the old and new consensus (e.g. Hold → Buy) and current upside.

### Refreshing Data

Click **↻ Refresh** to trigger a background update of all analyst data. This takes a few minutes to complete; a toast notification confirms the refresh has started.

---

## 6. Sector Analysis


### Sector Rotation

#### Sector Heatmap

A grid of all tracked ICB sectors, colour-coded by relative strength (RS) rank:

- **Ranks 1–4** (top performers): green background and text, labelled #1–#4
- **Ranks 8–11** (weakest): red background and text
- Middle ranks: neutral/dark

#### Business Cycle Wheel

An SVG compass wheel divided into four phases with a needle pointing to the current phase:

| Phase | Colour | Meaning |
|---|---|---|
| **Recovery** | Green | Early cycle — breadth improving, valuations cheap |
| **Expansion** | Blue | Mid cycle — earnings growth accelerating |
| **Slowdown** | Amber | Late cycle — growth decelerating |
| **Contraction** | Red | Recession — earnings falling |

Below the wheel:
- **Favour** (green): sectors to overweight in the current phase
- **Avoid** (red): sectors to underweight
- **F&G signal**: the phase suggested by the Fear & Greed index. "Unconfirmed" means only 1 of 2 consecutive readings confirm it. An **Accept** button lets you adopt the suggestion.
- **Rotation signal**: the phase suggested by which sectors are leading by RS rank.

Clicking **Accept** manually sets the cycle phase and logs an INFO event in the Signal Log.

#### RS Ranking Table

| Column | Description |
|---|---|
| Rank | 1 (strongest) to 11 (weakest) |
| Sector | ICB sector name |
| RS Score | Relative strength vs FTSE All-Share basket |
| Trend | ↑ Rising / ↓ Falling |
| Breadth | % of constituent stocks above their 50-day MA |
| Signal | **BUY** (RS >1.05, rising) / **AVOID** (RS <0.95, falling) / **NEUTRAL** |

### Market Breadth

Uses a basket of approximately 75 FTSE 100 stocks.

#### Summary Cards

| Card | What it shows |
|---|---|
| **% Above 50-Day MA** | Semicircular gauge — Bullish (>60%), Neutral (40–60%), Bearish (<40%) |
| **52-Week Highs / Lows** | Count of stocks at 52-week highs and lows, plus H/L ratio |
| **Advance / Decline** | Today's count of advancing, declining, and unchanged basket stocks |

#### Cumulative A/D Line

A line chart of the cumulative Advance/Decline line over the last 20 trading days. Rising = broad participation; falling = narrowing market.

---

## 7. Markets

### Fear & Greed

The app's proprietary UK Fear & Greed index — a composite score from 0 (extreme fear) to 100 (extreme greed).

#### Score Labels

| Range | Label |
|---|---|
| 0–24 | Extreme Fear |
| 25–44 | Fear |
| 45–54 | Neutral |
| 55–74 | Greed |
| 75–100 | Extreme Greed |

The colour-banded progress bar shows a needle at the current score position across red / orange / grey / amber / green zones.

#### Six Component Scores

Each component contributes equally to the overall score (simple average of all six):

| Component | Methodology |
|---|---|
| **FTSE Momentum** | FTSE 100 price vs its 125-day rolling average, z-score normalised |
| **Market Breadth** | % of FTSE 100 basket above their 50-day MA, z-score normalised |
| **VIX** | CBOE VIX level, inverted (high VIX = fear = low score), z-score normalised |
| **Safe Haven Demand** | 20-day return spread between FTSE 100 and UK gilt ETF (IGLT.L). Stocks outperforming gilts = greed |
| **Realised Vol** | 20-day annualised volatility of FTSE 100, inverted, z-score normalised |
| **New Highs/Lows** | % of basket at 52-week highs minus % at 52-week lows, scaled 0–100 |

Each component also shows its own 0–100 score and a mini progress bar.

### Cross-Asset

#### Asset Cards

| Card | Details |
|---|---|
| **GBP/USD** | Current rate (4 dp) and today's % change |
| **Brent Crude** | Current price (USD, 2 dp) and today's % change |
| **Gold** | Current price (USD) and today's % change |
| **Gilt vs Utilities z-score** | Z-score of the gilt ETF / Utilities spread over up to 252 days. Negative z-score (<−1) = gilts expensive vs utilities (background turns reddish as a warning) |

#### UK Gilt Yield Curve

Data is sourced from the Bank of England.

**Snapshot chart (left panel):** Shows the current yield curve across maturities 2Y, 5Y, 10Y, 20Y, 30Y. Labelled "Normal", "Flat", or "Inverted" (red label if inverted).

**History chart (right panel):** Multi-line chart of gilt yields from 2021 to present.

| Maturity | Colour |
|---|---|
| 2Y | Orange |
| 5Y | Amber |
| 10Y | Green |
| 20Y | Blue |
| 30Y | Purple |

Controls:
- **Time range buttons**: 1Y, 2Y, 3Y, 5Y
- **Toggle buttons per maturity**: click the coloured pill to show or hide that yield line

---

## 8. Signal Log

Found under **Sector Analysis → Signal Log**.

A chronological log of model-generated events, newest first (up to 50 entries; resets on server restart).

| Badge | Colour | Trigger |
|---|---|---|
| **BUY** | Green | Sector RS breakout: RS >1.05 and rising |
| **AVOID** | Red | Sector RS deterioration: RS <0.95 and falling |
| **ALERT** | Amber | Breadth threshold crossed (>65% bullish or <40% bearish) |
| **INFO** | Blue | System events: auto cycle phase update, or manual override via Accept button |

Each entry shows a timestamp (e.g. "07 Apr 14:32"), the badge type, and a plain-English message.

---

## 9. Scores Explained

### Momentum Score (1–10)

Measures 12-1 month price momentum: the return from 252 trading days ago to 63 trading days ago. Scores are percentile-ranked within the current screener universe, so a score of 8 means the stock is in approximately the top 20% of momentum for the stocks currently shown.

### Quality Score (0–10)

Rewards six financial characteristics, with a bonus for each being at or above the company's own historical median:

1. ROIC > 10%
2. ROE > 15%
3. Gross Margin > 30%
4. Operating Margin > 10%
5. FCF Margin > 5%
6. Each metric at or above the company's historical median (up to 1 bonus point per criterion met)

### Value / Piotroski F-Score (0–9)

The standard Piotroski F-Score — 9 binary tests scored 1 or 0 each:

**Profitability (4 points)**
- Positive ROA
- Positive CFO
- ROA improving year-on-year
- CFO > ROA (accruals quality)

**Leverage / Liquidity (3 points)**
- Debt/Equity improving (falling)
- Current Ratio improving
- No share dilution in the past year

**Efficiency (2 points)**
- Gross Margin improving
- Asset Turnover improving

A score of 7–9 is strong; 0–2 is weak.

### Risk Score (1–10)

A blend of two components:
- **Altman Z-Score** (60% weight) — a bankruptcy-prediction model. Mapped to 1–10 where lower Z-Score (more distress) produces a higher risk score.
- **Annualised Volatility** (40% weight) — 252-day price volatility, mapped 1–10 against absolute thresholds calibrated for FTSE-listed stocks.

A risk score of 1–3 = low risk (green); 4–6 = moderate (amber); 7–10 = high risk (red).

---

## 10. Data Sources

| Data | Source |
|---|---|
| Company metadata (name, sector, country, FTSE index) | PostgreSQL database |
| TTM financials (P/E, P/B, ROE, margins, etc.) | PostgreSQL database |
| Annual and quarterly financials | PostgreSQL database |
| Price history (daily close, up to 5 years) | PostgreSQL database, populated via yfinance |
| Live benchmarks, sectors, VIX, FX, commodities | yfinance (15-minute cache) |
| UK gilt yield curve (2Y, 5Y, 10Y, 20Y, 30Y) | Bank of England IADB API and BoE zip file |
| CNN Fear & Greed index | `fear_and_greed` Python package |
| Analyst consensus, price targets, EPS estimates, revisions | PostgreSQL database, populated via yfinance |
