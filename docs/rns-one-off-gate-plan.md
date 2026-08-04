# The `one_off` shadow gate — plan

Status: **NOT STARTED.** Written 2026-08-04 after the gate audit in
`docs/rns-gate-block-plan.md` (see the 2026-08-04 section) found that the RNS
vet's single most repeated objection has no gate at all.

Read `docs/rns-gate-block-plan.md` first — this plan reuses its registry, its
three-state contract, its shadow/armed distinction, and its §4 risk list.
Nothing here overrides it.

---

## 1. Why this exists

Across the 31 stored `vet_rationale` values, the objection the vet raises most
often is *the headline is flattered by something that will not repeat*:

| row | vet said |
|---|---|
| HSBA.L 9702338 (48) | "flattered by a $2.2bn net favourable swing in **notable items** and FX; underlying constant-currency PBT ex-notables rose only ~6%" |
| NWG.L 9697081 | "flattered by **£190m notable items** and the Evelyn Partners acquisition; underlying income growth ex-notables is only 8.9%" |
| CKN.L 9699653 | "Underlying PBT also benefits from **£5.9m acquisition-related cost add-backs**, flattering the headline" |
| STAN.L | "against a weak H1'25 base that included a **$238m gain on Solv India**; excluding that, growth is 8%" |
| FRES.L 9702443 (45) | "**entirely price-driven**, production volumes are falling" |
| CTEC.L 9702429 (60) | "the **InnovaMatrix impairment** and lowered outlook add real risk" |

The data to see this is **already captured**: `earnings_quality[].one_off_named`
on `rns_announcements`, populated by the ranker since migration 026. The
prompt (`backend/rns_llm.py:586`) asks the model to quote the company's own
words and forbids inferring an unnamed one-off, which is the right contract.

What is missing is any consumer. `showcase._named_one_offs`
(`backend/showcase.py:1014`) reads the field and **only `print()`s to the cron
log** — it writes no `rns_gate_evaluations` row, appears nowhere on `/gates`,
and therefore cannot be calibrated, queried, or argued about. It is the last
originally-deferred item from Phase 3 of the gate-block plan.

---

## 2. The measurements that shape the design

Run before writing any code, against prod, 30-day window. **Re-run these
first — if they have moved materially, redesign rather than proceed.**

**(a) Presence is far too common to ever be a blocker.**
683 `earnings_quality` entries, **122 carry `one_off_named`**, spread over
**75 of 145 ranked rows (52%)**. A gate that fires on half the universe is not
a gate. *Presence must never block. Not in shadow-then-armed, not ever.*

**(b) Materiality is computable on only 18% of them.**
Of the 122: line `value` money-parseable **105 (86%)**, but the one-off text
itself contains a parseable figure only **25 (20%)**, and **both → 22 (18%)**.
This is the existing `_named_one_offs` docstring's objection ("c.£225m against
increased 38% is not a computation") holding up under measurement. It is right.

**(c) Most computable ratios are degenerate.** Of those 22, the majority come
back at exactly 100% because the line *is* the one-off — `TW.L` "Cladding fire
safety provision" £222.2m vs "£222.2 million increase in cladding fire safety
provision". A naive ratio gate fires on all of these and looks like it is
working. The genuinely informative shape is the minority: `MRO.L` 2.6%,
`LLOY.L` 13.0%, `STX.L` 26.0% — a one-off that is a *fraction* of the line.

**(d) `_named_one_offs` discards half the signal.** It filters
`kind == "income"`, which is 60 of 122; the other **62 are `cost_or_charge`**,
and that is exactly where HSBA's restructuring and disposal losses live. Any
new gate must read both kinds.

**(e) Recall is bounded by the ranker, not by this gate.** `NWG.L` 9697081 has
**zero** `one_off_named` entries, yet the vet's central objection was "£190m
notable items". The vet reads the body; the ranker's structured extraction
missed it. **The gate can only ever be as good as that extraction, and here it
demonstrably is not good.** Measure this gap — do not assume the gate's misses
are gate bugs.

---

## 3. What the gate is

Register `one_off` in `GATES` (`backend/gates.py`), `mode="shadow"`,
`pool="wide"` — it reads `earnings_quality`, which every ranked Tier A/B row
carries, so the wide sweep can evaluate it. (Contrast `low_base`, whose pool
is `"vet"`. Get this wrong and you recreate the clobber this file's sibling
plan documents.)

**Phase 1 is a recorder, not a judge.** Its job is to make the sample exist.

```
block  — never in phase 1. The gate does not block, and `state="block"` is
         not written at all, so a future armed promotion cannot inherit an
         accidental precedent.
pass   — earnings_quality present and readable, no entry names a one-off.
n/a    — field_absent          earnings_quality missing/empty/not a list
         unnamed               entries exist, none carries one_off_named
                               (distinct from `pass`? NO — see below)
         not_quantified        one-off(s) named, but no figure parseable from
                               either side, so materiality is unknowable
         self_referential      the only computable ratios are ~100%, i.e. the
                               line IS the one-off (measurement (c))
         adjudicated           one-off named AND a real fractional ratio
                               computed — recorded in `evidence`
```

`pass` and `unnamed` are the same fact ("nothing named"), so use `pass` and
drop `unnamed`. The list above keeps it visible only so the next reader does
not re-invent it.

**`evidence` must carry, for every non-`field_absent` outcome:**
`n_entries`, `n_named`, `n_income`, `n_cost_or_charge`, and for each computable
one a `{item, period, kind, line_value, one_off_value, ratio_pct}`. Store the
parsed numbers alongside the printed strings — `low_base`'s history is that
whether a gate evaluates at all depended on prompt phrasing, and that was only
discoverable because the raw extraction was persisted (migration 028).

**Materiality ratio**, where computable:
`one_off_value / line_value`, both via `showcase._parse_money`. Guard the
degenerate case: a ratio within ~2pp of 100% means the line is the one-off, not
a one-off inside the line → `self_referential`, never an adjudication.

---

## 4. What it must NOT do

- **Must not block anything**, in any mode, in phase 1.
- **Must not infer a one-off the announcement did not name.** The prompt
  forbids it; the gate must not reintroduce it by keyword-scanning bodies for
  "exceptional", "restructuring", etc.
- **Must not treat direction as sign.** `one_off_named` is deliberately
  direction-neutral (`rns_llm.py:594`): a one-off *charge* that flatters the
  underlying trend is as disqualifying as a one-off *gain*. Do not filter to
  gains.
- **Must not change the ranker prompt.** Extraction recall is a real problem
  (measurement (e)) but fixing it is a separate change with its own evidence,
  and changing prompt and consumer together makes both unmeasurable.
- **Must not touch the public High Impact page.**

---

## 5. Promotion criterion — required at landing

`docs/rns-gate-block-plan.md` §4 names "shadow gates never getting armed" as a
failure mode, and requires the criterion be stated when the gate lands.

> `one_off` may be armed only on a **materiality threshold**, never on
> presence, and only once: (i) ≥ 30 rows have reached `adjudicated` within a
> single `llm_model` era; (ii) faceted by score band, the `adjudicated` rows'
> mean 1d excess on the `score >= 60` facet is negative; and (iii) the
> `population=reached_gates` facet is used for both — the wide pool overstates
> fire rates by ~11x on this page (measured 2026-08-04). If `adjudicated` has
> not reached 30 rows within 6 months, the honest conclusion is that
> materiality is not extractable and the gate should be **deleted**, not left
> in shadow forever.

At current rates ((b): 18% of 122/month) that is roughly 20 adjudicable
rows/month, so criterion (i) is ~2 months — but only if `self_referential`
does not eat most of them, which measurement (c) says it might. **Re-measure
after one month and reconsider before investing further.**

---

## 6. Controls

These are real stored rows; assert against them, not invented fixtures.

**Must come back `pass` (no named one-off):**
`ELIX.L` 9699755 (vet 80, approved) · `LSEG.L` 9694675 · `NWG.L` 9697081
— NWG is `pass` *and that is the known-wrong answer* (measurement (e)). Pin it
as a documented recall gap so nobody "fixes" the gate to catch it by inference.

**Must NOT block, and must be visible as named-but-not-adjudicated:**
`BA.L` 9694659 (2 income one-offs, **approved and published**) ·
`CKN.L` 9699653 (1 cost one-off, approved) · `RR.L` 9694691 (1 cost one-off,
approved). **These three are the whole argument against a presence rule** — it
would have suppressed three published stories.

**Should reach `adjudicated` with a fractional ratio:**
`LLOY.L` (£80m of a £617m impairment charge → 13.0%) ·
`MRO.L` (2.6%) · `STX.L` ($7.9M of $30.4M → 26.0%).

**Must come back `self_referential`, not adjudicated:**
`TW.L` cladding provision (£222.2m of £222.2m) · `RWA.L` one-off charge.

**Suggestive but must not be treated as evidence:** on the 5 rows that have a
real `vet_score`, the 4 shadowed (FRES 45, HSBA 48, CTEC 60, CGEO 65) all carry
≥1 named one-off and the 1 approved (ELIX 80) carries none. **n=5, one morning,
one model, interim season.** Perfect separation at n=5 is what a coincidence
looks like. It motivates the gate; it does not calibrate it.

---

## 7. Acceptance criteria

1. `one_off` appears in `GET /api/gates` with `mode: shadow`, and a `one-off`
   column renders on `/gates` (the page is already generic over `data.gates`;
   expect a one-line `GATE_LABEL` addition and nothing else).
2. `record_gate_evaluations` writes it for every ranked Tier A/B row —
   confirm `pool="wide"` by checking `gates_run` in the cron log includes it.
3. Every control in §6 returns its stated state, asserted in `test_gates.py`.
4. `blocking_reason()` is unchanged for every control — nothing newly blocks.
   A test must pin this directly.
5. Re-running the sweep over the last 30 days produces a non-trivial
   distribution across `pass` / `not_quantified` / `self_referential` /
   `adjudicated` — if it is ~100% one bucket, the design is wrong, stop.
6. `showcase._named_one_offs`' cron `print` is left alone or folded in
   deliberately, not orphaned by accident.

---

## 8. Risks

- **The 52% base rate is the whole problem.** Everything here exists to find a
  discriminator inside a signal that is present half the time. It may not
  exist. §5's delete clause is the honest exit.
- **`one_off_named` is free text, 300 chars, model-written.** `_parse_money`
  picks the *first* figure; a sentence naming two figures gives the wrong one.
  Record the raw string next to the parse so this is auditable later.
- **Extraction recall is unmeasured** beyond NWG being wrong. Consider a
  one-off manual read of ~10 vet rationales against their `earnings_quality`
  to size the gap before trusting any fire rate.
- **Model-era pooling.** Same trap as everywhere else in this system: the
  2026-07-16 `deepseek-chat`→`v4-flash` switch splits the sample. Facet by
  `llm_model`; never pool across it.
- **Adding a second uncalibrated shadow gate** while `guidance_wide` and
  `low_base` are both still accruing means three shadow gates and finite
  attention. Accepted deliberately — this one costs no LLM call and reads a
  field already stored — but do not add a fourth before one is resolved.

---

## 9. Files

- `backend/gates.py` — `_gate_one_off`, register in `GATES` with
  `pool="wide"`, `mode="shadow"`.
- `backend/showcase.py` — reuse `_parse_money`; decide `_named_one_offs`' fate
  (§7.6). No prompt change, no flag-path change.
- `backend/tests/test_gates.py` — §6 controls, §7.4 no-new-blocks test.
- `frontend/src/app/gates/_client.tsx` — one `GATE_LABEL` entry.
- No migration. `rns_gate_evaluations.gate` is free text.
