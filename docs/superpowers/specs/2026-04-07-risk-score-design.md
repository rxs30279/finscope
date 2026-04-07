# Risk Score — Design Spec
_Date: 2026-04-07_

## Overview

Add a composite 1–10 risk score to the UK stock screener, combining an Altman Z-Score (financial distress) with annualised price volatility. Higher score = higher risk.

**Colour bands:**
- 1–3: green (low risk)
- 4–6: amber (moderate risk)
- 7–10: red (high risk)

---

## 1. Data & Computation

### Altman Z-Score (60% weight)

Classic public-company formula:

```
Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5
```

| Component | Formula | Data source |
|-----------|---------|-------------|
| X1 = Working Capital / Total Assets | Treated as 0 if unavailable (conservative — omitting positive working capital understates safety) | annual_financials |
| X2 = Retained Earnings / Total Assets | Proxied: `(market_cap / price_to_book) / total_assets` | ttm_financials + annual_financials |
| X3 = EBIT / Total Assets | `operating_margin × revenue / total_assets` | ttm_financials + annual_financials |
| X4 = Market Cap / Total Liabilities | `market_cap / (total_assets − market_cap / price_to_book)` | ttm_financials + annual_financials |
| X5 = Revenue / Total Assets | `revenue / total_assets` | ttm_financials + annual_financials |

`total_assets` is fetched from `annual_financials` (most recent year, same JOIN pattern as Piotroski).

**Z → risk component mapping (1–10):**
- Z ≥ 3.0 → 1 (safe)
- Z ≤ 1.0 → 10 (distress)
- Linear interpolation between 1.0 and 3.0

### Volatility component (40% weight)

- Compute `std(daily_log_returns) × √252` from up to the most recent 252 rows in `price_history`
- Percentile-rank within the screener result universe → 1–10 (1 = least volatile)
- Fallback: if fewer than 63 rows of history exist for a symbol, that symbol's volatility component is omitted and Altman carries 100% of its weight

### Combined score

```
risk_score = round(0.6 × altman_component + 0.4 × vol_component)
```

Clamped to 1–10. If only one component is available, it carries 100% of the weight.

---

## 2. Backend

### `_attach_risk_score(results)` — `main.py`

Follows the same bulk-fetch pattern as `_attach_piotroski` and `_attach_momentum`:

1. Extract symbols from results
2. **One query** to `annual_financials` — fetch most recent `total_assets` per symbol (same CTE already used in Piotroski)
3. **One query** to `price_history` — fetch last 252 closes per symbol (same numbered CTE pattern as momentum)
4. Compute Z-Score and annualised volatility per symbol
5. Blend into `risk_score`, attach `altman_z` and `volatility_annualised` as separate fields
6. Attach all three to each result row

Called at the end of `/api/screener` alongside existing score functions.

### `/api/snapshot`

Add `risk_score`, `altman_z`, and `volatility_annualised` to the snapshot response so the company detail page can display sub-component detail. Computed inline using the same logic as `_attach_risk_score` but for a single symbol.

---

## 3. Frontend

### Screener table (`App.js`)

- New "Risk" column added after existing score columns
- Displays a colour-coded badge: `{ 1–3: green, 4–6: amber, 7–10: red }`
- Badge style: small pill with number, consistent with existing inline style approach
- Null-safe: shows `—` if score unavailable

### Company detail — Health tab (`App.js`)

New card in the Health tab:

```
[ RISK SCORE ]
     7          ← large colour-coded badge
Altman Z: 1.6 · Volatility: 34% ann.
Z > 3 safe · 1.8–3 grey zone · < 1.8 distress
```

- Follows existing card layout pattern in the Health tab
- No new component files — inline styles consistent with the rest of the app

---

## 4. Graceful degradation

| Missing data | Behaviour |
|---|---|
| No price history | Altman carries 100% weight |
| No financial data | Volatility carries 100% weight |
| Both missing | `risk_score = null`, display `—` |
| total_assets = 0 or null | Skip Altman, use volatility only |
| price_to_book = 0 or null | Skip X2, X4; use X3 + X5 only |

---

## 5. Out of scope

- No historical risk score trend chart
- No ability to filter screener by risk score (can be added later)
- No per-sector risk normalisation
