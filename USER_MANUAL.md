# Alpha Move AI — UK Stock Screener — User Manual

**Edition:** April 2026  
**Audience:** Investors new to financial analysis  
**Purpose:** A plain-English guide to understanding what you are seeing and how to use these tools to find UK companies with the **greatest chance of upside** and the **smallest downside risk**.

---

## Table of Contents

1. [Introduction — What Is a Stock Screener?](#1-introduction)
2. [The Dashboard Layout](#2-dashboard-layout)
3. [The Screener — Finding Stocks](#3-the-screener)
   - 3.1 [Understanding the Columns](#31-understanding-the-columns)
   - 3.2 [The Four Scores Explained](#32-the-four-scores-explained)
   - 3.3 [Using the Filters](#33-using-the-filters)
   - 3.4 [Analyst View](#34-analyst-view)
   - 3.5 [The PEGY Column — Are You Paying a Fair Price for Growth?](#35-the-pegy-column)
   - 3.6 [The Watchlist — Save Companies to Follow](#36-the-watchlist)
   - 3.7 [Excluding Sectors You Want to Avoid](#37-excluding-sectors)
4. [Company Detail — Drilling Into a Stock](#4-company-detail)
   - 4.1 [Chart Tab](#41-chart-tab)
   - 4.2 [Overview Tab](#42-overview-tab)
   - 4.3 [Financials Tab](#43-financials-tab)
   - 4.4 [Valuation Tab](#44-valuation-tab)
   - 4.5 [Health Tab](#45-health-tab)
   - 4.6 [Growth Tab](#46-growth-tab)
   - 4.7 [Analysts Tab](#47-analysts-tab)
   - 4.8 [Company News Tab — Press, RNS & AI Summary](#48-company-news-tab)
5. [Sector Analysis](#5-sector-analysis)
   - 5.1 [Sector Rotation](#51-sector-rotation)
   - 5.2 [Market Breadth](#52-market-breadth)
   - 5.3 [Signal Log](#53-signal-log)
6. [Markets](#6-markets)
   - 6.1 [Fear & Greed Index](#61-fear--greed-index)
   - 6.2 [Cross-Asset Monitor](#62-cross-asset-monitor)
   - 6.3 [Gilt Yields](#63-gilt-yields)
7. [Analyst Monitor](#7-analyst-monitor)
8. [RNS News Screener — Catching Catalysts Early](#8-rns-news-screener)
   - 8.1 [What is RNS?](#81-what-is-rns)
   - 8.2 [The Two-Layer AI Pipeline](#82-the-two-layer-pipeline)
   - 8.3 [Reading the Feed](#83-reading-the-feed)
   - 8.4 [Action Pills — BUY / WATCH / AVOID](#84-action-pills)
9. [Analytics — The Visual Map of the Market](#9-analytics)
10. [The Sidebar — Your Instant Dashboard](#10-the-sidebar)
11. [How To Find Investment Leads — Step-by-Step Workflows](#11-how-to-find-investment-leads)
    - 11.1 [The Quality + Value Filter](#111-the-quality--value-filter)
    - 11.2 [The Momentum Trend-Following Approach](#112-the-momentum-trend-following-approach)
    - 11.3 [The Analyst Upgrade Hunt](#113-the-analyst-upgrade-hunt)
    - 11.4 [The Sector Rotation Strategy](#114-the-sector-rotation-strategy)
    - 11.5 [The Defensive Screen (Capital Preservation)](#115-the-defensive-screen)
    - 11.6 [The Catalyst Hunt — RNS-Driven Upside](#116-the-catalyst-hunt)
    - 11.7 [The Visual Map Workflow — Cheap Quality Hunting](#117-the-visual-map-workflow)
    - 11.8 [The Combined "Maximum Upside / Minimum Downside" Workflow](#118-the-combined-workflow)
12. [Glossary of Financial Terms](#12-glossary-of-financial-terms)
13. [Appendix A — Methodology References](#appendix-a--methodology-references)
14. [Appendix B — ICB Sector Company List](#appendix-b--icb-sector-company-list)

---

## 1. Introduction

### What Is a Stock Screener?

Investing in individual shares means choosing from thousands of publicly traded companies. Without a tool to filter and compare them, the task is overwhelming. A **stock screener** lets you set criteria — like "show me only companies with low debt and strong profit growth" — and instantly narrows the universe down to a manageable shortlist.

Alpha Move AI goes further than a basic screener. It calculates composite scores for quality, momentum, value and risk; tracks what professional analysts are saying; reads the official regulatory news feed and uses AI to flag market-moving announcements; and monitors the overall health of the UK market so you can time your decisions more intelligently.

### The Investing Goal: Maximum Upside, Minimum Downside

Every tool in this app is built around two questions every investor needs to answer:

1. **Upside:** What is the realistic chance this share goes up, and by how much?
2. **Downside:** If I am wrong, how badly could I lose?

A great investment is one with **asymmetric returns** — the upside is much larger than the downside. The features in this manual are designed to help you systematically find those opportunities, by combining four kinds of signals:

| Signal Type | Tool to use | What it tells you |
|---|---|---|
| **Quality of the business** | Quality Score, Piotroski, Health tab | Will this company still exist and thrive in 5 years? |
| **Price you are paying** | P/E, P/B, PEGY, Valuation tab | Are you over-paying compared to growth and earnings? |
| **Trend & timing** | Momentum, Sector Rotation, Fear & Greed | Is the market currently agreeing with you? |
| **Catalysts & sentiment** | RNS News Screener, Analyst Monitor | Is something happening *right now* that could move the price? |

Workflows in [Section 11](#11-how-to-find-investment-leads) show exactly how to combine these signals to find candidates — including a master "**Maximum Upside / Minimum Downside**" workflow ([11.8](#118-the-combined-workflow)) that uses every tool in the app.

> **Important disclaimer:** Nothing in this tool constitutes financial advice. The scores and indicators are research aids. Always do your own due diligence and consider consulting a qualified financial adviser before making investment decisions.

### The Markets We Cover

The tool focuses on **UK-listed equities** — companies whose shares trade on the London Stock Exchange. These are grouped into several indexes:

| Index | What it contains |
|---|---|
| **FTSE 100** | The 100 largest UK-listed companies by market value (e.g. Shell, AstraZeneca, HSBC). Often called "the Footsie". |
| **FTSE 250** | The next 250 largest companies. More domestically focused than the FTSE 100. |
| **FTSE SmallCap** | Smaller companies below the FTSE 250. Higher growth potential but less liquidity. |
| **FTSE All-Share** | The combined FTSE 100 + 250 + SmallCap. |
| **AIM** | The Alternative Investment Market. Smaller, often younger businesses. Higher risk, higher potential reward. |

---

## 2. Dashboard Layout

When you open Alpha Move AI you see:

- **Top navigation bar** — Screener, Watchlist, Analysts, RNS News, Analytics, and a Markets dropdown (Fear & Greed, Cross-Asset, Rotation, Breadth, Signal Log).
- **Left sidebar** — a live pulse of the market: benchmark returns, market fear levels, and current cycle signals. Toggle the sidebar on or off using the icon at the top-left of the navigation bar.
- **Main content area** — changes depending on which page you are on.
- **Search bar** — type a company name or ticker symbol to jump straight to its detail page.

> **Direct links to companies:** When you open a company page, the URL updates to include the ticker (e.g. `…#company/AZN.L`). You can bookmark or share that link to land directly on that company. The browser **Back** button takes you back to wherever you came from (screener, watchlist, RNS feed, etc.).

---

## 3. The Screener

The Screener is the heart of the application. It displays a table of UK stocks which you can filter and sort to find candidates matching your strategy.

### 3.1 Understanding the Columns

#### Fundamentals View

| Column | What it means | What to look for |
|---|---|---|
| **Symbol** | The stock's ticker code, e.g. `AZN.L`. The `.L` means London-listed. | — |
| **Name** | Company name | — |
| **Sector** | The industry the company operates in (ICB classification — see Appendix B) | Use to compare like-for-like |
| **Index** | Which FTSE index the stock belongs to | Indicates size |
| **Mkt Cap** | **Market Capitalisation** — the total stock market value of all shares. Calculated as: Share price × number of shares outstanding. A £10bn market cap is a large company. | Larger = more stable; smaller = more growth potential |
| **P/E** | **Price-to-Earnings ratio** — how much investors pay for each £1 of profit. If a company earns £1 per share and trades at £20, its P/E is 20. A high P/E means investors expect strong future growth; a low P/E may mean the stock is cheap or the business is struggling. | Compare within the same sector; no universal "good" number |
| **P/B** | **Price-to-Book ratio** — share price divided by the company's net asset value per share. P/B < 1 means you are buying £1 of assets for less than £1. | Useful for asset-heavy sectors like banks and property |
| **ROE** | **Return on Equity** — net profit as a percentage of shareholders' equity. Measures how efficiently management uses your money. 15%+ is generally considered good. | Higher is better; look for consistency over several years |
| **Rev Growth** | Year-on-year revenue growth percentage | Positive and growing is ideal |
| **D/E** | **Debt-to-Equity ratio** — total debt divided by shareholders' equity. A D/E of 1.0 means the company has £1 of debt for every £1 of equity. High D/E increases risk, especially when interest rates are high. | Lower is safer; context matters (utilities typically carry more debt) |
| **PEGY** | **Price/Earnings divided by (Growth + Yield)**. A simple "value-for-money" check. See Section 3.5. | Below 1 = potentially great value; 1–2 = fair; above 2 = expensive for the growth |
| **Momentum** | A score from 1–10 measuring price trend strength. See Section 3.2. | Higher score = stronger upward trend |
| **Quality** | A score from 0–10 measuring the consistency and level of returns. See Section 3.2. | Higher is better |
| **Value** | The **Piotroski F-Score** (0–9), a measure of financial health and value. See Section 3.2. | 7+ is strong; below 3 is weak |
| **Risk** | A composite risk score from 1–10. See Section 3.2. | Lower is safer |
| **★ Star** | A small star icon at the start of each row. Click to add or remove the company from your **Watchlist** (see Section 3.6). | A gold star means the company is on your list |

#### What is Equity?

Think of a company like a house. If the house is worth £300,000 but you have a £200,000 mortgage, your equity (what you actually own) is £100,000. A company's equity is its total assets minus its total liabilities — what would be left for shareholders if the company sold everything and paid all its debts.

---

### 3.2 The Four Scores Explained

These are proprietary composite scores calculated from underlying financial data. They allow quick comparison across the universe without reading each company's accounts.

---

#### Momentum Score (1–10)

**What it measures:** How strongly the share price has been trending upward over the medium term.

**How it is calculated:**

The score uses the academic concept of **12-1 month price momentum** — one of the most extensively researched phenomena in finance. The formula compares the stock's price 63 trading days ago (~3 months) to its price 252 trading days ago (~12 months):

```
Momentum Return = (Price 63 days ago) ÷ (Price 252 days ago) − 1
```

The most recent 3 months are deliberately excluded. Research shows that very recent returns tend to **reverse** (a short-term bounce is often followed by a pullback), while the 3–12 month window tends to **persist** (winners keep winning, losers keep losing). This phenomenon is called **price momentum**.

All stocks are then ranked by this return and assigned a score of 1–10, where 10 = top 10% of momentum in the screened universe.

**What to look for:** A score of 7 or higher suggests the stock has been among the better performers. Combined with strong fundamentals, this can confirm that the market is already recognising the quality you have identified.

**Academic reference:** See Appendix A — Jegadeesh & Titman (1993).

---

#### Quality Score (0–10)

**What it measures:** How high and how consistent the company's returns and profit margins are.

**How it is calculated:**

The score awards up to 2 points for each of five criteria, checking both the absolute level and whether it beats the median of the screened universe:

| Criterion | Points |
|---|---|
| ROIC > 10% or above median ROIC | 0–2 |
| ROE > 15% or above median ROE | 0–2 |
| Gross Margin > 30% or above median | 0–2 |
| Operating Margin > 10% or above median | 0–2 |
| FCF Margin > 5% or Net Margin above median | 0–2 |

**Key terms:**
- **ROIC (Return on Invested Capital):** Profit generated for every £1 of capital invested in the business. It is the best single measure of business quality — a high ROIC means the company has a competitive advantage (a "moat") that lets it earn outsized returns.
- **Gross Margin:** Revenue minus the direct cost of making goods/services, as a percentage of revenue. A high gross margin (e.g. 70%+ in software, 40%+ in consumer brands) means pricing power.
- **Operating Margin:** Profit after all running costs but before interest and tax. Shows how efficiently the business is run day-to-day.
- **FCF Margin (Free Cash Flow Margin):** The cash actually generated after all capital expenditure, as a percentage of revenue. Cash is harder to manipulate than reported profit — this is often considered the most reliable profitability measure.

**What to look for:** A score of 7+ indicates a genuinely high-quality business. These companies tend to outperform over long periods because their superior returns compound capital more effectively.

---

#### Piotroski F-Score (0–9) — the "Value" column

**What it measures:** The fundamental financial health and improving momentum of a company. Originally designed to separate improving value stocks from deteriorating ones.

**How it is calculated:**

9 binary tests (each scores 0 or 1):

**Profitability (3 points)**
1. Is Return on Assets (ROA) positive? (Is the company actually profitable relative to its assets?)
2. Is Operating Cash Flow positive? (Is the business generating real cash?)
3. Is ROA higher this year than last year? (Is profitability improving?)

**Earnings Quality (1 point)**
4. Is Operating Cash Flow greater than Net Income? (Is profit backed by cash, not accounting entries?)

**Leverage & Liquidity (2 points)**
5. Is the Debt/Equity ratio lower this year than last? (Is the balance sheet improving?)
6. Is the Current Ratio higher this year than last? (Is short-term financial health improving?)

**Dilution (1 point)**
7. Has the share count stayed the same or fallen? (A rising share count dilutes existing shareholders.)

**Efficiency (2 points)**
8. Is the Gross Margin higher this year than last? (Are margins expanding?)
9. Is Asset Turnover higher this year than last? (Is the company generating more revenue per £1 of assets?)

**What to look for:** 
- **7–9:** Strong — the company is healthy and improving on most measures. Classic "buy" territory for value-oriented investors.
- **4–6:** Mixed — some positives, some concerns. Read the detail.
- **0–3:** Weak — multiple warning signs. Approach with caution.

**Academic reference:** See Appendix A — Piotroski (2000).

---

#### Risk Score (1–10)

**What it measures:** A composite assessment of financial distress risk and price volatility.

**How it is calculated:**

The score blends two components (60% Altman Z-Score, 40% Volatility):

**Altman Z-Score component:**
The Altman Z-Score was developed in 1968 to predict corporate bankruptcy. It combines five financial ratios into a single number. A Z-Score above 3.0 indicates a financially safe company; below 1.8 suggests significant distress risk. The tool converts this to the 1–10 scale:
- Z ≥ 3.0 → Risk score 1 (safe)
- Z ≤ 1.0 → Risk score 10 (distress)

**Volatility component:**
Annualised price volatility (standard deviation of daily log returns × √252). Converted to 1–10:
- < 10% annualised → score 1 (very low)
- Each additional 5% adds roughly 1 point
- > 60% → score 10 (very high)

**What to look for:** For capital preservation, filter for Risk Score ≤ 4. Scores of 7+ warrant serious investigation into the company's balance sheet before investing.

**Academic reference:** See Appendix A — Altman (1968).

---

### 3.3 Using the Filters

The filter panel (above the screener table) lets you narrow the universe. Filters can be combined.

#### Basic Filters

| Filter | Practical use |
|---|---|
| **Sector** | Focus on an industry you understand or that your research suggests is performing well. Click the **⊘** button next to a sector name in the dropdown to **exclude** it instead — see Section 3.7 |
| **FTSE Index** | Filter by company size. FTSE 100 = the largest blue chips; FTSE 250 = mid-cap; FTSE 350 = both combined; FTSE SmallCap = smaller companies; **AIM 100** = the largest 100 companies on the Alternative Investment Market |
| **Market Cap (min)** | Set a floor to exclude very small illiquid stocks |
| **P/E (max)** | Exclude very expensive stocks. Setting to 25 focuses on reasonably valued companies |
| **ROE (min)** | Set to 10% or 15% to find only profitable businesses |
| **Revenue Growth (min)** | Set to 5% to find growing companies |

#### Score-Based Filters

| Filter | Suggested starting value | Rationale |
|---|---|---|
| **Min Momentum** | 6 | Focus on stocks with above-average price trends |
| **Min Quality** | 6 | Only businesses with strong returns and margins |
| **Min Piotroski** | 6 | Financially healthy and improving |
| **Max Risk** | 5 | Exclude higher-risk names |

#### Analyst Filters (in Analyst View)

| Filter | Use |
|---|---|
| **Consensus** | Select "Buy" to see only stocks where the majority of analysts are positive |
| **Upside %** | Set to 15% to find stocks where analysts see meaningful appreciation potential |

---

### 3.4 Analyst View

Clicking the **Analyst** view tab on the screener changes the columns to show professional analyst data:

| Column | What it means |
|---|---|
| **Consensus** | The aggregated view of all analysts covering the stock: Buy, Hold, or Sell |
| **Upside** | How far (in %) the current share price is from the average analyst price target. +20% means analysts think the stock could rise 20%. |
| **Buy%** | Percentage of covering analysts with a Buy or Strong Buy recommendation |
| **# Analysts** | The number of analysts following the stock. More analysts = more reliable consensus |
| **Rev Score** | Earnings revision score: upward EPS revisions minus downward revisions in the past 30 days. Positive = analysts are raising their profit forecasts — a strong positive signal. |

> **Why analyst data matters:** Professional analysts spend their careers studying individual sectors and companies. While no analyst is always right, a strong consensus — especially when combined with rising earnings estimates — is a meaningful signal.

---

### 3.5 The PEGY Column

**What it is:** PEGY stands for **P/E divided by (Growth + Yield)**. It is one of the simplest and most useful "value-for-money" tests for a stock.

**The intuition:** A high P/E (say 30) sounds expensive — but if the company is growing earnings at 25% a year and pays a 5% dividend, you are paying 30 ÷ (25 + 5) = a PEGY of 1.0, which is actually fair. Conversely, a low P/E (say 10) sounds cheap — but if growth is only 2% and the dividend is 1%, the PEGY is 10 ÷ 3 = 3.3, meaning you are paying a lot for very little growth or income.

**The formula:**

```
PEGY = P/E ratio ÷ (Earnings growth % + Dividend yield %)
```

The growth figure used here is the **forward analyst EPS growth** (when at least three analysts are covering the stock); otherwise it falls back to the company's 10-year average earnings growth.

**How to read it:**

| PEGY | Interpretation | Colour in screener |
|---|---|---|
| **Below 1** | Potentially great value — you are paying less than fair price for the growth and income | Green |
| **1 to 2** | Fair value | Amber |
| **Above 2** | Expensive relative to the growth and income on offer | Red |
| **Blank (—)** | Not enough data — usually because growth is missing, negative, or the dividend is zero | Grey |

> **Why this matters for upside / downside:** PEGY directly answers the question "am I overpaying?". A low PEGY combined with a high Quality Score is the textbook setup for asymmetric upside — solid business, paying a fair price, and growth/income working in your favour.

---

### 3.6 The Watchlist

The Watchlist is your personal shortlist of companies to follow.

**How to add a company:**

- Click the **★ Star** icon at the start of any row in the Screener table. The star turns gold; the company is now saved.
- Click the star again to remove the company.

**Viewing your watchlist:**

- Click **Watchlist** in the top navigation bar. You will see a screener-style table containing only your saved companies, with all the same columns and sorting controls.
- The header shows the count, e.g. *"12 saved"*.

**Why use it:**

- Build a small focus list of 10–20 companies you want to monitor closely rather than scanning the whole universe every day.
- Track companies you have flagged for further research after running a screen.
- Keep a "buy when cheaper" list — companies you believe in but want to wait for a better entry price on.

> **Tip:** The watchlist is stored in your browser. Clearing your browser data will reset it. If you use the app on multiple devices, the watchlists are independent.

---

### 3.7 Excluding Sectors

Sometimes you want to screen "all stocks **except** these sectors" — for example, you may have ethical preferences (e.g. avoid Tobacco), or you may already have heavy exposure to a sector elsewhere in your portfolio.

**How it works:**

1. Open the **Sector** dropdown at the top of the Screener.
2. Each sector row has a **⊘** button on the right.
3. Click ⊘ to add a sector to your "excluded" list. Excluded sectors appear with a strikethrough in the dropdown.
4. Click ⊘ again to un-exclude.

**Visual feedback:**

- Excluded sectors appear as red chips above the screener table (e.g. *"Excluded: Energy ✕  Tobacco ✕"*).
- Click the **✕** on any chip to remove that exclusion.
- The dropdown header shows the count, e.g. *"All Sectors (−2)"*, when exclusions are active.

> **Tip:** You can combine "Sector = Health Care" (to focus on a single sector) with exclusions — but the focused sector takes precedence. Use exclusions when you want everything *except* certain industries.

---

## 4. Company Detail

Click on any company name or ticker to open the Company Detail panel. This gives you a deep dive into a single stock across seven tabs.

### 4.1 Chart Tab

Shows a **5-year price chart** with optional moving average overlays:

- **MA20 (20-day moving average):** The average closing price over the last 20 trading days. Used to gauge short-term trend direction. When the price is above the MA20, the stock is in a short-term uptrend.
- **MA50 (50-day moving average):** A medium-term trend indicator. A stock trading above its MA50 is broadly considered to be in an uptrend; crossing below is a warning sign.

**How to read it:** Look for a pattern of higher highs and higher lows (uptrend) or lower highs and lower lows (downtrend). The price being comfortably above both moving averages is a technically positive picture.

---

### 4.2 Overview Tab

A snapshot of the most important numbers. Key metrics to understand:

| Metric | Plain English |
|---|---|
| **Revenue** | Total sales generated. The top line. |
| **Net Income** | Profit after all costs, interest, and tax. The bottom line. |
| **EBITDA** | Earnings Before Interest, Tax, Depreciation & Amortisation. A proxy for operational cash-generating ability, often used for cross-company comparisons. |
| **FCF (Free Cash Flow)** | Cash left over after capital expenditure. This is the cash available to pay dividends, buy back shares, or pay down debt. Many consider this the most important profitability metric. |
| **EPS (Earnings Per Share)** | Net income divided by number of shares. Tells you how much profit each share generates. Rising EPS is positive; falling EPS is a warning. |
| **ROIC** | Return on Invested Capital — see Quality Score section. |
| **ROCE** | Return on Capital Employed — similar to ROIC, widely used in the UK. |
| **Current Ratio** | Current assets ÷ current liabilities. A ratio above 1.0 means the company can cover its near-term bills. Below 1.0 is a potential liquidity concern. |
| **Interest Coverage** | Operating profit ÷ interest expense. How many times over the company can pay its interest bill. Below 2× is risky; above 5× is comfortable. |

---

### 4.3 Financials Tab

Shows five years of annual income statement data in chart form:

- **Revenue** — Are sales growing? Is growth accelerating or decelerating?
- **Gross Profit** — Is the gross margin (Gross Profit / Revenue) stable or expanding?
- **Operating Income** — Is the business becoming more or less operationally efficient?
- **EBITDA** — Is cash earnings power growing?
- **Net Income** — Is the bottom line growing?
- **Free Cash Flow** — Is the company converting profit to cash?

**What to look for:** All five lines ideally trending upward over 5 years. A company where revenue grows but net income and FCF do not is potentially a value trap — revenue growth is not translating into shareholder value.

---

### 4.4 Valuation Tab

Contains valuation multiples and return metrics:

| Metric | What it tells you | Typical ranges (context-dependent) |
|---|---|---|
| **P/E** | How expensive the stock is relative to earnings | 10–15 cheap; 20–30 fair for growth; 40+ expensive |
| **P/B** | Price relative to book value | < 1 can indicate undervalue; > 5 indicates market expects high returns |
| **P/S (Price/Sales)** | Useful when a company is not yet profitable | < 1 cheap; > 5 expensive for most sectors |
| **EV/EBITDA** | Enterprise value relative to operational earnings. Used for buyout valuations. | 8–12 fair for most sectors; < 6 potentially cheap |

The **EPS History** and **Return on Capital** charts show trends over time — critical context for any single-year number.

---

### 4.5 Health Tab

Focuses on balance sheet and financial risk:

- **Current Ratio trend** — Is the ability to meet short-term obligations improving or worsening?
- **Net Debt** — Total debt minus cash. Negative net debt (more cash than debt) is an extremely healthy position.
- **Altman Z-Score** — See the Risk Score section (3.2). The visual risk gauge shows at a glance whether the company is in the safe, grey, or distress zone.
- **Debt/Equity trend** — Is leverage increasing (risk rising) or falling (risk reducing)?

---

### 4.6 Growth Tab

| Metric | What to look for |
|---|---|
| **Revenue CAGR** | Compound Annual Growth Rate — the year-on-year growth rate if returns were smoothed out. A 10%+ Revenue CAGR over 5–10 years is strong. |
| **EPS CAGR** | Are earnings per share growing faster or slower than revenue? Faster EPS growth = expanding margins. |
| **FCF CAGR** | Growing free cash flow is the ultimate sign of a compounding business. |
| **Margin trends** | Expanding gross, operating, and net margins signal an improving competitive position. |

---

### 4.7 Analysts Tab

The most detailed analyst view:

- **Consensus bar chart** — Visual breakdown of Strong Buy / Buy / Hold / Sell / Strong Sell ratings.
- **Price targets** — Mean, median, high, and low analyst price targets versus the current price.
- **EPS estimates** — What analysts collectively expect the company to earn this quarter, next quarter, this year, and next year.
- **Revenue estimates** — Expected sales for this year and next.
- **Revisions** — Number of upward and downward EPS revisions in the last 7 and 30 days.

**The revision trend is particularly powerful.** When analysts start revising their earnings estimates upward, it often precedes share price appreciation as the market reprices the improved outlook. Similarly, downward revisions are an early warning.

---

### 4.8 Company News Tab — Press, RNS & AI Summary

The Company News tab pulls together everything written about the company over the **last 6 months** in one place, and lets you ask the AI to summarise it for you.

**Three sections on this tab:**

1. **AI Summary — Last 60 Days** *(top of page, purple panel)*
   - Press the **✦ Generate summary** button and DeepSeek (an AI model) will read every regulatory announcement and press article from the last 60 days, then produce:
     - **Summary paragraph:** the top-level story
     - **Key themes:** 2–4 bulleted angles (e.g. "Margin pressure from input costs", "Successful product launch in Asia")
     - **Watch Next:** the one or two events that will determine whether the story continues or breaks
   - Click **↻ Regenerate** if new news has come in since the last summary.

2. **Regulatory (RNS) feed** *(orange header)*
   - The official Stock Exchange announcements the company has filed (results, M&A, director dealings, contract wins, capital raises, etc.).
   - Each row shows:
     - **Tier badge** (A / B / C) — the AI's view of how significant the announcement is. See [Section 8](#8-rns-news-screener).
     - **Headline** — click to open the full announcement on Investegate.
     - **AI thesis** — a one-sentence interpretation of why the announcement matters (when available).
     - **Action pill** — BUY / WATCH / AVOID / NEUTRAL — the AI's suggested response.

3. **Press / Google News feed** *(orange header)*
   - Articles from the wider press (FT, Reuters, Bloomberg, broker notes covered in the press, etc.) sourced from Google News.
   - Cached for 24 hours per company; click **↻ Refresh news** at the top to force a fresh fetch.

**Why the news tab matters for upside / downside:**

- Many of the strongest one-week share price moves happen on RNS announcements. Reading the recent RNS history tells you what catalysts have already played out — and helps you anticipate what might come next.
- The AI summary is especially useful when you are first researching a name: 60 days of news condensed into a few paragraphs you can read in 30 seconds.
- A clean run of positive Tier B announcements with rising analyst forecasts is a powerful "everything is going right" signal.
- A series of negative Tier A flags (profit warnings, going concern statements) is one of the clearest early warning signs of permanent capital loss.

---

## 5. Sector Analysis

### 5.1 Sector Rotation

**What is sector rotation?**

Different parts of the economy perform better at different points in the economic cycle:
- During a **recovery** (economy picking up after a downturn), cyclicals like Industrials and Consumer Discretionary tend to lead.
- During an **expansion** (strong growth), Technology and Materials often outperform.
- During a **slowdown**, defensive sectors like Consumer Staples, Health Care, and Utilities typically hold up better.
- During a **contraction** (recession), Utilities and Consumer Staples are relative safe havens.

Understanding which phase we are in can help you tilt your portfolio toward sectors likely to outperform.

**The Relative Strength (RS) Score:**

For each sector, the tool calculates a Relative Strength score:

```
RS Score = (Sector 63-day return) ÷ (FTSE All-Share 63-day return)
```

An RS Score > 1.05 means the sector has outperformed the broad market by more than 5% over the past 3 months — this is a **BUY signal** (the sector has leadership and momentum).

An RS Score < 0.95 means the sector has underperformed by more than 5% — this is an **AVOID signal**.

**Market Breadth** (% of sector stocks above their 50-day moving average) confirms the signal — a sector showing strong RS with broad participation across its constituent stocks is a more reliable signal than one carried by a single mega-cap name.

**The Cycle Wheel** visualises the current estimated phase of the economic cycle based on sector rotation patterns.

---

### 5.2 Market Breadth

Market breadth measures the **participation** in a market move — not just whether the index is rising, but how many individual stocks are rising with it.

| Breadth Indicator | What it tells you |
|---|---|
| **% above 50-day MA** | The proportion of FTSE stocks trading above their medium-term trend line. Above 70% = broad participation, healthy market. Below 40% = narrow market, caution warranted. |
| **52-Week Highs vs Lows** | Far more new highs than lows = strong bull market; more lows = deteriorating market. |
| **Advance/Decline Line** | Running total of (stocks rising - stocks falling) each day. A rising A/D line confirms an index uptrend; divergence (index rising but A/D falling) is a warning. |

---

### 5.3 Signal Log

A chronological record of automatically generated signals:

- **BUY** — A sector's RS score crossed above 1.05 with a rising trend.
- **AVOID** — A sector's RS score dropped below 0.95 with a falling trend.
- **ALERT** — A noteworthy change in breadth or sentiment.
- **INFO** — General market observations.

Use the signal log to track when sector rotation signals were generated and evaluate them with hindsight.

---

## 6. Markets

### 6.1 Fear & Greed Index

**What is it?**

Inspired by CNN's Fear & Greed Index (which covers US markets), FINScope's version is purpose-built for the UK market. It combines six independent data points into a single score from 0 (Extreme Fear) to 100 (Extreme Greed).

**Why does it matter?**

Markets are driven by two emotions: fear and greed. When greed dominates (score approaching 100), assets are often overpriced and a correction may be coming. When fear dominates (score near 0), assets are often underpriced and recovery may be near. As Warren Buffett famously said: *"Be fearful when others are greedy, and greedy when others are fearful."*

**The six components (each scored 0–100, equally weighted):**

| Component | What it measures |
|---|---|
| **FTSE Momentum** | How far the FTSE 100 is above/below its 125-day moving average, normalised statistically. A market well above its long-term trend is "greedy"; well below is "fearful". |
| **Market Breadth** | % of FTSE stocks above their 50-day moving average, z-score normalised. Broad participation = greed; narrow market = fear. |
| **VIX (Volatility)** | The CBOE VIX measures expected US market volatility. High VIX = fear; low VIX = greed. The score is inverted so high VIX produces a low (fearful) reading. |
| **Safe Haven Demand** | The spread between FTSE 100 returns and UK Gilt ETF returns over 20 days. When investors flee stocks for government bonds, it signals fear. |
| **Realised Volatility** | The actual 20-day volatility of the FTSE 100. High volatility indicates uncertainty and fear. |
| **New Highs vs Lows** | The ratio of stocks hitting 52-week highs versus 52-week lows across the FTSE universe. More highs = greed; more lows = fear. |

**Sentiment labels:**

| Score | Label | Implication |
|---|---|---|
| 75–100 | Extreme Greed | Market may be overheated; consider reducing risk |
| 55–74 | Greed | Positive momentum; maintain positions but stay selective |
| 45–54 | Neutral | No strong signal |
| 25–44 | Fear | Market under stress; look for quality stocks on sale |
| 0–24 | Extreme Fear | Potential buying opportunity for long-term investors |

**Cycle Phase Suggestion:** The tool automatically suggests a market cycle phase (Recovery / Expansion / Slowdown / Contraction) based on the F&G score and its trend over time.

---

### 6.2 Cross-Asset Monitor

Shows the current state of key assets relative to their recent history (using z-scores — how many standard deviations above/below average):

| Asset | Relevance |
|---|---|
| **GBP/USD** | Sterling strength. A rising pound is generally positive for UK importers and consumers but can hurt FTSE 100 exporters (whose overseas earnings are worth less in GBP). |
| **Brent Crude Oil** | Affects Energy sector stocks directly; indirectly affects inflation and consumer spending across the economy. |
| **Gold** | Often called a "safe haven." Rising gold prices typically indicate global uncertainty or inflation fears. |
| **UK Gilt Yields vs Utilities** | When gilt (government bond) yields rise sharply, income-seeking investors can earn more from bonds without taking equity risk. This typically puts downward pressure on high-dividend sectors like Utilities. |

---

### 6.3 Gilt Yields

UK government bonds (gilts) are loans to the UK government. The **yield** is the effective interest rate the government pays. Gilt yields are the foundation of all UK asset pricing:

- A rising yield curve (long-term rates well above short-term) generally signals economic optimism.
- An **inverted yield curve** (short-term rates above long-term) is historically a reliable recession warning signal.
- Rising gilt yields increase the "risk-free rate" — the return investors can get without any risk — which mechanically reduces the attractiveness of equities (particularly growth stocks).

The tool shows:
- **Snapshot** — Current yields across 2Y, 5Y, 10Y, 20Y, and 30Y maturities (the yield curve shape).
- **Historical** — How yields have changed over time.

---

## 7. Analyst Monitor

The Analyst Monitor page provides a dedicated view of professional analyst sentiment across all covered stocks.

**Latest Consensus table:** All stocks with analyst coverage, sortable by consensus rating, upside %, buy %, or revision score.

**Changes:** Flags stocks where the consensus or upside estimate has shifted materially since the last data refresh — these are often the most actionable signals, as a change in analyst view can precede a significant price move.

**Composite Score:** A single ranking that combines:
- Buy percentage (full weight)
- Expected upside (half weight, capped at 50%)
- Revision score × 10 (revision momentum is given extra weight as it is forward-looking)

> **Why the Buy% looks lower than you might expect:** When only one or two analysts cover a stock, a "100% bullish" rating is usually noise rather than signal. The composite score therefore applies **shrinkage** — it pulls thinly-covered stocks back toward a neutral 50% baseline. For example, a single analyst at 100% Buy counts as roughly 58%, while a 20-analyst stock at 80% Buy stays close to its raw value. This deliberately rewards stocks where many independent analysts agree.

**Top Bullish / Top Bearish:** The five stocks with the strongest positive and negative composite scores — your instant shortlist of where professional money is most positive and most negative.

---

## 8. RNS News Screener

The **RNS News Screener** (top nav → "RNS News") is one of the most powerful tools in the app for catching catalysts early.

### 8.1 What is RNS?

**RNS** stands for **Regulatory News Service** — the official Stock Exchange channel that all listed UK companies must use to release **price-sensitive information**. Examples include:

- Results announcements (full-year, half-year, quarterly trading updates)
- Profit warnings and earnings guidance
- Mergers, acquisitions, and offer announcements
- Major contract wins, drug approvals, drilling results
- Director share dealings, share issues, AGM results

When a company files an RNS, the market reacts quickly — often within seconds for large items. **Reading and reacting to RNS news is one of the most direct sources of edge for retail investors**, because the same announcement reaches you at exactly the same moment as everyone else.

The challenge is that there are hundreds of RNS releases every trading day, most of which are administrative (changes in share count, voting rights, etc.). The RNS News Screener solves this with an AI pipeline that filters and ranks announcements automatically.

### 8.2 The Two-Layer Pipeline

When you press **↻ Refresh + AI rank**, the app runs three stages in sequence (you can watch the live stage indicator on the button):

| Stage | What it does |
|---|---|
| **Ingest** | Pulls every new RNS announcement from Investegate (the standard data source for UK regulatory news). |
| **Summaries** | Fetches the AI-generated summary for each announcement from Investegate. |
| **Rank** | Sends each Tier A and Tier B item to **DeepSeek** (an AI model) for ranking, scoring, and a "what to do about it" recommendation. |

The pipeline takes 1–3 minutes per refresh. It also runs automatically in the background several times per UK trading day (every 15 minutes during the morning RNS window), so the feed is usually fresh.

#### The Tier system

A simple keyword-based **rules classifier** does a first-pass coarse sort:

| Tier | Label | Examples |
|---|---|---|
| **A** | **Significant** | Profit warnings, full-year results, firm offers (Rule 2.7), strategic reviews, drug approvals, major contract wins |
| **B** | **Noteworthy** | Trading updates, possible offers (Rule 2.4), capital raises, drill results, board changes, dividend changes |
| **C** | **Routine** | Total voting rights, holdings notifications, PDMR transactions, AGM admin |

Tier A and Tier B items are then sent to the AI for ranking. Tier C items are kept in the database but not ranked (you can still see them by setting Min Score = 0 and Tier filter = C).

### 8.3 Reading the Feed

**The summary cards at the top:**

- **Tier A — Significant** *(orange)* — count of high-significance items in the current window
- **Tier B — Noteworthy** *(blue)* — count of medium-significance items
- **AI-Ranked** *(green)* — how many items the AI has scored
- **Total in feed** — total items currently in your filtered view

**The controls bar:**

| Control | What it does |
|---|---|
| **Window** | Look back 6 hours up to 1 week |
| **Min score** | Hide items with a Rules score below this threshold (e.g. *60 (Tier A+)* hides everything below significant) |
| **Tier pills** | Filter by Tier A, Tier B, Tier C, or All |
| **Sort: AI score / Time** | Either rank by the AI's score (best first) or chronological (newest first) |
| **Search box** | Free-text filter by ticker, company name, or headline keyword |

**Each row shows:**

- **Time** — when the announcement was filed (e.g. "08:23" today, "23 Apr 14:47" earlier)
- **Tier badge** — A / B / C
- **Ticker / Company** — click the ticker to open the company detail page
- **Headline** — click to open the full announcement on Investegate
- **AI thesis** — a one-sentence interpretation of *why* the announcement matters
- **AI risks** — what could go wrong with the bullish reading
- **Category** — the rules-classifier category (Profit Warning, Trading Update, etc.)
- **Rules score** — 0–100, the rules-classifier importance
- **AI score** — 0–100, the DeepSeek score (typically a more refined version of the rules score, factoring in valuation, analyst views, and recent price action)
- **Action pill** — BUY / WATCH / AVOID / NEUTRAL — see Section 8.4

### 8.4 Action Pills

The AI assigns each ranked announcement an **action**, which is the simplest way to scan the feed quickly:

| Action | Colour | What it suggests |
|---|---|---|
| **BUY** | Green | A clear bullish catalyst with limited downside risk in the AI's reading. Worth investigating today. |
| **WATCH** | Amber | A mixed or interesting signal — not a clear buy yet, but put it on the watchlist and track follow-up news. |
| **AVOID** | Red | A clear negative — profit warning, going concern, etc. The AI sees more downside than upside. |
| **NEUTRAL** | Grey | Material announcement but no clear directional signal. |

> **Important:** The action is the AI's suggestion based on the announcement plus the company's valuation, analyst consensus, and recent price context. It is not a buy/sell recommendation — always cross-check by opening the company detail page and reading the full RNS yourself before acting.

#### How to use the RNS feed for upside hunting

The clearest opportunities tend to come from:

1. **Tier A "BUY" items where the company also has a high Quality Score and reasonable PEGY** — quality + catalyst + fair price = highest-conviction setup.
2. **Multiple Tier B "WATCH" items in the same week on the same company** — when several positive operational updates accumulate, the market often hasn't fully priced in the cumulative effect yet.
3. **Recommended offer (Rule 2.7) announcements** — these instantly mark the share price near the offered price, but sometimes there is a small "merger arbitrage" gap if you trust the deal will close.

#### How to use it for downside protection

- **Profit warnings** are listed as Tier A AVOID. If you hold the stock and see one, your downside is real and immediate — read the announcement immediately.
- **Going concern statements**, **suspensions**, and **delistings** are tagged in the Category column — these are some of the worst things that can happen to a stock you own.
- **Strategic Reviews** can go either way — sometimes leading to break-up value (upside), sometimes to forced asset sales (downside). Read the AI thesis carefully.

---

## 9. Analytics — The Visual Map of the Market

The **Analytics** page (top nav → "Analytics") shows the entire UK universe as a scatter plot, so you can spot opportunities visually.

**Two visual modes:**

### Mode 1 — Quality × PEGY

- **X axis:** PEGY (lower = cheaper for the growth and income on offer)
- **Y axis:** Quality Score (higher = better business)
- **Each dot = one company.** Dot size scales with market capitalisation — large companies are bigger dots.

**The four quadrants:**

| Quadrant | Meaning | Colour |
|---|---|---|
| **Top-left** | High Quality, Low PEGY — *Cheap quality* | Green dots |
| **Top-right** | High Quality, High PEGY — *Expensive quality* | Amber dots |
| **Bottom-left** | Low Quality, Low PEGY — *Cheap low-quality (potential value trap)* | Amber dots |
| **Bottom-right** | Low Quality, High PEGY — *Avoid* | Red dots |

> **Most asymmetric upside lives in the green top-left quadrant** — high-quality businesses trading at fair-or-below prices for the growth they are delivering. This is the "Buffett quadrant".

### Mode 2 — Momentum × Risk

- **X axis:** Risk Score (lower = safer, displayed left-to-right with the safer side on the left)
- **Y axis:** Momentum Score (higher = stronger price trend)

| Quadrant | Meaning | Colour |
|---|---|---|
| **Top-left** | Strong momentum + safe | Green dots |
| **Top-right** | Strong momentum + risky | Amber dots |
| **Bottom-left** | Weak momentum + safe | Amber dots |
| **Bottom-right** | Weak momentum + risky | Red dots |

> **Top-left is the goal:** a stock trending up *and* with a low risk score has the best risk-adjusted profile in the universe. Top-right (high momentum but risky) is the speculative quadrant — can pay off but blow-ups are sudden.

### Controls

- **Index pills** — limit the plot to FTSE 100, FTSE 250, FTSE 350, or All.
- **X-axis zoom slider** — pull leftwards to zoom into the dense central area; the grey indicator at the right tells you how many points are off-chart.
- **Click a dot** to open that company's detail page directly.

> **Why the visual matters:** A scatter plot of 1,000 stocks shows patterns the screener table cannot — clusters of similar companies, sector concentrations, and isolated outliers (often the most interesting opportunities). Use it to find ideas you would not have thought to filter for.

---

## 10. The Sidebar — Your Instant Dashboard

The sidebar is always visible (toggle it on or off via the icon at the top-left of the navigation) and gives you an instant market snapshot:

| Item | What it shows |
|---|---|
| **FTSE 100 / 250 / All-Share** | Total return for each index (price + dividends) |
| **VIX** | Current US volatility index level. Below 15 = calm; 20–30 = elevated; 30+ = stressed |
| **CNN Fear & Greed** | External US market sentiment gauge (from CNN) |
| **UK Fear & Greed** | The FINScope-calculated UK sentiment score |
| **Cycle Phase** | Current estimated market cycle phase |
| **Top RS Sector** | The sector with the highest relative strength — where market leadership currently sits |
| **Market Breadth** | Overall % of FTSE stocks above their 50-day MA |

---

## 11. How To Find Investment Leads — Step-by-Step Workflows

The following workflows use combinations of the tools described above to identify promising investment candidates. These are starting points for research, not buy recommendations.

The first five (11.1–11.5) are classic single-angle workflows. The last three (11.6–11.8) combine multiple tools in the app and are designed specifically to maximise the chance of upside while minimising downside risk.

---

### 11.1 The Quality + Value Filter

**Suitable for:** Long-term investors seeking high-quality businesses at reasonable prices.

**Philosophy:** The best investments combine high business quality (durable competitive advantages, high returns on capital) with a reasonable price (confirmed by fundamental health checks). This combines elements of Warren Buffett's quality-focused approach with Piotroski's systematic value screening.

**Steps:**

1. Go to **Screener** (Fundamentals view)
2. Set filters:
   - Min Quality Score: **7**
   - Min Piotroski: **6**
   - Max Risk Score: **5**
   - Min ROE: **12%**
3. Sort by **Quality Score** descending
4. For each result, click through to the **Valuation tab** and assess P/E and EV/EBITDA relative to the sector average
5. Check the **Growth tab** to confirm margins are stable or expanding
6. Check the **Health tab** to confirm the balance sheet is robust

**What you are looking for:** Companies with Quality 8+, Piotroski 7+, trading on a P/E below their historical average or sector peers. These are businesses the market may be undervaluing despite their fundamental strength.

---

### 11.2 The Momentum Trend-Following Approach

**Suitable for:** Investors comfortable with medium-term active management.

**Philosophy:** Stocks with strong price momentum tend to continue outperforming over the following 3–12 months. This is one of the most replicated findings in academic finance (see Appendix A). Combining momentum with a quality check reduces the risk of buying high-momentum but fundamentally weak stocks ("crowded trades").

**Steps:**

1. Check the **Fear & Greed Index** — only pursue this strategy when the score is in Neutral to Greed territory (45–80). In Extreme Fear markets, momentum strategies frequently fail.
2. Go to the **Screener**, check **Sector Rotation** for the top 2–3 sectors by RS Score (the BUY-signalled sectors)
3. Back in the Screener, filter by those sectors
4. Set: Min Momentum Score **7**, Min Quality Score **5**, Max Risk Score **6**
5. Sort by **Momentum Score** descending
6. Click through each result; on the **Chart tab**, confirm the price is above both the MA20 and MA50

**What you are looking for:** High-momentum stocks in leading sectors with the price above both moving averages. This combination — sector leadership + stock momentum + price confirmation — increases the probability of continued outperformance.

---

### 11.3 The Analyst Upgrade Hunt

**Suitable for:** Investors who want to follow professional money.

**Philosophy:** Analyst earnings upgrades (upward EPS revisions) are one of the strongest short-to-medium term price catalysts. When analysts raise their profit forecasts, it signals they have discovered something positive about the company's fundamentals — and the market typically reprices accordingly.

**Steps:**

1. Go to the **Analyst Monitor** page
2. Sort the **Latest Consensus** table by **Rev Score** descending
3. Look for stocks where Rev Score is positive (more upgrades than downgrades in the last 30 days) AND consensus is Buy AND upside % is 15%+
4. Cross-reference these names in the main Screener (Fundamentals view) to confirm they also score well on Quality and have a Risk Score ≤ 6
5. Check the **Analysts tab** in Company Detail for the individual breakdown of estimate changes

**What you are looking for:** Stocks where analysts are becoming increasingly positive AND the fundamentals support the bullish case. The "Changes" section on the Monitor page highlights stocks where consensus has recently shifted — these are the freshest signals.

---

### 11.4 The Sector Rotation Strategy

**Suitable for:** Investors who want to tilt their portfolio toward market-leading areas.

**Philosophy:** Markets rotate through sectors as the economic cycle progresses. Being in the leading sectors significantly improves returns; avoiding lagging sectors reduces drawdowns.

**Steps:**

1. Go to **Sector Analysis → Rotation**
2. Identify sectors with a BUY signal (RS > 1.05, rising trend) and strong breadth (>60% of stocks above 50-day MA)
3. Note the **Cycle Wheel** — does the suggested phase align with your macro view?
4. In the Screener, filter by the leading sector(s)
5. Apply: Min Momentum **6**, Min Quality **5**, sort by Market Cap descending for the largest, most liquid names
6. Review the **Signal Log** for context on how long the signal has been in place

**What you are looking for:** The "sweet spot" is a sector that has recently generated a BUY signal (not one that has been leading for 12 months and may be due to rotate). Combine with individual stock quality and momentum scores to find the best names within the sector.

---

### 11.5 The Defensive Screen (Capital Preservation)

**Suitable for:** Investors prioritising protecting capital, particularly in uncertain markets.

**Philosophy:** When Fear & Greed is in Fear or Extreme Fear territory, focus shifts to capital preservation. Defensive stocks — those in sectors like Consumer Staples, Health Care, and Utilities — tend to hold their value better in downturns because people still buy food, medicines, and pay their utility bills regardless of economic conditions.

**Steps:**

1. Check the **Fear & Greed Index** — if score < 40, the defensive screen is most relevant
2. Go to the Screener, filter by Sector: **Consumer Staples**, **Health Care**, or **Utilities**
3. Set: Max Risk Score **4**, Min Quality Score **6**, Min Piotroski **5**
4. In the **Health tab**, look for companies with Net Debt negative (cash-rich) or Interest Coverage > 5×
5. In the **Analysts tab**, check that consensus is at least Hold (avoid stocks with a Sell consensus in a declining market)

**What you are looking for:** High-quality, financially robust companies in defensive sectors. In a bear market, these companies decline less and recover faster — preserving your capital to redeploy when Fear & Greed signals a recovery.

---

### 11.6 The Catalyst Hunt — RNS-Driven Upside

**Suitable for:** Investors who can act on the same day news arrives.

**Philosophy:** Most large positive share-price moves happen on a specific day in response to a specific announcement. The RNS News Screener is designed to catch these as they happen, rank them by significance, and tell you which ones the AI sees as bullish opportunities versus risk events.

**Steps:**

1. Open the **RNS News** page first thing in the morning UK time (most RNS releases come between 07:00 and 08:00).
2. Set **Window** to *24 hours*, **Min score** to *60 (Tier A+)*, and **Sort: AI score**.
3. Look for items with the **BUY** action pill in green, especially those with an **AI score ≥ 75**.
4. For each candidate, click the ticker to open the company page.
5. On the company page, check three things in this order:
   - **Quality Score** ≥ 6 — confirms the underlying business is good
   - **Risk Score** ≤ 6 — confirms you are not chasing a catalyst on a fragile balance sheet
   - **Analysts tab** — confirms this is not a story analysts already see as priced in (look for upside % > 10)
6. If all three pass, read the full RNS by clicking the headline — make sure the AI thesis matches what the company actually said.

**What you are looking for:** A high-quality, low-risk company with an AI-flagged BUY catalyst that has not yet been fully priced by analysts.

---

### 11.7 The Visual Map Workflow — Cheap Quality Hunting

**Suitable for:** Long-term investors who want to find high-quality businesses at fair-or-better prices.

**Philosophy:** Plotting the entire universe on a Quality vs PEGY chart instantly reveals where the asymmetric opportunities are. The top-left "cheap quality" quadrant is where Buffett-style "wonderful businesses at a fair price" cluster.

**Steps:**

1. Go to **Analytics**.
2. Select mode **Quality × PEGY**.
3. Filter to **FTSE 350** (the largest 350 companies — best liquidity).
4. Use the X-zoom slider to zoom into the dense region (PEGY 0–3).
5. Look for **green dots in the top-left** quadrant — high Quality, low PEGY.
6. Click each green dot to open the company; on the detail page, run the standard checks:
   - Health tab: Is the balance sheet healthy?
   - Growth tab: Are revenue, profit, and FCF all growing?
   - Analysts tab: Does professional consensus agree it is undervalued?
   - Company News tab: Have there been any recent negative catalysts that explain why it is cheap?
7. Now switch the visualisation to **Momentum × Risk** and find where the same company sits. A company in the top-left of *both* charts (cheap quality AND positive momentum + low risk) is a rare and powerful setup.

**What you are looking for:** Companies that appear in the green quadrant of both visualisations — the rare intersection of "good business, fairly priced, currently trending up, low risk".

---

### 11.8 The Combined "Maximum Upside / Minimum Downside" Workflow

**Suitable for:** Any investor who wants a systematic way to assemble a high-conviction shortlist.

**Philosophy:** No single signal is reliable on its own. The strongest investment cases stack multiple independent signals — quality, value, momentum, professional consensus, and a recent catalyst — that all point the same way. When five independent things all say "buy", the probability of being wrong falls dramatically; this is how you maximise upside while minimising downside.

**Step-by-step — the full workflow:**

1. **Check the macro backdrop first** *(Sidebar + Markets)*
   - Open the sidebar. Note the **UK Fear & Greed** score.
     - 25–55 (Fear / Neutral): excellent time to be hunting — assets often mispriced
     - 55–75 (Greed): hunt selectively — focus on lagging quality names
     - 75+ (Extreme Greed): be defensive — see Workflow 11.5 instead
   - Check **Cycle Phase** in the sidebar — it tells you which sectors typically lead.

2. **Pick your sector battlefield** *(Sector Rotation)*
   - Go to **Markets → Rotation**. Note the top 3 sectors with the highest RS Score and rising trend.
   - Avoid sectors with RS < 0.95 (declining leadership).

3. **Narrow the universe** *(Screener)*
   - In the Screener, set: FTSE 350, leading sectors only.
   - Apply the *quality + value + safety* filters:
     - Min Quality ≥ 7
     - Min Piotroski ≥ 6
     - Max Risk ≤ 5
     - Min Momentum ≥ 6
     - Min Upside % ≥ 10 (Analyst View)
     - Consensus = Buy
   - Sort by **Quality Score** descending. You should now have 5–25 names.

4. **Visual cross-check** *(Analytics)*
   - Open **Analytics**, mode Quality × PEGY. Cross-reference your shortlist against the green top-left quadrant. Drop any names that fall outside it.
   - Switch to Momentum × Risk. Confirm survivors are top-left here too.

5. **Catalyst check** *(RNS News + Company News tab)*
   - For each survivor, open the company page → **News tab**.
   - Press **✦ Generate AI summary**. Read it.
   - Look at the recent RNS. Are there:
     - Positive Tier A or B items in the past 30 days? (BULLISH stack)
     - Negative profit warnings or going-concern flags? (DROP IT)
     - Nothing material recently? (NEUTRAL — fine; pure quality + momentum case)

6. **Final downside checks** *(Company Detail tabs)*
   - **Health tab:** Net Debt should be manageable (under 3× EBITDA), Current Ratio > 1, no Z-Score in distress zone.
   - **Valuation tab:** P/E should be in line with or below the sector. EV/EBITDA below 12.
   - **Growth tab:** Revenue, EPS, and FCF all rising over 3+ years.
   - **Analysts tab:** Confirm Rev Score is positive — analysts are still raising forecasts.

7. **Save and monitor** *(Watchlist)*
   - Star the survivors using the ★ icon in the screener — they go to your **Watchlist** for daily review.
   - Re-run the macro check (step 1) before each buy decision; even a great company is the wrong purchase in a panicked market.

**The signals that should all be GREEN before you buy:**

| Signal | Source | Threshold for "GREEN" |
|---|---|---|
| Macro backdrop | Sidebar Fear & Greed | < 75 |
| Sector leadership | Rotation page | Sector RS > 1.05 |
| Business quality | Screener | Quality ≥ 7, Piotroski ≥ 6 |
| Valuation | Screener | PEGY ≤ 1.5, P/E sector-comparable |
| Trend | Screener / Chart | Momentum ≥ 6, price above MA50 |
| Safety | Screener / Health tab | Risk ≤ 5, Net Debt manageable |
| Professional view | Analyst Monitor | Buy consensus, Upside ≥ 10%, Rev Score > 0 |
| Catalysts | RNS News, Company News | No negative Tier A in 30 days; ideally a recent positive one |
| Visual confirmation | Analytics | Green quadrant in both Quality × PEGY and Momentum × Risk |

When eight or nine of these are green for a single name, you have a high-conviction, asymmetric-risk setup. When fewer than five are green, walk away — there will be better opportunities.

> **What you are looking for:** A small portfolio (5–15 names) of stocks that pass this test. Trim positions when signals turn red — especially when negative RNS catalysts arrive — and rebuild the screen monthly.

---

## 12. Glossary of Financial Terms

| Term | Definition |
|---|---|
| **Annual Report** | A yearly document published by a listed company reporting its financial results and strategy |
| **Bear Market** | A sustained market decline of 20% or more from recent highs |
| **Bull Market** | A sustained market rise of 20% or more from recent lows |
| **CAGR** | Compound Annual Growth Rate — the smoothed annual rate of growth over a period |
| **Capital Gain** | Profit made when a share price rises above the price you paid |
| **Current Ratio** | Current assets ÷ current liabilities. A ratio above 1.0 means short-term bills can be met |
| **Dividend** | A cash payment made by a company to its shareholders, usually quarterly or annually |
| **Dividend Yield** | Annual dividend per share ÷ share price. Expressed as a percentage |
| **EPS** | Earnings Per Share — company net profit divided by shares outstanding |
| **Enterprise Value (EV)** | Market cap + net debt. The theoretical takeover cost of a business |
| **Equity** | Shareholders' ownership stake in a company. Assets minus liabilities. |
| **FCF** | Free Cash Flow — operating cash flow minus capital expenditure |
| **Gilts** | UK government bonds. The "risk-free" investment benchmark for UK investors |
| **Gross Margin** | (Revenue − Cost of Goods Sold) ÷ Revenue. The profitability before operating costs |
| **ICB** | Industry Classification Benchmark — the standard sector taxonomy for UK-listed companies |
| **IPO** | Initial Public Offering — when a company lists on a stock exchange for the first time |
| **Liquidity** | How easily a share can be bought or sold without affecting its price |
| **Market Cap** | Share price × shares outstanding. The total market value of the company |
| **Moving Average (MA)** | The average price over a specified number of recent days. Smooths out daily price noise |
| **Net Debt** | Total borrowings minus cash. Negative net debt = more cash than debt |
| **Operating Leverage** | How much a company's profits amplify when revenue grows. High leverage = profit rises faster than sales |
| **P/B Ratio** | Price to Book — share price divided by net assets per share |
| **P/E Ratio** | Price to Earnings — share price divided by earnings per share |
| **PEGY** | Price/Earnings divided by (Growth + Yield). A value-for-money check that combines the P/E with both growth and dividend yield in one figure |
| **P/S Ratio** | Price to Sales — market cap divided by annual revenue |
| **Relative Strength** | A stock's or sector's performance relative to a benchmark |
| **RNS** | Regulatory News Service — the official Stock Exchange channel that all UK listed companies must use to release price-sensitive information |
| **ROA** | Return on Assets — net income ÷ total assets |
| **ROCE** | Return on Capital Employed — operating profit ÷ capital employed |
| **ROE** | Return on Equity — net income ÷ shareholders' equity |
| **ROIC** | Return on Invested Capital — net operating profit after tax ÷ invested capital |
| **Sector Rotation** | The movement of investment capital between industry sectors as the economic cycle evolves |
| **Ticker** | A short code identifying a listed stock (e.g. `AZN.L` for AstraZeneca London) |
| **Volatility** | The degree of price fluctuation. Higher volatility = higher uncertainty = higher risk |
| **Yield Curve** | A graph of government bond yields across different maturities. Its shape signals economic expectations |
| **Z-Score (Altman)** | A statistical measure predicting probability of corporate bankruptcy |
| **Z-Score (statistical)** | How many standard deviations a value is from its historical average |

---

## Appendix A — Methodology References

The quantitative indicators used in FINScope are grounded in peer-reviewed academic research. Below are the key papers underlying each methodology.

---

### Price Momentum

**Jegadeesh, N. & Titman, S. (1993)**  
*"Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency"*  
Journal of Finance, 48(1), pp. 65–91.

The seminal paper demonstrating that stocks which perform well over the past 3–12 months continue to outperform over the following 3–12 months. This "momentum effect" has since been replicated across virtually every developed and emerging market studied.

**Asness, C., Moskowitz, T. & Pedersen, L. (2013)**  
*"Value and Momentum Everywhere"*  
Journal of Finance, 68(3), pp. 929–985.

Demonstrates that momentum and value factors work across asset classes (stocks, bonds, currencies, commodities) and geographies. Also shows the diversification benefit of combining momentum with value.

**The 12-1 Month Window:**  
The exclusion of the most recent month from the momentum calculation was formalised by Jegadeesh & Titman. Short-term return reversal (the tendency of the best recent performers to give back gains) is distinct from the medium-term momentum effect and would corrupt the signal if included.

---

### Piotroski F-Score

**Piotroski, J.D. (2000)**  
*"Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers"*  
Journal of Accounting Research, 38 (Supplement), pp. 1–41.

Piotroski showed that among stocks with high book-to-market ratios (classic "value" stocks), a simple 9-point scoring system based on improving fundamentals could separate the subsequent strong performers from the weak. Portfolios of high-F-Score value stocks significantly outperformed in his study. The score has since been validated across many markets and time periods.

---

### Altman Z-Score

**Altman, E.I. (1968)**  
*"Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy"*  
Journal of Finance, 23(4), pp. 589–609.

Altman used multiple discriminant analysis on 66 manufacturing firms to identify the financial ratios most predictive of bankruptcy within two years. The original model had 72% accuracy two years before failure; later variants for non-manufacturing and private companies improved this. The five-variable model combining working capital, retained earnings, operating income, market equity, and revenue relative to total assets remains widely used by credit analysts and risk managers.

**Altman, E.I. (2000)**  
*"Predicting Financial Distress of Companies: Revisiting the Z-Score and ZETA Models"*  
Working Paper, Stern School of Business, NYU.

Updated validation confirming continued predictive power and discussing adaptations for service industries and international markets.

---

### Quality / Return-Based Investing

**Novy-Marx, R. (2013)**  
*"The Other Side of Value: The Gross Profitability Premium"*  
Journal of Financial Economics, 108(1), pp. 1–28.

Demonstrates that highly profitable firms (measured by gross profit / assets) generate significantly higher returns than unprofitable firms, even controlling for value factors. This provides the academic basis for rewarding high gross margins in the quality score.

**Fama, E.F. & French, K.R. (2015)**  
*"A Five-Factor Asset Pricing Model"*  
Journal of Financial Economics, 116(1), pp. 1–22.

The expanded Fama-French model adds profitability and investment factors to the classic three-factor model, confirming that high-profitability firms earn a persistent premium.

---

### Sector Rotation and the Economic Cycle

**Stovall, S. (1996)**  
*"Standard & Poor's Guide to Sector Investing"*  
McGraw-Hill.

The foundational practical framework for understanding which sectors tend to lead and lag at each phase of the economic cycle. The rotation pattern described — Cyclicals leading in recovery, Defensives outperforming in contraction — has been the practitioner's standard since the 1990s.

---

### Fear & Greed / Sentiment Indicators

**Baker, M. & Wurgler, J. (2007)**  
*"Investor Sentiment in the Stock Market"*  
Journal of Economic Perspectives, 21(2), pp. 129–151.

Documents how investor sentiment — measurable through market breadth, new highs/lows, and other indicators — is predictive of subsequent returns, especially for smaller, harder-to-arbitrage stocks. When sentiment is high (greed), subsequent returns tend to be lower; when sentiment is low (fear), subsequent returns tend to be higher.

---

## Appendix B — ICB Sector Company List

The **Industry Classification Benchmark (ICB)** is the taxonomy used to classify UK-listed companies by sector. Below are the representative companies tracked by FINScope in each sector. Tickers ending `.L` are listed on the London Stock Exchange.

---

### Energy
Companies involved in oil and gas exploration, production, refining, and distribution.

| Ticker | Company |
|---|---|
| SHEL.L | Shell |
| BP.L | BP |
| HBR.L | Harbour Energy |

> **Sector characteristics:** Highly cyclical — profits are closely tied to the oil price. Shell and BP are among the largest companies in the FTSE 100. Revenue is partly in USD, so GBP/USD movements affect reported UK earnings.

---

### Financials
Banks, insurance companies, asset managers, and financial exchanges.

| Ticker | Company |
|---|---|
| HSBA.L | HSBC |
| LLOY.L | Lloyds Banking Group |
| BARC.L | Barclays |
| NWG.L | NatWest Group |
| LSEG.L | London Stock Exchange Group |
| STAN.L | Standard Chartered |
| AV.L | Aviva |
| LGEN.L | Legal & General |
| ADM.L | Admiral Group |
| MNG.L | M&G |
| PRU.L | Prudential |
| SDR.L | Schroders |
| III.L | 3i Group |

> **Sector characteristics:** Banks benefit from rising interest rates (higher margins) but face credit risk in recessions. Insurance companies are sensitive to claims inflation and investment yields. P/B ratio is particularly relevant for banks; P/E less so.

---

### Industrials
Aerospace and defence, engineering, construction, and business services.

| Ticker | Company |
|---|---|
| RR.L | Rolls-Royce |
| BA.L | BAE Systems |
| AHT.L | Ashtead Group |
| IAG.L | International Airlines Group (British Airways/Iberia) |
| IMI.L | IMI |
| WEIR.L | Weir Group |
| RTO.L | Rentokil Initial |
| ITRK.L | Intertek Group |
| MRO.L | Melrose Industries |
| EXPN.L | Experian |
| WPP.L | WPP |
| PSON.L | Pearson |

> **Sector characteristics:** Highly diverse. Defence names like BAE are increasingly seen as defensive given rising government spending. Cyclical industrials like Ashtead (equipment rental) are closely tied to construction activity.

---

### Materials
Mining companies producing metals, minerals, and chemicals.

| Ticker | Company |
|---|---|
| RIO.L | Rio Tinto |
| GLEN.L | Glencore |
| AAL.L | Anglo American |
| ANTO.L | Antofagasta |
| FRES.L | Fresnillo |
| MNDI.L | Mondi |
| SKG.L | Smurfit WestRock |
| CRDA.L | Croda International |

> **Sector characteristics:** Highly cyclical. Profits driven by commodity prices (iron ore, copper, gold, silver). Rio Tinto and Glencore are among the world's largest mining groups. CRDA and MNDI are specialty chemicals/packaging — less cyclical.

---

### Consumer Discretionary
Non-essential consumer goods and services — what people buy when they have money to spare.

| Ticker | Company |
|---|---|
| CPG.L | Compass Group |
| NXT.L | Next |
| IHG.L | InterContinental Hotels Group |
| GAW.L | Games Workshop |
| KGF.L | Kingfisher |
| JD.L | JD Sports Fashion |
| MKS.L | Marks & Spencer |
| WTB.L | Whitbread |
| EZJ.L | easyJet |
| ENT.L | Entain |
| FLTR.L | Flutter Entertainment |
| ABF.L | Associated British Foods (Primark) |
| SBRY.L | J Sainsbury |
| PSN.L | Persimmon |
| TW.L | Taylor Wimpey |

> **Sector characteristics:** Sensitive to consumer confidence and disposable income. Performs well in economic expansions; suffers in downturns. Housebuilders (Persimmon, Taylor Wimpey) also highly sensitive to mortgage rates.

---

### Consumer Staples
Essential everyday goods — food, beverages, household products, tobacco.

| Ticker | Company |
|---|---|
| BATS.L | British American Tobacco |
| ULVR.L | Unilever |
| RKT.L | Reckitt Benckiser |
| TSCO.L | Tesco |
| DGE.L | Diageo |
| IMB.L | Imperial Brands |
| ABF.L | Associated British Foods |

> **Sector characteristics:** Defensive — demand is stable regardless of the economic cycle. These companies often have strong brands and pricing power, leading to high and durable gross margins. A key safe-haven sector during downturns.

---

### Health Care
Pharmaceuticals, biotechnology, and medical equipment companies.

| Ticker | Company |
|---|---|
| AZN.L | AstraZeneca |
| GSK.L | GSK (formerly GlaxoSmithKline) |
| HLN.L | Haleon |
| SN.L | Smith & Nephew |
| HIK.L | Hikma Pharmaceuticals |

> **Sector characteristics:** Defensive, driven by healthcare demand rather than economic cycles. AstraZeneca is the FTSE 100's largest company by market cap. Drug development timelines create binary risk events (trial success/failure). Patent cliffs (when blockbuster drugs lose patent protection) are a key risk.

---

### Technology
Software, data analytics, online marketplaces, and IT services.

| Ticker | Company |
|---|---|
| REL.L | RELX |
| HLMA.L | Halma |
| SGE.L | Sage Group |
| AUTO.L | Auto Trader Group |
| RMV.L | Rightmove |

> **Sector characteristics:** The UK technology sector is smaller than the US equivalent. These companies tend to have high gross margins, recurring revenue models, and low capital requirements — qualities that lead to high Quality Scores. Valuations can be high given growth expectations; rising gilt yields are a particular headwind for growth stocks.

---

### Telecommunications
Mobile and fixed-line communications services.

| Ticker | Company |
|---|---|
| VOD.L | Vodafone |
| BT-A.L | BT Group |
| AAF.L | Airtel Africa |

> **Sector characteristics:** Capital-intensive (network infrastructure). Highly regulated. Historically high dividend payers but dividend sustainability depends on free cash flow. BT and Vodafone have both cut dividends in recent years following heavy investment cycles.

---

### Utilities
Electricity generation, gas distribution, and water companies.

| Ticker | Company |
|---|---|
| NG.L | National Grid |
| SSE.L | SSE |
| CNA.L | Centrica |
| SVT.L | Severn Trent |
| UU.L | United Utilities |

> **Sector characteristics:** Regulated businesses with predictable, defensive earnings. Often pay high dividends. Sensitive to interest rate changes because investors compare their yields to gilt yields. When gilt yields rise sharply, utility share prices tend to fall. Heavily involved in the UK's energy transition (grid infrastructure investment).

---

### Real Estate
Real Estate Investment Trusts (REITs) and property companies.

| Ticker | Company | Specialism |
|---|---|---|
| LAND.L | Land Securities | Commercial property (offices, retail) |
| SGRO.L | Segro | Industrial/logistics warehouses |
| BLND.L | British Land | Retail parks and offices |
| BBOX.L | Tritax Big Box REIT | Large logistics warehouses |
| PCTN.L | Picton Property Income | Diversified commercial |
| GPE.L | Great Portland Estates | London offices |

> **Sector characteristics:** REITs must distribute 90% of taxable income as dividends, making them income investments. Net Asset Value (NAV) is the key valuation metric (P/B is particularly relevant). Sensitive to interest rates (higher rates increase borrowing costs and reduce property valuations). Logistics-focused REITs (SGRO, BBOX) have benefited from the shift to e-commerce; traditional retail property faces structural headwinds.

---

*Alpha Move AI — UK Stock Screener — User Manual — April 2026*  
*For support or feedback, refer to the project repository.*
