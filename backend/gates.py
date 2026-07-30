"""The gate registry — one ordered list of named, testable Python predicates
that decide whether a ranked RNS candidate may be flagged to the public
High Impact showcase. See docs/rns-gate-block-plan.md.

Each gate reads fields the LLM ranker already wrote (guidance_checks,
earnings_quality, llm_sentiment/llm_thesis/category) and returns one of three
states — never a bare bool, because "this gate found nothing wrong" and "this
gate could not be evaluated" are different facts and collapsing them is what
made the guidance gate's ~91% no-consensus rate invisible before this existed:

    pass   — adjudicated, nothing wrong
    block  — adjudicated, disqualifying
    n/a    — could not adjudicate (wrong sector, field absent, unparseable,
             missing period, or the gate itself raised)

Gate logic is NOT reimplemented here — _sentiment / _disqualifying_guidance /
_worsening_loss_rate stay exactly as showcase.py's own tests exercise them.
This module only classifies WHY a non-block outcome happened, and wraps the
whole thing in try/except so a bug in a gate degrades to n/a rather than
propagating: dropping a tradeable announcement is the high-severity error in
this system, never a false green light.

evaluate_all() runs every gate regardless of outcome, for the /gates page.
blocking_reason() stops at the first ARMED block, for flag_high_impact_candidates.
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

from fastapi import APIRouter, Depends
from psycopg2.extras import Json

from admin_auth import require_admin_token

router = APIRouter(prefix="/api/gates", tags=["gates"])

GateState = Literal["pass", "block", "n/a"]


@dataclass(frozen=True)
class GateResult:
    state: GateState
    reason: Optional[str] = None      # why n/a, or which rule fired on a block
    evidence: Optional[dict] = None   # the entry/figures the verdict rests on


@dataclass(frozen=True)
class Gate:
    name: str                         # stable slug — stored, never renamed
    description: str
    mode: Literal["armed", "shadow"]
    fn: Callable[[dict], GateResult]

    def evaluate(self, cand: dict) -> GateResult:
        try:
            return self.fn(cand)
        except Exception as e:
            # Over-blocking is the high-severity error here — a gate that
            # raises must fail OPEN (n/a), never propagate and never block.
            return GateResult(
                state="n/a", reason="gate_error",
                evidence={"error": f"{type(e).__name__}: {e}"},
            )


# ── Gate: sentiment ───────────────────────────────────────────────────────────
# Never n/a — _sentiment always resolves to positive/negative/neutral (it falls
# back to a keyword scan, then defaults neutral). Anything but positive blocks.
def _gate_sentiment(cand: dict) -> GateResult:
    from showcase import _sentiment

    sent = _sentiment(cand)
    if sent != "positive":
        return GateResult(state="block", reason=sent, evidence={"sentiment": sent})
    return GateResult(state="pass", evidence={"sentiment": sent})


# ── Gate: guidance ─────────────────────────────────────────────────────────────
# See showcase._disqualifying_guidance for the LUCE case this exists to catch.
def _gate_guidance(cand: dict) -> GateResult:
    from showcase import _disqualifying_guidance

    checks = cand.get("guidance_checks")
    if not isinstance(checks, list) or not any(isinstance(e, dict) for e in checks):
        return GateResult(state="n/a", reason="field_absent")

    hit = _disqualifying_guidance(cand)
    if hit:
        return GateResult(
            state="block",
            reason=f"{hit.get('vs_prior')}_vs_consensus_{hit.get('vs_consensus')}",
            evidence=hit,
        )

    # Adjudicable means at least one entry printed a consensus figure this
    # gate could compare against — the common case (no consensus footnote at
    # all) is the ~91% amber rate the plan measured, not a pass.
    adjudicable = any(
        isinstance(e, dict) and e.get("vs_consensus") not in (None, "no_consensus_stated")
        for e in checks
    )
    if adjudicable:
        return GateResult(state="pass", evidence={"n_entries": len(checks)})
    return GateResult(state="n/a", reason="no_consensus_stated")


# ── Gate: earnings_quality (bank loan-loss rate) ───────────────────────────────
# See showcase._worsening_loss_rate for the BARC case this exists to catch.
def _gate_earnings_quality(cand: dict) -> GateResult:
    from showcase import _worsening_loss_rate, _parse_bps
    from quality import classify_risk_model

    # unknown_is_trust=False: company_metadata is a LEFT JOIN here too, so an
    # absent sector/industry means out-of-universe, not a closed-end fund —
    # same reasoning as showcase._worsening_loss_rate itself.
    if classify_risk_model(cand, unknown_is_trust=False) != "bank":
        return GateResult(state="n/a", reason="not_a_bank")

    entries = cand.get("earnings_quality")
    if not isinstance(entries, list) or not entries:
        return GateResult(state="n/a", reason="field_absent")

    hit = _worsening_loss_rate(cand)
    if hit:
        return GateResult(state="block", reason="loan_loss_rate_rise", evidence=hit)

    # None disqualified — but distinguish "read every cost_or_charge line and
    # none had risen" (pass) from "nothing here was actually readable" (n/a),
    # using the exact fields _worsening_loss_rate itself requires to adjudicate
    # a line: a 'cost_or_charge' kind, a non-blank period, and both figures
    # parseable as bps.
    reason = "field_absent"
    for e in entries:
        if not isinstance(e, dict) or e.get("kind") != "cost_or_charge":
            continue
        if reason == "field_absent":
            reason = "unparseable_value"  # at least one candidate line exists
        if not str(e.get("period") or "").strip():
            reason = "missing_period"
            continue
        if _parse_bps(e.get("value")) is None or _parse_bps(e.get("prior_value")) is None:
            continue
        return GateResult(state="pass", evidence={"n_entries": len(entries)})
    return GateResult(state="n/a", reason=reason)


# ── Gate: low_base (shadow) ─────────────────────────────────────────────────
# Phase 4 of docs/rns-gate-block-plan.md. The vet's four audited numeric
# errors (CAPD, SRT, STAN, JNEO — plan §1) all sat in the same step: a
# sequential comparison the model was asked to derive itself. This gate takes
# that arithmetic out of the model's hands — showcase._parse_low_base only
# ever copies figures verbatim (current_value, preceding_period_value,
# prior_year_value/growth) — and does the comparison here, in Python.
#
# Shadow: evaluated and recorded on every vetted candidate, blocks nothing.
# Per the plan's Phase 5, arming needs the four audited rows checked as a
# NEGATIVE control (must not block) and PTEC.L 9659657 as the positive
# control — that check runs through rns_body_context_validation.py over the
# stored bodies, not unit fixtures, and is a Phase 5 prerequisite, not done
# here.
_LOW_BASE_HALVES = ("H1", "H2")
_LOW_BASE_PERIODS = ("H1", "H2", "Q1", "Q2", "Q3", "Q4")
_LOW_BASE_METRICS = ("revenue", "operating_income", "net_income")


def _low_base_fy_figure(symbol: Optional[str], metric: str) -> Optional[float]:
    """The most recently reported COMPLETE fiscal year's value for `metric`.

    An interim announcement's prior-year comparator period (e.g. "H1 2025")
    belongs to the fiscal year immediately before the one in progress — which
    is, by construction, the latest year annual_financials has on file: the
    year containing the current period hasn't closed yet, so it can't be
    there instead.
    """
    from showcase import _annual_history

    hist = _annual_history(symbol)  # oldest first
    if not hist:
        return None
    v = hist[-1].get(metric)
    return float(v) if v is not None else None


def _gate_low_base(cand: dict) -> GateResult:
    from showcase import _parse_money

    lb = cand.get("low_base")
    if not isinstance(lb, dict):
        return GateResult(state="n/a", reason="not_vetted")

    period = str(lb.get("period") or "").strip().upper()
    if period not in _LOW_BASE_PERIODS:
        return GateResult(state="n/a", reason="missing_period")

    current = _parse_money(lb.get("current_value"))
    if current is None:
        return GateResult(state="n/a", reason="unparseable_value")

    # Route 1 — the announcement prints the immediately preceding same-length
    # period directly (CAPD's Q1'26 next to Q2'26). No divisor, no
    # derivation, the safest comparison available — prefer it whenever it's
    # there. This is the fix for the CAPD.L defect: the original vet divided
    # an FY total by 2 and called the result a "quarterly run-rate" when the
    # announcement already printed the true sequential quarters.
    preceding = _parse_money(lb.get("preceding_period_value"))
    basis = "printed_preceding_period"

    if preceding is None:
        # Route 2 — derive the preceding HALF as FY total minus the
        # prior-year SAME half, valid only for halves: H1 + H2 = FY for the
        # prior fiscal year, so FY - H1(prior year) = H2(prior year) = the
        # half immediately preceding this one. There is no equivalent
        # identity for quarters without the other three quarters, which
        # quarterly_financials cannot supply for ~95% of the universe (plan
        # §Phase 4 data-source audit) — so a quarter with nothing printed
        # directly is n/a, never a divide-by-4 guess.
        if period not in _LOW_BASE_HALVES:
            return GateResult(state="n/a", reason="quarter_unsupported")

        prior = _parse_money(lb.get("prior_year_value"))
        if prior is None:
            growth = lb.get("prior_year_growth_pct")
            if isinstance(growth, (int, float)) and growth > -100:
                prior = current / (1 + growth / 100.0)
        if prior is None:
            return GateResult(state="n/a", reason="no_period_split")

        metric = str(lb.get("metric") or "").strip().lower()
        if metric not in _LOW_BASE_METRICS:
            return GateResult(state="n/a", reason="metric_unmapped")

        fy_total = _low_base_fy_figure(cand.get("symbol"), metric)
        if fy_total is None:
            return GateResult(state="n/a", reason="no_annual_history")

        preceding = fy_total - prior
        basis = "derived_from_fy_total"

    if not preceding:
        return GateResult(state="n/a", reason="unparseable_value")

    delta_pct = round((current / preceding - 1) * 100, 1)
    evidence = {
        "period": period, "current_value": current,
        "preceding_value": round(preceding, 1), "delta_pct": delta_pct,
        "basis": basis,
    }

    # Guardrail 3 (STAN/JNEO) — the model's own direction claim, checked
    # mechanically against the sign Python just computed, field to field —
    # never by re-reading prose. A disagreement doesn't change the gate's
    # state (the Python figure is authoritative either way) but is worth
    # surfacing: it is exactly the failure mode that ran undetected for a
    # fortnight before the audit that started Phase 4.
    computed_direction = "above" if delta_pct > 1 else "below" if delta_pct < -1 else "in_line"
    model_direction = str(lb.get("direction") or "").strip().lower()
    if model_direction in ("above", "below", "in_line") and model_direction != computed_direction:
        evidence["model_direction_mismatch"] = {"model": model_direction, "computed": computed_direction}

    if delta_pct < 0:
        return GateResult(state="block", reason="below_preceding_period", evidence=evidence)
    return GateResult(state="pass", evidence=evidence)


GATES: tuple[Gate, ...] = (
    Gate("sentiment", "Announcement direction must read positive.", "armed", _gate_sentiment),
    Gate("guidance", "Guidance not raised against a printed consensus it fails to clear.", "armed", _gate_guidance),
    Gate("earnings_quality", "Bank loan-loss rate must not be rising.", "armed", _gate_earnings_quality),
    Gate("low_base", "Headline growth vs the immediately preceding period, not just the prior-year comparator.", "shadow", _gate_low_base),
)


def evaluate_all(cand: dict) -> list[tuple[Gate, GateResult]]:
    """Run every gate regardless of outcome — the /gates page needs the full
    row, not just the first failure."""
    return [(g, g.evaluate(cand)) for g in GATES]


def blocking_reason(cand: dict) -> Optional[tuple[Gate, GateResult]]:
    """First ARMED gate that blocks this candidate, else None. Stops at the
    first block (same short-circuit order as the pre-registry code — sentiment
    before guidance before earnings_quality — so a disqualified row still costs
    no LLM vet call)."""
    for g in GATES:
        if g.mode != "armed":
            continue
        r = g.evaluate(cand)
        if r.state == "block":
            return g, r
    return None


# ── DB helpers ────────────────────────────────────────────────────────────────
def _q(sql, params=None) -> list[dict]:
    from main import query
    return query(sql, params)


def _exec(sql, params=None) -> int:
    from main import get_pool
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.rowcount
    finally:
        pool.putconn(conn)


# ── Recording ─────────────────────────────────────────────────────────────────
# "Evaluate wide, block narrow" (plan section 2.4): gates over guidance_checks
# and earnings_quality are pure functions over stored JSONB with no LLM cost, so
# this runs over EVERY ranked Tier A/B row — no score floor, no leverage/margin/
# market-cap floor. Those only gate the public flag (flag_high_impact_candidates
# still applies them via its own SELECT). A score floor here would only shrink
# the calibration sample: on the one day measured, a score>=75 cohort saw 2 of
# 19 adjudicable rows, a tenth of what the wide pool sees.
_EVAL_SQL = """
    SELECT r.id, r.symbol, r.category, r.llm_score,
           r.llm_sentiment, r.llm_thesis, r.keyword_hits,
           r.guidance_checks, r.earnings_quality,
           m.sector, m.industry
    FROM rns_announcements r
    LEFT JOIN company_metadata m ON m.symbol = r.symbol
    WHERE r.symbol IS NOT NULL
      AND r.llm_processed_at IS NOT NULL
      AND r.tier IN ('A', 'B')
      AND r.published_at >= NOW() - (%s || ' hours')::interval
"""


def _upsert_evaluation(rns_id, gate: Gate, result: GateResult) -> int:
    return _exec(
        """
        INSERT INTO rns_gate_evaluations
            (rns_id, gate, state, reason, evidence, mode, evaluated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (rns_id, gate) DO UPDATE SET
            state = EXCLUDED.state, reason = EXCLUDED.reason,
            evidence = EXCLUDED.evidence, mode = EXCLUDED.mode,
            evaluated_at = EXCLUDED.evaluated_at
        """,
        (
            rns_id, gate.name, result.state, result.reason,
            Json(result.evidence) if result.evidence is not None else None,
            gate.mode, datetime.now(timezone.utc),
        ),
    )


def record_gate_evaluations(hours: int = 48) -> dict:
    """Run every gate over every ranked Tier A/B row from the last `hours` and
    upsert one row per (rns_id, gate) into rns_gate_evaluations. Idempotent —
    a re-run (or the morning cron re-covering an overlapping window) just
    refreshes the same rows. Returns a counts dict for cron logs.

    low_base always comes back n/a/not_vetted here — this sweep's rows never
    carry a `low_base` key (see record_low_base_evaluation)."""
    rows = _q(_EVAL_SQL, (hours,))
    written = 0
    for row in rows:
        for gate, result in evaluate_all(row):
            written += _upsert_evaluation(row["id"], gate, result)
    return {"candidates": len(rows), "gate_rows_written": written}


def record_low_base_evaluation(rns_id: int, cand: dict) -> int:
    """Evaluate + upsert just the low_base gate for one freshly-vetted
    candidate. Separate from record_gate_evaluations (the wide sweep) because
    this gate needs the vet's structured low_base output, which only exists
    for rows that reached the LLM vet inside
    showcase.flag_high_impact_candidates — the plan's Phase 4 note that this
    gate "cannot be backfilled and its evaluation pool is the vet's pool, not
    the wide one." `cand` must carry the candidate's own fields plus a
    `low_base` key (showcase._parse_low_base's output, or None on a vet
    failure)."""
    gate = next(g for g in GATES if g.name == "low_base")
    result = gate.evaluate(cand)
    return _upsert_evaluation(rns_id, gate, result)


# ── Returns — a separate consumer of rns_score_perf.py's conventions ──────────
# Entry = the OPEN on the announcement day itself (RNS drops ~07:00, before the
# 08:00 LSE open); horizon = trading days from entry to close (1d = the entry
# day's own close, i.e. open->close intraday; 1w = the 5th trading day's
# close); excess = raw return minus an equal-weighted AIM/Main benchmark.
# rns_score_perf.py stays read-only and untouched — this is a fresh, smaller
# implementation sized for a matrix of tens-to-hundreds of rows per request,
# not its multi-year workbook. The benchmark here is a direct two-date
# equal-weighted average (not a compounded daily index) — equivalent for a
# single-period return and far cheaper at this call scale.
def _seg(ftse_index) -> str:
    return "AIM" if (ftse_index or "").upper().find("AIM") >= 0 else "Main"


def _benchmark_return_cache():
    cache: dict = {}

    def get(seg: str, entry_date, exit_date) -> Optional[float]:
        key = (seg, entry_date, exit_date)
        if key in cache:
            return cache[key]
        rows = _q(
            """
            SELECT AVG(p2.close / NULLIF(p1.close, 0) - 1) AS ret
            FROM price_history p1
            JOIN price_history p2 ON p2.symbol = p1.symbol AND p2.date = %s
            JOIN company_metadata m ON m.symbol = p1.symbol AND m.is_active
            WHERE p1.date = %s
              AND (CASE WHEN COALESCE(m.ftse_index,'') ILIKE '%%AIM%%'
                        THEN 'AIM' ELSE 'Main' END) = %s
            """,
            (exit_date, entry_date, seg),
        )
        val = float(rows[0]["ret"]) if rows and rows[0]["ret"] is not None else None
        cache[key] = val
        return val

    return get


# A horizon that can't fill because the symbol has stopped updating (>30
# calendar days since the announcement with still no bar) reads 'terminated'
# rather than 'open' — a lighter version of rns_score_perf's stale-price check,
# adequate at this page's freshness (days, not years).
_TERMINATED_AFTER_DAYS = 30


def _row_returns(symbol: str, published_at, ftse_index: Optional[str], bench_get) -> dict:
    prices = _q(
        """
        SELECT date, open, close FROM price_history
        WHERE symbol = %s
          AND date BETWEEN %s::date - INTERVAL '5 days' AND %s::date + INTERVAL '16 days'
        ORDER BY date
        """,
        (symbol, published_at, published_at),
    )
    out = {
        "gap": None,
        "pct_1d": None, "excess_1d": None, "status_1d": "open",
        "pct_1w": None, "excess_1w": None, "status_1w": "open",
    }
    pub_date = published_at.date() if hasattr(published_at, "date") else published_at
    age_days = (datetime.now(timezone.utc).date() - pub_date).days
    stale = "terminated" if age_days > _TERMINATED_AFTER_DAYS else "open"
    out["status_1d"] = out["status_1w"] = stale
    if not prices:
        return out

    after = [p for p in prices if p["date"] >= pub_date]
    before = [p for p in prices if p["date"] < pub_date]
    if not after or after[0]["open"] is None:
        return out

    entry = after[0]
    entry_open = float(entry["open"])
    pre_close = float(before[-1]["close"]) if before and before[-1]["close"] is not None else None
    if pre_close:
        out["gap"] = round((entry_open / pre_close - 1) * 100, 2)

    seg = _seg(ftse_index)
    for hname, idx in (("1d", 0), ("1w", 4)):
        if idx >= len(after) or after[idx]["close"] is None:
            continue  # stays 'open'/'terminated' as set above
        exit_row = after[idx]
        exit_close = float(exit_row["close"])
        raw = exit_close / entry_open - 1
        br = bench_get(seg, entry["date"], exit_row["date"])
        out[f"pct_{hname}"] = round(raw * 100, 2)
        out[f"excess_{hname}"] = round((raw - br) * 100, 2) if br is not None else None
        out[f"status_{hname}"] = "matured"
    return out


# ── /gates page endpoint ────────────────────────────────────────────────────────
_MATRIX_SQL = """
    SELECT r.id AS rns_id, r.symbol, r.company_name, r.headline, r.url, r.category,
           r.published_at, r.llm_score, r.llm_sentiment, r.llm_action,
           m.sector, m.industry, m.ftse_index,
           t.market_cap, t.net_debt, t.ebitda, t.net_income_margin, t.roce,
           pm.margin_median,
           h.vet_verdict, h.vet_rationale
    FROM rns_announcements r
    LEFT JOIN company_metadata m ON m.symbol = r.symbol
    LEFT JOIN LATERAL (
        SELECT market_cap, net_debt, ebitda, net_income_margin, roce FROM ttm_financials
        WHERE company_symbol = r.symbol
        ORDER BY period_end_date DESC NULLS LAST LIMIT 1
    ) t ON TRUE
    -- Same industry-peer margin median the public flag's quality floor uses
    -- (showcase.py flag_high_impact_candidates) — kept in sync with it.
    LEFT JOIN LATERAL (
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY t2.net_income_margin)
                   AS margin_median
        FROM ttm_financials t2
        JOIN company_metadata m2 ON m2.symbol = t2.company_symbol
        WHERE m2.industry = m.industry
          AND t2.net_income_margin IS NOT NULL
        HAVING COUNT(*) >= {peer_min_group}
    ) pm ON TRUE
    -- Display-only: the vet only ever runs on rows that already cleared every
    -- gate AND the public flag's own floors (score/leverage/margin/market-cap),
    -- so this is null for the vast majority of the wider /gates cohort.
    LEFT JOIN high_impact_rns h ON h.rns_id = r.id
    WHERE {where}
    ORDER BY r.published_at DESC
"""


# ── Public-flag floor diagnostics (display-only) ────────────────────────────────
# Mirrors the non-gate eligibility floors in showcase.flag_high_impact_candidates
# — score, action, category, hours-window, market cap, leverage, quality margin,
# and the 30-day per-symbol dedupe — so a row that never reached the LLM vet (no
# gate blocked it either) shows WHY. Only meaningful when vet_verdict is NULL;
# a row that already has a verdict cleared all of these by definition.
_FLOOR_LABEL = {
    "score": "llm_score below the flag threshold",
    "action": "llm_action not in (watch, research)",
    "category": "category not in the High Impact category list",
    "mkt_cap": "market cap below the £50m floor (or missing)",
    "leverage": "net debt > 3x EBITDA (or unprofitable with debt, or debt > market cap)",
    "margin": "net income margin below the industry-peer floor (no ROCE escape)",
    "dedup": "same symbol already flagged in the last 30 days",
}


def _public_flag_fails(row: dict, recently_flagged: set) -> list[str]:
    from showcase import (
        HIGH_IMPACT_MIN_LLM_SCORE, HIGH_IMPACT_CATEGORIES, HIGH_IMPACT_MIN_MARKET_CAP,
        HIGH_IMPACT_MAX_NET_DEBT_TO_EBITDA, HIGH_IMPACT_MIN_NET_MARGIN, HIGH_IMPACT_MIN_ROCE,
    )

    def _f(key):
        v = row.get(key)
        return float(v) if v is not None else None

    fails = []
    score = row.get("llm_score")
    if score is None or score < HIGH_IMPACT_MIN_LLM_SCORE:
        fails.append("score")
    if row.get("llm_action") not in ("watch", "research"):
        fails.append("action")
    if row.get("category") not in HIGH_IMPACT_CATEGORIES:
        fails.append("category")

    mkt_cap = _f("market_cap")
    if mkt_cap is None or mkt_cap < HIGH_IMPACT_MIN_MARKET_CAP:
        fails.append("mkt_cap")

    net_debt, ebitda = _f("net_debt"), _f("ebitda")
    if net_debt is not None and (
        (ebitda is not None and ebitda > 0 and net_debt > HIGH_IMPACT_MAX_NET_DEBT_TO_EBITDA * ebitda)
        or (ebitda is not None and ebitda <= 0 and net_debt > 0)
        or (mkt_cap is not None and net_debt > mkt_cap)
    ):
        fails.append("leverage")

    margin, roce = _f("net_income_margin"), _f("roce")
    if margin is not None:
        peer_median = _f("margin_median")
        floor = max(0.0, peer_median if peer_median is not None else HIGH_IMPACT_MIN_NET_MARGIN)
        if margin < floor and not (margin > 0 and (roce or 0.0) >= HIGH_IMPACT_MIN_ROCE):
            fails.append("margin")

    if row["symbol"] in recently_flagged:
        fails.append("dedup")

    return fails


_LATEST_SESSION_CLAUSE = """
    r.published_at::date = (
        SELECT MAX(published_at::date) FROM rns_announcements
        WHERE symbol IS NOT NULL AND llm_processed_at IS NOT NULL
          AND tier IN ('A', 'B') AND published_at >= NOW() - INTERVAL '14 days'
    )
"""


@router.get("", dependencies=[Depends(require_admin_token)])
def list_matrix(window: str = "latest", cohort: str = "category", show_all: bool = False):
    """The gate matrix: one row per candidate (newest first), one column per
    gate, plus 1d/1w returns and a per-gate header (fire rate, amber rate,
    blocked-vs-passed excess). Private — see /gates in the frontend.

    window: latest (most recent ranked session) | 7d | 30d
    cohort: all (every ranked Tier A/B row) | in_universe (has ttm_financials)
            | category (in_universe + a High Impact category — default; every
            gate has what it needs below this line, see the plan doc)
    show_all: include rows where every gate came back n/a (default False —
              most rows on a quiet day carry nothing for any gate to judge,
              and a page that's mostly blank teaches you to stop opening it)
    """
    from showcase import HIGH_IMPACT_CATEGORIES, HIGH_IMPACT_DEDUPE_DAYS, PEER_MARGIN_MIN_GROUP

    where = ["r.symbol IS NOT NULL", "r.llm_processed_at IS NOT NULL", "r.tier IN ('A','B')"]
    if window == "7d":
        where.append("r.published_at >= NOW() - INTERVAL '7 days'")
    elif window == "30d":
        where.append("r.published_at >= NOW() - INTERVAL '30 days'")
    else:
        window = "latest"
        where.append(_LATEST_SESSION_CLAUSE)

    rows = _q(_MATRIX_SQL.format(where=" AND ".join(where), peer_min_group=PEER_MARGIN_MIN_GROUP))

    if cohort in ("in_universe", "category"):
        rows = [r for r in rows if r.get("market_cap") is not None]
    if cohort == "category":
        rows = [r for r in rows if r.get("category") in HIGH_IMPACT_CATEGORIES]
    else:
        cohort = cohort if cohort == "in_universe" else "all"

    # Private, low-traffic page — but a 30d/"all" pull with no cohort narrowing
    # could still be a few hundred rows, each costing its own price_history
    # query for the returns column, so bound it.
    rows = rows[:500]

    rns_ids = [r["rns_id"] for r in rows]
    evals = _q(
        "SELECT rns_id, gate, state, reason, evidence, mode "
        "FROM rns_gate_evaluations WHERE rns_id = ANY(%s)",
        (rns_ids,),
    ) if rns_ids else []
    by_row: dict[int, dict] = {}
    for e in evals:
        by_row.setdefault(e["rns_id"], {})[e["gate"]] = {
            "state": e["state"], "reason": e["reason"],
            "evidence": e["evidence"], "mode": e["mode"],
        }

    # Fire rate / amber rate are measured over the whole cohort for this
    # window, BEFORE the "adjudicated only" display filter below — a gate's
    # health is about what it saw, not what a reader chose to look at.
    header: dict[str, dict] = {}
    for g in GATES:
        row_gates = [by_row.get(r["rns_id"], {}).get(g.name, {}) for r in rows]
        states = [rg.get("state") for rg in row_gates]
        n = len(states)
        na_reasons = Counter(rg.get("reason") for rg in row_gates if rg.get("state") == "n/a" and rg.get("reason"))
        dominant = na_reasons.most_common(1)
        header[g.name] = {
            "mode": g.mode,
            "n": n,
            "fire_rate": round(states.count("block") / n, 3) if n else None,
            "amber_rate": round(states.count("n/a") / n, 3) if n else None,
            "dominant_na_reason": dominant[0][0] if dominant else None,
        }

    if not show_all:
        rows = [
            r for r in rows
            if any(by_row.get(r["rns_id"], {}).get(g.name, {}).get("state") in ("pass", "block") for g in GATES)
        ]

    # Symbols with another flag in the dedupe window — same rule
    # flag_high_impact_candidates uses (NOT EXISTS ... flagged_at >= NOW() - N
    # days). A row's own entry doesn't count against it: only rows with a NULL
    # vet_verdict get checked below, and a row already in high_impact_rns has one.
    symbols = list({r["symbol"] for r in rows})
    recently_flagged = {
        row["symbol"] for row in _q(
            "SELECT DISTINCT symbol FROM high_impact_rns "
            "WHERE symbol = ANY(%s) AND flagged_at >= NOW() - (%s || ' days')::interval",
            (symbols, HIGH_IMPACT_DEDUPE_DAYS),
        )
    } if symbols else set()

    bench_get = _benchmark_return_cache()
    out_rows = []
    for r in rows:
        out_rows.append({
            "rns_id": r["rns_id"], "symbol": r["symbol"],
            "company_name": r["company_name"], "headline": r["headline"], "url": r["url"],
            "category": r["category"], "published_at": r["published_at"],
            "llm_score": r["llm_score"], "llm_sentiment": r["llm_sentiment"],
            "in_universe": r.get("market_cap") is not None,
            "vet_verdict": r.get("vet_verdict"), "vet_rationale": r.get("vet_rationale"),
            "public_flag_fail": (
                [] if r.get("vet_verdict") else _public_flag_fails(r, recently_flagged)
            ),
            "gates": by_row.get(r["rns_id"], {}),
            "returns": _row_returns(r["symbol"], r["published_at"], r["ftse_index"], bench_get),
        })

    # Blocked-vs-passed mean 1d excess, over the displayed rows (where returns
    # were actually computed) — a gate whose blocked rows outperform its
    # passed rows is doing harm, and this is the number that would show it.
    for g in GATES:
        blocked = [o["returns"]["excess_1d"] for o in out_rows
                   if o["gates"].get(g.name, {}).get("state") == "block" and o["returns"]["excess_1d"] is not None]
        passed = [o["returns"]["excess_1d"] for o in out_rows
                  if o["gates"].get(g.name, {}).get("state") == "pass" and o["returns"]["excess_1d"] is not None]
        header[g.name]["blocked_mean_excess_1d"] = round(sum(blocked) / len(blocked), 2) if blocked else None
        header[g.name]["passed_mean_excess_1d"] = round(sum(passed) / len(passed), 2) if passed else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": window,
        "cohort": cohort,
        "show_all": show_all,
        "gates": [{"name": g.name, "description": g.description, "mode": g.mode} for g in GATES],
        "floor_labels": _FLOOR_LABEL,
        "header": header,
        "rows": out_rows,
    }
