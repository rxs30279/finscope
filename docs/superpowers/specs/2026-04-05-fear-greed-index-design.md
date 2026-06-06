# UK Fear & Greed Index — Design Spec

**Date:** 2026-04-05  
**Status:** Approved

---

## Overview

Build a UK-focused Fear & Greed index using market data already available via yfinance. The index scores market sentiment 0–100 from 5 components, displays compactly in the sidebar and in full detail in the Breadth tab, and automatically drives the Business Cycle phase on the Rotation tab.

---

## Components (6)

Each component produces a score 0–100. The overall F&G score is the simple average.

> **Revised 2026-06 (methodology review).** Four components were corrected so each is
> anchored to a *meaningful neutral* rather than a trailing-mean baseline that drifts with the
> regime (the old approach made e.g. a +1% gap above the MA read as Extreme Fear, and 50%
> breadth read as Greed). VIX was relabelled honestly as a US-derived global proxy. See the
> per-row notes below.

| # | Component | Source | Scoring method |
|---|---|---|---|
| 1 | FTSE Momentum | FTSE 100 (`^FTSE`, 2y) vs 125-day MA | **Deviation from zero gap**: `(price − MA125) / MA125`, scaled by ~1yr of the gap's volatility. Zero gap = 50, above MA = greed, below = fear. (Was a mean-relative z-score.) |
| 2 | Market Breadth | % of FTSE 100 basket above 50-day MA | Direct: `breadth_pct × 100`. 50% participation = 50 (neutral). (Was a mean-relative z-score.) |
| 3 | Implied Vol (VIX) | `^VIX` level | Inverted z-score vs trailing 1yr range (high VIX = low score). **US-derived (S&P 500 options)** — used as a global risk-appetite proxy; no free UK VFTSE exists. UK-specific vol is component 5. |
| 4 | Safe Haven Demand | 20-day total-return spread: FTSE 100 vs UK gilt ETF (`IGLT.L`, all-maturity) | **Deviation from zero spread**, scaled by the spread's volatility. Stocks beating bonds = greed, gilts winning = fear. A small structural greed lean (equity risk premium) is accepted. (`^TNGBP` from the original spec does not exist on Yahoo; IGLT.L total return is the correct input for a return spread.) |
| 5 | Realised Vol | 20-day annualised realised vol of FTSE 100 | Inverted z-score vs trailing 1yr range, `clip=3.0` (wider tail headroom). Genuinely UK; mean-relative framing is correct for a volatility measure (no absolute neutral). |
| 6 | New Highs / Lows | net (52w highs − lows) / universe from basket | `50 + (net / universe) × 100`, clamped 0–100. Centred at 50; net ±25% of the universe reaches the extreme bands. (Multiplier was ×50, which left it compressed in ~43–65 year-round.) |

**Z-score to 0–100 mapping** (components 3, 5): `score = clip((z + 2) / 4 × 100, 0, 100)` — z of +2 or above = 100, z of −2 or below = 0. Component 5 uses `clip=3` (z of ±3 → 0/100).

**Deviation-to-score mapping** (components 1, 4): identical to the z-score mapping but centred on **zero** (`z = value / std`) rather than the series mean — so the *sign* of the value is meaningful (above/below the neutral point), not just its rank vs recent history.

### Sentiment labels

| Score | Label |
|---|---|
| 0–25 | Extreme Fear |
| 25–45 | Fear |
| 45–55 | Neutral |
| 55–75 | Greed |
| 75–100 | Extreme Greed |

---

## Phase Auto-Detection

The F&G score and its short-term trend direction together determine a suggested cycle phase.

**State:** `_fg_history` — in-memory list of the last 4 readings, each containing `{score, suggested_phase, timestamp}`. Persists across cache refreshes within the same server session.

**Trend:** compare current score against the score 3 readings ago (~45 minutes). Rising = current > prior, Falling = current ≤ prior. If fewer than 4 readings exist, trend = "unknown" and no phase change fires.

| Condition | Suggested phase |
|---|---|
| Score < 45 + falling | Contraction |
| Score < 45 + rising | Recovery |
| Score > 55 + rising | Expansion |
| Score > 55 + falling | Slowdown |
| Score 45–55 (neutral zone) | No change |
| Trend unknown | No change |

**Confirmation rule:** the cycle phase only updates if the last 2 readings share the same suggested phase AND that phase differs from the current `_cycle["phase"]`. This prevents noisy day flipping.

When auto-update fires, it writes a signal log entry: `"Cycle phase auto-updated to {phase} by Fear & Greed index (score: {score})"`.

---

## Backend

### New function: `_compute_fear_greed()`

Returns:
```json
{
  "score": 62,
  "sentiment": "Greed",
  "trend": "rising",
  "suggested_phase": "Recovery",
  "confirmed": true,
  "components": {
    "momentum":   { "score": 74, "label": "FTSE Momentum",    "value": 2.1 },
    "breadth":    { "score": 58, "label": "Market Breadth",   "value": 58.0 },
    "vix":        { "score": 52, "label": "VIX",              "value": 18.4 },
    "safe_haven": { "score": 68, "label": "Safe Haven Demand","value": 3.2 },
    "hl_ratio":   { "score": 38, "label": "New Highs / Lows", "value": "3/5" }
  }
}
```

Cached under key `"fear_greed"` with standard 15-minute TTL.

### New endpoint: `GET /api/market/fear-greed`

Returns the full `_compute_fear_greed()` payload.

### Updated endpoint: `GET /api/market/sidebar`

Adds `"fear_greed": { "score": 62, "sentiment": "Greed", "trend": "rising" }` to the sidebar response.

### Auto-phase update

Runs inside `_compute_fear_greed()` after scoring. Appends to `_fg_history`, checks confirmation, calls the same logic as the existing `set_cycle()` POST handler if confirmed and phase differs from current.

---

## Frontend

### Sidebar.js

New block between VIX and ICB Sectors:

- Section label: **FEAR & GREED**
- Large score number, colour-coded: red (<25), orange (25–45), grey (45–55), yellow-green (55–75), green (>75)
- Sentiment label badge (same colour scheme)
- Thin progress bar 0–100
- Small line: `Auto phase: RECOVERY ↑` showing suggested phase + trend arrow

### BreadthTab.js

New card at the top of the tab (above existing breadth metrics):

- Title: **UK Fear & Greed Index**
- Large score + sentiment label
- Trend indicator + auto-phase + confirmation status (`2/2 readings`)
- Colour-banded progress bar (red → orange → grey → yellow-green → green)
- 5 component cards in a row, each showing: component name, score, mini progress bar, sentiment label

---

## Colour scheme

| Sentiment | Colour |
|---|---|
| Extreme Fear | `#ef4444` (red) |
| Fear | `#f97316` (orange) |
| Neutral | `#666` (grey) |
| Greed | `#f59e0b` (amber) |
| Extreme Greed | `#10b981` (green) |

---

## Out of scope

- No historical F&G chart (can be added later)
- No manual override of the auto-phase from the F&G panel (the cycle wheel on Rotation tab still works as a manual override)
- `_fg_history` is in-memory only — resets on server restart
