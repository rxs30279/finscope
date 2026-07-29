# Judge the composition of reported earnings, not just the guidance — plan

**Goal: catch the BARC failure mode — headline growth that is partly
non-repeating, alongside a deteriorating charge trend, reported in an
announcement that genuinely did raise guidance.** The guidance gate shipped in
`6b73dfb` cannot reach this class of announcement by design, and measurement
confirms it never fires on one.

Scope decision: the High Impact entry threshold **stays at 75**, and
`llm_score` is **not** tuned. This plan follows the architecture the previous
one arrived at — the model extracts facts, Python adjudicates — and adds no new
dependence on the score.

Sequencing decision: ~~do not start Phase 1 until the 2026-07-29 07:00 batch
latency reading is in.~~ **RESOLVED 2026-07-29 — the reading is in and the block
is lifted. This plan is cleared to start.** The body change cost no measurable
latency: p90 scored 07:07:29 UK against a pre-body band of 07:05–07:08, median
end-to-end 6.5m against 5.3–6.7m, and a max of 11.6m that is the *best* tail of
any high-volume day. `rns.morning_batch` did WARN (last story 07:11:34, 26s
before the 07:12 send) but that is a volume effect — n=55 was the largest
morning burst on record, and 07-27 pre-body already overran at 07:13:16 on n=29.

The headroom is nonetheless thin at high volume, so Phase 4 keeps the latency
acceptance criterion, and Phase 0 below now exists partly to buy some of it back.

Day-1 production readings that strengthen the case for this plan: of **75
`guidance_checks` entries across the batch, 68 were `no_consensus_stated`**.
The guidance gate can only act when the announcement prints its own consensus
figure, and large caps mostly don't — both flags that day (RIO 75, STAN 75) had
zero consensus figures across 11 combined entries, so the gate was a no-op on
them by construction. `skipped_guidance` was 0. **The BARC-shaped gap this plan
addresses is not an edge case; it is the common case.**

Motivating measurement (2026-07-28, `--repeat 7` on the shipped prompt):
BARC 9689888 scored **[55, 60, 65, 75, 80, 80, 80]**, median 75, positive 7/7,
against a stock that fell **−5.5%** on the day. Four of seven runs clear the
flag threshold.

---

## 1. What the guidance gate cannot reach — measured, not assumed

### The gate provably never fires on BARC

Across all 7 runs, every `guidance_checks` entry came back `raised` or
`reiterated` paired with `no_consensus_stated`. Both labels are correct —
Barclays really did upgrade FY2026 group income to c.£31.5bn and NII to
>£13.7bn, and printed no consensus footnote. `_disqualifying_guidance`
(`showcase.py:387`) is deliberately narrow on exactly these two labels so that
ULVR stays flaggable, so no tightening of the guidance gate reaches this row.
**BARC is not a bug in the guidance layer. It is a different failure mode.**

### The facts are already in the prompt

Verified against the stored body (24,030 chars — at the truncation cap, so
head+tail applied; `industry = "Banks - Diversified"`, which
`quality.classify_risk_model` already routes to `"bank"`):

| Fact | Present | Position in stored body |
| --- | --- | --- |
| AA co-branded card portfolio sale | yes (×2) | 56% |
| c.£225m gain | yes (×16) | 48% |
| Credit impairment £1.4bn vs £1.1bn | yes (×12) | 7% |
| LLR 62bps vs 52bps | yes (×23) | 52% |
| Structural hedge income | yes | 54% |
| Mortgage margin compression | yes | 54% |
| USCB 575bps loss rate | yes | 72% |
| FCA motor finance redress | yes | 64% |

**This is not a retrieval or truncation problem.** Everything needed survived
into the 24k we send.

They are also printed in directly copyable form, adjacent to the figures they
explain:

> "Barclays US Consumer Bank (USCB) income increased 38%, driven by portfolio
> changes including a c.£225m gain from the sale of the American Airlines
> co-branded credit cards portfolio (AA portfolio) and the impact of the Best
> Egg Inc. (Best Egg) acquisition"

> "Credit impairment charges were £1.4bn (H125: £1.1bn) with an LLR of 62bps
> (H125: 52bps), including a £0.2bn single name charge in the IB in Q126"

### No field asks for them

The schema (`rns_llm.py:606-674`) has exactly two structured fields, both about
guidance. Everything else is free prose. The only slot these facts can land in
is `risks` — "one sentence: what would invalidate the thesis". Measured
outcome over 7 runs:

- **the £225m disposal gain was mentioned 0/7 times**
- **`risks` named rising impairments 1/7** (sample 3, "especially in US
  consumer"); the other six were macro boilerplate — "economic slowdown
  could…", "credit deterioration could…", written about a bank whose loss rate
  had *already* gone 52 → 62bps

The model can see it and usually doesn't bother. That is a container problem,
not a capability problem, and it is the same lesson as `guidance_checks`:
**an enumerated field gets filled in, a free sentence gets improvised.**

### Do not read the low samples as progress

Samples 4, 5 and 7 (55/65/60) all cite size — "modest relative to £68bn market
cap", "incremental for a large cap bank". That is the `e26ce44` size discount,
not earnings-quality insight. Nothing about the actual failure improved.

---

## 2. Design — extract quotes, adjudicate in Python

### The field

New `earnings_quality` array in `_build_messages`' JSON schema, emitted
**before `score`** so enumeration constrains the number rather than
rationalising it — same placement and same reasoning as `guidance_checks`.
One entry per material income or charge line the announcement itself
quantifies:

```
  item            as printed, e.g. "Credit impairment charges"
  period          e.g. "H1 2026" / "Q2 2026"
  value           as printed, e.g. "£1.4bn" or "increased 38%"
  prior_value     the comparator the announcement prints, else null
  kind            "income" | "cost_or_charge"
  one_off_named   the non-repeating contributor the announcement itself
                  names, quoted as printed, else null
```

Applied to BARC this yields, among others:

| item | period | value | prior | kind | one_off_named |
| --- | --- | --- | --- | --- | --- |
| IB income | H1 2026 | increased 20% | — | income | null |
| USCB income | H1 2026 | increased 38% | — | income | "c.£225m gain from the sale of the AA co-branded cards portfolio" |
| Credit impairment charges | H1 2026 | £1.4bn | £1.1bn | cost_or_charge | "£0.2bn single name charge in the IB" |
| Loan loss rate | H1 2026 | 62bps | 52bps | cost_or_charge | null |
| Credit impairment charges | Q2 2026 | £0.6bn | £0.5bn | cost_or_charge | null |
| Loan loss rate | Q2 2026 | 51bps | 44bps | cost_or_charge | null |
| Litigation and conduct | H1 2026 | £0.1bn | — | cost_or_charge | "provision for the FCA motor finance redress scheme" |

### `one_off_named` is a quote, not a boolean — do not "tidy" this

The obvious schema is `recurring: yes | no | unclear`. **Reject it.** It works
on the disposal gain and fails on everything else: structural hedge income
repeats but is a rate-cycle tailwind, IB income repeats but at wildly variable
magnitude. Both are defensible either way, so the model will flip run to run —
exactly the failure that splitting `verdict` into `vs_prior`/`vs_consensus`
fixed for guidance. Copying the clause the company already wrote is the same
operation as `guided_value`, which is stable 7/7.

It is also deliberately **direction-neutral**. The £0.2bn single-name IB charge
is non-repeating in a way that makes the underlying trend look *better*. Python
decides what a one-off means from `kind`; the model just marks that part of the
number does not repeat.

### `period` is mandatory

The body prints H1 and Q2 impairments a few hundred chars apart, and the cost
line is worse: *"Group total operating expenses were £4.5bn, up 7%
year-on-year — Group operating costs increased to £4.5bn (Q225: £4.1bn)"*.
Without `period`, Python will compare a half-year against a quarter and produce
a confident wrong answer. All comparisons happen within a single period.

---

## 3. Plan

### Phase 0 — move the schema block into the system prompt (`rns_llm.py`)

**Do this first, in the same commit, because it is only free while you are
already rewriting the schema block and re-running `--repeat 7` anyway.** As a
standalone change it was explicitly rejected: it is a prompt change, and against
a ±30pt score spread it needs full revalidation on LUCE/ULVR/BARC to justify
~$10/yr. Bundled here, the validation is already being paid for.

**The problem.** The JSON schema block (`rns_llm.py:606-674`, ~4,943 chars) is
byte-identical on every row but sits at the *end* of the user message, after the
per-row body. DeepSeek's caching is prefix-based, so it is billed at full
cache-miss rate every single time. Measured shape of the current ranker prompt
(mean over the 58 bodies from the 2026-07-29 batch, via
`backend/analysis/rns_prompt_shape.py`):

| segment | chars | stable across rows? |
| --- | --- | --- |
| system prompt | 3,742 | yes — the only cacheable prefix |
| user: per-row header/context | 1,898 | no |
| user: body | 13,785 | no |
| user: JSON schema block | 4,943 | **yes, but uncacheable where it sits** |
| **total** | **24,368** | cacheable share **15%** |

Moving the schema block into the system prompt lifts the stable prefix to 8,685
chars — **15% → 36% of the prompt**. This is also the explanation for the
observed bill going from <1c/day to 5c/day, a 5x jump against a predicted 2x:
volume rose 2.3x *and* the cached share halved at the same time, because the
system prompt did not grow while the body inflated everything after it.

**The real risk, and the mitigation — read this before implementing.** This is
not a pure win. Moving the instructions from immediately-after-the-body to
*before* ~14k chars of body puts them far from the point of use, and
instruction-following commonly degrades when the instructions are buried at the
top of a long context. Everything this project has learned about adjudication
says the model is already weak at holding an instruction across a long body.

So: **move the bulk, keep a short pointer at the tail.** End the user message
with a few lines restating only the ordering constraint, e.g.

```
Produce the JSON object exactly as specified in the system instructions.
Fill in guidance_checks and earnings_quality FIRST and let them constrain the
score — do not pick a score and then justify it.
```

That preserves the recency of the one instruction that is load-bearing (the
`guidance_checks`-before-`score` ordering, which is the whole reason enumeration
constrains the number rather than rationalising it) while the ~4.9k of field
descriptions move into cache.

**Treat a degradation here as a reason to revert Phase 0 alone**, not to abandon
the plan — it is independent of Phases 1–3 and must be separable at review time.

### Phase 1 — the field (`rns_llm.py`, migration `026`)

- Add `earnings_quality` to the schema block, ahead of `score`, with the field
  descriptions above. Keep the prose minimal — four iterations of prompt prose
  failed to fix adjudication on LUCE and it is not the lever here either.
- One clause in the `score` guidance: *income growth with a named one-off
  contributor is worth less than the headline rate; a rising charge rate is a
  negative however positively the announcement is phrased.*
- `_clean_earnings_quality`, mirroring `_clean_guidance_checks`: normalise
  `kind` to the two known values, coerce unrecognised to `"unclear"`, drop
  entries with no `item`. **Unparseable entries must normalise to something the
  gate treats as non-disqualifying** — a parsing miss must never silently drop
  a row.
- Migration `026_rns_earnings_quality.sql`: JSONB column + partial index,
  mirroring `025`. Persisted as the audit trail for why a row was or was not
  blocked; survives the 30-day body prune. Written via `psycopg2.extras.Json`
  in `_save_ranking`.

### Phase 2 — the number parser (`showcase.py` or a small shared module)

- `_parse_bps(s)` and `_parse_money(s)` handling the printed forms actually
  observed: `£1.4bn`, `c.£225m`, `62bps`, `increased 38%`, `>£13.7bn`.
  Return `None` on anything unrecognised rather than guessing.
- Pure functions, no I/O, exhaustively unit-tested against the strings in the
  BARC table above plus the LUCE/ULVR bodies. This is the piece most likely to
  be quietly wrong and the cheapest to test.

### Phase 3 — the gate (`showcase.py`)

Primary rule, bank-branched:

```python
def _worsening_loss_rate(entries, model):
    """A bank's loan loss RATE rising materially year on year."""
    if model != "bank":
        return None
    for e in _same_period(entries):
        if e.get("kind") != "cost_or_charge":
            continue
        cur, prior = _parse_bps(e.get("value")), _parse_bps(e.get("prior_value"))
        if cur and prior and cur - prior >= _BANK_LLR_RISE_BPS:
            return e
    return None
```

**Gate on the loan loss rate, not the absolute impairment charge.** Any bank
growing its loan book grows impairments; the absolute number rising is not
evidence of anything. The LLR is already normalised for book size, which is why
banks report it. 52 → 62bps is a real deterioration; £1.1bn → £1.4bn on its own
is not. This distinction is the whole reason the rule is bank-branched, and it
belongs in Python where it is written once and unit-tested, not in a prompt
where it is re-derived every morning against a 25-point score spread.

- Called alongside `_disqualifying_guidance` in `flag_high_impact_candidates`,
  before `_vet_candidate`, so a blocked row costs no LLM call.
- Returns `skipped_earnings_quality` in the cron dict, sibling of
  `skipped_guidance`.
- `model` comes from `quality.classify_risk_model` on the row already joined in
  the candidate query — no new plumbing, no new columns.

Secondary signal, **not gated**: `one_off_named` on a rising `income` entry.
Surfaced in the thesis and on the showcase card. Judging materiality needs the
one-off as a share of the growth, and the base is not reliably printed in
comparable form — "c.£225m" against "increased 38%" is not a computation. A
named, quoted fact is valuable to a reader even unquantified; it is not sound
enough to block on. See Risks.

### Phase 4 — validate with `--repeat`

Extend `backend/analysis/rns_body_context_validation.py` to print
`earnings_quality` alongside `guidance_checks`. Then, per the standing rule,
**every judgement below is made on `--repeat 7`, never a single sample.**

Phase 0 rides the same runs but is judged separately, because it is the one
change here that could silently degrade something already working:

- Confirm the emitted JSON still carries `guidance_checks` (and
  `earnings_quality`) **before** `score` — this is the ordering the whole
  enumerate-then-score design rests on, and it is what the tail pointer exists
  to protect.
- Confirm `guidance_checks` extraction on **LUCE 9689898 is still 7/7
  correct** and still blocked. LUCE is the regression canary for Phase 0: it is
  the row where a long body and a buried instruction already interact badly.
- Confirm the control set's score distribution has not shifted materially.
  Given the ±30pt spread this can only be a sanity check, not a proof — a
  changed median on one row is noise, all rows moving one way is not.
- Re-run `backend/analysis/rns_prompt_shape.py` to confirm the cacheable prefix actually
  landed at ~8,685 chars, then read **actual DeepSeek billing** a day after
  deploy rather than inferring the saving. Do not quote v4-flash rates from
  memory.

---

## 4. Risks

- **Calibration on n=1.** `_BANK_LLR_RISE_BPS` cannot be set from one
  announcement, and the previous plan already warns against tuning on BARC
  alone. Ship it commented as provisional with the 52 → 62bps observation as
  its only datapoint, and revisit once more bank results have landed — RNS
  ingest only began 2026-06-29, so the table is shallow on banks.
- **Enumeration instability.** Entry counts on BARC ranged **2 to 7** across
  runs (one sample found only the two FY2026 upgrades; another found seven
  including FY2028 targets). Harmless there because no entry was
  disqualifying, but the gate only fires if the model enumerates the bad entry
  at all. LUCE was 7/7, so this has never bitten. Measure it explicitly in
  Phase 4 and treat a low enumeration rate as a blocker.
- **Latency — the body change is now measured and cost nothing, but headroom is
  thin at volume.** On 2026-07-29 p90 landed 07:07:29 against a 07:12 send, but
  the *last* story landed 07:11:34 on a record n=55 burst. This plan adds output
  tokens across 5 parallel workers, and output is the slow part. Phase 0's
  larger cache prefix should partly offset input latency, but that is an
  assumption, not a measurement — verify it, don't rely on it. If the batch
  starts overrunning, Phase 0's tail-pointer split is also the cheapest knob:
  the schema block in cache is faster to prefill than the same block inline.
- **False positives on healthy banks.** Using LLR rather than the absolute
  charge is the main mitigation. A bank normalising off an unusually benign
  prior year could still trip it; the control set has no second bank to check
  this against, which is the honest limit of what this plan can validate.
- **Over-blocking generally.** Dropping a tradeable announcement is the
  high-severity error in this system. Every ambiguous path — unparseable
  numbers, unknown `kind`, missing `period`, empty array — must fail open.

## 5. Out of scope

- Gating on `one_off_named` / income composition (surfaced only, see Phase 3).
- Any change to `HIGH_IMPACT_MIN_LLM_SCORE`, to `llm_score` itself, or to the
  sentiment gate.
- Insurer, REIT and miner equivalents (reserve releases, revaluation gains,
  asset sales). The extraction field is sector-neutral and will capture them;
  only the bank rule is being built now.
- Dropping temperature to 0. Separate experiment, unrelated to this field.
- Re-ranking history in place. The validation script stays read-only —
  `rns_score_perf.py`'s point-in-time integrity depends on it.

## 6. Acceptance criteria

1. **BARC 9689888 is blocked in ≥6 of 7 runs** via
   `skipped_earnings_quality`. Note this is an *outcome* test, not a score
   test — as with LUCE, `llm_score` is expected to stay around 75 and that is
   fine.
2. **The control set gains no new blocks**: ULVR 9689925, COA 9689907,
   PCIP 9689852, JNEO 9689848, INCH 9689910, BOY 9690269 — all
   non-banks, so `_worsening_loss_rate` must return `None` on every run.
3. **LUCE 9689898 is still blocked by the guidance gate**, unchanged.
4. **Extraction stability**: the impairment and LLR entries appear with a
   parseable `value` and `prior_value` in ≥6 of 7 BARC runs. If enumeration is
   flakier than that, the gate is not dependable and the design needs
   rethinking before shipping.
5. **Parser unit tests pass** on every printed form in the BARC table.
6. **Morning batch still completes before the digest send** — checked on
   `rns.morning_batch` after the first batch post-deploy. Note this check now
   WARNs at high volume for reasons unrelated to this plan; judge it on p90
   (target: still ≤07:08) rather than on the last story alone.
7. **Phase 0 causes no behavioural regression**: `guidance_checks` /
   `earnings_quality` still emitted before `score`, LUCE still 7/7 correct and
   still blocked, control-set scores not systematically shifted. Phase 0 is
   revertible on its own if any of these fail — do not let it take the rest of
   the plan down with it.
8. **Phase 0 delivers the saving it claims**: cacheable prefix ~8,685 chars
   confirmed by `backend/analysis/rns_prompt_shape.py`, and the DeepSeek bill measurably
   below the 5c/day baseline a day after deploy. If the prefix grew but the bill
   didn't move, the caching assumption is wrong — record that and stop, rather
   than adding more prompt restructuring on top of a broken model of the cost.

---

## Appendix D — implementation record (2026-07-29)

Phases 0–4 built in one commit, as the plan intended (Phase 0 is only free
while the schema block is being rewritten anyway).

- **Phase 0** — `_JSON_SCHEMA_BLOCK` moved into the system message,
  `_SCHEMA_POINTER` restates the ordering constraint at the tail of the user
  message. `rns_prompt_shape.py` final reading: cacheable prefix **13,184 chars
  = 45%** of a 29,066-char prompt, against a 3,742/15% baseline. That is *above*
  the plan's 8,685/36% prediction because the prediction assumed the schema
  block stayed 4,943 chars — it is 9,680 with `earnings_quality` in it. The
  number that matters is uncacheable bytes per row: **20,626 → 15,882, −23%**.
  The billing half of criterion 8 needs a day of real DeepSeek invoices; do not
  infer it.
- **Phase 1** — `earnings_quality` added to the schema ahead of `score`;
  `_clean_earnings_quality` mirrors `_clean_guidance_checks` (unknown `kind` →
  `"unclear"`, which no gate matches; entries with no `item` dropped; None
  rather than `[]` when nothing usable came back). Migration `026` applied to
  prod 2026-07-29 — column and partial index both verified present.
- **Phase 2** — `_parse_bps` / `_parse_money` in `showcase.py`. `_parse_bps`
  deliberately refuses percentages: "increased 38%" read as 3,800bps would fire
  the bank gate on an income line's own comparator.
- **Phase 3** — `_worsening_loss_rate` gates on the loan loss RATE, bank-only,
  `skipped_earnings_quality` in the cron dict. `_BANK_LLR_RISE_BPS = 5`, set
  below **both** observed rises (H1 +10, Q2 +7) so the outcome doesn't depend on
  which period the model happened to enumerate. `_named_one_offs` reports the
  secondary signal to the cron log; it is not stored or shown on the card
  (see below).
- **Phase 4** — `rns_body_context_validation.py` now runs showcase's real gates
  over the model's own output and reports blocked/not-blocked per run, entries
  enumerated, parseable rate pairs, and whether the enumerate-before-score
  ordering held. The criteria are read off those lines, not off the score.

### Two defects the validation found, neither anticipated by the plan

**1. `max_tokens` was too small, and failed silently.** `earnings_quality`
roughly doubled the JSON answer against a cap (4000) sized for a ~400-token
one. The response is cut mid-string, `json.loads` raises, and
`_rank_pending`'s per-row isolation turns that into a row that is never
scored, never flagged and never in the digest — landing on exactly the
long-bodied large caps this field exists to judge. Measured failure rates:
**19/56 calls at 4000**, 1/7 at 6000, 0/28 at 8000. Raised to 8000, and
`_log_cache_usage` now prints completion/reasoning tokens with an explicit
`finish_reason == "length"` warning, so the next occurrence is a one-line
diagnosis instead of a re-run of this investigation. Note this failure path
pre-dates the plan; the field only made it frequent enough to see.

**2. The model would not enumerate the loan loss rate.** The first BARC run
blocked **0/7** — not a threshold problem, an input problem: the model
enumerated the impairment charge in £bn on every sample and the LLR in bps on
none, and `_worsening_loss_rate` ignores the absolute charge by design. Two
independent 7-sample runs at 8000 tokens (so not truncation) both gave 0
parseable rate pairs. Fixed with a `RATES COUNT AS LINES` clause in the field
description: **0/7 → 7/7 blocked, rate pairs 0,0,0,0,0,0,0 → 1,2,2,2,1,1,1.**

That clause then over-corrected — enumeration went exhaustive on long bodies
(BOY 2-5 entries → 5-22, INCH 2-8 → 5-13) and cost an INCH sample to the 8000
cap. Bounded with a ranked keep-list — named one-offs first, then rates with a
comparator, then the largest lines — which holds every row at ≤8 entries with
**0 truncations in 56 calls** and BARC still blocking 7/7.

### `vs_prior` is ~90% stable, not deterministic

Not a defect, but a property of the design that was not known when the plan was
written, and it qualifies the plan's claim that the structured field is steady
where the score is not. Across 29 LUCE samples on the final prompt the guidance
gate blocked **26 (90%)**; the three misses were `vs_prior` landing on
`unknown` or `new` instead of `reiterated`. The consensus side never wavered —
`>£40m` against `£40.7m` was extracted in every single sample. It cuts both
ways: JNEO, a control row, was blocked in 1 of 7 runs when its PBT line came
back `reiterated/in_line` rather than the `new/in_line` the other six gave.

So the field is far steadier than `llm_score` (42-point spread on the same
rows) but it is not a deterministic input, and a gate on it inherits a ~10%
label error in both directions. If that needs closing later, the targeted move
is to disqualify **any** `vs_prior` when the announcement printed a consensus
the guide fails to clear — that catches all three observed misses and stays
safe for ULVR, whose entries are all `no_consensus_stated`. Deliberately NOT
done here: it widens a gate the plan kept narrow, and it belongs in its own
before/after.

Built but **not** delivered, flagged rather than quietly dropped: the plan's
Phase 3 secondary signal says `one_off_named` should be surfaced "on the
showcase card". It is currently only logged. Putting it on the card needs a
column on `high_impact_rns`, an API field and a frontend change — none of which
appear in the acceptance criteria, and all of which are a wider surface than a
non-gating annotation justifies on the same commit as the gate. Left as a
follow-up decision.

## Appendix A — why the score was left alone again

BARC's 7-run spread was **25 points** (55–80) at temperature 0.2, against
LUCE's 30 and ULVR's 30. This is now three rows showing the same thing: the
score is not a stable enough quantity to gate on, and no prompt change has
narrowed it. The architecture of gating on enumerated facts in Python is
therefore not a workaround for one bad row — it is the only approach that has
produced a reproducible outcome.

## Appendix B — measurements this plan rests on

All from 2026-07-28, `rns_body_context_validation.py --only 9689888 --repeat 7`
against the shipped prompt at `6b73dfb`:

- scores `[55, 60, 65, 75, 80, 80, 80]`, median 75, spread 25, sentiment
  positive 7/7
- `guidance_checks` entries: all `raised`/`reiterated` + `no_consensus_stated`,
  7/7 — the guidance gate cannot fire
- `£225m` disposal gain named in the model's output: **0/7**
- rising impairments named in `risks`: **1/7**
- entries enumerated per run: **2 to 7**
- stored body 24,030 chars, `body_is_stub = False`, all nine target facts
  present

## Appendix C — day-1 production readings (2026-07-29, first batch with bodies)

Added after the plan was written; these are what lifted the sequencing block and
motivated Phase 0.

- **Capture is clean**: 56/57 Tier A/B rows carry a body, **0 stubs**, mean
  13,785 chars, several at the 24,030 truncation cap (RIO, STAN, ABDN).
  `rns.body_capture` PASS. `guidance_checks` populated on 26/59 ranked rows; the
  33 empties are legitimately guidance-free (directorate changes, drilling
  updates), not parse failures.
- **Latency: no body cost.** p90 scored 07:07:29 UK (pre-body band 07:05–07:08),
  median e2e 6.5m (pre-body 5.3–6.7m), max e2e 11.6m — the best tail of any
  high-volume day. Measure this **only** on write-once `published_at` →
  `llm_processed_at`: the 07-28 body backfill overwrote `summary_fetched_at` on
  every pre-existing row, so anything scoped on it silently drops or corrupts
  pre-body days.
- **The guidance gate is structurally a no-op on the rows that matter.**
  `skipped_guidance` = 0. It did correctly identify 4 LUCE-pattern rows (CDGP 55,
  FRAN 25, NICL 25, BREE 25 — all `reiterated`/`in_line` against a printed
  consensus), but the candidate SQL filters `llm_score >= 75` *before* the gate
  runs, so none reached it. And 68 of 75 entries batch-wide were
  `no_consensus_stated`.
- **Score distribution dropped sharply**: mean 28.6 vs 33–42 across the prior ten
  sessions, ≥75 rate **5.1% (3/59) vs 13–26%**. One day, confounded with day mix,
  and inside the known ±30pt noise — **do not recalibrate thresholds off it**,
  but do re-check it before trusting any acceptance criterion measured against
  the ≥75 band.
- Cost: <1c/day → 5c/day. Expected; ~$18/yr absolute. See Phase 0 for why the
  jump was 5x rather than the predicted 2x.
