# Plan — hand the vet a Python-computed sequential base

**Status:** built 2026-08-04, backend suite green, NOT deploy-verified (§8
still to run against the live container). Written 2026-08-04.

**Implementation notes, for anyone reading this after the fact:**
- §7's open question ("HSBA-style rows where revenue is extractable but the
  story is about another metric") got resolved during the build, on real
  data: HSBA.L 9702338's stored Revenue entry carries a non-null
  `one_off_named` ("net favourable impact of notable items of $0.8bn and
  one-off property asset disposal gain of $0.2bn"), while ELIX's does not.
  `showcase._sequential_base_from_earnings_quality` skips any revenue entry
  with a named one-off — a fact read off the extraction, not a guess about
  what the story is about — and that alone reproduces the required silence on
  the HSBA fixture without any category/headline heuristic.
- `compute_sequential_base(cand)` in gates.py is the factored-out arithmetic
  (§4 step 3); `_gate_low_base` is now a thin wrapper over it, unchanged
  behaviour, verified by test.
- The vet prompt block never states an exact fiscal year for the "preceding
  half" (`_low_base_fy_series` only ever returns bare values, not years) —
  it reads "the latest full fiscal year's total revenue" instead of
  "FY2025". Accurate, just less specific than the worked example in §5;
  revisit only if the vet's rationale text turns out to need the label.
**Goal:** stop the vet marking a story down for a comparison it could have made.

---

## 1. The defect, with the evidence

The vet's system prompt asks it to work out the *sequential* trend — this half
versus the half immediately before — because a figure quoted year-on-year
against a weak base can be a deceleration dressed as growth. It is told how:
`preceding half = full-year total minus the prior-year half quoted in the
announcement`.

On the 2026-08-04 06:04 batch, five rows were vetted. Auditing the arithmetic by
hand and re-running `gates._gate_low_base` over the stored extractions:

| symbol | Python computed | vet said | agree? |
|---|---|---|---|
| ELIX | +13.5% above | derived it by hand, "sequentially ahead" | yes |
| CTEC | −2.1% below | "revenue is below H2 2025" | yes |
| HSBA | `metric_unmapped` (figure is PBT) | declined — basis mismatch | yes, both decline |
| CGEO | `quarter_unsupported` | did not attempt | yes, both decline |
| **FRES** | **+28.9% above** | "cannot be verified" → **45, low confidence** | **no — Python is right** |

FRES had every ingredient: the announcement printed H1'25 revenue US$1,936.2m
(the model captured it correctly into `low_base.prior_year_value`), and FY25
revenue US$4,561.2m was in the prompt's own annual block. 4,561.2 − 1,936.2 =
2,625.0, against H1'26 of 3,382.6 → **+28.9%**. The vet said the comparison
could not be made and marked the score down for the gap.

**The `+28.9%` is already in the database.** `record_low_base_evaluation` ran
milliseconds after the vet call and wrote it to `rns_gate_evaluations`. The
model scored the row before anything computed it.

### The reframe — read this before designing anything

The model is **not** bad at this arithmetic any more. It got ELIX and CTEC
right, and correctly *declined* HSBA and CGEO on genuine basis/period grounds.
The July audit's 4-of-5 wrong-direction failure rate does not reproduce; turning
reasoning on for the vet (2026-07-31) appears to have fixed it.

The remaining defect is **variance in whether the calculation is attempted at
all**. Python never forgets. So the target is not "replace bad arithmetic with
good arithmetic" — it is "guarantee the number is present in the prompt".

That is a smaller, safer change than the original Phase 4 framing in
`docs/rns-gate-block-plan.md`, which assumed the model's arithmetic was the
problem.

---

## 2. What already exists — do NOT rebuild these

- **`gates._gate_low_base`** (`gates.py:283`) — the full derivation. Route 1 uses
  a printed preceding period; Route 2 does `preceding = fy[0] - prior`
  (`gates.py:350`). Verified correct against all five rows above.
- **`gates._low_base_fy_series`** (`gates.py:261`) — pulls FY totals via
  `showcase._annual_history`.
- **`showcase._parse_money`** (`showcase.py:1095`) — handles `US$3,382.6m`,
  `£89.0m`, `GEL 690,727k`.
- **Constants** (`gates.py:216-218`) — `_LOW_BASE_HALVES`, `_LOW_BASE_PERIODS`,
  `_LOW_BASE_METRICS`.
- **The mis-copy guard** (`gates.py:319`) — if `preceding_period_value` equals
  `prior_year_value`, distrust it and fall through to the FY-derived route. It
  exists because v4-flash once copied the prior-year half into both fields.
  **Keep this behaviour in any new path.**

The machinery is built and correct. **The only defect is ordering**: it runs
after the vet has already scored (`showcase.py:1358` then `:1375`).

---

## 3. Why the fix is not simply "swap those two lines"

The computation needs the prior-year same-period figure, which only exists in
the announcement text — so it depends on an LLM extraction. Today that
extraction (`low_base`) is produced by the same call that does the scoring.

**But pass 1 already extracts comparable data.** `earnings_quality` carries
`item` / `period` / `value` / `prior_value` for every material line, on every
ranked row (~1,000/month, versus ~107 that reach the vet). Checked against the
same five rows:

| symbol | revenue captured with a prior? |
|---|---|
| ELIX | yes — `Revenue H1 2026: £89.0m / £71.2m` |
| HSBA | yes — `Revenue 1H26: $37.7bn / $34.1bn` |
| CGEO | net income only — `1H26: 720,646 / 988,747` |
| **FRES** | **no** — profit, EPS, tax, costs, but no revenue line |
| **CTEC** | **no** — operating profit and EPS only |

So the data is *sometimes* already there, and absent on exactly the row that
failed. Making it reliable is a prompt tweak to pass 1, not a new LLM call.

### Two constraints that shape the design

1. **Period strings are free text**: `H1 2026`, `1H26`, `2Q26` all appear.
   `_LOW_BASE_PERIODS` needs `H1`/`H2`/`Q1`–`Q4`. Needs a normaliser.
2. **Profit measures are NOT safely mappable.** Announcements quote *adjusted*;
   `annual_financials` stores *statutory*. CTEC prints
   `Adjusted operating profit $262m` next to `Reported operating profit $115m`
   for the same period. Subtracting an adjusted half from a statutory full year
   produces a plausible-looking wrong answer. The July extraction eval reached
   this independently and concluded profit measures must go `n/a`.
   **Revenue is the only safely mappable line** — there is no "adjusted
   revenue". Scope the first cut to revenue only.

---

## 4. Build steps

### Step 1 — make pass 1 reliably capture the top line
`rns_llm.py:568`, the `earnings_quality` schema block.

Add an explicit requirement: on any results/trading-update announcement, always
emit an entry for the **top-line revenue/turnover** with its prior-period
comparator, even when nothing about it is remarkable. Today the instruction is
"every material income or charge line", and the model reasonably omits revenue
when the story is about margins or one-offs.

Extraction is a copying task, so thinking-off (current default) is fine.

*Consequence to accept:* this changes the ranker prompt, so `llm_score` is not
strictly comparable across the change. There is no prompt-version column —
`llm_model` records only `:fast`/`:thinking`. Consider adding one (see §7).

### Step 2 — period normaliser
New helper in `gates.py`, next to the constants at `:216`.

Map `H1 2026` / `1H26` / `H1` → `H1`; `2Q26` / `Q2 2026` → `Q2`. Return `None`
on anything unrecognised — never guess. Unit-test the real observed forms
above plus junk.

### Step 3 — factor the computation out of the gate verdict
`gates.py:283`.

Split `_gate_low_base` into:
- `compute_sequential_base(cand) -> dict | None` — the arithmetic and its
  evidence (`current_value`, `preceding_value`, `delta_pct`, `basis`, plus the
  two inputs and where each came from).
- `_gate_low_base` — unchanged behaviour, now calling the above and applying the
  seasonality/blocking logic on top.

**Why the split matters:** CTEC's gate state is `n/a`
(`seasonality_unadjudicable`) but its evidence still holds the −2.1%. The prompt
wants the *number* regardless of whether the gate would block on it. Do not gate
the prompt feed on the gate's verdict.

### Step 4 — source the computation from `earnings_quality`
New function, `showcase.py`, near the other prompt helpers.

Given a candidate, find a revenue entry in `earnings_quality` whose period
normalises to `H1`/`H2` and which has a parseable `value` and `prior_value`,
then call `compute_sequential_base`. Return `None` when there is no usable
entry — silence is correct, a guess is not.

Precedence if both are available: prefer a **printed** preceding period over a
derived one (mirroring Route 1/Route 2 in the existing gate).

### Step 5 — put it in the vet prompt
`showcase._vet_messages` (`showcase.py:587`), as its own block near the annual
financials.

Show the **inputs as well as the answer**, so the model can reject a bad one:

```
Sequential comparison (computed by us, not by you)
  H1 2026 revenue US$3,382.6m is 28.9% ABOVE the preceding half.
  Preceding half (H2 2025) = US$2,625.0m, derived as FY2025 total US$4,561.2m
  minus the H1 2025 figure of US$1,936.2m printed in this announcement.
  If either input looks wrong against the text, say so and disregard this.
```

And a line in the system prompt: where this block is present, use it rather than
deriving your own, and do **not** mark the score down for an unverifiable
sequential trend. Where it is absent, the existing instructions stand.

### Step 6 — leave the existing post-vet gate recording alone
`showcase.py:1375`. It validates the model's *own* extraction independently of
the new path, which stays useful as a cross-check. Note the redundancy in a
comment so nobody "tidies" one of the two away.

---

## 5. Test fixtures — use these exact rows

All five are real, from 2026-08-04, with figures verified by hand.

- **FRES — the canonical case.** Revenue H1'26 3,382.6, H1'25 1,936.2, FY25
  4,561.2 → **+28.9% above**. Must produce a block in the prompt. This is the
  row that failed.
- **ELIX — positive control.** 89.0 / 71.2 / 149.6 → **+13.5% above**. The model
  already got this right unaided; the computed figure must agree.
- **CTEC — negative-direction control.** 1,232 / 1,180 / 2,439 → **−2.1%
  below**. Must still surface the number despite the gate returning `n/a` for
  seasonality. Note: revenue is NOT in its `earnings_quality` today, so this row
  also tests Step 1.
- **HSBA — must stay silent.** The vet's figure is PBT. Even though revenue *is*
  in `earnings_quality` (37.7bn / 34.1bn, → +2.1% vs a derived H2'25 of
  36,920), emitting a revenue comparison for a row whose story is about PBT
  risks answering a question nobody asked. Decide deliberately; default to
  silence.
- **CGEO — must stay silent.** Q2, and `quarter_unsupported` is correct — there
  is no H1+H2=FY identity for quarters and `quarterly_financials` covers ~5% of
  the universe. Do **not** add a divide-by-4 fallback.

---

## 6. Acceptance criteria

1. FRES's prompt contains the sequential block with `+28.9%` and both inputs.
2. ELIX and CTEC produce blocks agreeing with the hand-checked figures.
3. CGEO and HSBA produce no block (no fabricated comparison).
4. No profit/EPS measure is ever mapped to an `annual_financials` column.
5. A missing or unparseable extraction degrades to today's behaviour — the
   prompt simply omits the block. **Never** publish a computed number the
   inputs do not support.
6. Full backend suite green.
7. Deploy-verified by reading the running container (see §8).

---

## 7. Risks and open questions

- **Resets the calibration sample again.** Both prompts change. As of
  2026-08-04 there were only 5 rows with a `vet_score` — the vet only became a
  scorer that day — so the cost is near-zero *now* and rises every day this
  waits. That argues for doing it soon rather than after a month of accumulation.
- **A confidently wrong computed number is worse than none.** This is why Step 5
  shows the inputs and invites contradiction, and why the `gates.py:319`
  mis-copy guard must survive.
- **Adjusted-vs-statutory is the trap that will bite** if scope creeps beyond
  revenue. It has already produced a −97.2% garbage answer once, in the Python
  meant to prevent exactly this.
- **Open:** should `llm_model` (or a new column) record a prompt version, so
  score eras are separable without archaeology? Currently only `:fast`/
  `:thinking` is recorded. Cheap to add now, impossible retrospectively.
- **Open:** HSBA-style rows where revenue is extractable but the story is about
  another metric — surface it anyway, or stay silent? §5 defaults to silence.

---

## 8. Deploy verification

No HTTP surface. Test for a **symbol** the commit introduces:

```bash
ssh root@167.233.123.195 'docker exec $(docker ps -qf name=finscopeapi|head -1) \
  python -c "import sys;sys.path.insert(0,\"/app\");import gates;print(hasattr(gates,\"compute_sequential_base\"))"'
```

Then confirm on the next weekday 06:04 batch that a vetted row's log shows the
block being used. See `project-hetzner-dokploy-backend` gotchas 1, 4, 6.

---

## 9. Related

- `docs/rns-gate-block-plan.md` — Phase 4, which built the machinery §2 reuses.
- `docs/rns-one-off-gate-plan.md` — same shadow-first discipline.
- `backend/analysis/rns_period_extraction_eval.py` — the 2026-07-30 eval that
  proved the model *can* supply these figures (backward axis 21/21) and found
  the three harness errors §3 is shaped around.
