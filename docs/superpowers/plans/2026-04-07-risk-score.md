# Risk Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a composite 1–10 colour-coded risk score (Altman Z-Score + price volatility) to the screener table and company detail Health tab.

**Architecture:** Pure computation helpers (no I/O) are defined first and tested in isolation. A bulk-fetch function assembles DB data and calls the helpers, then attaches results to screener rows. The snapshot endpoint reuses the same helpers. Frontend adds one screener column and one Health tab card.

**Tech Stack:** Python/FastAPI backend, PostgreSQL via psycopg2, React frontend with inline styles, pytest + unittest.mock for tests.

> **Design note:** Volatility uses absolute thresholds (not universe-relative percentile) so the risk score is deterministic and identical in the screener and company detail page.

---

## File Map

| File | Change |
|------|--------|
| `backend/main.py` | Add helpers, `_attach_risk_score`, update screener + snapshot |
| `backend/tests/test_risk.py` | New — all backend risk tests |
| `frontend/src/App.js` | Add Risk column to screener table, Risk card to Health tab |

---

## Task 1: Pure computation helpers

**Files:**
- Modify: `backend/main.py` (add helpers after existing `_quality_score`)
- Create: `backend/tests/test_risk.py`

- [ ] **Step 1: Create the test file with failing tests for all helpers**

Create `backend/tests/test_risk.py`:

```python
import sys, os, math, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import _altman_z, _z_to_risk, _annualised_vol, _vol_to_score, _blend_risk


# ── _altman_z ─────────────────────────────────────────────────────────────────

def test_altman_z_returns_none_when_total_assets_none():
    row = {'market_cap': 1e9, 'revenue': 5e8, 'operating_margin': 0.2, 'price_to_book': 2.0}
    assert _altman_z(row, None) is None

def test_altman_z_returns_none_when_total_assets_zero():
    row = {'market_cap': 1e9, 'revenue': 5e8, 'operating_margin': 0.2, 'price_to_book': 2.0}
    assert _altman_z(row, 0) is None

def test_altman_z_computes_correctly():
    # market_cap=5B, revenue=3B, op_margin=0.25, p2b=3.0, total_assets=4B
    # book_equity = 5B/3 = 1.6667B
    # X1 = 0 (skipped)
    # X2 = 1.6667B / 4B = 0.4167
    # X3 = (0.25 * 3B) / 4B = 0.1875
    # X4 = 5B / (4B - 1.6667B) = 5B / 2.3333B = 2.1429
    # X5 = 3B / 4B = 0.75
    # Z = 0 + 1.4*0.4167 + 3.3*0.1875 + 0.6*2.1429 + 1.0*0.75
    # Z = 0.5833 + 0.6188 + 1.2857 + 0.75 = 3.2378
    row = {'market_cap': 5e9, 'revenue': 3e9, 'operating_margin': 0.25, 'price_to_book': 3.0}
    result = _altman_z(row, 4e9)
    assert result == pytest.approx(3.238, abs=0.01)

def test_altman_z_skips_x2_x4_when_price_to_book_none():
    # Only X3 + X5 contribute
    # X3 = (0.20 * 2B) / 4B = 0.10
    # X5 = 2B / 4B = 0.50
    # Z = 3.3*0.10 + 1.0*0.50 = 0.33 + 0.50 = 0.83
    row = {'market_cap': 1e9, 'revenue': 2e9, 'operating_margin': 0.20, 'price_to_book': None}
    result = _altman_z(row, 4e9)
    assert result == pytest.approx(0.83, abs=0.01)

def test_altman_z_skips_x3_when_operating_margin_none():
    # market_cap=4B, p2b=2.0, revenue=2B, total_assets=4B
    # book_equity = 4B/2 = 2B
    # X2 = 2B/4B = 0.5
    # X3 skipped (operating_margin=None)
    # X4 = 4B / (4B - 2B) = 4B/2B = 2.0
    # X5 = 2B/4B = 0.5
    # Z = 1.4*0.5 + 0 + 0.6*2.0 + 1.0*0.5 = 0.7 + 1.2 + 0.5 = 2.4
    row = {'market_cap': 4e9, 'revenue': 2e9, 'operating_margin': None, 'price_to_book': 2.0}
    result = _altman_z(row, 4e9)
    assert result == pytest.approx(2.4, abs=0.01)

def test_altman_z_returns_none_when_total_liabilities_not_positive():
    # book_equity >= total_assets → total_liabilities <= 0 → skip X4
    # market_cap=10B, p2b=1.0 → book_equity=10B > total_assets=4B
    # X2 = 10B/4B = 2.5 (still computed)
    # X4 skipped (total_liabilities <= 0)
    # X3 = (0.20*2B)/4B = 0.10
    # X5 = 2B/4B = 0.50
    # Z = 1.4*2.5 + 3.3*0.10 + 0 + 1.0*0.50 = 3.5 + 0.33 + 0.5 = 4.33
    row = {'market_cap': 10e9, 'revenue': 2e9, 'operating_margin': 0.20, 'price_to_book': 1.0}
    result = _altman_z(row, 4e9)
    assert result == pytest.approx(4.33, abs=0.01)


# ── _z_to_risk ────────────────────────────────────────────────────────────────

def test_z_to_risk_safe_zone():
    assert _z_to_risk(3.0) == 1
    assert _z_to_risk(5.0) == 1

def test_z_to_risk_distress_zone():
    assert _z_to_risk(1.0) == 10
    assert _z_to_risk(-1.0) == 10

def test_z_to_risk_midpoint():
    # z=2.0 → 1 + (3.0-2.0)*4.5 = 1 + 4.5 = 5.5 → round → 6
    assert _z_to_risk(2.0) == 6

def test_z_to_risk_grey_zone_interpolation():
    # z=2.5 → 1 + (3.0-2.5)*4.5 = 1 + 2.25 = 3.25 → round → 3
    assert _z_to_risk(2.5) == 3

def test_z_to_risk_none_input():
    assert _z_to_risk(None) is None


# ── _annualised_vol ───────────────────────────────────────────────────────────

def test_annualised_vol_empty():
    assert _annualised_vol([]) is None

def test_annualised_vol_single_price():
    assert _annualised_vol([100.0]) is None

def test_annualised_vol_flat_prices():
    # All same price → zero returns → vol = 0
    closes = [100.0] * 252
    result = _annualised_vol(closes)
    assert result == pytest.approx(0.0, abs=1e-10)

def test_annualised_vol_positive():
    # 10% daily vol annualises to ~10% * sqrt(252) ≈ 158.7%
    import random
    random.seed(42)
    closes = [100.0]
    for _ in range(251):
        closes.append(closes[-1] * (1 + random.gauss(0, 0.01)))
    result = _annualised_vol(closes)
    assert result > 0
    assert result < 2.0  # sanity bound — well under 200%


# ── _vol_to_score ─────────────────────────────────────────────────────────────

def test_vol_to_score_none():
    assert _vol_to_score(None) is None

def test_vol_to_score_very_low():
    assert _vol_to_score(0.08) == 1   # < 10%

def test_vol_to_score_boundaries():
    assert _vol_to_score(0.10) == 2   # 10-15%
    assert _vol_to_score(0.20) == 4   # 20-25%
    assert _vol_to_score(0.30) == 6   # 30-35%
    assert _vol_to_score(0.50) == 9   # 50-60%
    assert _vol_to_score(0.70) == 10  # > 60%


# ── _blend_risk ───────────────────────────────────────────────────────────────

def test_blend_risk_both_components():
    # 0.6 * 4 + 0.4 * 6 = 2.4 + 2.4 = 4.8 → round → 5
    assert _blend_risk(4, 6) == 5

def test_blend_risk_altman_only():
    assert _blend_risk(7, None) == 7

def test_blend_risk_vol_only():
    assert _blend_risk(None, 3) == 3

def test_blend_risk_both_none():
    assert _blend_risk(None, None) is None

def test_blend_risk_clamped():
    # Should stay within 1-10
    assert _blend_risk(10, 10) == 10
    assert _blend_risk(1, 1) == 1
```

- [ ] **Step 2: Run tests to verify they all fail**

```bash
cd backend && python -m pytest tests/test_risk.py -v 2>&1 | head -40
```

Expected: `ImportError` or `FAILED` — helpers don't exist yet.

- [ ] **Step 3: Add helpers to `backend/main.py` after `_quality_score`**

Add this block after the closing `return score` of `_quality_score` (around line 161):

```python
import math as _math


def _altman_z(row, total_assets):
    """Compute Altman Z-Score from a ttm_financials row + total_assets.

    X1 (working capital) is treated as 0 (conservative — unavailable from stored data).
    X2 uses book equity as a proxy for retained earnings.
    X3 uses operating income (operating_margin * revenue) as EBIT proxy.
    Returns None if insufficient data to compute any meaningful score.
    """
    if not total_assets or total_assets <= 0:
        return None

    mc       = row.get('market_cap')
    revenue  = row.get('revenue')
    op_margin = row.get('operating_margin')
    p2b      = row.get('price_to_book')

    z = 0.0
    computed_terms = 0

    # X2 = book_equity / total_assets  (proxy for retained earnings / total_assets)
    book_equity = None
    if mc and p2b and p2b > 0:
        book_equity = mc / p2b
        z += 1.4 * (book_equity / total_assets)
        computed_terms += 1

    # X3 = EBIT / total_assets  (operating income as EBIT proxy)
    if op_margin is not None and revenue:
        ebit = op_margin * revenue
        z += 3.3 * (ebit / total_assets)
        computed_terms += 1

    # X4 = market_cap / total_liabilities
    if book_equity is not None:
        total_liabilities = total_assets - book_equity
        if total_liabilities > 0:
            z += 0.6 * (mc / total_liabilities)
            computed_terms += 1

    # X5 = revenue / total_assets
    if revenue:
        z += 1.0 * (revenue / total_assets)
        computed_terms += 1

    if computed_terms == 0:
        return None

    return round(z, 3)


def _z_to_risk(z):
    """Map Altman Z to 1-10 risk component. Lower Z = higher risk.

    Z >= 3.0 → 1 (safe), Z <= 1.0 → 10 (distress), linear between.
    """
    if z is None:
        return None
    if z >= 3.0:
        return 1
    if z <= 1.0:
        return 10
    # Linear: z=3.0→1, z=1.0→10. Slope = (10-1)/(1.0-3.0) = -4.5
    return round(1 + (3.0 - z) * 4.5)


def _annualised_vol(closes):
    """Compute annualised volatility from a list of closes (oldest first).

    Returns annualised std of log returns, or None if fewer than 2 prices.
    """
    if len(closes) < 2:
        return None
    log_returns = [_math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    n = len(log_returns)
    mean = sum(log_returns) / n
    variance = sum((r - mean) ** 2 for r in log_returns) / (n - 1) if n > 1 else 0.0
    return _math.sqrt(variance) * _math.sqrt(252)


def _vol_to_score(vol):
    """Map annualised volatility to 1-10 risk score using absolute thresholds.

    Thresholds calibrated for FTSE-listed stocks (typical range 10-40% ann. vol).
    Returns None if vol is None.
    """
    if vol is None:
        return None
    thresholds = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]
    for i, t in enumerate(thresholds):
        if vol < t:
            return i + 1
    return 10


def _blend_risk(altman_component, vol_component):
    """Combine Altman (60%) and volatility (40%) components into 1-10 score.

    Falls back to whichever component is available. Returns None if both are None.
    """
    if altman_component is not None and vol_component is not None:
        return max(1, min(10, round(0.6 * altman_component + 0.4 * vol_component)))
    if altman_component is not None:
        return max(1, min(10, altman_component))
    if vol_component is not None:
        return max(1, min(10, vol_component))
    return None
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd backend && python -m pytest tests/test_risk.py -v
```

Expected: all tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
cd backend && git add main.py tests/test_risk.py && git commit -m "feat: add risk score computation helpers (_altman_z, _z_to_risk, _annualised_vol, _vol_to_score, _blend_risk)"
```

---

## Task 2: `_attach_risk_score` bulk function

**Files:**
- Modify: `backend/main.py` (add `_attach_risk_score` after `_attach_piotroski`)
- Modify: `backend/tests/test_risk.py` (add integration-style tests with mocking)

- [ ] **Step 1: Add tests for `_attach_risk_score`**

Append to `backend/tests/test_risk.py`:

```python
# ── _attach_risk_score ────────────────────────────────────────────────────────

from unittest.mock import patch


def _make_result(symbol, **kwargs):
    """Minimal screener result row."""
    defaults = {
        'symbol': symbol,
        'market_cap': 5e9,
        'revenue': 3e9,
        'operating_margin': 0.25,
        'price_to_book': 3.0,
    }
    defaults.update(kwargs)
    return defaults


def test_attach_risk_score_empty():
    from main import _attach_risk_score
    assert _attach_risk_score([]) == []


def test_attach_risk_score_attaches_fields():
    from main import _attach_risk_score
    results = [_make_result('SHEL.L')]

    ta_rows = [{'company_symbol': 'SHEL.L', 'total_assets': 4e9}]
    # 10 closes with mild upward drift — oldest first
    price_rows = [{'symbol': 'SHEL.L', 'close': 100.0 + i * 0.1} for i in range(252)]

    with patch('main.query', side_effect=[ta_rows, price_rows]):
        _attach_risk_score(results)

    r = results[0]
    assert 'risk_score' in r
    assert 'altman_z' in r
    assert 'volatility_annualised' in r
    assert r['risk_score'] is None or 1 <= r['risk_score'] <= 10


def test_attach_risk_score_null_when_no_data():
    from main import _attach_risk_score
    results = [_make_result('SHEL.L')]

    with patch('main.query', side_effect=[[], []]):
        _attach_risk_score(results)

    r = results[0]
    assert r['risk_score'] is None
    assert r['altman_z'] is None
    assert r['volatility_annualised'] is None


def test_attach_risk_score_vol_none_when_insufficient_history():
    from main import _attach_risk_score
    results = [_make_result('SHEL.L')]

    ta_rows = [{'company_symbol': 'SHEL.L', 'total_assets': 4e9}]
    # Only 10 closes — below the 63-row threshold
    price_rows = [{'symbol': 'SHEL.L', 'close': 100.0 + i} for i in range(10)]

    with patch('main.query', side_effect=[ta_rows, price_rows]):
        _attach_risk_score(results)

    r = results[0]
    assert r['volatility_annualised'] is None
    # risk_score should still be set (from Altman alone)
    assert r['risk_score'] is not None
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_risk.py::test_attach_risk_score_empty tests/test_risk.py::test_attach_risk_score_attaches_fields -v
```

Expected: `ImportError` — `_attach_risk_score` not defined yet.

- [ ] **Step 3: Add `_attach_risk_score` to `backend/main.py` after `_attach_piotroski`**

Add this function after the closing brace of `_attach_piotroski` (around line 195):

```python
def _attach_risk_score(results):
    """Add risk_score (1-10), altman_z, and volatility_annualised to each result row.

    Fetches total_assets from annual_financials and price history in two bulk queries.
    risk_score = blend of Altman Z component (60%) and volatility component (40%).
    """
    if not results:
        return results

    symbols = [r['symbol'] for r in results]

    # 1. Fetch most recent total_assets per symbol from annual_financials
    ta_rows = query("""
        WITH ranked AS (
            SELECT company_symbol, total_assets,
                   ROW_NUMBER() OVER (PARTITION BY company_symbol ORDER BY period_end_date DESC) AS rn
            FROM annual_financials
            WHERE company_symbol = ANY(%s)
        )
        SELECT company_symbol, total_assets FROM ranked WHERE rn = 1
    """, (symbols,))
    total_assets_map = {r['company_symbol']: r['total_assets'] for r in ta_rows}

    # 2. Fetch up to 252 most recent closes per symbol, oldest-first for log-return ordering
    #    rn=1 is the latest date; ORDER BY rn DESC puts oldest (largest rn) first.
    price_rows = query("""
        WITH numbered AS (
            SELECT symbol, close,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
            FROM price_history
            WHERE symbol = ANY(%s)
        )
        SELECT symbol, close
        FROM numbered
        WHERE rn <= 252
        ORDER BY symbol, rn DESC
    """, (symbols,))

    # Group closes by symbol (list is already oldest-first within each symbol)
    closes_map = {}
    for r in price_rows:
        closes_map.setdefault(r['symbol'], []).append(float(r['close']))

    # 3. Compute and attach scores
    for r in results:
        sym = r['symbol']
        ta  = total_assets_map.get(sym)

        z                = _altman_z(r, ta)
        altman_component = _z_to_risk(z)

        closes = closes_map.get(sym, [])
        vol    = _annualised_vol(closes) if len(closes) >= 63 else None
        vol_component = _vol_to_score(vol)

        r['risk_score']          = _blend_risk(altman_component, vol_component)
        r['altman_z']            = z
        r['volatility_annualised'] = round(vol * 100, 1) if vol is not None else None

    return results
```

- [ ] **Step 4: Run all risk tests**

```bash
cd backend && python -m pytest tests/test_risk.py -v
```

Expected: all tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_risk.py && git commit -m "feat: add _attach_risk_score bulk function with DB queries"
```

---

## Task 3: Wire risk score into `/api/screener`

**Files:**
- Modify: `backend/main.py` (update `screener` endpoint)

- [ ] **Step 1: Add a test for the screener endpoint returning risk fields**

Append to `backend/tests/test_risk.py`:

```python
def test_screener_includes_risk_score(client):
    from unittest.mock import patch

    screener_row = {
        'symbol': 'SHEL.L', 'name': 'Shell', 'sector': 'Energy',
        'country': 'GB', 'exchange': 'LSE', 'ftse_index': 'FTSE 100',
        'financial_currency': 'USD',
        'market_cap': 5e9, 'revenue': 3e9, 'net_income': 5e8,
        'price_to_earnings': 12.0, 'price_to_book': 3.0, 'price_to_sales': 1.0,
        'roe': 0.15, 'roa': 0.08, 'roic': 0.12, 'roce': 0.10,
        'gross_margin': 0.4, 'operating_margin': 0.25, 'net_income_margin': 0.17,
        'revenue_growth': 0.05, 'eps_diluted_growth': 0.03, 'fcf_growth': 0.04,
        'debt_to_equity': 0.5, 'current_ratio': 1.5, 'fcf': 4e8, 'ebitda': 9e8,
        'revenue_cagr_10': 0.06, 'eps_cagr_10': 0.05, 'period_end_date': '2024-12-31',
        'fcf_margin': 0.13,
        'gross_margin_median': 0.38, 'operating_margin_median': 0.23,
        'net_margin_median': 0.15, 'roe_median': 0.14, 'roic_median': 0.11,
    }
    piotroski_row = {
        'company_symbol': 'SHEL.L',
        'roa_cur': 0.08, 'roa_prev': 0.07, 'cf_cfo': 4e8,
        'ta_cur': 4e9, 'ta_prev': 3.8e9,
        'de_cur': 0.5, 'de_prev': 0.6,
        'cr_cur': 1.5, 'cr_prev': 1.4,
        'sh_cur': 1e9, 'sh_prev': 1e9,
        'gm_cur': 0.4, 'gm_prev': 0.38,
        'rev_cur': 3e9, 'rev_prev': 2.8e9,
    }
    ta_row = [{'company_symbol': 'SHEL.L', 'total_assets': 4e9}]
    price_rows = [{'symbol': 'SHEL.L', 'close': 100.0 + i * 0.05} for i in range(252)]

    with patch('main.query', side_effect=[
        [screener_row],   # screener SQL
        [piotroski_row],  # _attach_piotroski annual_financials
        ta_row,           # _attach_risk_score total_assets
        price_rows,       # _attach_risk_score price_history
    ]):
        with patch('prices.query', return_value=[]):  # _attach_momentum
            r = client.get('/api/screener')

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert 'risk_score' in data[0]
    assert 'altman_z' in data[0]
    assert 'volatility_annualised' in data[0]
```

- [ ] **Step 2: Run the new test to verify it fails**

```bash
cd backend && python -m pytest tests/test_risk.py::test_screener_includes_risk_score -v
```

Expected: `FAILED` — `risk_score` key missing from response.

- [ ] **Step 3: Update `screener` endpoint in `backend/main.py`**

Find the end of the `screener` function (around line 247):

```python
    results = query(sql, params)
    for r in results:
        r['quality_score'] = _quality_score(r)
    _attach_momentum(results)
    return _attach_piotroski(results)
```

Replace with:

```python
    results = query(sql, params)
    for r in results:
        r['quality_score'] = _quality_score(r)
    _attach_momentum(results)
    _attach_piotroski(results)
    return _attach_risk_score(results)
```

- [ ] **Step 4: Run the test**

```bash
cd backend && python -m pytest tests/test_risk.py::test_screener_includes_risk_score -v
```

Expected: `PASSED`.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd backend && python -m pytest -v
```

Expected: all tests `PASSED`.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_risk.py && git commit -m "feat: attach risk_score to /api/screener results"
```

---

## Task 4: Add risk fields to `/api/snapshot`

**Files:**
- Modify: `backend/main.py` (update `snapshot` endpoint)

The snapshot endpoint returns raw `ttm_financials` rows where the company identifier key is `company_symbol`, not `symbol`. `_attach_risk_score` expects `symbol`. We normalise by aliasing before calling.

- [ ] **Step 1: Add a snapshot test**

Append to `backend/tests/test_risk.py`:

```python
def test_snapshot_includes_risk_fields(client):
    snap_row = {
        'company_symbol': 'SHEL.L',
        'market_cap': 5e9, 'revenue': 3e9, 'net_income': 5e8,
        'price_to_earnings': 12.0, 'price_to_book': 3.0, 'price_to_sales': 1.0,
        'roe': 0.15, 'roa': 0.08, 'roic': 0.12, 'roce': 0.10,
        'gross_margin': 0.4, 'operating_margin': 0.25, 'net_income_margin': 0.17,
        'revenue_growth': 0.05, 'eps_diluted_growth': 0.03, 'fcf_growth': 0.04,
        'debt_to_equity': 0.5, 'current_ratio': 1.5, 'fcf': 4e8, 'ebitda': 9e8,
        'revenue_cagr_10': 0.06, 'eps_cagr_10': 0.05, 'period_end_date': '2024-12-31',
        'fcf_margin': 0.13,
        'gross_margin_median': 0.38, 'operating_margin_median': 0.23,
        'net_margin_median': 0.15, 'roe_median': 0.14, 'roic_median': 0.11,
        'debt_to_assets': 0.3, 'cash_and_equiv': 2e8, 'net_debt': 5e8,
        'working_capital': 3e8, 'interest_coverage': 8.0, 'book_value': 1.5e9,
        'net_income_growth': 0.06, 'fcf_cagr_10': 0.05, 'equity_cagr_10': 0.04,
    }
    ta_row = [{'company_symbol': 'SHEL.L', 'total_assets': 4e9}]
    price_rows = [{'symbol': 'SHEL.L', 'close': 100.0 + i * 0.05} for i in range(252)]

    with patch('main.query', side_effect=[
        [snap_row],   # SELECT * FROM ttm_financials
        ta_row,       # _attach_risk_score total_assets
        price_rows,   # _attach_risk_score price_history
    ]):
        r = client.get('/api/snapshot?symbol=SHEL.L')

    assert r.status_code == 200
    data = r.json()
    assert 'risk_score' in data
    assert 'altman_z' in data
    assert 'volatility_annualised' in data
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_risk.py::test_snapshot_includes_risk_fields -v
```

Expected: `FAILED` — risk fields missing.

- [ ] **Step 3: Update the `snapshot` endpoint in `backend/main.py`**

Find the current snapshot function (around line 76):

```python
@app.get("/api/snapshot")
def snapshot(symbol: str = Query(...)):
    rows = query("SELECT * FROM ttm_financials WHERE company_symbol = %s", (symbol,))
    if not rows: raise HTTPException(404, "No data")
    return rows[0]
```

Replace with:

```python
@app.get("/api/snapshot")
def snapshot(symbol: str = Query(...)):
    rows = query("SELECT * FROM ttm_financials WHERE company_symbol = %s", (symbol,))
    if not rows: raise HTTPException(404, "No data")
    row = rows[0]
    # _attach_risk_score expects a 'symbol' key (screener convention)
    row['symbol'] = symbol
    _attach_risk_score([row])
    row.pop('symbol', None)
    return row
```

- [ ] **Step 4: Run all tests**

```bash
cd backend && python -m pytest -v
```

Expected: all tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_risk.py && git commit -m "feat: add risk_score, altman_z, volatility_annualised to /api/snapshot"
```

---

## Task 5: Frontend — Risk column in screener table

**Files:**
- Modify: `frontend/src/App.js`

- [ ] **Step 1: Add Risk column header**

Find the screener table header in `App.js` (around line 550):

```javascript
{[['Symbol',false],['Name',false],['Sector',false],['Index',false],['Mkt Cap',true],['P/E',true],['P/B',true],['ROE',true],['Rev Growth',true],['D/E',true],['Momentum',true],['Quality',true],['Value',true]].map(([h,num])=>(
```

Replace with:

```javascript
{[['Symbol',false],['Name',false],['Sector',false],['Index',false],['Mkt Cap',true],['P/E',true],['P/B',true],['ROE',true],['Rev Growth',true],['D/E',true],['Momentum',true],['Quality',true],['Value',true],['Risk',true]].map(([h,num])=>(
```

- [ ] **Step 2: Add Risk cell after the Piotroski cell**

Find the Piotroski table cell (around line 588):

```javascript
                  <td style={{ ...S.tdNum,
                    color: r.piotroski_score == null ? '#444'
                         : r.piotroski_score >= 7   ? '#10b981'
                         : r.piotroski_score >= 4   ? '#f59e0b'
                         :                            '#ef4444',
                    fontWeight: 700,
                  }}>{r.piotroski_score ?? '—'}</td>
                </tr>
```

Replace with:

```javascript
                  <td style={{ ...S.tdNum,
                    color: r.piotroski_score == null ? '#444'
                         : r.piotroski_score >= 7   ? '#10b981'
                         : r.piotroski_score >= 4   ? '#f59e0b'
                         :                            '#ef4444',
                    fontWeight: 700,
                  }}>{r.piotroski_score ?? '—'}</td>
                  <td style={{ ...S.tdNum }}>
                    {r.risk_score == null ? <span style={{ color:'#444' }}>—</span> : (
                      <span style={{
                        display: 'inline-block',
                        padding: '1px 7px',
                        borderRadius: 4,
                        fontWeight: 700,
                        fontSize: 12,
                        background: r.risk_score <= 3 ? '#14532d'
                                  : r.risk_score <= 6 ? '#78350f'
                                  :                    '#7f1d1d',
                        color:      r.risk_score <= 3 ? '#4ade80'
                                  : r.risk_score <= 6 ? '#fbbf24'
                                  :                    '#f87171',
                      }}>{r.risk_score}</span>
                    )}
                  </td>
                </tr>
```

- [ ] **Step 3: Start the frontend dev server and verify the Risk column appears**

```bash
cd frontend && npm start
```

Open the screener. The table should now have a "Risk" column as the last column showing colour-coded numbers (green 1-3, amber 4-6, red 7-10) or `—` for stocks with no data.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.js && git commit -m "feat: add Risk column to screener table"
```

---

## Task 6: Frontend — Risk card in Health tab

**Files:**
- Modify: `frontend/src/App.js`

- [ ] **Step 1: Add the Risk card at the top of the Health tab**

Find the Health tab opening in `App.js` (around line 274):

```javascript
      {/* HEALTH */}
      {tab==='health' && (
        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(145px,1fr))', gap:10 }}>
```

Replace with:

```javascript
      {/* HEALTH */}
      {tab==='health' && (
        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
          {/* Risk Score card */}
          <div style={{ background:'#141414', borderRadius:2, padding:'18px 22px', border:'1px solid #2a2a2a', display:'flex', alignItems:'center', gap:24 }}>
            <div>
              <div style={{ fontSize:10, color:'#666', marginBottom:8, textTransform:'uppercase', letterSpacing:1, fontFamily:'monospace' }}>Risk Score</div>
              {snap.risk_score == null ? (
                <span style={{ fontSize:28, fontFamily:'monospace', fontWeight:700, color:'#444' }}>—</span>
              ) : (
                <span style={{
                  display: 'inline-block',
                  padding: '4px 14px',
                  borderRadius: 6,
                  fontSize: 28,
                  fontFamily: 'monospace',
                  fontWeight: 700,
                  background: snap.risk_score <= 3 ? '#14532d'
                            : snap.risk_score <= 6 ? '#78350f'
                            :                       '#7f1d1d',
                  color:      snap.risk_score <= 3 ? '#4ade80'
                            : snap.risk_score <= 6 ? '#fbbf24'
                            :                       '#f87171',
                }}>{snap.risk_score}</span>
              )}
            </div>
            <div style={{ display:'flex', flexDirection:'column', gap:6, color:'#888', fontSize:12, fontFamily:'monospace' }}>
              <span>Altman Z: {snap.altman_z != null ? snap.altman_z.toFixed(2) : '—'}</span>
              <span>Volatility: {snap.volatility_annualised != null ? `${snap.volatility_annualised}% ann.` : '—'}</span>
              <span style={{ color:'#555', fontSize:11, marginTop:2 }}>Z &gt; 3.0 safe · 1.8–3.0 grey · &lt; 1.8 distress</span>
            </div>
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(145px,1fr))', gap:10 }}>
```

- [ ] **Step 2: Verify in the browser**

Navigate to any company detail → Health tab. The Risk Score card should appear at the top of the tab showing:
- A large colour-coded number badge
- Altman Z and Volatility values alongside
- The zone legend

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.js && git commit -m "feat: add Risk Score card to Health tab"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Altman Z-Score computation (X1 treated as 0, X2-X5 with proxies)
- ✅ 252-day annualised volatility from price_history
- ✅ 60/40 blend into 1–10 score
- ✅ Colour bands: green 1-3, amber 4-6, red 7-10
- ✅ Screener table column (Task 5)
- ✅ Health tab card with sub-components (Task 6)
- ✅ Graceful degradation: null data, insufficient history, zero total_assets, null price_to_book
- ✅ Both `altman_z` and `volatility_annualised` returned as raw values for detail display
- ✅ No new files beyond test file — follows existing patterns

**Type consistency:** `_altman_z` returns float|None, consumed by `_z_to_risk` → int|None, consumed by `_blend_risk`. `_annualised_vol` returns float|None, consumed by `_vol_to_score` → int|None. All consistent throughout.
