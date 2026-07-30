# RNS Score vs Forward Return — analysis & monitoring plan

Goal: measure whether `llm_score` on an RNS announcement predicts subsequent price
movement at 1d / 1w / 1m / 3m, segmented by the scoring model (the DeepSeek "flash
reasoning" switch changed the score distribution), and stand this up as a monitoring
page that keeps re-measuring as data matures.

## What we already have (no new capture needed)

- `rns_announcements` Tier **A/B rows are retained indefinitely** (`_prune_old` only
  culls Tier C at 14d). Every scored row carries `llm_score`, `llm_sentiment`,
  `llm_model`, `symbol`, `published_at`, `category`, `tier`.
- `price_history`: ~5y adjusted daily OHLCV (`auto_adjust=True` → split/dividend
  clean), refreshed nightly. Baseline helpers already exist in `showcase.py`
  (`_story_close`, `_next_open`).
- Model change is **self-labelling** via `llm_model` → segment by exact string,
  never by an assumed cutover date.

## Central constraint: horizon maturity

The flash-reasoning model went live ~2026-07-16. A 3-month forward return needs an
announcement ≥3 months old, so **the new model currently has zero mature 1m/3m data**
— only 1d and (partial) 1w. The old-model cohort (v4 and earlier) is the only one with
mature long horizons today. This is why it must be a *monitoring* page: horizons fill
in over time. Every stat is reported with its `n` and a "matured / still open" split.

## Methodology decisions (recommended defaults)

1. **Entry price = next trading-day OPEN.** RNS drops ~07:00 pre-open; you cannot buy
   the prior close. Report since-news-close as a secondary reference only (it flatters
   the signal — the known +8.3% vs +0.8% gap).
2. **Horizons in TRADING days**, matched to the nearest available close:
   1d=+1, 1w=+5, 1m=+21, 3m=+63. Return = `close[entry+h] / open_entry − 1`.
3. **Excess return vs a benchmark**, not raw. Raw return conflates the signal with
   market beta (a high score in a rising market looks predictive when it isn't).
   Subtract a market proxy matched to listing: FTSE All-Share proxy for Main Market,
   AIM All-Share proxy for AIM (reuse/extend `market.py` SECTOR_TICKERS baskets or add
   two index proxies). Keep raw return in the table too for sanity.
4. **Sign by sentiment.** `llm_score` is *impact magnitude*; `llm_sentiment` is
   *direction*. A high-score/negative row should predict DOWN. Either analyse
   positive/negative/neutral cohorts separately (preferred) or fold direction into a
   signed return. Never pool them — positive and negative high-scorers cancel.
5. **Score bands aligned to existing thresholds**: `<40 / 40–59 / 60–75 / 76–84 / 85+`.
   The 76/80 boundaries are where the digest analysis already saw a ~3.4× big-move lift,
   so they're the interesting cut points. Also compute a continuous rank-correlation
   (Spearman) of score vs excess return per horizon.
6. **Stats built for fat tails + small n**: report **median** and **hit rate**
   (% excess>0) alongside mean, with bootstrap CIs. Means alone are hostage to one
   outlier at these sample sizes.
7. **Point-in-time integrity**: use the score as first written (`llm_processed_at`),
   not any re-score. Guard against a re-rank overwriting history.

## Data-quality handling

- **Delisting / truncated windows**: symbols flip `is_active=false` and stop updating;
  a 3m window may never complete. Forward return is NULL until its horizon date has a
  recorded close; a horizon that can never fill (delisted) is marked `terminated`, not
  silently dropped — report coverage %.
- **Unresolved symbols**: rows with `symbol IS NULL` (ticker never resolved to a
  yfinance symbol) are excluded — no price series to join.
- **Suspensions / gaps**: if no close exists within a small tolerance of the horizon
  date, take the next available close and record the actual offset used.

## Build phases

### Phase 0 — offline exploratory analysis (validate before building UI)
A one-off script/notebook (`backend/analysis/rns_score_perf.py`, read-only) that joins
A/B rows → `price_history`, computes the excess returns above, and prints the
calibration table (band × horizon × sentiment, plus model segment) and Spearman ρ.
Purpose: confirm the signal exists and lock the bucketing before investing in the page.
Deliverable: a short findings note. **Do this first.**

### Phase 1 — persistent performance table + maturation cron
- New table `rns_score_performance` (migration NNN, RLS-enabled per project rule):
  one row per scored announcement with entry_open, entry_date, and one column per
  horizon for both raw and excess return, plus `status` per horizon
  (`open/matured/terminated`). Frozen once matured so a later delisting can't erase it.
- A daily job (fold into the existing prices or RNS cron) recomputes only the rows
  whose horizons have newly matured. Cheap, idempotent.
- This generalises the High Impact showcase's tracking to **all** scored RNS, not just
  curated positives — reuse `_story_close`/`_next_open` patterns.

### Phase 2 — admin monitoring page
- Endpoint returning aggregates: **calibration** (band → median/mean excess + hit rate
  + n), faceted by horizon, model, and sentiment; a **decay** view (mean excess vs
  horizon per band) to see how fast edge fades; and a **model A/B** panel
  (old vs flash-reasoning on the horizons both have matured).
- Page under the admin/status area (token-guarded like `/status`). Charts via the
  already-code-split recharts. Show maturity/coverage prominently so thin cells aren't
  over-read.

## Open questions for you
- Scope now: **Phase 0 only** (just tell me if the signal is real), or straight through
  to the page?
- Benchmark: happy with All-Share + AIM proxies, or do you want sector-relative
  (more precise, more work / thinner cells)?
- Universe: all A/B scored rows, or restrict to a tier/category (e.g. exclude routine
  Tier B paperwork that scores low anyway)?
