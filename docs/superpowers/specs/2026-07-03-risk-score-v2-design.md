# Risk Score v2 — Sector-Aware Models — Design Spec
_Date: 2026-07-03_

## Overview

Rework the 1–10 risk score so companies are scored by a model that fits their
business, instead of one Altman-Z-plus-volatility formula for everyone. Audit of
the live DB (2026-07-03) found four systematic problems:

1. **Capital-intensive businesses are over-penalised.** The classic Z-Score's
   X5 term (asset turnover) was calibrated on manufacturers; regulated water
   utilities (PNN/SVT/UU, Z 0.79–0.90), REITs and telecoms all land in the
   "distress" band and score risk 7–8 despite 18–27% volatility.
2. **Banks are scored on ROE + volatility only**, ignoring leverage
   (equity/assets) and price-to-book — both available in the DB and both more
   informative for banks.
3. **The Altman inputs are proxies** (X1 hardcoded 0, book equity via
   `market_cap / price_to_book`) even though `ttm_financials` now stores the
   real fields: `working_capital` (77%), `retained_earnings` (72%),
   `total_equity` (95%), `operating_income` (97%).
4. **~71 active investment trusts have NULL sector**, miss the `_is_financial`
   check, and get nonsense Altman scores (Z up to 576; some trusts wrongly
   flagged risk 9).

Score stays 1–10, same colour bands, same `screener_scores` daily pipeline.

---

## 1. Classification

Each company routes to exactly one model, decided from `company_metadata`
(sector + industry, both already in the DB):

| Model | Rule (checked in this order) | ~Count |
|---|---|---|
| `trust` | sector IS NULL AND industry IS NULL | 71 |
| `bank` | industry contains "bank" | 14 |
| `insurer` | industry contains "insur" | 11 |
| `financial` | sector contains "financ" / "bank" / "insurance" (asset managers, capital markets, credit) | ~147 |
| `asset_heavy` | sector ∈ {Utilities, Real Estate, Energy, Basic Materials} OR industry contains "telecom" OR asset turnover (`revenue / total_assets`) < 0.4 | ~145 |
| `general` | everything else | ~238 |

The asset-turnover trigger exists because sector labels miss two groups whose
`/total_assets` ratios are structurally depressed: goodwill/property-heavy
names outside the listed sectors (Whitbread, Ocado, BATS, Haleon) and
**float-heavy fintechs** — e.g. Boku (BOKU.L, Technology / Software -
Infrastructure) carries merchant float on its balance sheet like a bank,
turns over 0.26× assets, and scores risk 8 today despite £194m net cash and
65× interest cover. Verified: distressed low-turnover names (Ocado, PureTech)
stay high-risk under the `asset_heavy` model, so the reroute doesn't
whitewash genuine risk. The trigger only fires when revenue is present and
`total_assets > 0`; pre-revenue biotechs with NULL revenue stay in `general`.

Replaces the boolean `_is_financial(row)` with `_classify_risk_model(row) → str`.
The chosen model name is stored and exposed (see §3/§4) so the UI can label the
score honestly.

---

## 2. Models & Computation

All component scores map onto 1–10 via a shared linear helper
`_lin(x, safe, risky)`: `x` at or beyond `safe` → 1, at or beyond `risky` → 10,
linear between, `None` in → `None` out. Blending uses a shared
`_weighted_blend([(component, weight), ...])` that renormalises weights over
whichever components are non-None (generalises today's `_blend_risk` /
`_financial_risk`), returns None if all are None, clamps to 1–10.

### 2.1 Shared inputs — one bulk query

`_attach_risk_score` currently fetches `total_assets` from `annual_financials`.
Replace with a single bulk query joining `ttm_financials` +
`company_metadata` keyed by symbol (ttm has 100% `total_assets` coverage, so
the annual query is dropped):

```
sector, industry, market_cap, price_to_book, revenue, operating_income,
working_capital, retained_earnings, total_equity, total_assets,
interest_coverage, net_debt, ebitda, roe, roe_median
```

Result rows passed in then only need `symbol` — the attacher no longer depends
on callers supplying `roe`/`sector` (fixes the snapshot path implicitly). The
price-history volatility query is unchanged.

### 2.2 Volatility component (all models)

Unchanged thresholds (`_vol_to_score`), one robustness fix: **winsorise daily
log returns to ±25%** before computing the std. Suspension/relisting artefacts
currently produce 800%+ annualised vol (FXPO, SAVE) which pins the component at
10 regardless of the real trading range.

### 2.3 Rewired Altman inputs (used by `general`)

`_altman_z` switches from proxies to stored fields:

| Term | Now | Becomes |
|---|---|---|
| X1 | hardcoded 0 | `working_capital / total_assets` (0 if NULL, as before) |
| X2 | `(mc / p2b) / total_assets` | `retained_earnings / total_assets`; fallback `total_equity / total_assets` |
| X3 | `operating_margin × revenue / TA` | `operating_income / total_assets` (direct) |
| X4 | `mc / (TA − mc/p2b)` | `mc / (total_assets − total_equity)`, skipped if equity NULL or ≥ TA |
| X5 | `revenue / total_assets` | unchanged |

The `mc/p2b` book-equity proxy is retired: the Yahoo p2b snapshot can be stale
relative to `market_cap`, distorting X2 and X4 together. Negative retained
earnings are kept (that's signal, not noise). `general` blend is unchanged:
**0.6 × Z-component + 0.4 × vol**, `_z_to_risk` bands unchanged (≥3.0 → 1,
≤1.0 → 10).

### 2.4 `asset_heavy` — Z″ + debt service

**Altman Z″** (the non-manufacturer variant — drops X5, reweights):

```
Z″ = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4
```

Bands: Z″ ≥ 2.6 → 1, ≤ 1.1 → 10, linear between (`_zdd_to_risk`).

**Debt-service component** — average of whichever legs are available:

- Interest coverage: `_lin(interest_coverage, safe=6, risky=0.5)` — negative
  coverage → 10. (96% coverage in these sectors. Calibration note: the
  original safe=8/risky=1 band pinned regulated utilities — which
  structurally run 2-3x cover — at 8-9; sub-1x cover still saturates at 10.)
- Net debt / EBITDA: `_lin(net_debt / ebitda, safe=1, risky=8)`; net cash
  (net_debt ≤ 0) → 1 **only when st_debt/lt_debt were actually reported** —
  updater.py derives net_debt = -cash when yfinance misses the debt lines, so
  an unreported balance sheet must not read as "net cash" (PHP: phantom net
  cash at a real ~48% LTV); EBITDA ≤ 0 → leg unavailable (interest coverage
  catches that case). (79% coverage.)

**Blend: 0.4 × Z″ + 0.3 × debt service + 0.3 × vol.**

This is the substantive fix for utilities/REITs/telecoms/miners and
float-heavy fintechs: a regulated water company (or a payments processor
holding merchant float) stops being "a manufacturer with terrible asset
turnover" and is instead judged on whether it can service its (structurally
large) balance sheet.

`altman_z` for these companies stores the Z″ value (the `risk_model` field
tells the UI which scale applies).

### 2.5 `bank`

| Component | Mapping | Weight |
|---|---|---|
| ROE quality | `_roe_to_risk` (unchanged) on **0.5·roe + 0.5·roe_median** (whichever available) | 0.30 |
| Leverage | `_lin(total_equity / total_assets, safe=0.10, risky=0.03)` — UK banks span 5–14%; the ~3.25% regulatory leverage floor anchors the risky end | 0.25 |
| Market signal | `_lin(price_to_book, safe=1.0, risky=0.35)` — a bank at <0.6× book is the market pricing balance-sheet doubt (CBG 0.45, ARBB 0.48) | 0.20 |
| Volatility | unchanged | 0.25 |

The ROE median blend stops a single flattering or ugly IFRS year dominating
(today `roe_median` is only a NULL-fallback).

### 2.6 `insurer`

ROE (same median blend) is kept but demoted — IFRS-17 makes life-insurer ROE
noisy (sector avg −14% in the DB) — and the P/B market signal is added:

**0.35 × ROE + 0.25 × P/B + 0.40 × vol** (same mappings as banks).
Equity/assets is *not* used — policy liabilities make it meaningless.

### 2.7 `financial` (asset managers etc.)

Unchanged formula (**0.6 × vol + 0.4 × ROE**), except ROE uses the same
median blend. These are asset-light; the current model is honest for them.

### 2.8 `trust`

**Vol component only.** No Altman of any flavour — a closed-end fund's balance
sheet looks like a failing manufacturer's and the current output (Z 23–576,
ASLI risk 9) is noise. `altman_z = NULL`. (NAV discount would be the right
second signal but isn't in the DB — out of scope.)

### 2.9 Display clamp

`altman_z` is clamped to **[−10, 30]** before storing. EEE.L currently stores
Z = 1402 (market cap 15× total assets); the 1–10 score is unaffected but the
Health tab and any averages are polluted.

---

## 3. Backend

### `main.py`

- `_classify_risk_model(row)` replaces `_is_financial`.
- `_lin`, `_weighted_blend` helpers; `_zdd`, `_zdd_to_risk`,
  `_debt_service_component`, `_bank_risk`, `_insurer_risk` added;
  `_altman_z` rewired per §2.3; `_annualised_vol` winsorises returns.
- `_attach_risk_score` routes per §1, attaches `risk_score`, `altman_z`,
  `volatility_annualised` and **`risk_model`** to each row. Still exactly two
  bulk queries (ttm+metadata join, price history).
- `compute_and_store_scores` upserts `risk_model` alongside the existing
  columns.
- `/api/screener` SELECT and `/api/snapshot` include `risk_model`. The
  snapshot path additionally attaches a small `risk_components` dict (the
  per-component 1–10 values actually used) so the Health card can show *why*
  — computed inline, no schema impact.

### Migration `007_risk_model.sql`

```sql
ALTER TABLE screener_scores ADD COLUMN IF NOT EXISTS risk_model TEXT;
```

### Tests — `tests/test_risk.py`

Extend with: classification routing (incl. NULL-sector trust, telecom
industry override), Z″ arithmetic, debt-service legs (negative coverage, net
cash, EBITDA ≤ 0), bank/insurer blends, weight renormalisation when
components are missing, winsorised vol, Z clamp.

---

## 4. Frontend

Minimal — the score, bands and colours are unchanged everywhere (screener
pill, watchlist, trending, digest).

**Company page Health card** (`CompanyDetail.tsx`): caption switches on
`risk_model`:

- `general`: current caption (Z > 3 safe · 1.8–3 grey · < 1.8 distress)
- `asset_heavy`: "Altman Z″ (asset-heavy): > 2.6 safe · 1.1–2.6 grey ·
  < 1.1 distress" + interest-cover / net-debt-EBITDA line from
  `risk_components`
- `bank` / `insurer` / `financial`: "Scored on ROE / leverage / price-to-book /
  volatility (Altman N/A for financials)" with the available components
- `trust`: "Investment trust — scored on volatility only"

---

## 5. Graceful degradation

| Missing data | Behaviour |
|---|---|
| Any model, some components NULL | `_weighted_blend` renormalises over what's left |
| All components NULL | `risk_score = NULL`, display "—" |
| `retained_earnings` NULL | X2 falls back to `total_equity / total_assets` |
| `total_equity` NULL or ≥ total_assets | X2 (equity fallback) / X4 skipped |
| `working_capital` NULL | X1 = 0 (conservative, as today) |
| EBITDA ≤ 0 or NULL | ND/EBITDA leg dropped; interest coverage carries debt service |
| Bank with no ROE / equity / P/B | vol-only (same as today's worst case) |
| Trust with no price history | `risk_score = NULL` |

---

## 6. Calibration & validation

Thresholds above are starting points. Before storing, run
`compute_and_store_scores` logic in a dry-run script (print-only, per-sector
before/after distribution) and check the sanity table:

| Symbol | Today | Expected v2 | Why |
|---|---|---|---|
| SVT.L / UU.L / PNN.L | 8 | 5–7 | Leveraged but stable regulated water |
| PHP.L | 7 | 4–5 | Low-vol healthcare REIT |
| BP.L | 7 | 4–5 | Integrated major, cover 3.1× |
| TLW.L / KIST.L | 10 / 9 | 9–10 | Genuinely distressed E&P — must stay high |
| HSBA.L / LLOY.L / NWG.L | 5 | 3–5 | Profitable, ≥1× book |
| MTRO.L / VANQ.L | 7 | 6–7 | Weak ROE, sub-book |
| CBG.L | 9 | 8–9 | Negative ROE, 0.45× book |
| ADM.L | 3 | 2–3 | High-ROE P&C insurer |
| BOKU.L | 8 | 3–4 | Float-heavy fintech: net cash £194m, 65× cover — turnover trigger routes it to `asset_heavy` (verified by simulation: scores 3) |
| OCDO.L | 10 | 9–10 | Low-turnover but genuinely stressed (cover −1.5×) — must stay high |
| ASLI.L (trust) | 9 | ~vol (≤6) | Currently mis-scored by Altman |
| GAW.L | low | unchanged low | Asset-light `general` names shouldn't move much |

Adjust `_lin` bands (not weights first) if a row misses its range, re-run,
then apply the migration and let the daily job repopulate.

**Dry-run outcome (2026-07-03, after the two calibration notes above):**
15/18 targets hit — SVT 7, UU 5, PHP 4, TLW 9, HSBA 4, LLOY 5, NWG 4, MTRO 6,
VANQ 6, ADM 3, ASLI 9 (= its vol component), GAW 3, BOKU 3, OCDO 9, KIST 8.
Three land adjacent to target, each defensibly: PNN 8 (genuinely stressed —
1.6x cover, dividend rebase, rights issue), BP 6 (real leverage; down from 7),
CBG 7 (strong capital ratio offsets the ROE/P/B distress signals). Sector
averages: Energy 7.4→5.4, Real Estate 5.5→3.9, Utilities 5.6→4.7,
Basic Materials 5.2→3.8; asset-light sectors essentially unchanged.

---

## 7. Out of scope

- External data: CET1 / NPLs / liquidity for banks, solvency ratios for
  insurers, NAV discounts for trusts (none available from yfinance)
- Historical risk-score trend
- Sector-relative percentile normalisation
- Screener filtering by risk model
- Any change to momentum / Piotroski / valuation scores
