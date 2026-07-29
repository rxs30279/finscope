# One Python gate block, and a page to calibrate it — plan

**Goal: turn the ad-hoc sequence of pre-vet checks into a single ordered
registry of named, testable Python predicates, and build a private page that
shows every gate's verdict on every candidate as a traffic light — so a gate
can be watched before it is armed.**

This is not a new architecture. It is the one `showcase.py:359-365` already
argues for, finished: *"The structured field is far steadier, so the decision
is made here in Python, deterministically and testably."* The LLM extracts
facts; Python adjudicates them. Today two gates follow that pattern and one
judgement (the growth-arithmetic vet) does not.

Scope decisions, both carried forward from the previous two plans:
`HIGH_IMPACT_MIN_LLM_SCORE` **stays at 75**, and `llm_score` is **not** tuned.
Three rows have now shown a 25-30pt spread on the same announcement; nothing
here adds a dependence on that number.

---

## 1. Why now — three measurements

**The gates cannot currently be measured at all.** A blocked candidate is never
inserted into `high_impact_rns`; it leaves a `print` in the cron log
(`showcase.py:661-679`) and nothing else. There is no record of what was
blocked, by which rule, or what the stock subsequently did. Every threshold in
the system is therefore calibrated on the sample that motivated it and cannot
be revisited without re-deriving it by hand.

**The thresholds are on n=1.** `_BANK_LLR_RISE_BPS = 5` (`showcase.py:501`) has
exactly two observations behind it, both the same real deterioration seen over
two windows. The comment says so and says to revisit — but there is no
mechanism by which revisiting would produce data.

**The gates mostly do not fire.** On 2026-07-29, `skipped_guidance` was 0. Not
because nothing deserved blocking — the gate correctly identified four
LUCE-pattern rows (CDGP, FRAN, NICL, BREE) — but because the candidate SQL
filters `llm_score >= 75` *before* the gate runs (`showcase.py:598`), so none
of them ever reached it. And 68 of 75 `guidance_checks` entries batch-wide were
`no_consensus_stated`, the one state in which that gate can do nothing.

`earnings_quality` is populated on **0 of 1,040** announcements from the last
three days; the first morning batch since `d0cf0bf` has not run. So the newest
gate has never been observed in production either.

### The case that started this

`SRT.L` and `CAPD.L` are both on the public showcase right now, both carrying
`vet_verdict = exclude` at `high` confidence:

> **SRT.L** — "Profit before tax of £10m is flattered by a 105% increase from a
> low base of £4.9m… net margins remain thin at 8.6%"

> **CAPD.L** — "Q2 2026 revenue of $117.3m is actually below the preceding
> half's implied quarterly run-rate of ~$172.9m (FY2025 $345.8m / 2)… the 34.2%
> year-on-year growth is against a weak Q2 2025 base"

Both were caught by prose reasoning in `_vet_messages` (`showcase.py:264-280`),
and prose reasoning does not gate: the vet is advisory and the row is inserted
`'approved'` regardless (`showcase.py:719`). **The strongest detector in the
system for this failure mode is the only one with no blocking authority.**

---

## 2. Design

### 2.1 Three states, not two

A gate returns one of three verdicts, and the third is the important one:

| state | meaning | light |
| --- | --- | --- |
| `pass` | the gate adjudicated this row and found nothing | green |
| `block` | the gate adjudicated this row and it fails | red |
| `n/a` | the gate **could not** adjudicate — wrong sector, field absent, number unparseable, entry lacked a `period` | amber |

Today all three collapse to "returned `None`", which is why nobody can tell a
gate that is passing rows from a gate that is structurally incapable of firing
on them. The 68/75 `no_consensus_stated` finding is an amber rate of ~91% and
it took a bespoke query to discover. **Amber rate is the primary health metric
of a gate**, and the reason the page exists.

Every `n/a` carries a machine-readable `reason` (`not_a_bank`,
`no_consensus_stated`, `unparseable_value`, `missing_period`, `field_absent`,
`gate_error`) so the amber column is diagnosable at a glance rather than being
a shrug.

### 2.2 The registry

```python
# backend/gates.py
@dataclass(frozen=True)
class GateResult:
    state: Literal["pass", "block", "n/a"]
    reason: str | None = None      # why n/a, or which rule fired
    evidence: dict | None = None   # the entry/figures the verdict rests on

@dataclass(frozen=True)
class Gate:
    name: str                      # stable slug — stored, never renamed
    description: str
    mode: Literal["armed", "shadow"]
    fn: Callable[[dict], GateResult]

GATES: tuple[Gate, ...] = (...)    # ordered; evaluation order is display order

def evaluate_all(cand) -> list[tuple[Gate, GateResult]]
def blocking_reason(cand) -> tuple[Gate, GateResult] | None  # first ARMED block
```

`evaluate_all` runs every gate regardless of outcome — the page needs the full
row, not just the first failure. `blocking_reason` returns the first armed
block for the flag path. **Every gate is wrapped in a try/except that converts
an exception to `n/a`/`gate_error`.** Over-blocking is the high-severity error
in this system; a bug in a gate must never drop a tradeable announcement.

### 2.3 Shadow mode is the whole point

A gate lands as `shadow`: fully evaluated, fully recorded, shown on the page,
**blocks nothing**. It is promoted to `armed` only when its recorded history
supports the threshold. This is what makes it safe to add gates faster than the
data arrives to calibrate them, and it is the direct answer to the n=1 problem
— `_BANK_LLR_RISE_BPS` would have shipped as shadow and been armed on evidence.

Mode lives in code, not config: it is a reviewable, revertible line in a
tracked file, and the recording table stores the mode in force at evaluation
time so history stays interpretable after a promotion.

### 2.4 Evaluate wide, block narrow — do not skip this

If gates are only evaluated on rows that clear `llm_score >= 75`, the page gets
~2-3 rows a day and nothing is ever calibrated. Gates over `guidance_checks`
and `earnings_quality` are **pure functions over stored JSONB with no LLM
cost**, so:

- **Evaluation** runs over all ranked Tier A/B rows, independent of score and
  of the market-cap/leverage/margin floors.
- **Blocking** happens only inside `flag_high_impact_candidates`, on rows that
  passed those floors, exactly as today.

**There is no backfill shortcut out of n=1 — measured, and it kills the
obvious plan.** Replaying the registry over history only works where the
extraction it reads already exists, and it barely does. `guidance_checks` is
non-empty on **26 rows, all from the single 2026-07-29 session** (first ever at
06:00 UTC that day); `earnings_quality` on **0 rows**. Against 1,016 ranked
Tier A/B rows going back to 2026-06-29, that is 2.6% coverage for one gate and
zero for the other. Producing the extractions for the rest means re-running the
LLM over historical bodies, which is out of scope by standing decision and
impossible anyway once the 30-day body prune has run.

So the backfill script is worth building for idempotency and for replaying a
changed threshold over rows already extracted — but **the sample accrues
forward, at roughly one session a day, and nothing changes that.** Plan the
promotion timeline accordingly (see Risks).

Facet everything on the page by score band — a gate's fire rate over all Tier
A/B rows is not its fire rate over flag candidates, and conflating them would
produce a confidently wrong precision estimate.

### 2.5 Recording

Migration `027_rns_gate_evaluations.sql`:

```
rns_gate_evaluations
  rns_id        FK -> rns_announcements(id)
  gate          text     -- Gate.name
  state         text     -- pass | block | n/a
  reason        text
  evidence      jsonb
  mode          text     -- armed | shadow AT EVALUATION TIME
  evaluated_at  timestamptz
  UNIQUE (rns_id, gate)   -- re-evaluation upserts
```

RLS enabled on creation (migration 016 rule). Upsert on re-evaluation so a
backfill re-run is idempotent and a re-armed gate refreshes cleanly.

### 2.6 The page — `/gates`

Private, exactly like `/status`: `robots: { index: false, follow: false }` in
`page.tsx`, `useIsAdmin()` in the client, data from an API route behind
`Depends(require_admin_token)`. Not in the nav, not in the sitemap.

**The matrix** — one row per candidate, newest first; one column per gate:

```
                                            guid  bank  base  1off   gap    1d     1w
BARC  H1 2026 Results              78  ●     ○     ●     ○     ▲    -2.1%  -5.5%  -4.0%
SRT   FY2026 Trading Update        80  ●     ○     ○     ●     ○    +1.2%  +0.4%   open
CAPD  Q2 2026 Trading Update       76  ●     ○     ○     ▲     ○    -0.3%  -1.8%  -6.2%
                                        ● block   ○ n/a   ▲ pass
```

Outcome columns reuse `rns_score_perf.py`'s conventions verbatim — entry at the
announcement-day **open**, day-1 decomposed into gap / intraday / since-news,
excess return against the AIM-vs-Main equal-weighted benchmark, and `open` /
`terminated` for horizons that cannot yet be filled. Do not invent a second
return convention; the whole point is that a red light next to `+8%` is a
false block and a green light next to `-5.5%` is the BARC miss.

**Volume, measured over the last 14 sessions**: 25-75 Tier A/B rows per day,
median ~42, essentially all of them ranked (1,016 of 1,040 since 2026-06-29).
So ~42 rows × N gate columns per day, ~200 a week.

### Cohort: not bounded by score

`/gates` is private, so there is no dilution risk to trade against and **no
score floor belongs in its cohort at all** — not 75, not 30. Score is not an
input to any gate; a loan loss rate rising 10bps or a guide reiterated below
consensus is the same fact at score 20 as at score 80. A score floor only
shrinks the calibration sample. Measured over 30 days on the category +
in-universe cohort: 248 rows at no floor, 171 at ≥30, **30 at the current ≥75**
— and on the one session where `guidance_checks` exists, only **2 of 19
adjudicable rows cleared 75**. The gate sees a tenth of the sample it could.

Score becomes a **column and a facet**, never a boundary. The cohort is bounded
only by whether gates have their inputs:

| cohort | rows/30d | ~per session | |
| --- | --- | --- | --- |
| all Tier A/B | 976 | 49 | toggle |
| in-universe (`ttm_financials` present) | 417 | 21 | toggle |
| **in-universe + category** | **248** | **12** | **default** |

Below that line every gate has what it needs. Above it, out-of-universe rows
have no `ttm_financials`, so market cap, margin, leverage and the bank
classification are all structurally amber — worth being able to see, since that
is the point of `in_universe` and `category` being lights rather than a silent
pre-filter, but not the default view.

**`HIGH_IMPACT_MIN_LLM_SCORE` is untouched at 75.** It governs public flagging
and is a separate product decision; changing it is not folded into this plan.

**Most rows will be all-amber, and that is correct.** On 2026-07-29 only 26 of
57 Tier A/B rows carried any `guidance_checks` at all — the other 31 were
directorate changes, drilling updates and similar, with nothing for any gate to
judge. The page must therefore **default to rows where at least one gate
adjudicated** (any green or red), with an explicit toggle to show everything.
A default view that is 55% blank teaches you to stop opening it.

Windowing: default to the latest session, with a date picker and a rolling
7/30-day option, since per-gate rates only mean anything pooled.

**The header** — per gate, over the selected window and score band: fire rate,
amber rate (with the dominant `n/a` reason), and once returns mature, mean
excess return of blocked vs passed rows. A gate whose blocked rows outperform
its passed rows is doing harm and the page should make that impossible to miss.

Shadow gates render in the matrix with a visual distinction (hollow marker or
dimmed column) — a red light that did not actually block must never read as one
that did.

---

## 3. Phases

### Phase 1 — the registry, with no behaviour change

`backend/gates.py`. Move `_sentiment`, `_disqualifying_guidance` and
`_worsening_loss_rate` behind `Gate` wrappers returning `GateResult`, all
`armed`. `flag_high_impact_candidates` calls `blocking_reason` instead of the
three inline checks (`showcase.py:652-690`). Counters become a dict keyed by
gate name instead of a variable per gate.

**Acceptance is that nothing changes**: the existing `test_showcase.py` cases
pass untouched, and a dry run over the last 30 days blocks exactly the same
rows as the current code. Land this alone. A refactor that changes behaviour
while claiming not to is the expensive kind of mistake here.

### Phase 2 — recording and backfill

Migration `027`. `evaluate_all` called over all ranked Tier A/B rows in the
morning cron, writing one row per gate. `backend/analysis/gate_backfill.py`
(read-only against `rns_announcements`, writes only `rns_gate_evaluations`)
replays the registry over whatever extractions exist — which is 26 rows today,
not a history. Its real job is re-evaluation after a threshold change, not
sample generation; do not size expectations off it.

**`rns_score_perf.py` stays read-only and untouched** — its point-in-time
integrity is load-bearing and the previous plan explicitly protects it. The
returns join for the page is a separate consumer of the same conventions.

### Phase 3 — the page

`GET /api/gates` behind `require_admin_token`, returning the matrix plus the
per-gate summary. `/gates` page + `_client.tsx` following `/status`.

This phase also resolves a dangling follow-up: `_named_one_offs`
(`showcase.py:543`) is currently only printed to the cron log, and the
earnings-quality plan flagged that surfacing it "on the showcase card" needed a
column, an API field and a frontend change it did not justify. As a shadow
annotator column on this page it needs none of that — it is already in
`earnings_quality`.

### Phase 4 — the low-base gate, in shadow

The gate this conversation started from, and the first genuinely new one.

The vet stops returning a prose verdict and starts returning **numbers**: the
comparator period, the figure the announcement prints for it, the implied
preceding half/quarter derived from the annual series, and the base as a share
of its own history. Python adjudicates. **Keep a prose `rationale` field
alongside** — the vet also catches things nobody enumerated (liquidity-
fragmenting secondary listings, dilution, a cut buried in an upbeat headline),
and a Python block can only adjudicate failure modes already named. The prose
channel keeps the unknown-unknowns visible without blocking authority.

**Do not solve this by feeding annual history into the ranker prompt.** That is
per-company text on every row of the morning batch and would undo the 15% → 45%
cacheable-share win from `d0cf0bf` (uncacheable bytes/row 20,626 → 15,882). The
vet runs only on candidates that clear the floors — a handful a day — which is
the right place for expensive per-company context.

Consequence to accept honestly: because this gate needs an LLM call the other
two don't, it **cannot be backfilled** and its evaluation pool is the vet's
pool, not the wide one. It will calibrate slower than the pure-JSONB gates.

### Phase 5 — arm on evidence

Promote shadow → armed only with: a fire rate that is neither ~0% nor
implausibly high, an amber rate that shows the gate can actually reach its
target rows, and blocked-row returns visibly worse than passed-row returns over
a horizon with enough matured rows to mean something. Record the promotion and
its evidence in this doc's implementation record.

---

## 4. Risks

- **Compounding false-block rate.** `vs_prior` is ~90% stable, not
  deterministic (26/29 LUCE blocks; one control row blocked 1/7 on the same
  wobble). Each armed gate adds an independent chance of firing on a
  mislabelled field, so a block of six gates has an aggregate false-block rate
  worse than any single gate's — and per-gate testing will never show it. The
  page must report **block rate for the block as a whole**, not only per gate.
- **Shadow gates never getting armed.** The failure mode of a safe mechanism is
  that everything sits in shadow forever and nothing is enforced. Each shadow
  gate needs a stated promotion criterion when it lands, not when it is
  reviewed.
- **Calibrating on the wide pool.** Fire rate and amber rate calibrate fine
  score-independently — the gate rules are facts about the announcement, not
  about the score. **Return impact does not.** A gate whose blocked-vs-passed
  return gap was measured on score-30 rows and is then armed against score-75
  flag candidates has been calibrated on the wrong population. Facet by score
  band before any promotion; an unfaceted precision number here is actively
  misleading.
- **The calibration timeline is long, and forward-only.** At ~42 Tier A/B rows
  a session and 26 of 57 carrying `guidance_checks` on the only day we have,
  a month of sessions is order 800 evaluated rows but only a few dozen rows
  per gate that the gate could actually adjudicate — and the 1m/3m return
  horizons that judge a block need another 21/63 trading days on top. **Nothing
  in this plan can arm a gate quickly.** That is the honest cost of not arming
  on n=1; the alternative is what the system does today.
- **Pool homogeneity.** The evaluation history spans prompt changes
  (`6b73dfb`, `d0cf0bf`) and a model switch. Stamp each evaluation with the
  row's `llm_model` and prompt era, and never pool across a prompt change
  without saying so.
- **A page that invites tuning.** Every threshold visible next to its outcome is
  an invitation to fit the thresholds to the sample. The promotion criteria in
  Phase 5 exist to make that a decision with a written basis rather than a
  Tuesday-afternoon nudge.
- **Over-blocking, still.** Dropping a tradeable announcement remains the
  high-severity error. Registry-level try/except → `n/a`, every ambiguous path
  fails open, and shadow is the default for anything new.

## 5. Out of scope

- Any change to `HIGH_IMPACT_MIN_LLM_SCORE`, to `llm_score`, or to the
  sentiment rule's own logic (it moves into the registry unchanged).
- Making `vet_verdict` block. The vet's prose verdict stays advisory
  permanently; what gains blocking authority is the structured field Phase 4
  extracts from it.
- Public exposure of `/gates`, or any gate state on the public showcase card.
- Insurer / REIT / miner analogues of the bank rule.
- Re-ranking history in place.

## 6. Acceptance criteria

1. **Phase 1 changes no outcomes**: over a 30-day dry run, the set of blocked
   rows is identical to the current code, and `test_showcase.py` passes
   unmodified.
2. **Every gate returns all three states** on constructed fixtures, and a gate
   that raises produces `n/a`/`gate_error` rather than propagating.
3. **The known cases still reproduce** — but through
   `rns_body_context_validation.py`, which re-runs the model over the stored
   body, **not** through the backfill: LUCE 9689898 blocked by the guidance
   gate, BARC 9689888 by the bank gate, the six-row control set by neither.
   Neither row has a stored extraction the backfill could read.
4. **The page shows a real amber rate for the guidance gate** — expected to be
   high, ~91% on the 2026-07-29 sample. If it comes back near zero, the `n/a`
   reasons are not being recorded correctly.
5. **`/gates` is unreachable without a token** and carries
   `robots: index:false`, verified the same way `/status` was.
6. **The recording write does not extend the morning batch** past the digest
   send. Headroom is thin at volume (last story 07:11:34 on n=55 against an
   07:12 send); judge on p90, and note this write is pure Python over rows
   already in memory.
7. **No gate is armed in the same commit that introduces it**, Phase 1's
   like-for-like move excepted.
