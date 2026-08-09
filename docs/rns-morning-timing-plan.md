# Moving the digest send from 07:30 to 07:15

Status: **plan only, nothing implemented.** Written 2026-08-09.

Goal: send the weekday RNS digest at 07:15 UK instead of 07:30, without
shipping a thinner or later email.

---

## 1. Baseline — what the data actually says

Measured over the last 30 days (read-only queries against prod).

`analysis/rns_morning_batch_completion.py` reports "07:15 safe on 3/20 days".
**That number is wrong for this decision.** Its scope is Tier A/B published
06:30–08:30 UK, which includes stories published at 08:00–08:28 that no 07:30
send could ever contain. It measures when the whole morning finishes, not when
the *sendable* batch finishes.

Re-scoped to only stories a given send could include (published ≥10 min before
the send, allowing for ingest lag):

| | 07:15 send | 07:30 send |
|---|---|---|
| Fully ranked before send | 15/30 days | 20/30 days |
| Healthy-day completion, post-2026-07-10 | **07:04:36 – 07:08:21** | same |

There is a clean regime change at 2026-07-10. Before it, completion clustered
at 07:16–07:17. Every healthy day since is under 07:09.

The days that miss are **not slow days** — they are known incidents:

- 2026-07-28 10:02 — ULVR/GAW classifier re-tier (fd253f3 landed 09:30)
- 2026-07-31 15:17 — the token-budget stall (21 rows scored NULL)
- 2026-08-05 09:00 — TPFG, single row +120m
- 2026-07-23 / 07-29 / 07-30 15:17–15:18 — **one** bulk backfill, not three
  late mornings (identical clock stamp across days)

Ingest lag (publish → became a ranking candidate): **p50 5.0 min, p90 7.3,
p99 27.2**.

**Content cost of the move is small.** The 07:05–07:20 publication window holds
only ~1–2 Tier A/B stories/day (07-30: 57 rows in scope either way; 08-07: 8 vs
10). You are not giving up much by cutting 15 minutes off the tail.

**Conclusion:** the margin exists on healthy days. What does not exist is
tolerance for the failure modes, which are all-or-nothing stalls rather than
gradual slippage. 07:30's extra 15 minutes is currently the only thing
absorbing them. Fixes 1–3 below are prerequisites, not nice-to-haves.

---

## 2. Fix 1 — put a timeout on the DeepSeek client (PREREQUISITE)

**Problem.** `backend/rns_llm.py:197` constructs the client with neither
`timeout` nor `max_retries`, so openai-python defaults apply: **600s timeout,
2 retries**. `_call_deepseek` then layers its own two-budget retry on top. One
hung call can occupy a ranking worker for up to 30 minutes. Because
`_rank_pending` blocks on `list(pool.map(...))` (`rns_llm.py:1471`), the whole
run cannot return, the pipeline lock stays held, and every burst cron behind it
exits immediately without ingesting.

This is the single biggest tail risk against any send time, and it is currently
hidden by the 07:30 slack.

```diff
--- a/backend/rns_llm.py
+++ b/backend/rns_llm.py
@@
+# Per-call ceiling on a DeepSeek request. openai-python defaults to a 600s
+# timeout with 2 retries, so one hung call can hold a ranking worker for ~30
+# minutes; because _rank_pending blocks on pool.map that holds the pipeline
+# lock too, and every burst cron behind it exits without ingesting. The
+# morning batch has minutes of slack, not tens of minutes.
+#
+# Two values because the two callers have genuinely different tails: the
+# ranker's fast path is ~6.5s/call, while the showcase vet runs thinking=True
+# and was measured at 85-172s (rns_llm) / ~40s (showcase, 2026-08-06). A
+# single cap would either strangle the vet or be useless for the ranker.
+_TIMEOUT_FAST_S     = float(os.environ.get("DEEPSEEK_TIMEOUT_FAST", "60"))
+_TIMEOUT_THINKING_S = float(os.environ.get("DEEPSEEK_TIMEOUT_THINKING", "240"))
+# One retry, not openai's default 2: _call_deepseek already retries on
+# truncation, and the cron re-runs every 3 min. Stacking three layers of retry
+# is how a 6s call becomes a 30-minute lock hold.
+_CLIENT_MAX_RETRIES = int(os.environ.get("DEEPSEEK_MAX_RETRIES", "1"))
+
 _client = None


 def _get_client():
     """Lazy-initialised OpenAI-compatible client pointed at DeepSeek."""
     global _client
     if _client is None:
         if not _DEEPSEEK_API_KEY:
             raise RuntimeError("DEEPSEEK_API_KEY not set in environment")
         from openai import OpenAI

-        _client = OpenAI(api_key=_DEEPSEEK_API_KEY, base_url=_DEEPSEEK_BASE_URL)
+        _client = OpenAI(
+            api_key=_DEEPSEEK_API_KEY,
+            base_url=_DEEPSEEK_BASE_URL,
+            timeout=_TIMEOUT_THINKING_S,   # per-call override below
+            max_retries=_CLIENT_MAX_RETRIES,
+        )
     return _client
```

and pass the right one per call:

```diff
--- a/backend/rns_llm.py
+++ b/backend/rns_llm.py
@@ def _call_deepseek(
     for attempt, attempt_budget in enumerate(budgets, start=1):
         resp = client.chat.completions.create(
             model=_DEEPSEEK_MODEL,
             messages=messages,
             response_format={"type": "json_object"},
             temperature=_DEFAULT_TEMPERATURE,
             max_tokens=attempt_budget,
             extra_body=_THINKING_ON if thinking else _THINKING_OFF,
+            timeout=_TIMEOUT_THINKING_S if thinking else _TIMEOUT_FAST_S,
         )
```

**Risk.** A timeout that is too tight turns a slow-but-fine row into an error
row. `_attempt` already isolates per-row failures and the row keeps
`llm_processed_at IS NULL`, so the next run retries it — the failure mode is
"scored 3 minutes later", not "lost". 60s against a 6.5s fast path is ~9x
headroom.

**Verify.** Watch one morning's cron log for `rank failed for <id>` lines. If
the fast path is genuinely slower than the 6.5s assumption (the ranker comment
at `rns_llm.py:167-171` flags that 6.5s is a *pre-reasoning* figure and fast
mode was never latency-measured), this is where it will show. Raise
`DEEPSEEK_TIMEOUT_FAST` in the Dokploy env — no deploy needed.

---

## 3. Fix 2 — a mid-run ingest abort leaves a permanent hole (PREREQUISITE)

**Problem.** `_run_ingest` breaks out of the page loop on the first rate-limit
or network error (`backend/rns.py:1290-1300`). On the next run, page 1 has new
rows so the loop continues, page 2 is all-known, and `stop_on_known` breaks at
page 2 (`rns.py:1320`). **Pages 3+ are never re-read.** `_compute_max_pages`
cannot rescue it because `MAX(published_at)` is fresh, so the 6h catch-up never
fires. The middle of the 07:00 drop is lost silently and permanently.

The urgent-window backoff cap (5s, `rns.py:961`) deliberately fails fast
between 06:30–07:30, which makes this *more* likely exactly when it costs most.
That cap is the right call — the bug is that nothing recovers from it.

Make the abort visible in the return value, then act on it.

```diff
--- a/backend/rns.py
+++ b/backend/rns.py
@@ def _run_ingest(
     processed = inserted = updated = errors = 0
     rate_limited = False
+    # Why the loop ended. "caught_up" is the only outcome that proves we saw
+    # every new row: an abort leaves rows on the unread pages, and because the
+    # next run's page 2 will be all-known, stop_on_known guarantees no future
+    # run ever reaches them. The caller must force a deep sweep instead.
+    stopped = "ceiling"
     for page in range(1, max_pages + 1):
         try:
             html = _fetch_page(page)
         except _RateLimited as e:
             print(f"[rns] RATE LIMITED on page {page} — aborting ingest ({e})")
             rate_limited = True
             errors += 1
+            stopped = "rate_limited"
             break
         except (urllib.error.URLError, TimeoutError) as e:
             print(f"[rns] page {page} fetch failed: {e}")
             errors += 1
+            stopped = "fetch_error"
             break
         raws = _parse_rows(html)
         if not raws:
             print(f"[rns] page {page}: no rows parsed")
+            stopped = "caught_up"
             break
@@
         print(f"[rns] page {page}: parsed={len(raws)} new={page_new}")
         if stop_on_known and page_new == 0 and page > 1:
+            stopped = "caught_up"
             break
         if page < max_pages:
             time.sleep(sleep_s)
     result = {
         "processed": processed,
         "inserted": inserted,
         "updated": updated,
         "errors": errors,
         "rate_limited": rate_limited,
+        "stopped": stopped,
+        "complete": stopped == "caught_up",
     }
     print(f"[rns] ingest done — {result}")
     return result
```

Then persist the incomplete state and force a deep sweep next run. Reuses the
existing migration-008 `pipeline_runs` convention (mirrors
`run_email_events.record_run`).

```diff
--- a/backend/run_rns.py
+++ b/backend/run_rns.py
@@
+def _record_ingest(status: str, detail: dict) -> None:
+    """Stamp pipeline_runs('rns_ingest') — migration-008 convention. Carries
+    the incomplete flag across runs, which is the only durable place to put it:
+    a truncated ingest is invisible in the data (the rows it missed simply
+    never arrive) and the next run cannot otherwise know to sweep deeper."""
+    import psycopg2.extras
+    from db import connection
+
+    try:
+        with connection() as conn:
+            cur = conn.cursor()
+            cur.execute(
+                """
+                INSERT INTO pipeline_runs (pipeline, last_run_at, status, detail)
+                VALUES ('rns_ingest', NOW(), %s, %s)
+                ON CONFLICT (pipeline) DO UPDATE SET
+                    last_run_at = EXCLUDED.last_run_at,
+                    status      = EXCLUDED.status,
+                    detail      = EXCLUDED.detail
+                """,
+                (status, psycopg2.extras.Json(detail)),
+            )
+            conn.commit()
+    except Exception as e:
+        print(f"[rns] pipeline_runs stamp FAILED (non-fatal) — {type(e).__name__}: {e}")
+
+
+def _last_ingest_incomplete() -> bool:
+    from db import query
+    try:
+        rows = query(
+            "SELECT status, detail FROM pipeline_runs WHERE pipeline = 'rns_ingest'"
+        )
+    except Exception:
+        return False
+    return bool(rows) and rows[0]["status"] != "ok"
+
+
 def _run_pipeline() -> int:
     print(f"[rns] pipeline starting at {datetime.now(timezone.utc).isoformat()}")
     try:
         # Stage 1: Ingest
         max_pages, reason = _compute_max_pages()
         print(f"[rns] ingest: {reason}")
-        ingest = _run_ingest(max_pages=max_pages, stop_on_known=True, sleep_s=1.5)
+        # A truncated previous run left rows on pages we never read, and
+        # stop_on_known would break at page 2 again and never reach them. Sweep
+        # the full depth once to close the hole, then resume normal behaviour.
+        resume = _last_ingest_incomplete()
+        if resume:
+            max_pages = max(max_pages, CATCHUP_PAGE_CAP)
+            print(f"[rns] previous ingest was incomplete — deep sweep to {max_pages} pages")
+        ingest = _run_ingest(
+            max_pages=max_pages, stop_on_known=not resume, sleep_s=1.5
+        )
         print(f"[rns] ingest done — {ingest}")
+        _record_ingest(
+            "ok" if ingest.get("complete") else ingest.get("stopped", "error"),
+            ingest,
+        )
```

with the import updated:

```diff
-from refresh_rns import _compute_max_pages, RNS_PIPELINE_LOCK_KEY
+from refresh_rns import _compute_max_pages, CATCHUP_PAGE_CAP, RNS_PIPELINE_LOCK_KEY
```

**Cost.** A deep sweep is 24 pages × (fetch + 1.5s) ≈ 60–75s, and only on the
run after an abort. `stop_on_known=False` means it reads all 24 pages even when
they are all known — that is the point.

**Risk.** If investegate is throttling persistently, the deep sweep is 24
requests into a host that just said no. The urgent-window cap still applies, so
it fails fast and re-stamps incomplete. Acceptable, but worth watching the
first time it fires.

---

## 4. Fix 3 — `rate_limited` is computed and never read

**Problem.** Grep across `backend/`: `rate_limited` is set in `rns.py`
(lines 1286, 1294, 1329, 1478, 1501, 1516), asserted in
`tests/test_rns_throttling.py`, and **read nowhere else**. `run_rns.py` prints
the dict and moves on. No alert, no forced catch-up, no non-zero exit. Fix 2
makes the state durable; this makes it visible.

```diff
--- a/backend/healthcheck.py
+++ b/backend/healthcheck.py
@@
+    @check("rns.ingest_complete")
+    def _rns_ingest_complete():
+        # A truncated ingest is invisible in the data — the rows it missed
+        # simply never arrive, so a thin digest and a quiet news day look
+        # identical. This is the only signal that distinguishes them.
+        row = query_one(
+            "SELECT last_run_at, status, detail FROM pipeline_runs "
+            "WHERE pipeline = 'rns_ingest'"
+        )
+        if not row or row["last_run_at"] is None:
+            return WARN, "no rns_ingest marker yet (stamp lands on the next run)"
+        if row["status"] != "ok":
+            return FAIL, (
+                f"last ingest stopped early: {row['status']} — "
+                f"pages beyond the abort were not read, {row['detail']}"
+            )
+        h = _age_hours(row["last_run_at"])
+        # */15 sweep on weekdays; generous slack for weekends.
+        return _tier(h / 24.0, warn_at=3, fail_at=5), f"last ingest ok, {h:.1f}h ago"
```

---

## 5. Fix 4 — `limit=50` is binding on the biggest mornings

**Problem.** `run_rns.py:61,65` caps both `_backfill_summaries(limit=50)` and
`_rank_pending(limit=50)`. Observed morning batch sizes: 53, 54, 54, 57.

Every day with >50 rows in scope had late rows; days at ≤46 were almost all
clean. The correlation is direct — a 57-row morning needs a second full run,
which at 5–8 min/run lands ~07:12–07:16, straddling 07:15.

```diff
--- a/backend/run_rns.py
+++ b/backend/run_rns.py
@@
+# 80, not 50. Measured over 30 days the morning Tier A/B batch runs 8-57 rows,
+# and every day above 50 left rows for a second run — which at 5-8 min/run
+# lands ~07:12-07:16 and straddles the send. The cap has to clear the observed
+# peak with headroom, not sit inside it.
+#
+# This is not free: the summary stage is serial at ~2s/row (one fetch plus
+# sleep_s), so 80 rows is ~160s against 50 rows' ~100s. Fix 5 below pays for
+# it by moving the vet out of the pre-send window, which frees 1-4 min.
+_SUMMARY_LIMIT = int(os.environ.get("RNS_SUMMARY_LIMIT", "80"))
+_RANK_LIMIT    = int(os.environ.get("RNS_RANK_LIMIT", "80"))
@@
-        summaries = _backfill_summaries(limit=50, sleep_s=1.0, tiers=("A", "B"))
+        summaries = _backfill_summaries(limit=_SUMMARY_LIMIT, sleep_s=1.0, tiers=("A", "B"))
         print(f"[rns] summaries done — {summaries}")

         # Stage 3: LLM rank
-        ranked = _rank_pending(limit=50, tiers=("A", "B"), hours=48)
+        ranked = _rank_pending(limit=_RANK_LIMIT, tiers=("A", "B"), hours=48)
```

**Note on the tradeoff.** You can have full coverage of a 57-row morning or the
current investegate request rate, not both, unless summary fetching goes
concurrent. Given the live throttling concern (investegate already runs
~130–210 req/day), keep `sleep_s=1.0` and buy the time back from Fix 5 instead.
Ranking is concurrent so its limit is nearly free — 80 rows at 5 workers is
~104s at the 6.5s baseline.

---

## 6. Fix 5 — move the vet out of the pre-send window

**Problem.** `showcase.flag_high_impact_candidates` runs a plain
`for c in cands:` loop calling `_vet_candidate` with `thinking=True`
(`backend/showcase.py:1896-1925`, `thinking=True` at line 1139). No
concurrency. Measured 1–6 vet calls/day at ~40s each (08-06: 07:06:52 →
07:08:11 for two).

That is 1–4 minutes of pipeline-lock hold **after the digest content is already
final** — the digest reads `llm_score` directly (`email_rns_digest.py:78`) and
never touches `vet_score`. Every second of it blocks the next burst run from
ingesting late-breaking stories, which is precisely the coverage a 07:15 send
needs most.

Stages 3.5, 3.6 and 4 are all post-ranking and none of them affect the email.
Defer them past the send.

First, a public helper on the existing window (`rns.py:964`):

```diff
--- a/backend/rns.py
+++ b/backend/rns.py
@@ def _backoff_cap_s(now: Optional[datetime] = None) -> float:
     t = (now or datetime.now(_UK_TZ)).time()
     lo, hi = _URGENT_WINDOW
     return _URGENT_BACKOFF_CAP_S if lo <= t < hi else _RETRY_AFTER_CAP_S
+
+
+def in_urgent_window(now: Optional[datetime] = None) -> bool:
+    """True while the morning batch is racing the digest send.
+
+    Public because run_rns uses it to defer post-ranking work: the vet, the
+    gate sweep and the prune all run AFTER the digest's content is settled
+    (the digest reads llm_score, never vet_score), but they hold the pipeline
+    lock while they do it, which stops the next burst run ingesting.
+    """
+    t = (now or datetime.now(_UK_TZ)).time()
+    lo, hi = _URGENT_WINDOW
+    return lo <= t < hi
```

Then guard the tail of the pipeline:

```diff
--- a/backend/run_rns.py
+++ b/backend/run_rns.py
@@
-        # Stage 3.5: High Impact RNS showcase — flag new candidates and snapshot
+        # Stages 3.5-4 are deferred inside the pre-send window. None of them
+        # changes what the digest sends — it reads llm_score, never vet_score —
+        # but the vet is serial, thinking-mode and ~40s/candidate, so it holds
+        # the pipeline lock for 1-4 min while late 07:05+ stories wait for an
+        # ingest slot they cannot get. Post-send there is no contention and the
+        # next sweep picks all three up unchanged.
+        if in_urgent_window():
+            print("[rns] pre-send window — deferring showcase/gates/prune")
+            print("[rns] pipeline completed successfully (ranking only)")
+            return 0
+
+        # Stage 3.5: High Impact RNS showcase — flag new candidates and snapshot
```

with the import updated:

```diff
-from rns import _run_ingest, _backfill_summaries, _prune_old
+from rns import _run_ingest, _backfill_summaries, _prune_old, in_urgent_window
```

**Risk.** The High Impact page and `/gates` populate ~15 min later on weekday
mornings. Both are admin/showcase surfaces with no send deadline. The prune is
a daily-scale garbage collector — deferring it by one run is irrelevant.

**Watch for.** If a morning is so busy that runs chain back-to-back past the
send, the deferred stages still run on the first post-window sweep. But confirm
the `*/15` sweep is actually still firing after 07:15 — if the burst cron is
the only thing running post-open, these stages need their own schedule.

---

## 7. Fix 6 — one definition of the send time

**Problem.** 07:30 is hardcoded in at least three places plus the external
cron-job.org config:

- `backend/rns.py:960` — `_URGENT_WINDOW = (_dt_time(6, 30), _dt_time(7, 30))`
- `backend/healthcheck.py:363` — `send_uk = "07:30"`
- `backend/main.py:2474` — docstring

The comment at `healthcheck.py:332-336` records that this drift has already
bitten once: the check was calibrated to 07:12 while production sent at 07:30,
leaving the monitor 18 minutes stricter than reality. Move the send without
updating these and you get the same class of bug pointing the other way — a
monitor that passes a batch which missed the email.

```diff
--- a/backend/rns.py
+++ b/backend/rns.py
@@
-_URGENT_WINDOW = (_dt_time(6, 30), _dt_time(7, 30))
+# THE send time, in one place. cron-job.org holds the trigger (see main.py's
+# /api/digest) and cannot import this, so that schedule must be changed by hand
+# to match — but everything inside the backend derives from here: the
+# fail-fast throttle window below, run_rns's deferral of post-ranking stages,
+# and healthcheck's rns.morning_batch bar.
+DIGEST_SEND_UK = _dt_time(7, 15)
+_URGENT_WINDOW = (_dt_time(6, 30), DIGEST_SEND_UK)
```

```diff
--- a/backend/healthcheck.py
+++ b/backend/healthcheck.py
-        send_uk = "07:30"
+        from rns import DIGEST_SEND_UK
+        send_uk = DIGEST_SEND_UK.strftime("%H:%M")
```

and correct the `main.py:2474` docstring to 07:15.

---

## 8. Sequencing

Fixes 1–3 are prerequisites. Do not move the cron until they are deployed and
have survived at least one full week of mornings.

1. **Fix 1** (client timeout) — deploy alone. Watch a week of cron logs for new
   `rank failed` lines. This is the highest-value change even if the send never
   moves.
2. **Fix 2 + Fix 3** (ingest hole + healthcheck) — deploy together; the check is
   what tells you the resume logic works. Needs no migration (`pipeline_runs`
   already exists). Confirm the `rns.ingest_complete` check appears on `/status`.
3. **Fix 5** (defer vet) — deploy. Confirm from the cron log that morning runs
   print the deferral line and that a post-07:15 run still flags showcase rows.
4. **Fix 4** (raise limits) — deploy after 5, since 5 pays for its wall clock.
   Re-run the scoped measurement and confirm >50-row mornings now clear in one
   run.
5. **Fix 6 + cron flip** — change `DIGEST_SEND_UK` to 07:15, deploy, **then**
   change the cron-job.org schedule. Backend first: if the trigger moves before
   `_URGENT_WINDOW` does, the 07:15–07:30 band loses its fail-fast throttle
   handling for one deploy cycle.

## 9. Verification

Re-run the scoped measurement (the throwaway script from this session, or fold
its scope fix into `analysis/rns_morning_batch_completion.py` — its current
06:30–08:30 window should not be trusted for send-time decisions). Target:
**20 consecutive weekday mornings with zero rows late against a 07:15 bar**,
excluding same-day classifier backfills, which `healthcheck.py:358-362` already
explains how to scope out.

Also confirm the send itself: a real send takes ~34s including pacing
(`main.py:2497`), so a 07:15 trigger puts mail in inboxes ~07:16.

## 10. What this cannot fix

The ~5 minute floor is discovery, not compute: investegate's publish delay plus
the 3-minute burst cadence. p50 ingest lag is 5.0 min and p90 is 7.3. No amount
of pipeline optimisation gets the send below roughly 07:12, and pushing the
burst cron faster trades against the throttling risk that Fix 2 exists to
handle. 07:15 is close to the practical floor for this architecture.

## 11. Checked and clean

`_backfill_summaries` has no time window while `_rank_pending` has a 48h one,
so a permanently-unfetchable Tier A/B row would be retried every run forever
with no attempt cap — and Tier A/B rows are never pruned (`run_rns.py:92`).
Queried: **0 such rows currently.** Theoretical, not live. Worth a counter if
that ever changes, but not worth code today.
