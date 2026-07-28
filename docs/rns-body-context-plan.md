# Give the RNS models more to work with — plan

**Goal: widen what the ranker and the vet actually see before they score an
announcement.** Today both read a single third-party paraphrase and nothing else.
Everything below is about closing that gap.

Scope decision: the High Impact entry threshold **stays at 75**. It is a live
calibration question with real evidence behind it (Appendix A), but acting on it now
would shrink the sample that answers it. This plan does not touch it.

Motivating incident: 2026-07-28, five announcements auto-flagged onto the High
Impact page, two fell the same session — LUCE.L **−11.8%** and BARC.L **−6.3%**,
both scored exactly 75/positive.

---

## 1. What the models are missing

`rns_llm.py:511` puts exactly one piece of announcement content in the prompt:

```
Investegate AI summary
{cand.get('summary') or '(not available)'}
```

`showcase.py:285` does the same for the vet. **Neither layer has ever seen an RNS
body.** The vet cannot act as a second opinion on the ranker because it reads the
identical paraphrase.

### LUCE — the disproving sentence was in the text we discard

The body carried, as a footnote ~85% of the way through:

> Company-compiled analyst consensus as at 27 July 2026 for full year Adjusted
> Operating Profit: 2026 **£40.7m**, with a range of £40.2m – £41.0m; 2027 £42.3m.

…against guidance of "the Board **continues to** expect Adjusted Operating Profit
for 2026 to exceed **£40m**" — the same figure as the 19 May Q1 update, when
consensus was £38.3m and it genuinely *was* an upgrade. Ten weeks on consensus had
overtaken it: an unchanged guide, now below the consensus midpoint. The model wrote
"significantly exceeds market expectations".

Also dropped by the summary: *"changes to the regulated mechanics of Demand
Flexibility have begun to crystallise"*, expected to **reduce per-charger recurring
revenue** — the optionality behind the +68.9% six-month re-rating. And the word
*"continues"*, so a reiteration rendered as "The company expects…".

**Recoverable.** Everything needed was in the body.

### BARC — the model was right; the market disagreed

Not a comprehension failure. Q2 income £8,338m (+16%), Q2 PBT £3,252m (+31%), Q2
RoTE 16.1%, 2026 income target genuinely raised to c.£31.5bn, distributions +61%.
The thesis was accurate and the stock fell ~6% anyway, on things the body contained
and the summary omitted:

- **2028 targets reaffirmed, not raised** — *"remain committed to, and confident
  in"* — where the 2028 RoTE target is **>14%** against H126 actual **14.8%** and
  Q226 16.1%. Ambition already delivered reads as a ceiling.
- **Q2 buyback flat.** The "+50%" is H1 (£1,500m vs £1,000m); the quarterly
  announcement was £1,000m vs £1,000m, with CET1 at 14.3%.
- **Beat quality** — driven by the Investment Bank (Q2 +20%), the most volatile,
  lowest-multiple earnings stream Barclays has.

Positioning does not explain it: the prompt showed `6m +10.6%`, `P/E 11.8`,
`P/B 1.09`.

**Only partly recoverable, and say so honestly.** "Targets reaffirmed when the
market wanted them raised" is a market-psychology judgement, not reading
comprehension. The body would plausibly have pushed the score down; it would not
reliably have produced "negative".

One thing the body **would** have fixed outright — the vet's own rationale shows it
guessing at a printed number:

> "H1 2025 income ~£14.9bn based on FY 2025 total of £29.14bn minus H2 2025
> estimate…"

The first results table states **H125 total income = £14,896m**. The vet spent its
reasoning budget reconstructing a figure it was never shown.

### LUCE, second gap: the model has no memory of prior guidance

Knowing ">£40m" is a *reiteration* requires knowing what May said. The prompt has no
such channel, for two reasons — one structural, one that fixes itself:

- **Structural:** `_load_history` (`rns_llm.py:202`) passes only headline + category
  — never a figure. And its 60-day window excludes a Q1-May → H1-July cadence (70
  days) by construction.
- **Self-resolving:** the 19 May Q1 update isn't in `rns_announcements` because RNS
  ingest only began **2026-06-29** — the table holds 29 days. Not a bug, and not
  worth investigating.

Coverage today: only **62 of 305** issuers with a Tier A/B row have two or more, so
the addressable set for any prior-announcement feature is ~20% and rising.

---

## 2. Feasibility — measured, not assumed

**The body is already in the HTML we download.** `_fetch_summary` (`rns.py:1111`)
fetches the announcement page and reads `#collapseSummary`; the full text is on that
same response. Capturing it costs **zero extra HTTP requests** and no additional
rate-limit pressure.

Selectors, verified over 20 recent Tier A/B rows (**20/20 coverage**):

| Wire | Container |
| --- | --- |
| RNS | `div.fr-view-element` |
| PRN (PR Newswire) | `div.prn-announcement` |

Do **not** use `.art-board` — it matches 6 nodes per page, the first being chrome.

Body-length distribution (chars of extracted text): median **5,580**, p75 9,591,
p90 68,528, max 115,158 (COA) — and BARC alone was **246,861**.

Two distinct populations. **Trading updates — where consensus footnotes live —
cluster at 3–8k chars (~1–2k tokens).** Full interim/final results run 70–250k chars
(~18–60k tokens), mostly statutory tables and notes. A few rows are **stubs**
(238 / 340 / 465 chars) — bodies that only point at a PDF.

Volume: **~42 ranked A/B rows per weekday**. 30-day category mix: `trading_update`
191, `final_results` 185, `interim_results` 117, `board_change` 113,
`capital_raise` 97.

### Negative result: do not pre-extract consensus with a regex

I prototyped a consensus-sentence regex over 38 recent bodies: 13 hits, 25 misses,
and **several hits were the wrong sentence**. On LUCE itself it matched the
*leverage* sentence rather than the consensus footnote — `[^.]*` sentence-splitting
breaks on decimals (`£40.7m`, `1.5x`). It also matched an interest-rate-swap
valuation note on UTG. An extractor that silently returns the wrong sentence is
worse than none: it would have fed this very incident a false-precision input.
**Pass the body to the model.** Regex is for *truncation*, not *comprehension*.

---

## 3. Plan

Phases 1–2 are the substance and pay off immediately. Phase 3 is a separate input
channel whose value accrues over months rather than on landing — build its capture
half alongside 1–2 so the clock starts. Phase 4 gates the whole thing.

### Phase 1 — capture the body (`rns.py`)

- Add `_fetch_body(soup)` using the two selectors. Refactor `_fetch_summary` to
  parse the page **once** and return `(summary, body)` — one fetch, both fields.
- **Truncate at write time; store only what we would send.** Cap at **24,000 chars**
  via **head + tail**, not head-only: outlook statements sit near the top and in the
  CEO quote, consensus footnotes near the *end* (LUCE's was ~85% through). Suggested
  16k head / 8k tail with an explicit `[… N chars omitted …]` marker so the model
  knows the middle was cut. Under-cap bodies stored whole.
- Treat `< 600 chars` as a **stub**: store it but set `body_is_stub`, so the prompt
  can say "(body unavailable — announcement links to an external document)" rather
  than passing a fragment off as the full text.
- Migration `0NN_rns_body.sql`: `body TEXT`, `body_chars INT` (pre-truncation, for
  diagnostics), `body_fetched_at TIMESTAMPTZ`, `body_is_stub BOOLEAN`.
- **Storage guard.** The DB is at **287 MB against Supabase's 500 MB free tier**;
  `rns_announcements` is 3.5 MB today. Tier A/B rows are retained forever, so bodies
  must be bounded: ~1,250 A/B rows/month × ~6k median chars ≈ 7 MB/month, worst case
  ~30 MB. The body is only needed at scoring time — extend `_prune_old` to **NULL
  `body` after 30 days**, keeping `body_chars`/`body_fetched_at` for diagnostics.
  Steady state ~10 MB.
- Backfill mirrors `_backfill_summaries` (rate-limited, `body_fetched_at IS NULL`);
  reuse the existing endpoint rather than adding a second.

### Phase 2 — put it in both prompts

- `rns_llm.py:_build_messages` — new section **after** the summary, labelled as the
  primary source:

  ```
  Announcement text (verbatim, may be truncated)
  {body}
  ```

  Keep the summary. It is a useful lead, and dropping it is an uncontrolled second
  change landing at the same time.
- One tightly-scoped system-prompt clause: *when the announcement states
  company-compiled analyst consensus, compare the guided figure against it and state
  which side of consensus the guidance falls on; reiterated guidance ("continues to
  expect") is not an upgrade.* Resist writing more — LUCE had the positioning data
  (`6m +68.9%`, `upside +8.6%`) and a system prompt that already warns about
  priced-in news, and ignored both. Extra prose is not the lever.
- Optional second clause for the BARC mode: *multi-year targets reaffirmed rather
  than raised, when current performance already exceeds them, are a negative signal.*
  Lower confidence — treat as an experiment and validate in Phase 4 before keeping.
- `showcase.py:_vet_messages` — same body section. On identical inputs the vet
  cannot be a second opinion.
- Cost: median ~1.4k extra input tokens × ~42/day ≈ **60k tokens/day**; worst case
  ~250k at the 24k cap. Negligible on DeepSeek. Watch `_log_cache_usage` across the
  first run rather than reasoning about prompt-cache effects.

### Phase 3 — give the model a memory of prior guidance

**This is a data-accrual investment, not a fix — and that is the argument for
building the capture half early rather than late.** RNS ingest began 2026-06-29, so
the table is 29 days deep and only 62 of 305 A/B issuers have a second row. Nothing
built here helps LUCE-class cases for months. But every guidance figure stored from
today forward is available to that issuer's *next* announcement, so the payoff curve
starts the day capture ships and compounds from there. Deferring it just moves the
start of the curve.

- **Capture the figure at scoring time** (do with Phases 1–2). When the body states
  a guidance number, store it against the issuer. Cheap once the body is in hand,
  and it's the half that accrues.
- **Surface it in the history block** so "continues to expect >£40m" can be seen as
  unchanged. Only useful once an issuer has two captured announcements — expect a
  reporting-cycle lag (half-year cadence ⇒ ~6 months to broad coverage; quarterly
  reporters sooner).
- **Widen `_load_history` 60 → ~120 days.** Do it as part of the above, not
  separately. It is a no-op today (the whole table is 29 days) and becomes correct
  automatically as history fills — a Q1-May → H1-July cadence is 70 days and would
  otherwise be excluded by construction, permanently.

Set expectations accordingly: **do not measure this phase before ~Q4 2026.** If it
looks inert in the Phase 4 validation, that is the expected result, not a failure.

### Phase 4 — validate against labelled cases

- **LUCE 9689898** — must stop reading as a guidance upgrade; target is a score
  below 75 (or flipped sentiment) with the £40m vs £40.7m gap named in the thesis.
  **This is the acceptance test.** If it doesn't move, stop and reconsider.
- **BARC 9689888** — weaker target: score below 75. Do *not* expect "negative", and
  do not tune until it produces one — that is fitting to a single observation.
- **A control set of high scorers that worked** (from the `rns_score_perf.py`
  cohort) — the change must not flatten genuine catalysts.
- **The 70–250k-char monsters** (BOY, COA, BARC, INCH) — confirm truncation retains
  the outlook/targets material.

Re-ranking overwrites `llm_score`, and `rns_score_perf.py` depends on point-in-time
score integrity. **Diff into a scratch table or CSV; never re-rank history in place.**

---

## 4. Risks

- **Selector rot.** The classes around the body are obfuscated (`iz`, `jn`, `kv`);
  `fr-view-element` (Froala) and `prn-announcement` look stable but aren't
  contractual. Add a `rns.body_capture` healthcheck — WARN if the share of recent
  A/B rows with a non-stub body drops below ~80%. Silent degradation would return us
  to today's behaviour with no signal.
- **Score-distribution shift.** More context may move scores broadly, not just on
  these failure modes. Capture before/after distributions in Phase 4 — and note the
  interaction with Appendix A: **this work invalidates the threshold measurement**,
  which must be re-derived on post-change data.
- **Overfitting to two bad days.** Two losses is not a validated failure mode. The
  body fix is justified on its own terms — we were withholding the primary source
  from both models. The prompt clauses are not, and are marked as experiments.
- **Truncation cutting the wrong middle.** Mitigated by head+tail and the omission
  marker, but a footnote midway through a 200k-char document is still lost.
  Acceptable — those are the announcements where the summary was least load-bearing.
- **Latency.** No new requests, but larger prompts on 5 parallel workers in the
  07:00 batch. There is ~13 minutes of headroom to the 07:20 digest. Measure it,
  don't assume it.

## 5. Out of scope

- **External broker consensus feeds.** The company-compiled figure printed in the
  announcement is free, point-in-time correct, and is what the market traded against.
- **The entry threshold.** See Appendix A — deliberately held at 75.

## 6. Acceptance criteria

1. ≥95% of new Tier A/B rows have a non-stub `body` within one ingest cycle.
2. LUCE 9689898 re-ranked no longer reads as a guidance upgrade, and the thesis
   names the consensus gap.
3. Control-set high scorers do not collapse.
4. `rns_announcements` stays under ~20 MB after the 30-day body prune.
5. Full suite green (`cd backend; python -m pytest tests/ -q`) with new coverage for
   `_fetch_body` (RNS node, PRN node, missing node, stub, over-cap truncation).

---

## Appendix A — the entry threshold: measured, deliberately parked

**Decision (2026-07-28): keep `HIGH_IMPACT_MIN_LLM_SCORE = 75`.** Recorded here so
the analysis isn't redone, and so the reasoning is available when it *is* revisited.

The threshold sits on the modal score. Scores are quantised to round numbers — over
60 days: 70→47 rows, **75→49**, 80→14, 85→46, 90→5, 95→7, 100→2. Nothing lands
between 75 and 80, so page inclusion for the largest single cluster turns on a
boundary the model cannot resolve. Four of the five entries flagged on 07-28 scored
exactly 75.

Performance by **exact score** (positive sentiment, matured, day-1; `intraday` =
open→close, the only tradeable leg — median / hit%):

| score | n | gap (untradeable) | **intraday** | excess 1w |
| --- | --- | --- | --- | --- |
| 75 | 11 | +1.77% / 73% | **−0.71% / 45%** | +0.31% / 67% (n=6) |
| 80 | 6 | +2.91% / 67% | **−0.30% / 50%** | −1.89% / 33% (n=3) |
| 85 | 12 | +3.10% / 75% | **+1.14% / 75%** | +0.37% / 57% (n=7) |
| 90 | 1 | +1.49% | +2.94% | +1.74% |
| 95 | 4 | +26.18% / 100% | −0.07% / 50% | −0.24% / 0% (n=3) |

The 80 bucket has no edge of its own; all the tradeable edge sits at 85. (The 95s
are bid situations — +26% gap, nothing left intraday.) Cumulative:

| gate | n (matured) | intraday | **hit%** | eligible rows / 60d |
| --- | --- | --- | --- | --- |
| ≥75 | 34 | +0.37% | 59% | 63 |
| ≥80 | 23 | +0.41% | **65%** | 36 |
| ≥85 | 17 | +0.41% | **71%** | 25 |

**Why hold at 75 anyway:**

1. **n=6 to 17 per bucket.** Directional, not conclusive.
2. **Raising the gate starves the measurement.** The 75 bucket is the cohort that
   answers the threshold question, and it has 11 matured observations. Cutting it
   off now stops the evidence accruing for a decision made on thin data.
3. **Phases 1–2 invalidate the numbers anyway.** More input shifts the score
   distribution; a threshold derived pre-change doesn't transfer.

**Revisit when:** the 75 and 85 cohorts each have ~30 matured observations *on
post-Phase-2 scores*, or the page starts costing real money. Re-run
`rns_score_perf.py --sentiment positive` and rebuild the tables above.

## Appendix B — the sentiment gate is NOT a defect

Recorded because it was investigated and **wrongly written up as a defect** — don't
repeat the mistake. `flag_high_impact_candidates`' SQL selects `r.llm_sentiment`
(line 352) and never filters on it, which reads like a missing gate. The filter is
in Python, immediately after the query:

```python
# showcase.py:427
for c in cands:
    if _sentiment(c) != "positive":
        skipped_sentiment += 1
        continue
```

`_sentiment()` (`showcase.py:88`) is *stronger* than a SQL column check: category
override → stored `llm_sentiment` → thesis keyword scan → `keyword_hits` counts.
Negative-sentiment high scorers never reach the page — over 60 days, 14 rows scored
≥80 with negative sentiment (BOOT 85, NACON 85, HEAD 85, CBA 80) and none were
flagged. BOOT in particular passes every SQL gate and is stopped here.

**Lesson: read past the query into the loop before declaring a filter missing.**
