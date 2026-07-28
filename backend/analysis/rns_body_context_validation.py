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

Usage:
    python backend/analysis/rns_body_context_validation.py
    python backend/analysis/rns_body_context_validation.py --csv out.csv
"""

import argparse
import csv
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)

from rns_llm import (
    _load_candidate,
    _load_history,
    _load_price_change,
    _load_prior_guidance,
    _build_messages,
    _call_deepseek,
)

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


def _rerank(row_id: int) -> dict:
    cand = _load_candidate(row_id)
    if cand is None:
        return {"id": row_id, "error": "row not found"}
    history = _load_history(cand.get("symbol"))
    price = _load_price_change(cand.get("symbol"))
    prior_guidance = _load_prior_guidance(cand.get("symbol"), exclude_id=row_id)
    messages = _build_messages(cand, history, price, prior_guidance)
    new = _call_deepseek(messages)
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
        for i in range(n):
            try:
                r = _rerank(row_id)
            except Exception as e:
                print(f"  sample {i+1}: FAILED — {type(e).__name__}: {e}")
                continue
            scores.append(r["new_score"])
            sentiments.append(r["new_sentiment"])
            print(f"  sample {i+1}: score={r['new_score']} "
                  f"sentiment={r['new_sentiment']}")
            print(f"      thesis: {r['new_thesis']}")
            print(f"      risks:  {r['new_risks']}")
            print(f"      checks: {r['new_guidance_checks']}")
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
