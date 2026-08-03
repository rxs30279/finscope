# Link an amendment to the announcement it corrects — plan

**Goal: make a corrected announcement resolvable to its original, so a
figure-restating amendment cannot leave superseded numbers on the public
showcase or feed a Python gate.**

**Read the scope note first: this is a guard against a class, not a fix for an
observed failure.** Every correction in the measured window is a date, a word,
or a reformat. Nothing has been misreported because of this. The reason to write
it down now is that the population is exactly the population where stale figures
are most likely — an amendment exists *because* something was wrong — and
Phase 4 of `docs/rns-gate-block-plan.md` is about to start adjudicating printed
figures in Python, where a superseded number is invisible rather than merely
wrong.

Sizing decision up front: the addressable population is **4 announcements in
4,335**. Build the smallest thing that records the link and makes it visible.
Do not build a versioning system.

---

## 1. Measurements

Taken 2026-07-30 over the full `rns_announcements` table (4,335 rows).

**Headline matching is not detection.** A regex on
`(amendment|replacement|correction|amended)` in the headline returns **45** rows.
Only **4** of those carry a correction preamble in the body. The other 41 are
mostly a different thing entirely:

| Headline | What it actually is |
|---|---|
| `Execution of Amendment rig contract to drill MOU-6` (PRD, tier B) | a contract amendment — a normal operational announcement |
| `Amended JDA with Licella Holdings` (QED) | a commercial agreement |
| `AMENDMENTS TO THE ARTICLES OF ASSOCIATION` (AIRC) | governance |
| `Correction: Director / PDMR shareholding` (STAN) | a real correction, but to a tier C holdings notice |

So **detection must key on the body preamble, never the headline.** The four true
corrections all print a machine-readable one, naming the original by RNS number
and timestamp:

> "The following amendment has been made to the 'Trading Update' announcement
> released on 28/07/2026 at 7:00 a.m. under RNS No 0234O: In the first sentence
> below the Financial Highlights bullet points, "Journeo had a strong H1 2025"
> has been changed to "Journeo had a strong H1 2026". All other details remain
> unchanged."

**The four true corrections are all tier A/B** (3 A, 1 B) — i.e. all in the
population that reaches the ranker. Tier C is a hard drop before the LLM, so
corrections to tier C rows are out of scope by construction.

**No correction has ever reached the showcase.** Zero rows in
`high_impact_rns` have an amendment-shaped headline. The originals are what got
flagged; the corrections scored below the 75 threshold and stopped there.

**Every observed correction is non-substantive:**

| Row | Change |
|---|---|
| `JNEO` 9691776 | "strong H1 2025" → "strong H1 2026"; all figures identical |
| `JDW` 9681606 | "19 July 2025" → "19 July 2026"; "All other details remain unchanged" |
| `MEX` 9688615 | reformatted; "All material details remain unchanged" |
| `DIA` 9692144 | an EBT shareholding percentage |

**There is no systematic score penalty for being a correction** — a hypothesis
this measurement killed. Pairing each correction against its own original
(same ticker, within 36h, non-correction headline) gives n=4:

| Ticker | Correction | Original | Δ |
|---|---|---|---|
| JNEO | 55 | 75 | **−20** |
| JDW | 35 | 35 | **±0** |
| PAIM | 5 | 0 | +5 |
| MCJ | 20 | 30 | −10 |

Mean −6.2, lower in 2 of 4. The earlier guess that an administrative preamble
drags the score down does not survive: `JDW` scored **identically** on
near-identical text. What the JNEO pair does give is the cleanest single data
point available for `llm_score` instability — a 20-point spread where the input
differs by one word — which belongs to that argument, not this one.

## 2. Design

**Detect on the preamble.** A correction is a row whose body opens with a
reference to a prior announcement: `following (amendment|correction|change)s?
(has|have) been made`, `announcement released (today|on)`, `has been
(reformatted|replaced)`, `under RNS (No|Number)`. Headline text may raise
suspicion but never decides.

**Resolve by (ticker, prior announcement).** The preamble names a time and an
RNS number. We do not store RNS numbers, so match on ticker plus the most recent
non-correction announcement before this one within a bounded window (36h covers
all four observed cases; JNEO's gap was 7h45m). Record the result in one new
nullable column, `amends_rns_id`, and **leave it NULL when the match is
ambiguous** — a wrong link is worse than no link.

**Do not re-rank, re-vet, or rewrite the original.** That would breach the
point-in-time integrity `rns_score_perf.py` depends on, the same constraint
`rns_body_context_validation.py` documents. The link is a pointer, not a
mutation.

**What consumes the link:** initially nothing. Recording it, and making it
visible on `/gates` beside the row it corrects, is the whole of Phase 1-2. A
correction that restates a figure has never been observed, so the handling for
one cannot be designed against evidence yet — and guessing at it is how you get
a mechanism that fires wrongly on a population of four.

## 3. Phases

### Phase 1 — record the link, change nothing
Migration adding `amends_rns_id BIGINT NULL` plus the detector, run over history
as a backfill. Report how many of the 45 headline matches resolve to a real
original and how many stay NULL. **Acceptance: exactly the four known
corrections link, and no tier C holdings notice acquires a spurious parent.**

### Phase 2 — make it visible
Show it on `/gates`: a row carrying `amends_rns_id` gets a marker, and a flagged
row that has *been* amended gets one too. This is the cheap version of the guard
— a human reading `/gates` can see the original was corrected, which is more
than exists today.

### Phase 3 — only on evidence
If a correction is ever observed restating a figure that a flagged row or a gate
relied on, that incident designs the handling. Until then, stop at Phase 2.
Write the incident up here when it happens.

## 4. Risks

- **Building more than 4 rows justify.** The strongest argument against this
  plan is that ~0.09% of the feed does not warrant schema change. The counter is
  that Phase 1-2 is one nullable column and one detector, and that Phase 4 of
  the gate plan raises the cost of a stale figure from "a wrong label" to "a
  wrong block". If Phase 4 is deferred, defer this too.
- **Preamble format is issuer-dependent.** Four samples is not a specification.
  ATYM's "Correction re: Q2 2026 Operations Update" and STAN's PDMR correction
  are real corrections that the preamble regex does **not** catch, so recall is
  unknown and probably below 100%. Failing to link must stay harmless — hence
  NULL rather than a guess, and hence nothing consuming the link in Phase 1.
- **Window matching is a heuristic.** 36h fits all four observed gaps but an
  issuer correcting a week-late announcement would mislink or miss. Prefer miss:
  bound the window and leave NULL outside it.
- **The original stays on the showcase either way.** This plan does not remove or
  replace a flagged row, so a figure-restating correction would still need a
  human to act. That is deliberate for now — automatic withdrawal of a public
  showcase row on a heuristic link is a worse failure mode than a stale row.

## 5. Out of scope

- Any change to `llm_score`, to `HIGH_IMPACT_MIN_LLM_SCORE`, or to tier
  assignment. A correction scoring 55 while its original scored 75 is the score
  instability problem, tracked with `docs/rns-gate-block-plan.md`'s scope note,
  not this one.
  <!-- 2026-08-03 (5d6f7f5): HIGH_IMPACT_MIN_LLM_SCORE no longer exists — split
       into HIGH_IMPACT_VET_ENTRY_SCORE (60) and HIGH_IMPACT_MIN_VET_SCORE (75).
       llm_score itself is still untuned, so this scope line still holds in
       substance. NOTE for this plan specifically: the JNEO 75->55 instability
       case now matters MORE, because 60 is the entry floor — an amendment can
       drop a row out of vet eligibility entirely, not just below the flag. -->

- Re-ranking or re-vetting history in place.
- Storing RNS numbers as a first-class identifier. Worth revisiting only if
  window matching proves insufficient.
- Corrections to tier C announcements.

## 6. Acceptance criteria

1. **Detection precision on the known set**: all four true corrections
   (`JNEO` 9691776, `JDW` 9681606, `MEX` 9688615, `DIA` 9692144) are detected,
   and none of the 41 headline false positives is — checked explicitly against
   `PRD`'s rig-contract amendment and `AIRC`'s articles amendment.
2. **No spurious parents**: every `amends_rns_id` written points to a
   same-ticker announcement that precedes it, and the count of non-NULL links
   over history is exactly 4 after the Phase 1 backfill.
3. **Nothing else moves**: `llm_score`, `vet_verdict`, `high_impact_rns`
   membership and the gate evaluations are byte-identical before and after the
   backfill.
4. **The migration enables RLS** on nothing new (column add only), and is
   idempotent under re-run.
