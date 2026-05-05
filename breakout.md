BREAKOUT STOCK SCREENING
Algorithm Design & Indicator Reference
MESI Investment Club  |  May 2026
1. What Is a Breakout?
A breakout occurs when price moves decisively beyond a level where it previously stalled — a resistance ceiling, a consolidation range, or a statistical boundary. The core challenge in screening is distinguishing genuine breakouts from noise and false breaks.

The most reliable breakouts share three characteristics:
•	A prior period of consolidation (compressed volatility, tight range)
•	Price moving through a defined resistance level
•	Significantly above-average volume confirming institutional conviction

2. Algorithm Families
2.1 Price-Level Breakouts (Classic)
Price closes above a defined resistance level — typically the highest high over a lookback window (20, 52, or 200 days). Simple and interpretable but triggers on every new high in a trending stock, generating significant noise.

What to screen for:
•	New N-day highs
•	Break above prior swing high
•	Break above round-number or prior-peak resistance

2.2 Consolidation / Range Breakouts
More selective than simple price-level screens. The approach identifies stocks that have been coiling — low volatility, tight price range — before breaking out. The logic is that compressed volatility precedes expansion.

Measured using:
•	Bollinger Band squeeze — bands narrowing to a multi-period low
•	ATR (Average True Range) dropping to a low relative to its own history
•	NR7 / NR4 patterns — narrowest range bar in last 7 or 4 sessions

These tend to be higher quality signals because you are catching the start of a move rather than the middle of one.

2.3 Volume-Confirmed Breakouts
Volume confirmation is the most important filter. A genuine breakout typically exhibits volume 1.5–2x the 20-day average on the breakout bar, with declining volume during the prior consolidation phase.

Core metric: Volume Ratio = today's volume / 20-day average volume

2.4 Moving Average Breakouts
Price crossing above a key moving average (50-day, 200-day) or a shorter MA crossing a longer one (golden cross). These are lagging indicators and are better used as trend filters than primary breakout triggers.

2.5 Volatility-Adjusted Breakouts (Donchian / Keltner)
Donchian channels define breakouts as price exceeding the N-period high/low channel. Keltner channels are ATR-based rather than price-range-based. Both are systematic and readily backtestable.

2.6 Statistical / Z-Score Approaches
Compute the rolling mean and standard deviation of returns. A breakout is defined as a return exceeding μ + 2σ. This normalises across stocks with very different price levels and volatility profiles — particularly useful for a heterogeneous 600-stock universe.

3. Breakout Patterns
The following patterns are the most reliably traded breakout setups in systematic screens:

Pattern	What It Looks Like	Why It Works
Flat Base	4–6 weeks of tight, sideways price action before a surge	Sellers exhausted; buyers absorbing available supply
Cup and Handle	Rounded bottom, brief pullback, then breakout	Classic institutional accumulation shape
Bull Flag	Sharp move up, tight diagonal pullback, then continuation	Profit-taking absorbed before next leg higher
Ascending Triangle	Higher lows hitting flat resistance level	Buyers becoming more aggressive on each dip
Pocket Pivot	Up day on volume greater than any down-day volume in prior 10 sessions	Early-stage institutional buying signal

4. Volume — The Primary Signal
4.1 Why Volume Dominates
When a stock breaks out on 2–3x average volume, that is institutions moving — and they cannot hide it. You cannot fake sustained volume across a liquid stock without genuine buying interest behind it. Price tells you what happened; volume tells you whether it will continue.

A volume spike with no price breakout may indicate accumulation — worth watching. A price breakout with no volume is likely a false break — ignore it.

4.2 Volume Pattern Before the Breakout
The volume pattern during consolidation is as important as the volume on the breakout day itself. A genuine setup shows:
•	Volume declining through the base — sellers losing interest
•	Volume at a relative low by the end of the consolidation period
•	The breakout bar showing a dramatic volume expansion by contrast

This ratio — breakout volume vs average volume during the base — is more powerful than simply comparing to the global 20-day average.

4.3 Relative vs Absolute Volume
Always normalise. A stock that normally trades 50,000 shares doing 150,000 is a stronger signal than a stock normally trading 5 million shares doing 7 million. Volume ratio (relative) is always more meaningful than raw volume count (absolute) when screening a large, diverse universe.

5. Volume-Price Indicators
5.1 On-Balance Volume (OBV)
A running cumulative total. Full volume is added on up days and subtracted on down days. The absolute number is meaningless — the direction and shape of the OBV line is what matters.

Key signal: OBV divergence during consolidation
Price is flat or slightly declining — looking weak — but OBV is quietly trending upward. This means more volume is coming in on up days than leaving on down days. Institutions are accumulating without moving the price. When they finish buying, supply is exhausted and price explodes upward.

Conversely, if price makes a new high but OBV does not confirm it, that indicates distribution — institutions selling into retail enthusiasm.

Weakness: OBV treats a 0.01% up day identically to a 5% up day — full volume is added in both cases. Volume Price Trend (VPT) addresses this.

5.2 Chaikin Money Flow (CMF)
A more sophisticated approach built on the Money Flow Multiplier — where did price close within the day's range?

Formula: MFM = ((close - low) - (high - close)) / (high - low)

•	Closes at the top of the range → multiplier near +1 (strongly bullish)
•	Closes at the bottom of the range → multiplier near -1 (strongly bearish)
•	Closes in the middle → near zero

CMF is the sum of (MFM × volume) over 20 days, divided by total volume over 20 days. Result is always between -1 and +1.

What to look for
•	CMF positive and rising during consolidation → accumulation confirmed
•	CMF crossing above zero after being negative → potential inflection point
•	CMF strongly positive on breakout day → institutional conviction behind the move

CMF is superior to OBV for screening because it captures the quality of each session, not just direction. A stock closing at the top of its range on high volume reads very differently from one closing mid-range on the same volume.

5.3 Money Flow Index (MFI)
Often described as volume-weighted RSI — that is the clearest description of what it does. Calculated using Typical Price (high + low + close / 3), scaled 0–100.

What to look for
•	MFI below 20 during consolidation then rising sharply → buyers returning
•	MFI making higher lows while price makes lower lows → bullish divergence
•	MFI above 80 on the breakout bar → strong money flow confirmation

Distinct advantage: MFI is bounded (0–100) and directly comparable across all 600 stocks without normalisation. OBV values are arbitrary numbers that vary widely between stocks. MFI gives a universal scale.

5.4 Volume Price Trend (VPT)
Hybrid of OBV and price momentum. Instead of adding or subtracting full volume based on direction, it weights volume by the percentage price change:

Formula: VPT = prior VPT + (volume × (close - prior close) / prior close)

A 5% up day on 1 million volume contributes far more than a 0.1% up day on the same volume. This is the key difference from OBV and makes VPT more sensitive to conviction moves.

During a genuine consolidation, VPT should be relatively flat. If it trends strongly in either direction, something is happening beneath the surface of the price action.

6. Recommended Combined Screen
Requiring multiple independent signals to align simultaneously reduces false break rate considerably. The recommended three-layer approach:

Layer	Purpose	Indicator	Threshold
1 — Trend Filter	Ensure buying with the trend	Price vs 150 or 200-day MA	Close above MA
2 — Consolidation	Confirm coiling before breakout	Bollinger Band width percentile rank	Below 25th percentile
3 — Accumulation	Smart money buying during base	OBV divergence or VPT trend	Rising while price flat
4 — Money Flow	Quality of volume during base	Chaikin Money Flow (CMF)	Positive and rising
5 — Breakout Trigger	Confirm directional move	Close vs N-day high	Close > 20-day high
6 — Volume Confirmation	Institutional conviction on day	Volume ratio + MFI	Ratio > 1.5x, MFI rising

A stock passing all six layers is a substantially higher quality signal than one that simply prints a new 20-day high on decent volume. You are requiring independent evidence of accumulation, money flow quality, and breakout conviction simultaneously.

7. Implementation Architecture
7.1 Data Stack
•	Data source: yfinance — returns OHLCV as standard, no additional feed required
•	Storage: Supabase (Postgres) with prices table keyed on (ticker, date)
•	Daily refresh: Render cron job — runs after market close weekdays
•	Screen computation: Python / pandas — runs sequentially after refresh
•	Results: Written to screens table in Supabase, queried by Vercel frontend

7.2 Processing Notes
•	Batch download all 600 tickers in a single yf.download() call — never loop
•	Use auto_adjust=True to handle splits and dividends correctly
•	Pull minimum 60 days of history to support 20-day rolling windows plus consolidation lookback
•	The .shift(1) on N-day high is critical — compare today's close to yesterday's 20-day high, not today's
•	Use percentile rank (rank(pct=True)) for ATR and Bollinger width — normalises across heterogeneous 600-stock universe
•	Upsert not insert — idempotent, safe to re-run the daily job without duplication

7.3 Run Order
Sequence within the Render cron job:
•	Step 1: Refresh prices (fetch yesterday's OHLCV for all 600 tickers, upsert to Supabase)
•	Step 2: Fetch last 60 days per ticker from Supabase
•	Step 3: Compute indicators in pandas (OBV, CMF, MFI, VPT, Bollinger, ATR, volume ratio)
•	Step 4: Apply screen filters on the latest bar per ticker
•	Step 5: Write hits to screens table with today's date

Document prepared May 2026 for MESI Investment Club. For internal research use only.
