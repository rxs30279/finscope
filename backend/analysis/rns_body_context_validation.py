"""Phase 4 validation for docs/rns-body-context-plan.md.

Re-ranks a fixed set of announcement ids with the NEW prompt (body +
guidance-memory context, now wired into rns_llm._build_messages) and diffs the
result against each row's already-stored (pre-change) llm_score/sentiment/
thesis. Read-only against rns_announcements — every DeepSeek call here is a
throwaway re-rank; nothing is written back via _save_ranking, so prod
llm_score is never touched and rns_score_perf.py's point-in-time integrity is
preserved (see the plan's Phase 4 note on never re-ranking history in place).

Acceptance targets (plan Phase 4):
  - LUCE 9689898 (id below) must stop reading as a guidance upgrade: score
    below 75 or flipped sentiment, with the £40m vs £40.7m gap named.
    This is THE acceptance test — if it doesn't move, stop and reconsider.
  - BARC 9689888: weaker target, score below 75. Do NOT expect "negative".
  - A control set of recent high-scoring positive-sentiment rows must not
    collapse (these are a same-day proxy for "high scorers that worked" —
    the plan's own forward-return cohort needs rns_score_perf.py against
    matured price data, which these same-day rows aren't yet).
  - The truncation stress set (BOY/COA/BARC/INCH — all 90k-250k char bodies)
    must show the model actually using outlook/target material, not just
    reproducing the old summary-only thesis.

Extended for docs/rns-earnings-quality-plan.md Phase 4. That plan's criteria are
outcome tests, not score tests — llm_score is expected to sit around 75
throughout — so this script now runs showcase's real Python gates over the
model's own output and reports which rows they block:
  - BARC 9689888 blocked by skipped_earnings_quality in >= 6 of 7 runs
    (its loan loss rate went 52 -> 62bps under raised guidance).
  - LUCE 9689898 still blocked by the guidance gate, unchanged.
  - Control set (ULVR/COA/PCIP/JNEO/INCH/BOY) gains no new blocks — all
    non-banks, so the earnings gate must return None on every run.
  - Enumeration stability: the charge lines must arrive with a parseable
    value/prior_value pair in >= 6 of 7 runs, or the gate isn't dependable.
  - Phase 0 regression: guidance_checks and earnings_quality still emitted
    BEFORE score, now that the schema block lives in the system message.

Every judgement here is made on --repeat 7, never a single sample: at
temperature 0.2 the run-to-run score spread is ~30 points, wider than any
effect a prompt edit produces.

Usage:
    python backend/analysis/rns_body_context_validation.py
    python backend/analysis/rns_body_context_validation.py --csv out.csv
    python backend/analysis/rns_body_context_validation.py --only 9689888 --repeat 7
"""

import argparse
import csv
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)

# Announcements print ≥, £, — and en-dashes, and this script echoes them back
# verbatim. On Windows a redirected stdout defaults to cp1252, so a single
# "≥12%" in a guidance figure raises UnicodeEncodeError mid-report and takes
# the whole run down — after the DeepSeek calls have already been paid for.
# Downgrade that to a replaced character: a mangled glyph in a report is a
# nuisance, a lost 40-minute validation run is not.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from rns_llm import (
    _load_candidate,
    _load_history,
    _load_price_change,
    _load_prior_guidance,
    _build_messages,
    _call_deepseek,
    _clean_guidance_checks,
    _clean_earnings_quality,
)
import showcase

# id -> label, for readable output. Primary acceptance-test rows first.
TARGETS = {
    9689898: "LUCE — acceptance test (guidance upgrade misread)",
    9689888: "BARC — weaker target (market-psychology miss)",
    # Truncation stress set (90k-250k char bodies)
    9690269: "BOY — truncation stress (90k chars)",
    9689907: "COA — truncation stress (115k chars)",
    9689910: "INCH — truncation stress (104k chars)",
    # Control set — recent high-scoring positive rows, must not collapse
    9689925: "ULVR — control (80, positive)",
    9689852: "PCIP — control (80, positive)",
    9689848: "JNEO — control (75, positive, small body)",
}


def _fmt_checks(checks) -> str:
    """One line per guidance statement the model enumerated.

    This is the field the LUCE re-test turns on: the failure was that the
    model read both the reiterated FY26 figure and the new FY27 comment and
    scored off the louder one, so what matters is whether FY26 shows up here
    at all and what verdict it carries — not just the headline score move.
    """
    if not isinstance(checks, list):
        return ""
    out = []
    for c in checks:
        if not isinstance(c, dict):
            continue
        cons = c.get("consensus_value")
        out.append(
            f"{c.get('period') or '?'} {c.get('metric') or '?'}: "
            f"guided {c.get('guided_value') or '?'}"
            f"{f' vs consensus {cons}' if cons else ''}"
            f" -> {c.get('vs_prior') or '?'} / {c.get('vs_consensus') or '?'}"
        )
    return " | ".join(out)


def _fmt_earnings(entries) -> str:
    """One line per income/charge line the model enumerated.

    This is what the earnings-quality gate turns on (plan Phase 3): the BARC
    failure was headline growth partly credited to a c.£225m disposal gain,
    against a loan loss rate that had gone 52 -> 62bps, in an announcement that
    genuinely DID raise guidance. What matters here is whether the impairment
    and LLR lines show up at all and carry a parseable prior_value — not the
    headline score, which stays around 75 by design.
    """
    if not isinstance(entries, list):
        return ""
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        prior = e.get("prior_value")
        one_off = e.get("one_off_named")
        out.append(
            f"[{e.get('kind') or '?'}] {e.get('period') or '?'} "
            f"{e.get('item') or '?'}: {e.get('value') or '?'}"
            f"{f' vs {prior}' if prior else ''}"
            f"{f'  one-off: {one_off}' if one_off else ''}"
        )
    return " | ".join(out)


def _field_order_ok(new: dict) -> bool:
    """Both enumerated fields must be emitted BEFORE score.

    json.loads preserves key order, so this reads the model's actual emission
    order. It is the whole premise of the design — enumerate first so the
    facts constrain the number instead of the number being rationalised — and
    it is what Phase 0's tail pointer exists to protect now that the schema
    itself sits ~14k chars earlier, in the system message.
    """
    keys = list(new)
    if "score" not in keys:
        return False
    score_at = keys.index("score")
    return all(
        f in keys and keys.index(f) < score_at
        for f in ("guidance_checks", "earnings_quality")
    )


def _parseable_charge_rates(entries) -> int:
    """Charge lines whose value AND prior_value both read as basis points.

    Acceptance criterion 4: the gate can only fire on a fully-read pair, so an
    entry the parser can't read is an entry the gate ignores.
    """
    if not isinstance(entries, list):
        return 0
    return sum(
        1
        for e in entries
        if isinstance(e, dict)
        and e.get("kind") == "cost_or_charge"
        and showcase._parse_bps(e.get("value")) is not None
        and showcase._parse_bps(e.get("prior_value")) is not None
    )


def _rerank(row_id: int) -> dict:
    cand = _load_candidate(row_id)
    if cand is None:
        return {"id": row_id, "error": "row not found"}
    history = _load_history(cand.get("symbol"))
    price = _load_price_change(cand.get("symbol"))
    prior_guidance = _load_prior_guidance(cand.get("symbol"), exclude_id=row_id)
    messages = _build_messages(cand, history, price, prior_guidance)
    new = _call_deepseek(messages)
    # Run the real gates over the real cleaners, so this reports the outcome
    # the cron would reach rather than a human reading of the JSON.
    checks = _clean_guidance_checks(new.get("guidance_checks"))
    earnings = _clean_earnings_quality(new.get("earnings_quality"))
    gate_cand = {
        "sector": cand.get("sector"),
        "industry": cand.get("industry"),
        "guidance_checks": checks,
        "earnings_quality": earnings,
    }
    return {
        "id": row_id,
        "ticker": cand.get("ticker"),
        "old_score": cand.get("score"),  # rules score, for context only
        "old_llm_score": None,  # filled by caller from the stored row
        "new_score": new.get("score"),
        "new_sentiment": new.get("sentiment"),
        "new_thesis": new.get("thesis"),
        # Earnings-quality caveats land here, not in the thesis — without it
        # you cannot tell "the model missed it" from "the model said it".
        "new_risks": new.get("risks"),
        "new_guidance_metric": new.get("guidance_metric"),
        "new_guidance_value": new.get("guidance_value"),
        # Flattened to one CSV cell; printed one-per-line in the console report.
        "new_guidance_checks": _fmt_checks(new.get("guidance_checks")),
        "new_earnings_quality": _fmt_earnings(earnings),
        "n_earnings_entries": len(earnings or []),
        "n_parseable_charge_rates": _parseable_charge_rates(earnings),
        # The two Python gates, as flag_high_impact_candidates would run them.
        "blocked_guidance": showcase._disqualifying_guidance(gate_cand) is not None,
        "blocked_earnings": showcase._worsening_loss_rate(gate_cand) is not None,
        # Phase 0 regression check — the enumerate-then-score ordering survived
        # the schema block moving into the system prompt.
        "field_order_ok": _field_order_ok(new),
        "body_chars": len(cand.get("body") or ""),
        "body_is_stub": cand.get("body_is_stub"),
    }


def _repeat_mode(ids: list[int], n: int) -> None:
    """Score the same rows n times to separate signal from sampling noise.

    Added after four single-sample runs showed rows moving 35->75 on prompts
    that hadn't changed those cases at all: at temperature 0.2 the run-to-run
    spread is wide enough to swamp a prompt edit, so a single re-rank cannot
    tell you whether a change worked. Anything judged off one sample per
    config is guesswork.
    """
    for row_id in ids:
        scores, sentiments = [], []
        blocked_g = blocked_e = order_ok = 0
        entry_counts, rate_counts = [], []
        for i in range(n):
            # Nothing a single sample can do — a decode failure, a bad glyph,
            # an API blip — is worth losing the other samples over. They cost
            # ~40 minutes and real money to collect.
            try:
                r = _rerank(row_id)
            except Exception as e:
                print(f"  sample {i+1}: FAILED — {type(e).__name__}: {e}")
                continue
            scores.append(r["new_score"])
            sentiments.append(r["new_sentiment"])
            blocked_g += bool(r["blocked_guidance"])
            blocked_e += bool(r["blocked_earnings"])
            order_ok += bool(r["field_order_ok"])
            entry_counts.append(r["n_earnings_entries"])
            rate_counts.append(r["n_parseable_charge_rates"])
            print(f"  sample {i+1}: score={r['new_score']} "
                  f"sentiment={r['new_sentiment']}  "
                  f"gate: guidance={'BLOCK' if r['blocked_guidance'] else 'pass'} "
                  f"earnings={'BLOCK' if r['blocked_earnings'] else 'pass'}  "
                  f"order={'ok' if r['field_order_ok'] else 'WRONG'}")
            print(f"      thesis: {r['new_thesis']}")
            print(f"      risks:  {r['new_risks']}")
            print(f"      checks: {r['new_guidance_checks']}")
            print(f"      earnings: {r['new_earnings_quality']}")
        clean = [s for s in scores if isinstance(s, int)]
        if clean:
            clean_sorted = sorted(clean)
            median = clean_sorted[len(clean_sorted) // 2]
            print(
                f"\n{row_id} ({TARGETS.get(row_id, '?')})\n"
                f"  n={len(clean)}  min={min(clean)}  median={median}  "
                f"max={max(clean)}  spread={max(clean) - min(clean)}\n"
                f"  scores={clean_sorted}\n"
                f"  sentiments={sentiments}\n"
                # The acceptance criteria are read off these three lines, not
                # off the score — the score is expected to stay ~75 throughout.
                f"  blocked: guidance {blocked_g}/{len(scores)}, "
                f"earnings_quality {blocked_e}/{len(scores)}\n"
                f"  earnings entries per run: {entry_counts}  "
                f"(charge lines with a parseable rate pair: {rate_counts})\n"
                f"  enumerate-before-score ordering held: "
                f"{order_ok}/{len(scores)}\n"
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="optional path to write full results")
    ap.add_argument("--only", type=int, nargs="*",
                    help="restrict to these announcement ids")
    ap.add_argument("--repeat", type=int,
                    help="score each id this many times and report the spread")
    args = ap.parse_args()

    if args.repeat:
        _repeat_mode(args.only or list(TARGETS), args.repeat)
        return

    from rns import _query

    stored = {
        r["id"]: r
        for r in _query(
            "SELECT id, llm_score, llm_sentiment, llm_thesis, llm_risks "
            "FROM rns_announcements WHERE id = ANY(%s)",
            (list(TARGETS.keys()),),
        )
    }

    rows = []
    for row_id, label in TARGETS.items():
        print(f"[validation] re-ranking {row_id} ({label}) ...")
        try:
            result = _rerank(row_id)
        except Exception as e:
            print(f"[validation]   FAILED — {type(e).__name__}: {e}")
            continue
        old = stored.get(row_id, {})
        result["label"] = label
        result["old_llm_score"] = old.get("llm_score")
        result["old_sentiment"] = old.get("llm_sentiment")
        result["old_thesis"] = old.get("llm_thesis")
        rows.append(result)

    print("\n" + "=" * 100)
    print(f"{'id':>9}  {'label':<45} {'old':>4} -> {'new':>4}  sentiment")
    print("=" * 100)
    for r in rows:
        print(
            f"{r['id']:>9}  {r['label']:<45} "
            f"{str(r['old_llm_score']):>4} -> {str(r['new_score']):>4}  "
            f"{r['old_sentiment']} -> {r['new_sentiment']}"
        )
        print(f"           old thesis: {r['old_thesis']}")
        print(f"           new thesis: {r['new_thesis']}")
        print(f"           new risks:  {r['new_risks']}")
        for i, line in enumerate(
            (r.get("new_guidance_checks") or "").split(" | ")
        ):
            if line:
                label = "guidance checks:" if i == 0 else ""
                print(f"           {label:<17}{line}")
        for i, line in enumerate(
            (r.get("new_earnings_quality") or "").split(" | ")
        ):
            if line:
                label = "earnings quality:" if i == 0 else ""
                print(f"           {label:<17}{line}")
        print(
            f"           gates:           "
            f"guidance={'BLOCK' if r['blocked_guidance'] else 'pass'} "
            f"earnings={'BLOCK' if r['blocked_earnings'] else 'pass'} "
            f"order={'ok' if r['field_order_ok'] else 'WRONG'}"
        )
        if r.get("new_guidance_metric"):
            print(
                f"           remembered:      {r['new_guidance_metric']} "
                f"= {r['new_guidance_value']}"
            )
        print(f"           body: {r['body_chars']} chars"
              f"{' (stub)' if r['body_is_stub'] else ''}")
        print("-" * 100)

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
            w.writeheader()
            w.writerows(rows)
        print(f"\n[validation] wrote {len(rows)} rows to {args.csv}")


if __name__ == "__main__":
    main()
