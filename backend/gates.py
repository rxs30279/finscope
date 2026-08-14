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

import re
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
    # Which population this gate can actually be evaluated over. "wide" = every
    # ranked Tier A/B row, so record_gate_evaluations' sweep can write it.
    # "vet" = only rows that reached the LLM vet, because the gate reads fields
    # only the vet call produces; the sweep must SKIP these or it overwrites the
    # real verdict with an uninformative one (see record_gate_evaluations).
    pool: Literal["wide", "vet"] = "wide"

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
    from showcase import (
        _disqualifying_guidance, _guidance_entries, _guidance_states_consensus,
        _unarmed_disqualifying_guidance,
    )

    entries = _guidance_entries(cand)
    if not entries:
        return GateResult(state="n/a", reason="field_absent")

    hit = _disqualifying_guidance(cand)
    if hit:
        return GateResult(
            state="block",
            reason=f"{hit.get('vs_prior')}_vs_consensus_{hit.get('vs_consensus')}",
            evidence=hit,
        )

    # `pass` claims "adjudicated, nothing wrong", so it must not be returned for
    # a row an UNARMED rule flags — that is precisely how CLI.L 9702416 came
    # back clean while guiding ~32% below the consensus it printed. The armed
    # rule not covering an entry is a scope limit, not a clean bill of health,
    # and collapsing the two is the same mistake this module's docstring was
    # written about. The shadow gate below carries the verdict; this only
    # withholds the green light.
    unarmed = _unarmed_disqualifying_guidance(cand)
    if unarmed:
        rule, entry = unarmed
        return GateResult(state="n/a", reason=f"unarmed_{rule}", evidence=entry)

    # Adjudicable means at least one entry printed a consensus figure this
    # gate could compare against — the common case (no consensus footnote at
    # all) is the ~91% amber rate the plan measured, not a pass.
    if any(_guidance_states_consensus(e) for e in entries):
        return GateResult(state="pass", evidence={"n_entries": len(entries)})
    return GateResult(state="n/a", reason="no_consensus_stated")


# ── Gate: guidance_wide (shadow) ──────────────────────────────────────────────
# The two guidance rules that are deliberately not armed — see the long note
# above showcase._GUIDANCE_UNARMED_IN_LINE_VS_PRIOR. One of them (reiterated +
# in_line) WAS armed until 2026-08-04 and accounts for 8 of the 9 guidance
# blocks ever recorded, so this gate is also the record of what the armed gate
# would still be doing, kept in a form a return horizon can eventually judge.
#
# Promotion criterion (the plan's §4 requires one to be stated at landing, not
# at review): a rule here is armed only once it has >= 20 adjudicated rows in a
# single llm_model era, faceted by score band, whose blocked-vs-passed mean 1d
# excess is negative on the score>=60 facet — the population the armed gate
# actually runs against. Anything less and it goes back to shadow.
def _gate_guidance_wide(cand: dict) -> GateResult:
    from showcase import (
        _guidance_entries, _guidance_states_consensus,
        _unarmed_disqualifying_guidance,
    )

    entries = _guidance_entries(cand)
    if not entries:
        return GateResult(state="n/a", reason="field_absent")

    unarmed = _unarmed_disqualifying_guidance(cand)
    if unarmed:
        rule, entry = unarmed
        return GateResult(state="block", reason=rule, evidence=entry)

    if any(_guidance_states_consensus(e) for e in entries):
        return GateResult(state="pass", evidence={"n_entries": len(entries)})
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

# Period strings in earnings_quality are free text — "H1 2026", "1H26", "2Q26"
# and "Q2 2026" all occur (see docs/rns-sequential-base-plan.md §3, and CGEO's
# own stored row uses "2Q26" and "1H26" side by side). The vet's OWN low_base
# object is asked for the canonical H1/H2/Q1-4 form directly and needs no
# normalising; this is only for text the ranker wrote for a different purpose.
# Matches the digit adjacent to H/Q either side, since which side the digit
# falls on is inconsistent between filers. Returns None on anything that
# doesn't contain a recognisable half/quarter marker — never a guess.
_HALF_RE = re.compile(r"\bH\s*([12])\b", re.I)
_HALF_ALT_RE = re.compile(r"\b([12])\s*H(?:\d|\b)", re.I)
_QUARTER_RE = re.compile(r"\bQ\s*([1-4])\b", re.I)
_QUARTER_ALT_RE = re.compile(r"\b([1-4])\s*Q(?:\d|\b)", re.I)


def _normalize_period(raw) -> Optional[str]:
    """"H1 2026" / "1H26" / "H1" -> "H1"; "2Q26" / "Q2 2026" -> "Q2". None on
    anything unrecognised."""
    if not isinstance(raw, str):
        return None
    s = raw.strip().upper()
    if not s:
        return None
    m = _HALF_RE.search(s) or _HALF_ALT_RE.search(s)
    if m:
        return f"H{m.group(1)}"
    m = _QUARTER_RE.search(s) or _QUARTER_ALT_RE.search(s)
    if m:
        return f"Q{m.group(1)}"
    return None

# ── Seasonality ───────────────────────────────────────────────────────────────
# A sequential comparison is seasonality-contaminated and, taken alone, is not
# evidence of anything. Greggs earns ~62% of its operating profit in H2, so its
# H1 sits 25-40% below the preceding H2 EVERY year no matter how well it trades.
# This gate's first ever real adjudication (GRG.L 9692273, 2026-07-29) blocked
# on a -26.1% gap that was pure December; the stock rose 18.5% that session.
#
# So a NEGATIVE sequential step no longer blocks on its own. It is ambiguous
# between "decelerating" and "seasonal", and the two are told apart with the
# same-period figure from TWO years ago — which UK interims routinely print
# (Greggs prints H1 2026 / H1 2025 / H1 2024 side by side in its highlights):
#
#   B  two-year like-for-like — is the period below the SAME period two years
#      ago? Seasonally immune by construction, because it compares H1 to H1.
#      This is the seasonally-valid form of what the gate was built for: a
#      headline growth rate flattering a level that has not actually recovered.
#   A  seasonal norm — is this year's sequential step materially worse than the
#      company's OWN step a year earlier? Greggs ran -26.1% against a -41.1%
#      norm, i.e. 15pp BETTER than usual. Catches a genuine change in the
#      seasonal pattern that B sleeps through, but it is level-blind on its own
#      (a uniformly shrinking business keeps a normal-looking step), so it only
#      ever runs alongside B, never instead of it.
#
# A POSITIVE sequential step still passes immediately and needs none of this: no
# seasonal pattern can make a period beat the one before it unless trading
# genuinely improved. That is what keeps the CAPD/STAN/JNEO negative controls
# passing on exactly the evidence they passed on before this change.
#
# Where prior_year_2_value is absent neither test can run and the result is n/a,
# never a block. Over-blocking is the high-severity error in this system, and
# this gate has ZERO production observations to calibrate against — 127 of 127
# recorded evaluations are n/a/not_vetted, because the only code path that
# supplies a low_base object is the vet, which no candidate has reached.
#
# PROVISIONAL threshold, calibrated on nothing. Unlike the old -0% cutoff it is
# at least a threshold on a meaningful quantity — how far this year's seasonal
# step falls short of the company's own — rather than on a structural artefact.
# Revisit once the gate has actually adjudicated some rows.
_SEASONAL_WORSENING_PP = 5.0


def _low_base_fy_series(
    symbol: Optional[str], metric: str, n: int = 2, currency: Optional[str] = None
) -> list:
    """The last `n` COMPLETE fiscal years' values for `metric`, newest first.

    An interim announcement's prior-year comparator period (e.g. "H1 2025")
    belongs to the fiscal year immediately before the one in progress — which
    is, by construction, the latest year annual_financials has on file: the
    year containing the current period hasn't closed yet, so it can't be
    there instead. The second element is the year before that, needed to
    derive the company's own seasonal step a year earlier (test A).

    `currency`, when given, is the announcement's own reporting currency
    (cand["financial_currency"]). A row is nulled out — not returned — when
    its stored currency is POSITIVELY known and disagrees with it: HILS.L
    reported its FY2025 annual results in GBP and its H1 2026 interim in USD
    after switching mid-cycle, and subtracting one from the other produced a
    fabricated "preceding half" (migration 034). A row whose currency is
    unknown (NULL — true of every row written before that migration) is left
    alone rather than guessed at, so this only ever removes a row the
    database can actually name a conflicting currency for.
    """
    from showcase import _annual_history

    hist = _annual_history(symbol)  # oldest first
    out = []
    for h in reversed(hist):
        v = h.get(metric)
        row_ccy = h.get("currency")
        if v is not None and currency and row_ccy and row_ccy != currency:
            v = None
        out.append(float(v) if v is not None else None)
        if len(out) >= n:
            break
    return out


def compute_sequential_base(cand: dict) -> dict:
    """Arithmetic core of the low_base gate, factored out (plan §2 step 3,
    docs/rns-sequential-base-plan.md) so both the gate and
    showcase._sequential_base_from_earnings_quality — which builds a
    low_base-shaped dict from pass 1's earnings_quality, ahead of the vet call
    — share one implementation rather than a second copy of Route 1/Route 2
    and the mis-copy guard.

    Reads the same `cand["low_base"]` shape the gate has always read:
    period/metric/current_value/preceding_period_value/prior_year_value/
    prior_year_growth_pct. Returns {"ok": False, "reason": ...} on anything it
    cannot establish — the `reason` vocabulary matches GateResult.reason
    exactly, so _gate_low_base needs no second mapping — or
    {"ok": True, period, metric, current_value, preceding_value, delta_pct,
    basis, prior_year_value, fy} on success. `prior_year_value` and `fy` are
    only populated on the derived-from-FY route; they exist here so
    _gate_low_base's seasonal-norm test (which needs them) doesn't have to
    redo Route 2 itself.
    """
    from showcase import _parse_money

    lb = cand.get("low_base")
    if not isinstance(lb, dict):
        return {"ok": False, "reason": "not_vetted"}

    period = str(lb.get("period") or "").strip().upper()
    if period not in _LOW_BASE_PERIODS:
        return {"ok": False, "reason": "missing_period"}

    current = _parse_money(lb.get("current_value"))
    if current is None:
        return {"ok": False, "reason": "unparseable_value"}

    # Route 1 — the announcement prints the immediately preceding same-length
    # period directly (CAPD's Q1'26 next to Q2'26). No divisor, no
    # derivation, the safest comparison available — prefer it whenever it's
    # there. This is the fix for the CAPD.L defect: the original vet divided
    # an FY total by 2 and called the result a "quarterly run-rate" when the
    # announcement already printed the true sequential quarters.
    preceding = _parse_money(lb.get("preceding_period_value"))
    basis = "printed_preceding_period"
    # Kept in scope for the seasonal-norm test below, which needs the
    # prior-year half and the FY before last to derive last year's own step.
    prior = None
    fy: list = []

    # Route 1 is only the safest route while the model can tell "the period
    # immediately before this one" from "the same period a year ago". On
    # GRG.L 9692273 v4-flash:thinking copied £70.4m — the prior-year H1 — into
    # BOTH fields, which turned a -26.1% sequential step into a +22.9% one and
    # would have passed the row for the wrong reason. Two identical figures are
    # that mis-copy far more often than a genuine coincidence, so fall through
    # to the FY-derived route, which reconstructs the preceding period from
    # data we own rather than from the field in doubt.
    if preceding is not None and preceding == _parse_money(lb.get("prior_year_value")):
        preceding = None

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
            return {"ok": False, "reason": "quarter_unsupported"}

        prior = _parse_money(lb.get("prior_year_value"))
        if prior is None:
            growth = lb.get("prior_year_growth_pct")
            if isinstance(growth, (int, float)) and growth > -100:
                prior = current / (1 + growth / 100.0)
        if prior is None:
            return {"ok": False, "reason": "no_period_split"}

        metric = str(lb.get("metric") or "").strip().lower()
        if metric not in _LOW_BASE_METRICS:
            return {"ok": False, "reason": "metric_unmapped"}

        fy = _low_base_fy_series(
            cand.get("symbol"), metric, 2, currency=cand.get("financial_currency")
        )
        if not fy or fy[0] is None:
            return {"ok": False, "reason": "no_annual_history"}

        preceding = fy[0] - prior
        basis = "derived_from_fy_total"

    if not preceding:
        return {"ok": False, "reason": "unparseable_value"}

    delta_pct = round((current / preceding - 1) * 100, 1)
    return {
        "ok": True,
        "period": period,
        "metric": str(lb.get("metric") or "").strip().lower() or None,
        "current_value": current,
        "preceding_value": round(preceding, 1),
        "delta_pct": delta_pct,
        "basis": basis,
        "prior_year_value": prior,
        "fy": fy,
    }


def _gate_low_base(cand: dict) -> GateResult:
    from showcase import _parse_money

    base = compute_sequential_base(cand)
    if not base["ok"]:
        return GateResult(state="n/a", reason=base["reason"])

    period = base["period"]
    current = base["current_value"]
    preceding = base["preceding_value"]
    delta_pct = base["delta_pct"]
    basis = base["basis"]
    prior = base["prior_year_value"]
    fy = base["fy"]

    evidence = {
        "period": period, "current_value": current,
        "preceding_value": preceding, "delta_pct": delta_pct,
        "basis": basis,
    }

    lb = cand.get("low_base") or {}

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

    # At or above the preceding period — unambiguous in the safe direction. No
    # seasonal pattern can lift a period above the one before it without real
    # improvement, so this needs no seasonality evidence at all.
    if delta_pct >= 0:
        return GateResult(state="pass", evidence=evidence)

    # Below it — could be deceleration, could be December. Both seasonality-
    # immune tests need the same period two years ago, copied not derived.
    prior2 = _parse_money(lb.get("prior_year_2_value"))
    if prior2 is None or prior2 <= 0:
        evidence["note"] = (
            "sequential shortfall not adjudicable — no same-period figure from "
            "two years ago, so seasonality cannot be ruled out"
        )
        return GateResult(state="n/a", reason="seasonality_unadjudicable",
                          evidence=evidence)

    # Test B — two-year like-for-like (level).
    lfl_pct = round((current / prior2 - 1) * 100, 1)
    evidence["same_period_2y_ago"] = prior2
    evidence["two_year_lfl_pct"] = lfl_pct
    evidence["like_for_like_direction"] = (
        "above" if lfl_pct > 1 else "below" if lfl_pct < -1 else "in_line"
    )

    # Test A — seasonal norm (pattern). Only derivable on the FY-total route,
    # where we hold the year before last and the model copied the prior-year
    # half; a printed preceding period gives no equivalent for last year.
    if basis == "derived_from_fy_total" and len(fy) >= 2 and fy[1]:
        preceding_prior = fy[1] - prior2
        if preceding_prior:
            step_prior = round((prior / preceding_prior - 1) * 100, 1)
            evidence["preceding_value_prior_year"] = round(preceding_prior, 1)
            evidence["seasonal_step_prior_year_pct"] = step_prior
            evidence["vs_seasonal_norm_pp"] = round(delta_pct - step_prior, 1)

    if lfl_pct < 0:
        return GateResult(state="block", reason="below_same_period_two_years_ago",
                          evidence=evidence)
    norm_pp = evidence.get("vs_seasonal_norm_pp")
    if norm_pp is not None and norm_pp < -_SEASONAL_WORSENING_PP:
        return GateResult(state="block", reason="worse_than_seasonal_norm",
                          evidence=evidence)
    return GateResult(state="pass", evidence=evidence)


# ── Gate: one_off (shadow) ─────────────────────────────────────────────────
# docs/rns-one-off-gate-plan.md. Across the 31 stored vet_rationale values, the
# vet's single most repeated objection is "the headline is flattered by
# something that will not repeat" (HSBA $2.2bn notable items, NWG £190m
# notable items, CKN £5.9m acquisition add-backs, STAN $238m Solv India
# gain) — and until now nothing gated on it. The data was already captured:
# earnings_quality[].one_off_named, populated by the ranker since migration
# 026 (rns_llm.py:586). The only reader, showcase._named_one_offs, just
# print()s to the cron log — no rns_gate_evaluations row, nothing on /gates,
# so it could never be calibrated.
#
# Phase 1 is a recorder, not a judge — this gate NEVER returns state="block",
# not even in shadow mode, unlike low_base above. The measurements the plan
# ran before writing this (2026-08-04, 30d window) explain why:
#   (a) presence is 52% of ranked rows — far too common to ever be a blocker.
#   (b) materiality parses on only 18% of named one-offs (both the line and
#       the one-off text itself have to parse as money).
#   (c) most of that 18% comes back ~100% because the line IS the one-off
#       (TW.L cladding £222.2m of £222.2m) — a naive ratio gate would fire on
#       these and look like it's working. Guarded off as self_referential.
#   (e) recall is bounded by the RANKER, not this gate: NWG.L 9697081 has
#       ZERO one_off_named entries despite the vet's central objection being
#       "£190m notable items" — the vet reads the body, structured
#       extraction missed it. Pinned as a known-wrong `pass` control so
#       nobody "fixes" this gate by inferring unnamed one-offs (the prompt
#       forbids that, and so must the gate).
#
# `kind` covers both "income" and "cost_or_charge" — _named_one_offs only
# ever read "income", discarding the 62 of 122 (measurement (d)) that are
# cost_or_charge, which is exactly where HSBA's restructuring/disposal
# losses sit.
_ONE_OFF_SELF_REFERENTIAL_PP = 2.0


def _gate_one_off(cand: dict) -> GateResult:
    from showcase import _parse_money

    entries = cand.get("earnings_quality")
    if not isinstance(entries, list) or not entries:
        return GateResult(state="n/a", reason="field_absent")

    named = [
        e for e in entries
        if isinstance(e, dict) and e.get("kind") in ("income", "cost_or_charge")
        and str(e.get("one_off_named") or "").strip()
    ]
    evidence = {
        "n_entries": len(entries),
        "n_named": len(named),
        "n_income": sum(1 for e in named if e.get("kind") == "income"),
        "n_cost_or_charge": sum(1 for e in named if e.get("kind") == "cost_or_charge"),
    }
    if not named:
        return GateResult(state="pass", evidence=evidence)

    # Materiality ratio where computable — both the line and the one-off text
    # itself have to parse as money (measurement (b): only 18% do).
    computed = []
    for e in named:
        line_value = _parse_money(e.get("value"))
        one_off_value = _parse_money(e.get("one_off_named"))
        if not line_value or one_off_value is None:
            continue
        computed.append({
            "item": e.get("item"), "period": e.get("period"), "kind": e.get("kind"),
            "line_value": line_value, "one_off_value": one_off_value,
            "ratio_pct": round(one_off_value / line_value * 100, 1),
            "one_off_named": e.get("one_off_named"),  # raw text, for audit
        })
    evidence["computed"] = computed

    if not computed:
        return GateResult(state="n/a", reason="not_quantified", evidence=evidence)

    # Guard the degenerate case (measurement (c)): a ratio within ~2pp of 100%
    # means the line IS the one-off, not a fraction of it — not an
    # adjudication, however clean it looks.
    real = [c for c in computed
            if abs(c["ratio_pct"] - 100.0) > _ONE_OFF_SELF_REFERENTIAL_PP]
    if not real:
        return GateResult(state="n/a", reason="self_referential", evidence=evidence)

    return GateResult(state="n/a", reason="adjudicated", evidence=evidence)


GATES: tuple[Gate, ...] = (
    Gate("sentiment", "Announcement direction must read positive.", "armed", _gate_sentiment),
    Gate("guidance", "Guidance not reiterated or lowered below a printed consensus.", "armed", _gate_guidance),
    Gate("guidance_wide", "Shadow: guidance merely in line with consensus, or below it on a first-time guide.", "shadow", _gate_guidance_wide),
    Gate("earnings_quality", "Bank loan-loss rate must not be rising.", "armed", _gate_earnings_quality),
    Gate("low_base", "Headline growth vs the immediately preceding period, seasonally adjudicated against the same period two years earlier.", "shadow", _gate_low_base, pool="vet"),
    Gate("one_off", "Shadow: an earnings-quality line the announcement credits to a named one-off, and how material it is where quantifiable.", "shadow", _gate_one_off),
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


# A verdict of n/a because the row never reached the vet carries no information
# about the announcement — it is a statement about which pipeline stage ran. It
# must therefore never overwrite a verdict that DID adjudicate something.
#
# This is not hypothetical. Between the low_base gate shipping and 2026-08-04 it
# destroyed 100% of that gate's output: showcase.flag_high_impact_candidates
# wrote the real evaluation at ~06:06-06:11 each morning and the wide sweep
# (stage 3.6, four hours later) upserted `not_vetted` straight over it, leaving
# 185 of 185 stored evaluations reading not_vetted and the gate's Phase 5
# calibration sample permanently empty. The `pool` field on Gate now keeps the
# sweep away from vet-pool gates; this guard is the second line, covering
# re-runs, backfills and any future caller that doesn't know the rule.
_UNINFORMATIVE_REASON = "not_vetted"


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
        WHERE EXCLUDED.reason IS DISTINCT FROM %s
           OR rns_gate_evaluations.reason IS NOT DISTINCT FROM %s
        """,
        (
            rns_id, gate.name, result.state, result.reason,
            Json(result.evidence) if result.evidence is not None else None,
            gate.mode, datetime.now(timezone.utc),
            _UNINFORMATIVE_REASON, _UNINFORMATIVE_REASON,
        ),
    )


def record_gate_evaluations(hours: int = 48) -> dict:
    """Run every gate over every ranked Tier A/B row from the last `hours` and
    upsert one row per (rns_id, gate) into rns_gate_evaluations. Idempotent —
    a re-run (or the morning cron re-covering an overlapping window) just
    refreshes the same rows. Returns a counts dict for cron logs.

    Vet-pool gates (low_base) are SKIPPED. This sweep's rows never carry a
    `low_base` key, so evaluating it here can only ever produce n/a/not_vetted —
    which is not a harmless no-op, because this stage runs AFTER stage 3.5 and
    the upsert would land on top of the real verdict the vet just wrote. That
    is what emptied the gate's calibration sample for its entire life; see
    _UNINFORMATIVE_REASON."""
    rows = _q(_EVAL_SQL, (hours,))
    wide = [g for g in GATES if g.pool == "wide"]
    written = 0
    for row in rows:
        for gate in wide:
            written += _upsert_evaluation(row["id"], gate, gate.evaluate(row))
    return {
        "candidates": len(rows),
        "gates_run": [g.name for g in wide],
        "gate_rows_written": written,
    }


def backfill_low_base_evaluations() -> dict:
    """Re-record the low_base gate from the vet output stored on
    high_impact_rns.low_base (migration 028).

    The clobber above destroyed the gate's evaluations but not its INPUTS —
    those were persisted onto the flag row itself precisely because "the gate's
    own evidence only survives on rows it manages to adjudicate" (showcase.py).
    So the verdicts are recoverable for every row flagged since migration 028,
    which is the only calibration sample this gate has ever had."""
    rows = _q(
        """
        SELECT h.rns_id, h.low_base, r.symbol, r.category,
               m.sector, m.industry
        FROM high_impact_rns h
        JOIN rns_announcements r ON r.id = h.rns_id
        LEFT JOIN company_metadata m ON m.symbol = r.symbol
        WHERE h.low_base IS NOT NULL
        """
    )
    counts: Counter = Counter()
    for row in rows:
        cand = {k: row[k] for k in ("symbol", "category", "sector", "industry")}
        cand["low_base"] = row["low_base"]
        gate = next(g for g in GATES if g.name == "low_base")
        result = gate.evaluate(cand)
        _upsert_evaluation(row["rns_id"], gate, result)
        counts[f"{result.state}:{result.reason or '-'}"] += 1
    return {"rows": len(rows), "outcomes": dict(counts)}


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
        if entry_date == exit_date:
            # 1d horizon: entry and exit are the same trading day (raw is
            # open->close intraday, per the comment above), so p1/p2 close-to-
            # close would join each symbol's row to itself and read 0 for
            # every row, always — not "no move", a structural no-op. Match
            # `raw`'s own-day open->close instead.
            rows = _q(
                """
                SELECT AVG(p1.close / NULLIF(p1.open, 0) - 1) AS ret
                FROM price_history p1
                JOIN company_metadata m ON m.symbol = p1.symbol AND m.is_active
                WHERE p1.date = %s
                  AND (CASE WHEN COALESCE(m.ftse_index,'') ILIKE '%%AIM%%'
                            THEN 'AIM' ELSE 'Main' END) = %s
                """,
                (entry_date, seg),
            )
        else:
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
           t.market_cap, t.net_debt, t.ebitda, t.net_income_margin, t.roce, t.roic,
           pm.margin_median,
           h.vet_verdict, h.vet_rationale, h.vet_score, h.status AS showcase_status
    FROM rns_announcements r
    LEFT JOIN company_metadata m ON m.symbol = r.symbol
    LEFT JOIN LATERAL (
        SELECT market_cap, net_debt, ebitda, net_income_margin, roce, roic FROM ttm_financials
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
    "margin": "net income margin below the industry-peer floor (no ROCE/ROIC escape)",
    "dedup": "same symbol already flagged in the last 30 days",
}
# NB "score" now means "below the vet ENTRY floor (60)" — clearing every floor
# here means the row reached the vet, not that it was published. Publication is
# decided afterwards by vet_score >= HIGH_IMPACT_MIN_VET_SCORE.


def _public_flag_fails(row: dict, recently_flagged: set) -> list[str]:
    from showcase import (
        HIGH_IMPACT_VET_ENTRY_SCORE, HIGH_IMPACT_CATEGORIES, HIGH_IMPACT_MIN_MARKET_CAP,
        HIGH_IMPACT_MAX_NET_DEBT_TO_EBITDA, HIGH_IMPACT_MIN_NET_MARGIN, HIGH_IMPACT_MIN_ROCE,
        HIGH_IMPACT_MIN_ROIC,
    )

    def _f(key):
        v = row.get(key)
        return float(v) if v is not None else None

    fails = []
    # Since 2026-08-03 this is the VET ENTRY floor, not the publish floor.
    # Clearing it no longer means a row is published — that is now decided by
    # the vet's own vet_score, which this diagnostic cannot predict because it
    # runs before the vet call. "score" here means "never reached the vet".
    score = row.get("llm_score")
    if score is None or score < HIGH_IMPACT_VET_ENTRY_SCORE:
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

    margin, roce, roic = _f("net_income_margin"), _f("roce"), _f("roic")
    if margin is not None:
        peer_median = _f("margin_median")
        floor = max(0.0, peer_median if peer_median is not None else HIGH_IMPACT_MIN_NET_MARGIN)
        # Mirrors the SQL hatch in showcase.py: ROCE *or* ROIC clears it, because
        # ROCE reads a cash pile or an investment portfolio as idle capital.
        hatch = margin > 0 and (
            (roce or 0.0) >= HIGH_IMPACT_MIN_ROCE or (roic or 0.0) >= HIGH_IMPACT_MIN_ROIC
        )
        if margin < floor and not hatch:
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
def list_matrix(window: str = "latest", cohort: str = "category",
                show_all: bool = False, population: str = "all"):
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
    population: which rows the HEADER statistics are computed over. Displayed
              rows are unaffected either way.
              all           — every row in the cohort (default, unchanged).
              reached_gates — only rows that cleared every non-gate floor and
                              so actually reached blocking_reason() inside
                              flag_high_impact_candidates.

    Why `population` exists (2026-08-04). "Evaluate wide, block narrow" means
    record_gate_evaluations writes a verdict for every ranked Tier A/B row,
    including rows that die at the score or leverage floor before any gate can
    matter. A stored `block` on such a row is a diagnostic record, not a
    decision the gate made. Averaging them together produced a genuinely
    misleading page: on the audit that prompted this, the guidance gate showed
    9 lifetime blocks and NONE of them was load-bearing — 7 scored below the
    vet entry floor and the other 2 were excluded by dedup and by
    leverage/margin. Fire rate, amber rate and blocked-vs-passed excess were
    all being computed over a population where the gate could not bind, which
    is the plan's own §4 "calibrating on the wide pool" warning happening in
    practice. This does not change a single stored verdict; it only lets the
    denominator match the question.

    CAVEAT, and it is not small: _public_flag_fails runs at REQUEST time
    against today's dedupe window and the CURRENT ttm_financials row, not the
    state at announcement time. Over a 30d window a symbol flagged after the
    announcement now reads `dedup` when it did not then, and a company whose
    margin has since moved can cross the floor either way. Good enough for "was
    this row anywhere near flaggable"; NOT a point-in-time reconstruction, and
    it must not be quoted as one. Making it exact means stamping the floor
    outcome at evaluation time, which is a schema change.
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

    # Symbols with another flag in the dedupe window — same rule
    # flag_high_impact_candidates uses (NOT EXISTS ... flagged_at >= NOW() - N
    # days). A row's own entry doesn't count against it: only rows with a NULL
    # vet_verdict get checked, and a row already in high_impact_rns has one.
    # The status filter must stay in step with the candidate SQL: shadow rows
    # (vetted, below the publish floor) do not consume a symbol's dedupe window,
    # or a 62 on Monday would lock out a 90 on Wednesday.
    #
    # Computed here rather than after the display filter because `population`
    # below needs the floor diagnostics for every row in the cohort, not just
    # the displayed ones. Widening the symbol set is harmless — it is a
    # membership test, and a superset costs one slightly larger IN list.
    symbols = list({r["symbol"] for r in rows})
    recently_flagged = {
        row["symbol"] for row in _q(
            "SELECT DISTINCT symbol FROM high_impact_rns "
            "WHERE symbol = ANY(%s) AND status <> 'shadow' "
            "AND flagged_at >= NOW() - (%s || ' days')::interval",
            (symbols, HIGH_IMPACT_DEDUPE_DAYS),
        )
    } if symbols else set()

    # A row with a vet_verdict cleared every floor by definition — it reached
    # the vet, which is downstream of the gates.
    flag_fails: dict[int, list] = {
        r["rns_id"]: ([] if r.get("vet_verdict") else _public_flag_fails(r, recently_flagged))
        for r in rows
    }

    # Captured before the show_all filter below rebinds `rows`.
    cohort_n = len(rows)
    reached = [r for r in rows if not flag_fails[r["rns_id"]]]
    # Always reported, whichever population is selected — the gap between this
    # and cohort_n is the point, and a reader on the default view needs to see
    # it to know the default is worth switching away from.
    reached_n = len(reached)
    if population == "reached_gates":
        stat_rows = reached
    else:
        population = "all"
        stat_rows = rows

    # Fire rate / amber rate are measured over the whole `population` for this
    # window, BEFORE the "adjudicated only" display filter below — a gate's
    # health is about what it saw, not what a reader chose to look at.
    header: dict[str, dict] = {}
    for g in GATES:
        row_gates = [by_row.get(r["rns_id"], {}).get(g.name, {}) for r in stat_rows]
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
            # Both LLM passes side by side: llm_score decided whether this row
            # earned a vet call (>= 60), vet_score decided whether it published
            # (>= 75). Seeing them together is the only way to spot the vet
            # systematically promoting or demoting the ranker — and the only
            # calibration evidence for the vet's threshold, which currently
            # rests on zero observations.
            "vet_score": r.get("vet_score"),
            # 'shadow' = vetted but below the publish floor. Distinguishes
            # "never vetted" from "vetted and rejected", which vet_score alone
            # cannot when the vet call itself failed (NULL score, shadow row).
            "showcase_status": r.get("showcase_status"),
            "public_flag_fail": flag_fails[r["rns_id"]],
            "gates": by_row.get(r["rns_id"], {}),
            "returns": _row_returns(r["symbol"], r["published_at"], r["ftse_index"], bench_get),
        })

    # Blocked-vs-passed mean 1d excess, over the displayed rows (where returns
    # were actually computed) — a gate whose blocked rows outperform its
    # passed rows is doing harm, and this is the number that would show it.
    #
    # `population` applies here too, or the header would mix denominators: fire
    # rate over the load-bearing rows and return impact over everything. The
    # show_all filter costs nothing here — it only drops rows where EVERY gate
    # is n/a, and such a row contributes to neither list by construction.
    stat_ids = {r["rns_id"] for r in stat_rows}
    ret_rows = [o for o in out_rows if o["rns_id"] in stat_ids]
    for g in GATES:
        blocked = [o["returns"]["excess_1d"] for o in ret_rows
                   if o["gates"].get(g.name, {}).get("state") == "block" and o["returns"]["excess_1d"] is not None]
        passed = [o["returns"]["excess_1d"] for o in ret_rows
                  if o["gates"].get(g.name, {}).get("state") == "pass" and o["returns"]["excess_1d"] is not None]
        header[g.name]["blocked_mean_excess_1d"] = round(sum(blocked) / len(blocked), 2) if blocked else None
        header[g.name]["passed_mean_excess_1d"] = round(sum(passed) / len(passed), 2) if passed else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": window,
        "cohort": cohort,
        "show_all": show_all,
        "population": population,
        # How many rows the header numbers rest on, and how many the cohort
        # holds in total. A large gap is the finding, not a footnote: it is the
        # difference between what a gate saw and what it could ever have
        # decided.
        "population_n": len(stat_rows),
        "cohort_n": cohort_n,
        "reached_gates_n": reached_n,
        "gates": [{"name": g.name, "description": g.description, "mode": g.mode} for g in GATES],
        "floor_labels": _FLOOR_LABEL,
        "header": header,
        "rows": out_rows,
    }
