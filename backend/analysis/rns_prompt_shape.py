"""Measure the cacheable-prefix shape of the real RNS ranker prompt.

DeepSeek's context caching is prefix-based, so only a segment that is identical
across rows AND positioned before any per-row content is ever billed at the
cache-hit rate. This script builds the real prompt for a day's Tier A/B rows and
reports how much of it is actually cacheable.

Why it exists: on 2026-07-29 the bill went <1c/day -> 5c/day, a 5x jump against
a predicted 2x. The extra 3x is that the cached SHARE halved at the same time
the volume doubled — the system prompt did not grow while the body inflated
everything after it. The ~4.9k JSON schema block is byte-identical on every row
but sits at the END of the user message, after the body, so it never caches.

See docs/rns-earnings-quality-plan.md Phase 0, which proposes moving that block
into the system prompt (cacheable share 15% -> 36%). Acceptance criterion 8 of
that plan is a re-run of this script confirming the prefix actually landed.

Usage:  python analysis/rns_prompt_shape.py [YYYY-MM-DD]
Default date = 2026-07-29 (the first batch with bodies). Read-only: SELECT only.
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv
load_dotenv(os.path.join(_BACKEND, ".env"))

from db import query
import rns_llm

DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-07-29"

# Marker for the start of the schema block. It now lives in the SYSTEM message
# (Phase 0, shipped) but the script still looks for it in both places, so the
# before/after comparison stays runnable and a regression that pushes it back
# into the user message shows up as a collapsed cacheable share rather than as
# silence. If _build_messages is reworded this must be updated, or the block
# measures as 0 wherever it actually is.
_SCHEMA_MARKER = "Produce a JSON object with these fields exactly"

rows = query(
    """
    SELECT a.*, m.sector, m.industry, m.country, m.ftse_index,
           t.market_cap, t.net_debt, t.ebitda
      FROM rns_announcements a
      LEFT JOIN company_metadata m ON m.symbol = a.symbol
      LEFT JOIN ttm_financials t ON t.company_symbol = a.symbol
     WHERE a.tier IN ('A','B')
       AND a.llm_processed_at >= %s::date
       AND a.llm_processed_at <  (%s::date + INTERVAL '1 day')
       AND a.body IS NOT NULL
     ORDER BY LENGTH(a.body)
    """,
    (DAY, DAY),
)

if not rows:
    print(f"No ranked Tier A/B rows with a body on {DAY}.")
    sys.exit(0)

sys_len = 0
tot_user = tot_body = tot_tail = 0
missing_marker = 0
schema_in_system = False

for c in rows:
    msgs = rns_llm._build_messages(dict(c), [], {})
    system, user = msgs[0]["content"], msgs[1]["content"]
    sys_len = len(system)  # stable across rows by construction
    schema_in_system = _SCHEMA_MARKER in system
    idx = user.find(_SCHEMA_MARKER)
    if idx < 0 and not schema_in_system:
        missing_marker += 1
    tail = 0 if idx < 0 else len(user) - idx
    tot_user += len(user)
    tot_body += len(c["body"] or "")
    tot_tail += tail

n = len(rows)
user_mean = tot_user // n
body_mean = tot_body // n
tail_mean = tot_tail // n
header_mean = user_mean - body_mean - tail_mean
total_mean = sys_len + user_mean

print(f"=== RNS ranker prompt shape — {DAY} (n={n} rows) ===\n")
if missing_marker:
    print(f"  !! schema marker not found in {missing_marker}/{n} prompts — "
          f"update _SCHEMA_MARKER, the tail is being undercounted\n")

print(f"  system prompt (STABLE, cacheable)      {sys_len:>7,} chars"
      f"{'   <- includes the JSON schema block' if schema_in_system else ''}")
print(f"  user message (mean)                    {user_mean:>7,} chars")
print(f"    per-row header/context               {header_mean:>7,} chars")
print(f"    body (unique per row)                {body_mean:>7,} chars")
print(f"    trailing JSON schema block           {tail_mean:>7,} chars"
      f"{'   (moved to system — this is now just the pointer)' if schema_in_system else '   <- IDENTICAL every row'}")
print(f"  {'-' * 52}")
print(f"  total prompt (mean)                    {total_mean:>7,} chars\n")

print(f"  cacheable now (system only)            {sys_len:>7,} chars"
      f"  = {100 * sys_len / total_mean:>2.0f}% of prompt")
if schema_in_system:
    # Phase 0 acceptance criterion 8: the prefix should have landed at ~8,685
    # chars, i.e. ~36% of the prompt, up from 3,742 / 15%. If it did but the
    # DeepSeek bill doesn't move, the caching model is wrong — record that and
    # stop, rather than restructuring more prompt on a broken cost model.
    print(f"  (pre-Phase-0 baseline was 3,742 chars = 15% of a 24,368-char prompt)")
else:
    moved = sys_len + tail_mean
    print(f"  cacheable if schema moved to system    {moved:>7,} chars"
          f"  = {100 * moved / total_mean:>2.0f}% of prompt")
    print(f"\n  uncacheable today: {total_mean - sys_len:,} chars/row"
          f"  ->  {total_mean - moved:,} after the move"
          f"  ({100 * tail_mean / (total_mean - sys_len):.0f}% less)")
