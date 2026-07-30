# One Python gate block, and a page to calibrate it — plan

**Goal: turn the ad-hoc sequence of pre-vet checks into a single ordered
registry of named, testable Python predicates, and build a private page that
shows every gate's verdict on every candidate as a traffic light — so a gate
can be watched before it is armed.**

This is not a new architecture. It is the one `showcase.py:359-365` already
argues for, finished: *"The structured field is far steadier, so the decision
is made here in Python, deterministically and testably."* The LLM extracts
facts; Python adjudicates them. Today two gates follow that pattern and one
judgement (the growth-arithmetic vet) does not — and that one is now measured
wrong in 4 of its last 5 numeric attempts (§1, *The case that started this*).

Scope decisions, both carried forward from the previous two plans:
`HIGH_IMPACT_MIN_LLM_SCORE` **stays at 75**, and `llm_score` is **not** tuned.
Three rows have now shown a 25-30pt spread on the same announcement; nothing
here adds a dependence on that number.

**A fourth, cleaner data point for that spread, found 2026-07-30.** `JNEO`
published its 2026-07-28 trading update twice: the original at 06:00
(`9689848`) and an amendment at 13:45 (`9691776`) whose only substantive change
is the words "strong H1 2025" corrected to "strong H1 2026". Every figure is
identical and the amendment says so ("All other details remain unchanged"). The
two scored **75 and 55**. This is stronger evidence than the earlier three
because there is no content difference to argue about — a 20-point swing on one
word, 7h45m apart, and the 75 is the one that reached the showcase.

Read it as a bound on `llm_score`, not as a fact about amendments. Pairing all
four detectable corrections against their own originals gives mean −6.2 with
`JDW` scoring **identically** (35/35) on near-identical text, so there is no
systematic correction penalty — the instability is per-row, not per-type. The
amendment-linking question that measurement opened is its own small plan:
`docs/rns-amendment-supersedes-plan.md`.

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

### The case that started this — corrected 2026-07-30

This plan was originally motivated by `SRT.L` and `CAPD.L`, both on the public
showcase carrying `vet_verdict = exclude` at `high` confidence, and both read as
the vet catching something Python could not block:

> **SRT.L** — "Profit before tax of £10m is flattered by a 105% increase from a
> low base of £4.9m… net margins remain thin at 8.6%"

> **CAPD.L** — "Q2 2026 revenue of $117.3m is actually below the preceding
> half's implied quarterly run-rate of ~$172.9m (FY2025 $345.8m / 2)… the 34.2%
> year-on-year growth is against a weak Q2 2025 base"

**Both rationales are wrong.** On 2026-07-30 all 8 rows in `high_impact_rns`
with `vet_verdict` in (`caution`, `exclude`) were re-checked line by line
against `rns_announcements.body`, `ttm_financials` and `price_history`. Four
contain a hard error — a stated conclusion contradicted by the rationale's own
cited figures — and all four are the same error: the sequential comparison
`_vet_messages` asks for (`showcase.py:264-273`), drawn backwards.

| Row | Verdict | Defect |
|---|---|---|
| `CAPD.L` 9671246 | `exclude` / high | Divided FY2025 by **2** and called the result a *quarterly* run-rate. Correct divisor is 4 ($86.4m), so Q2'26 is +35.7% above it — and the announcement prints Q1'26 $101.7m → Q2'26 $117.3m, **+15.3% sequentially**, described as "another record revenue quarter" |
| `SRT.L` 9682985 | `exclude` / high | Asserted "H2 FY2025 was likely much higher than H1 FY2025" about an announcement that publishes **no half-year split at all**. Separately, "£4.9m estimated from FY2025 PBT of £2m plus tax" is not a derivation: £4.9m is printed in the RNS summary table, and £2m is FY2025 *net income* (£2.03m) mislabelled as PBT |
| `STAN.L` 9692325 | `caution` / med | Used H1'26's own operating income ($11.6bn) as the H2'25 comparator. Actual H2'25 is $9.65bn (FY'25 $20.55bn − H1'25 $10.91bn), so H1'26 is **+20.3%**, not "flat versus H2'25" |
| `JNEO.L` 9689848 | `caution` / med | Derived H2'25 = £30.5m correctly, then called H1'26's £37.6m "below" it. It is **+23.2% above**. The cash claim is a YoY artefact too — the £10.7m CFDS payment fell in H2'25, and cash *rose* ~£0.6m across the half being reported (FY25 year-end £12.03m → H1'26 £12.6m) |

**The inputs are not the problem.** Every figure in all four traced correctly to
the announcement body or to `ttm_financials`. What fails is the last step, the
comparison itself.

Three rows survive the audit. `PTEC.L` performs the identical move correctly
(€270m − €155m = €115m, −25.8% sequential) *and* has it corroborated in the text
— "management expects Adjusted EBITDA to be lower than H1". `RNK.L` has two soft
spots but no arithmetic error: 6% LFL NGR pinned to a statutory-revenue base
(£795.4m, a different measure from the £834.1m NGR that grew), and a "−11.8% in
the past month" that is −8.9% close-to-close in `price_history`. `SYNT.L` is
qualitative with nothing numeric to check.

**The split falls on the model switch.** All three sound rows are
`deepseek-chat`, dated on or before 2026-07-14. All five flawed rows are
`deepseek-v4-flash`, dated on or after 2026-07-16 — the day v4-flash went live.
n=8 and the groups are a before/after rather than a controlled comparison, but
the failure mode is uniform and it lands on the model change rather than
anywhere else. Cheap confirmation: re-run the five v4-flash bodies through
`rns_body_context_validation.py` under `deepseek-chat` and diff the verdicts.

**What this costs today: nothing, and that is the whole point.** `vet_verdict`
never blocks — insertion is hardcoded `'approved'` (`showcase.py:702`) and the
vet fields are display-only, surfaced on `/gates` and on the showcase card. So
four wrong rationales are currently a misleading label on rows that are
otherwise fine, not a suppression. The four errors are free *because* the vet
has no blocking authority.

Two conclusions replace the original ones:

1. **The vet is not "the strongest detector in the system for this failure
   mode."** It is an unreliable one, and the two catches cited above as
   motivation are both false positives. Had they gated, they would have dropped
   a record quarter with FY guidance implying +19-27% growth (`CAPD.L`) and a
   full year at +49% revenue / +105% PBT with gross cash up 473% (`SRT.L`) —
   §4's over-blocking risk, realised twice in a fortnight.
2. **Phase 4's design is still right, and its justification is now stronger.**
   Moving the derivation into Python was framed as giving a good detector teeth.
   It is better understood as removing an arithmetic step the model
   demonstrably cannot perform from the path to a block. The prompt at
   `showcase.py:264-273` even spells out the formula — "preceding half =
   full-year total minus the prior-year half quoted in the announcement" — and
   `_annual_lines` supplies only FY totals, so the model must do the subtraction
   itself on every row. That subtraction is the thing to move.

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
comparator period, the figure the announcement prints for it, and the base as a
share of its own history. **Python derives the implied preceding half/quarter
and does every comparison** — the model supplies only figures it can copy, never
a subtraction and never a direction word. That division of labour is not a
stylistic preference; it is the direct lesson of the audit above, where all four
errors sat in the arithmetic and none in the extraction.

#### Where the two terms come from — we own one of them

The derivation needs a full-year total and a prior-year half. **We hold the
first and not the second**, so the model cannot be cut out of the loop entirely;
it can only be demoted from computing to copying.

| Term | Source | Coverage |
|---|---|---|
| Full-year total | `annual_financials`, already fetched by `_annual_history()` (`showcase.py:205`) | **713** of ~748 active symbols, 5 fiscal years deep |
| Prior-year half/quarter | the announcement body — the model copies it | per-row; absent on some announcements, see below |

**Do not reach for `quarterly_financials` — it cannot carry this.** It holds
**34 symbols** (4.8% of the universe), 8 rows deep at most, and it is *empty for
five of the six audited rows* — JNEO, SRT, CAPD, INCH and PTEC all have zero
rows; only STAN has any, and that series has a hole at 2025-09-30. This is an
upstream ceiling rather than a stalled job: the table is fed from Yahoo's
quarterly income statement (`updater.py:699`), which returns nothing for issuers
that report semi-annually, i.e. most of the AIM and small-cap names where this
gate is meant to fire. Backfilling it is not an option.

**Second trap in that table, if it is ever used for anything else:**
`updater.py:714` derives `q_key = f"Q{((period_end.month-1)//3)+1} {year}"` from
the period-end month alone, with no reference to the period's actual length. A
six-month column from a semi-annual reporter is therefore stamped `Q2` or `Q4`
and is indistinguishable from a true quarter by the key. Any period arithmetic
over that table has to verify spacing between consecutive `period_end_date`s
first — the label is not evidence of the period length.

**Consequence for the extracted field:** the prior figure is not always printed,
so a single `prior_value` is too narrow. Of the audited rows, JNEO
(`"(H1 2025: £24.5m)"`), CAPD (`H1 2025 159.2` in its metrics table) and STAN
(`10,906` in the statement of results) all print it outright; INCH prints only
"up 9%" against a £4.7bn current half, so the base is £4.7bn ÷ 1.09; and SRT
prints no half-year figures at all. The field wants **`prior_value` OR
`prior_growth_pct`**, with Python resolving whichever is present and returning
`n/a` when neither is — never asking the model to convert one into the other.

Three guardrails fall out of the four audited failures, and each maps to one:

- **`CAPD.L` — the period of every figure is a required field, not a label.**
  A quarterly figure compared against a half-year one is only possible if the
  divisor is chosen in prose. Python holds the divisor and derives it from the
  stated period; a figure whose period is absent or unparseable is `n/a`, never
  compared.
- **`SRT.L` — no published split means the sequential axis is unavailable.**
  If the body yields neither a prior half nor a growth rate to derive one from,
  the gate returns `n/a`/`no_period_split` and the model is given no route to
  assert one. "Likely much higher" must be unrepresentable, not merely
  discouraged. Note this is the *common* case, not the edge case: SRT's is a
  full-year update, and with `quarterly_financials` covering 4.8% of the universe
  there is no fallback to fill the gap. Expect a high `n/a` rate here, the same
  way the guidance gate runs ~91% amber.
- **`STAN.L` and `JNEO.L` — assert the direction mechanically.** Both named the
  right two numbers and stated the wrong relation between them. Once Python owns
  the comparison this cannot recur by construction; while the prose `rationale`
  survives alongside, a cheap assertion that its direction word agrees with the
  sign of the Python-computed delta catches the same class in the advisory
  channel and is worth having regardless of gate state.

**Keep a prose `rationale` field alongside** — the vet also catches things nobody
enumerated (liquidity-fragmenting secondary listings, dilution, a cut buried in
an upbeat headline), and a Python block can only adjudicate failure modes already
named. The prose channel keeps the unknown-unknowns visible without blocking
authority. The audit is a reason to distrust its arithmetic, not a reason to
delete it: `SYNT.L`'s one-off competitor-disruption benefit is exactly the kind
of catch no enumerated field would have reached.

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

**The four audited errors are a negative control set, not evidence for the
gate.** `CAPD.L` 9671246, `SRT.L` 9682985, `STAN.L` 9692325 and `JNEO.L`
9689848 are rows the low-base gate **must not** fire on; if it blocks any of
them it has reproduced the prose error in Python, which is strictly worse than
the status quo because it would then gate. Check this before looking at fire
rate at all — it is the one criterion available immediately, needs no return
horizon, and no amount of favourable return data offsets failing it. `PTEC.L`
9659657 is the positive control: same move, correct answer, and the gate should
fire on it.

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
  without saying so. **This is now measured, not hypothetical**: §1's audit
  found 0 of 3 `deepseek-chat` rationales and 4 of 5 `deepseek-v4-flash`
  rationales carrying a hard numeric error, splitting exactly on the
  2026-07-16 switch. Facet by `llm_model` as well as by score band, and treat a
  metric pooled across that boundary as uninterpretable rather than noisy.
- **Model-quality regressions are invisible to per-gate tests.** The v4-flash
  arithmetic failures ran undetected for a fortnight because the vet is
  advisory, nothing asserts against its output, and `/gates` displays the
  rationale without checking it. Phase 4 removes the arithmetic from the block
  path, but any *future* field the model fills is exposed the same way. Prefer
  fields the model can only copy (`guided_value`, `one_off_named`) over fields
  it must compute — migration 026's stated reason for storing values as printed
  is the same reason, arrived at independently.
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
8. **The low-base gate does not fire on the audit's negative control set** —
   `CAPD.L` 9671246, `SRT.L` 9682985, `STAN.L` 9692325, `JNEO.L` 9689848 (§1) —
   and does fire on `PTEC.L` 9659657. Checked through
   `rns_body_context_validation.py` over the stored bodies, and a prerequisite
   for Phase 5 rather than a nice-to-have. Note `SRT.L` must come back
   `n/a`/`no_period_split` specifically, not merely "not blocked": passing for
   the wrong reason here means the guardrail is untested.
