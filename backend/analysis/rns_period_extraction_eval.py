"""Can the model COPY period figures reliably, if Python does the arithmetic?

Phase 4 of docs/rns-gate-block-plan.md rests on one empirical bet: the vet's
failures are all in the arithmetic and none in the extraction (see that doc's
§1 audit — 4 of 8 rationales inverted a sequential comparison while every input
figure traced correctly to the body). If that bet holds, moving the subtraction
into Python fixes the gate. If the model cannot even copy the figures, Phase 4
is dead and the low-base gate needs a different design.

This script tests the bet directly and cheaply:

  * the prompt asks for figures ONLY — metric, period, value as printed. No
    subtraction, no ratio, no direction word, no verdict. Every field is a copy
    operation, which migration 026 already established is the stable one.
  * Python resolves the sequential comparison from that extraction plus
    annual_financials, and reports the direction.
  * both halves are scored against hand-verified ground truth (GROUND below,
    checked line by line against rns_announcements.body on 2026-07-30).

Read-only. Nothing is written back to rns_announcements — no _save_ranking, no
UPDATE. Point-in-time integrity for rns_score_perf.py is preserved, same
contract as rns_body_context_validation.py.

Judgements are made on --repeat, never a single sample: at temperature 0.2 the
run-to-run spread on this feed is wide enough that one call proves nothing.

Usage:
  python backend/analysis/rns_period_extraction_eval.py --repeat 3
  python backend/analysis/rns_period_extraction_eval.py --repeat 5 --model deepseek-chat
  python backend/analysis/rns_period_extraction_eval.py --only 9689848 --repeat 7
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)

# Same reasoning as rns_body_context_validation.py: announcements print £, €, ≥
# and en-dashes, this script echoes them, and a redirected stdout on Windows
# defaults to cp1252. Losing a paid run to UnicodeEncodeError is not acceptable.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# db.py and rns_llm.py both call bare load_dotenv(), which walks up from the
# CWD — so running this from the repo root finds ./.env (DB_* only) and silently
# misses DEEPSEEK_API_KEY, which lives in backend/.env. Load that explicitly and
# first, so the script works from any directory instead of only from backend/.
from dotenv import load_dotenv

load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

import db
from rns_llm import _load_candidate, _get_client, _THINKING_ON


# ── Ground truth ───────────────────────────────────────────────────────────────
# Hand-verified against the STORED rns_announcements.body, 2026-07-30, then
# corrected 2026-07-30 after the first 42-call run (see CORRECTIONS below).
# Values in MILLIONS of the announcement's own reporting currency — the gate
# only ever compares a figure against another from the same announcement, so
# currency never has to be resolved, only kept consistent.
#
# TWO AXES, deliberately separate. The first run collapsed them into one number
# and the route that happened to fire first decided the answer, which produced a
# spurious "wrong sign" on JNEO. They answer different questions and a gate
# needs both:
#   back_truth  is the CURRENT period growing against the PRECEDING one?
#               (the axis all four audited errors were about)
#   fwd_truth   does full-year guidance imply the NEXT period declines against
#               the current one? (the axis PTEC's correct rationale used)
# None means "the announcement does not publish enough to compute this", which
# is a valid and common answer, not a failure.
#
# CORRECTIONS from run 1 — all four were my errors, not the model's:
#   * CAPD fy_guidance was None; the announcement reiterates "$410 - $440
#     million". The model was right and scored as wrong.
#   * INCH current/prior were 4700.0/None from the rounded "£4.7bn … up 9%".
#     The stored body prints £4,722m and £4,320m in the statements and the model
#     read both, so the exact figures are now truth and back_truth is -1.2%.
#   * JNEO fy_guidance was None; the announcement footnotes "FY26 market
#     expectations are revenue of £72m".
#   * RNK metric is genuinely ambiguous — the announcement's own subtitle leads
#     on "underlying operating profit … at least £76m" while the growth figure
#     quoted is LFL NGR. metric_ambiguous marks it so a defensible read is not
#     scored as a copy failure.
GROUND = {
    9689848: {
        "label": "JNEO — inverted the inequality",
        "current": 37.6, "current_period_months": 6,
        "prior_year": 24.5,          # printed: "(H1 2025: £24.5m)"
        "preceding": None,           # not printed; Python derives from FY25 total
        "fy_guidance": 72.0,         # footnote: FY26 market expectations £72m
        "back_truth": +0.232,
        "fwd_truth": -0.085,         # (72 - 37.6) / 37.6 - 1
    },
    9671246: {
        "label": "CAPD — compared a quarter to a half",
        "current": 117.3, "current_period_months": 3,
        "prior_year": 87.4,          # printed: Q2 2025 $87.4m
        "preceding": 101.7,          # printed: Q1 2026 $101.7m — direct
        "fy_guidance": 410.0,        # "$410 - $440 million", low end
        "fy_guidance_hi": 440.0,
        "back_truth": +0.153,
        # Guidance is a range and the implied H2 direction flips across it
        # (410 - 219 = 191 vs H1 219 is -13%; 440 - 219 = 221 is +1%), so the
        # forward axis is genuinely unresolvable here and must return None.
        "fwd_truth": None,
    },
    9692325: {
        "label": "STAN — used H1'26 as its own comparator",
        "current": 11604.0, "current_period_months": 6,
        "prior_year": 10906.0,       # printed in the statement of results
        "preceding": None,
        "fy_guidance": None,         # guidance is a growth %, not an absolute
        "back_truth": +0.203,
        "fwd_truth": None,
    },
    9689910: {
        "label": "INCH — exact statement figures, not the rounded headline",
        "current": 4722.0, "current_period_months": 6,
        "prior_year": 4320.0,        # printed in the income statement
        "preceding": None,
        "fy_guidance": None,         # ">10% EPS growth", not a revenue absolute
        "back_truth": -0.012,
        "fwd_truth": None,
    },
    9682985: {
        "label": "SRT — no period split exists at all",
        "current": 116.0, "current_period_months": 12,
        "prior_year": 78.0,          # FY25, a full year — not a half
        "preceding": None,
        "fy_guidance": None,
        "back_truth": None,          # must resolve to n/a, NOT to a number
        "fwd_truth": None,
    },
    9659657: {
        "label": "PTEC — the vet's one success was the FORWARD axis",
        "current": 155.0, "current_period_months": 6,
        "prior_year": None,          # no prior-year EBITDA printed
        "preceding": None,
        "fy_guidance": 270.0,        # ">= EUR 270m", so implied H2 <= 115
        "back_truth": None,          # nothing to compare backwards against
        "fwd_truth": -0.258,
    },
    9666644: {
        "label": "RNK — full-year figure, no sequential axis",
        "current": 834.1, "current_period_months": 12,
        "prior_year": None,
        "preceding": None,
        # "at least £76m" full-year underlying operating profit IS guidance —
        # the model returned it and was scored wrong in run 1. Corrected.
        "fy_guidance": 76.0,
        "metric_ambiguous": True,    # NGR vs underlying operating profit
        "back_truth": None,
        "fwd_truth": None,           # months=12, so no axis either way
    },
}


# ── The extraction prompt — copy operations only ───────────────────────────────
# Every instruction here is deliberately a transcription instruction. There is
# no "work out", no "estimate", no "compare", and no field whose value is a
# conclusion. Contrast showcase.py:264-273, which hands the model the formula
# and asks it to execute it.
_SYSTEM = (
    "You transcribe figures out of UK RNS announcements. You do NOT analyse "
    "them, do not judge them, and do not calculate anything.\n\n"
    "Rules, in order of importance:\n"
    "1. Every value you return must appear IN THE ANNOUNCEMENT TEXT, copied as "
    "printed. Never compute a value. Never infer one. Never fill a gap from "
    "your own knowledge of the company.\n"
    "2. If a figure is not printed, return null for it. A null is a correct, "
    "expected answer and is always better than a guess.\n"
    "3. Copy the number exactly as written, including its unit and any bound: "
    "\"£37.6m\", \"$117.3 million\", \"11,604\", \"over €155 million\".\n"
    "4. Do not convert units, scale, or currency.\n\n"
    "Return STRICT JSON only, with exactly these fields:\n"
    "  metric                  the headline financial measure this announcement "
    "leads on, named as the announcement names it (e.g. \"Group revenue\", "
    "\"adjusted EBITDA\", \"operating income\")\n"
    "  metric_kind             which standard measure that is, EXACTLY one of: "
    "\"revenue\", \"operating_profit\", \"net_income\", \"ebitda\", \"other\". "
    "Use \"revenue\" only for a top-line sales/turnover figure. Use \"other\" "
    "for anything you are unsure about — including sector-specific measures "
    "like net gaming revenue or net operating income.\n"
    "  current_period          the period label for the headline figure, as "
    "printed (e.g. \"H1 2026\", \"Q2 2026\", \"FY2026\")\n"
    "  current_period_months   how many months that period covers: 3, 6 or 12\n"
    "  current_value           the headline figure for that period, as printed\n"
    "  prior_year_period       the equivalent earlier-year period the "
    "announcement compares against, as printed, or null\n"
    "  prior_year_value        that period's figure, as printed, or null if the "
    "announcement gives only a percentage change\n"
    "  prior_year_growth_pct   the percentage change quoted against that prior "
    "period, as printed, or null\n"
    "  preceding_period        the period IMMEDIATELY BEFORE current_period, "
    "but ONLY if the announcement prints a figure for it (e.g. Q1 of the same "
    "year when reporting Q2). Usually null.\n"
    "  preceding_value         that period's figure, as printed, or null\n"
    "  full_year_guidance      a full-year figure for the CURRENT year that the "
    "announcement states as guidance or expectation, as printed, or null\n"
    "  period_split_published  true only if this announcement reports a period "
    "SHORTER than a full year. False for a full-year or annual update.\n"
)


def _messages(cand: dict) -> list[dict]:
    body = cand.get("body") or "(not available)"
    user = (
        f"Company: {cand.get('company_name') or '?'} ({cand.get('symbol') or '?'})\n"
        f"Headline: {cand.get('headline')}\n\n"
        f"Announcement text (verbatim):\n{body}\n\n"
        "Return the JSON object described in your instructions. JSON only."
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def _call(messages: list[dict], model: str) -> dict:
    resp = _get_client().chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=8000,
        extra_body=_THINKING_ON,
    )
    choice = resp.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise RuntimeError("response hit max_tokens")
    return json.loads(choice.message.content)


# ── Parsing: Python's job, not the model's ─────────────────────────────────────
_NUM = re.compile(r"-?[\d,]+(?:\.\d+)?")


def _to_millions(printed) -> "float | None":
    """Parse a printed money figure to millions. Returns None on anything
    ambiguous — a None here means the gate goes n/a, which is the safe
    direction. Never guess a scale."""
    if printed is None:
        return None
    s = str(printed).strip().lower().replace(",", "")
    if not s:
        return None
    m = _NUM.search(s)
    if not m:
        return None
    v = float(m.group().replace(",", ""))
    tail = s[m.end():]
    if re.search(r"\bbn\b|\bbillion\b|\bb\b", tail):
        return v * 1000.0
    if re.search(r"\bm\b|\bmillion\b|\bmn\b", tail):
        return v
    if re.search(r"\bk\b|\bthousand\b", tail):
        return v / 1000.0
    # No unit printed (e.g. a figure lifted from a "$million" table column).
    # Treat as already-in-millions rather than refusing: the tables this comes
    # from state their unit in a header the model is not asked to copy.
    return v


def _to_pct(printed) -> "float | None":
    if printed is None:
        return None
    m = _NUM.search(str(printed).replace(",", ""))
    return float(m.group()) / 100.0 if m else None


# The model's declared metric must select the matching annual_financials column.
# Defaulting to revenue is what produced the -97.2% on INCH run 1: the model
# legitimately picked "Adjusted operating profit" (£248m), Python subtracted it
# from revenue (£9,100m), and compared incommensurable quantities — the vet's own
# error class, relocated into Python. Anything not mappable must go n/a rather
# than fall back to a column that happens to exist.
#
# Deliberately REVENUE ONLY. Mapping operating_profit -> operating_income makes
# the units cohere but not the basis: announcements quote ADJUSTED profit
# (INCH: adjusted operating profit £248m, adjusted PBT £188m) while
# annual_financials stores STATUTORY (INCH FY25 operating_income £563m,
# statutory PBT £124m). Subtracting an adjusted half from a statutory year gave
# a plausible-looking -21.5% that is still comparing different things — the same
# failure one layer down. Top-line revenue is the one measure where adjusted and
# statutory almost always agree, so it is the only one this route may use.
# Profit measures decline to n/a; recovering them needs the model to declare
# adjusted-vs-statutory and a matching stored column for each.
_METRIC_COLUMN = {
    "revenue": "revenue",
}


def _prior_fy_total_m(symbol: str, metric_kind) -> "float | None":
    """The prior full year's figure FOR THE DECLARED METRIC, in millions.

    annual_financials, not quarterly_financials: the latter covers 34 symbols
    (4.8% of the universe) and is empty for five of the seven rows here. See the
    plan's Phase 4 note.
    """
    col = _METRIC_COLUMN.get(str(metric_kind or "").strip().lower())
    if col is None:
        return None
    rows = db.query(
        f"""
        SELECT {col} AS v FROM annual_financials
        WHERE company_symbol = %s AND {col} IS NOT NULL
        ORDER BY period_end_date DESC LIMIT 1
        """,
        (symbol,),
    )
    if not rows or rows[0]["v"] is None:
        return None
    return float(rows[0]["v"]) / 1e6


def _money_range(printed) -> tuple:
    """Parse a printed figure that may be a range ("$410 - $440 million") into
    (lo, hi) in millions. A single figure returns (v, v).

    Ranges matter: taking the low end silently, as the first version did, turns
    "guidance implies H2 between -13% and +1%" into a confident "-13%".
    """
    if printed is None:
        return (None, None)
    s = str(printed).strip().replace(",", "")
    nums = _NUM.findall(s)
    if len(nums) < 2:
        v = _to_millions(printed)
        return (v, v)
    # Re-attach the trailing unit to each bare number so both ends scale.
    unit = ""
    for u in ("bn", "billion", "million", "mn", "m"):
        if re.search(rf"\b{u}\b", s.lower()):
            unit = u
            break
    lo = _to_millions(f"{nums[0]}{unit}")
    hi = _to_millions(f"{nums[-1]}{unit}")
    if lo is None or hi is None:
        return (None, None)
    return (min(lo, hi), max(lo, hi))


def _resolve(ext: dict, symbol: str) -> dict:
    """Python does every comparison. The model contributed only copied figures.

    Returns both axes independently — never one collapsed number. A None on
    either axis means the announcement does not publish enough to adjudicate it,
    which is a valid and common outcome and must never be filled with a guess.
    """
    months = ext.get("current_period_months")
    try:
        months = int(months) if months is not None else None
    except (TypeError, ValueError):
        months = None

    out = {"back": None, "back_route": "none", "back_reason": "",
           "fwd": None, "fwd_route": "none", "fwd_reason": ""}

    cur = _to_millions(ext.get("current_value"))
    if cur is None or cur <= 0:
        out["back_reason"] = out["fwd_reason"] = "current_unparseable"
        return out

    # A full-year report has no sequential axis at all. The SRT guardrail, and
    # it gates BOTH axes before any branch below can manufacture one.
    if ext.get("period_split_published") is False or months == 12:
        out["back_reason"] = out["fwd_reason"] = "no_period_split"
        return out

    # ── Backward axis: is the current period growing on the preceding one? ────
    prec = _to_millions(ext.get("preceding_value"))
    if prec and prec > 0:
        # Route 1 — the announcement printed the immediately preceding period.
        # Direct, no derivation, no annual table needed. This is CAPD.
        out.update(back=cur / prec - 1.0, back_route="printed_preceding",
                   back_reason="ok")
    elif months == 6:
        # Route 2 — derive the preceding half as prior FY total minus the
        # prior-year half. The prior-year half is copied from the announcement
        # (or backed out of a printed growth rate); the FY total is ours.
        # This is JNEO, STAN, and INCH.
        prior = _to_millions(ext.get("prior_year_value"))
        derived_from_pct = False
        if prior is None:
            g = _to_pct(ext.get("prior_year_growth_pct"))
            if g is not None and g > -1.0:
                prior = cur / (1.0 + g)
                derived_from_pct = True
        fy_prior = _prior_fy_total_m(symbol, ext.get("metric_kind"))
        if prior is None:
            out["back_reason"] = "no_prior_period_figure"
        elif fy_prior is None:
            # Either no stored series, or the declared metric has no column we
            # can compare like-for-like against. Both must decline, not guess.
            out["back_reason"] = "metric_not_mappable_or_no_annuals"
        elif fy_prior <= prior:
            # The prior-year HALF exceeds the prior-year FULL YEAR — proof the
            # two figures are on different bases (or the metric was misread).
            # Bail rather than emit a nonsense preceding-half.
            out["back_reason"] = "prior_half_exceeds_full_year"
        else:
            preceding_half = fy_prior - prior
            if preceding_half > 0:
                out.update(
                    back=cur / preceding_half - 1.0,
                    back_route="derived_half_pct" if derived_from_pct
                               else "derived_half",
                    back_reason="ok")
            else:
                out["back_reason"] = "derived_half_nonpositive"
    else:
        out["back_reason"] = "no_preceding_figure"

    # ── Forward axis: does FY guidance imply the next period declines? ────────
    lo, hi = _money_range(ext.get("full_year_guidance"))
    if lo is None:
        out["fwd_reason"] = "no_fy_guidance"
    elif months != 6:
        # Only meaningful when exactly one period remains in the year.
        out["fwd_reason"] = "not_a_half_year_report"
    elif lo <= cur:
        out["fwd_reason"] = "guidance_below_reported"
    else:
        d_lo = (lo - cur) / cur - 1.0
        d_hi = (hi - cur) / cur - 1.0
        if (d_lo > 0) != (d_hi > 0):
            # The range straddles flat — CAPD. Refusing is the honest answer;
            # picking an end would be the same class of error as the audit's.
            out["fwd_reason"] = "guidance_range_straddles_flat"
        else:
            out.update(fwd=d_lo if abs(d_lo) < abs(d_hi) else d_hi,
                       fwd_route="guidance_split", fwd_reason="ok")

    return out


# ── Scoring ────────────────────────────────────────────────────────────────────
def _close(a, b, tol=0.02) -> bool:
    """Relative tolerance on a copied figure. 2% absorbs £4.7bn vs £4,700m and
    'over €155 million' vs €155m, without absorbing a wrong number."""
    if a is None or b is None:
        return a is None and b is None
    if b == 0:
        return abs(a) < 1e-9
    return abs(a - b) / abs(b) <= tol


def _score_extraction(ext: dict, truth: dict) -> dict:
    """Did the model COPY correctly? Independent of whether Python's resolution
    then worked — these are the two halves of the Phase 4 bet and conflating
    them is how you'd miss which half failed."""
    out = {}
    # Where the announcement leads on two defensible metrics (RNK), any figure
    # the model picks is a correct copy of something — score the null-discipline
    # fields only and exempt the value itself.
    ambiguous = truth.get("metric_ambiguous", False)
    out["current"] = (True if ambiguous
                      else _close(_to_millions(ext.get("current_value")),
                                  truth["current"]))

    got_prior = _to_millions(ext.get("prior_year_value"))
    if truth["prior_year"] is None:
        # Correct answer is null. Inventing a figure here is the SRT failure.
        out["prior_year"] = True if ambiguous else got_prior is None
    else:
        out["prior_year"] = _close(got_prior, truth["prior_year"])

    got_prec = _to_millions(ext.get("preceding_value"))
    if truth["preceding"] is None:
        out["preceding"] = got_prec is None
    else:
        out["preceding"] = _close(got_prec, truth["preceding"])

    lo, hi = _money_range(ext.get("full_year_guidance"))
    want_guide = truth.get("fy_guidance")
    if want_guide is None:
        out["fy_guidance"] = lo is None
    else:
        # Accept either end of a printed range against the recorded low end.
        want_hi = truth.get("fy_guidance_hi", want_guide)
        out["fy_guidance"] = _close(lo, want_guide) or _close(hi, want_hi)

    months = ext.get("current_period_months")
    try:
        months = int(months) if months is not None else None
    except (TypeError, ValueError):
        months = None
    out["months"] = months == truth["current_period_months"]

    out["_all"] = all(out.values())
    return out


def _score_axis(got, want) -> str:
    """Did Python reach the right conclusion on one axis? Declining to answer is
    a PASS when the announcement genuinely does not support one — for SRT, RNK
    and PTEC's backward axis, n/a IS the right answer."""
    if want is None:
        return "OK(n/a)" if got is None else "WRONG(invented)"
    if got is None:
        return "MISS(n/a)"
    if (want > 0) != (got > 0):
        return "WRONG(sign)"
    if _close(got, want, tol=0.15):
        return "OK"
    # A right sign with a wild magnitude is NOT a pass. INCH run 1 returned
    # -97.2% against a -1.2% truth and the old scoring called it "OK(sign)",
    # hiding a metric-basis mismatch. 25pp of absolute error is the line.
    if abs(got - want) > 0.25:
        return "WRONG(magnitude)"
    return "OK(sign,loose mag)"


def _score_direction(res: dict, truth: dict) -> tuple:
    return (_score_axis(res["back"], truth["back_truth"]),
            _score_axis(res["fwd"], truth["fwd_truth"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3,
                    help="calls per row; judge on >=3, never 1")
    ap.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL",
                                                      "deepseek-v4-flash"))
    ap.add_argument("--only", type=int, nargs="*", help="subset of rns ids")
    ap.add_argument("--json", help="optional path to dump raw extractions")
    args = ap.parse_args()

    ids = args.only or list(GROUND)
    print(f"\nExtraction eval — model={args.model} repeat={args.repeat} "
          f"rows={len(ids)}")
    print("The model copies figures; Python does every comparison.\n")

    raw = []
    ext_tally = defaultdict(int)
    runs_tally = defaultdict(int)
    back_tally = defaultdict(lambda: defaultdict(int))
    fwd_tally = defaultdict(lambda: defaultdict(int))
    field_fails = defaultdict(lambda: defaultdict(int))

    for rid in ids:
        truth = GROUND.get(rid)
        if truth is None:
            print(f"  {rid}: no ground truth entry, skipped")
            continue
        cand = _load_candidate(rid)
        if cand is None:
            print(f"  {rid}: row not found (body pruned?), skipped")
            continue
        symbol = cand.get("symbol") or ""
        print(f"── {truth['label']}")
        print(f"   {symbol}  body={len(cand.get('body') or '')} chars")

        for i in range(args.repeat):
            try:
                ext = _call(_messages(cand), args.model)
            except Exception as e:
                print(f"   run {i+1}: CALL FAILED — {e}")
                runs_tally[rid] += 1
                back_tally[rid]["call_failed"] += 1
                continue
            sc = _score_extraction(ext, truth)
            res = _resolve(ext, symbol)
            v_back, v_fwd = _score_direction(res, truth)

            runs_tally[rid] += 1
            ext_tally[rid] += 1 if sc["_all"] else 0
            back_tally[rid][v_back] += 1
            fwd_tally[rid][v_fwd] += 1
            for k, v in sc.items():
                if not k.startswith("_") and not v:
                    field_fails[rid][k] += 1

            b = "n/a" if res["back"] is None else f"{res['back']*100:+.1f}%"
            f_ = "n/a" if res["fwd"] is None else f"{res['fwd']*100:+.1f}%"
            bad = "" if sc["_all"] else ("  copy-fail: " + ",".join(
                k for k, v in sc.items() if not k.startswith("_") and not v))
            print(f"   run {i+1}: copy={'OK ' if sc['_all'] else 'BAD'}  "
                  f"back={b:>8s} [{v_back}] via {res['back_route']:<18s} "
                  f"fwd={f_:>7s} [{v_fwd}]{bad}")
            raw.append({"id": rid, "run": i + 1, "extraction": ext,
                        "resolved": res, "back": v_back, "fwd": v_fwd,
                        "copy_ok": sc["_all"]})
        print()

    print("=" * 78)
    print("SUMMARY — extraction accuracy (every copied field correct)\n")
    tot_ok = tot = 0
    for rid in ids:
        if rid not in GROUND or rid not in runs_tally:
            continue
        n, ok = runs_tally[rid], ext_tally[rid]
        tot_ok += ok
        tot += n
        ff = field_fails.get(rid) or {}
        note = ("  weakest: " + ", ".join(f"{k}×{v}" for k, v in
                sorted(ff.items(), key=lambda x: -x[1]))) if ff else ""
        print(f"  {GROUND[rid]['label'][:44]:<46s} {ok}/{n}{note}")
    if tot:
        print(f"\n  TOTAL copy-clean runs: {tot_ok}/{tot} "
              f"({tot_ok/tot*100:.0f}%)")

    for name, tally, key in (("BACKWARD (current vs preceding period)",
                              back_tally, "back_truth"),
                             ("FORWARD (guidance-implied next period)",
                              fwd_tally, "fwd_truth")):
        print(f"\nSUMMARY — {name}\n")
        for rid in ids:
            if rid not in GROUND or rid not in tally:
                continue
            parts = ", ".join(f"{k}×{v}" for k, v in
                              sorted(tally[rid].items(), key=lambda x: -x[1]))
            want = GROUND[rid][key]
            want_s = "n/a" if want is None else f"{want*100:+.1f}%"
            print(f"  {GROUND[rid]['label'][:44]:<46s} truth {want_s:>7s} "
                  f" →  {parts}")

    wrong = sum(v for t in (back_tally, fwd_tally) for rid in t
                for k, v in t[rid].items() if k.startswith("WRONG"))
    miss = sum(v for t in (back_tally, fwd_tally) for rid in t
               for k, v in t[rid].items() if k.startswith("MISS"))
    print(f"\n  Wrong-direction conclusions: {wrong} "
          f"(target 0 — a wrong sign is the audited failure, reproduced)")
    print(f"  Declined-but-answerable:     {miss} "
          f"(safe: costs a gate opportunity, never a false block)")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        print(f"\n  raw extractions → {args.json}")


if __name__ == "__main__":
    main()
