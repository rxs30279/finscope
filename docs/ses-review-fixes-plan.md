# SES commit review fixes — action plan

Source: code review of commit 982c0fb ("Move subscriber list to Postgres and add
SES sending path"), 2026-07-22. All 77 tests in test_emailer / test_ses_events /
test_subscribers_db / test_email_events pass as of the review; keep them green.

Context for a fresh session: 982c0fb is already deployed to prod and sending
still goes via Resend (EMAIL_PROVIDER unset). Migrations 019/020 are applied to
prod. The fixes below are pre-cutover hardening; none change live behaviour
except item 4 (which improves the current Resend sends too).

Run tests from `backend/` with `python -m pytest tests/ -q` (PowerShell; the
suite must be run from the backend dir). Per standing feedback: **ask before
any git commit/push** — prepare everything, show the diff summary, then ask.

Suggested execution order: 3 → 1 → 2 → 4 → 5 → 6 (small/self-contained first,
then the two that add a migration/monitoring surface, then nits).

---

## 1. Add a `ses_events` check to healthcheck.py  (HIGH)

**Problem:** `run_email_events.py:8` claims "healthcheck.py reads it, so a
silent drain failure surfaces as a failed check" — but healthcheck.py has no
`ses_events` check. The drain is pull-based: if the cron dies, delivery history
silently stops and /status looks healthy. This gap recreates the exact failure
mode the commit was written to prevent.

**Change:** in `backend/healthcheck.py`, inside `run_db_checks()`, add a
`@check("ses_events.drain")` next to `digest.sent` (~line 261), following the
existing pattern (`shorts.refresh` at line 245 is the closest template):

- Query `pipeline_runs WHERE pipeline = 'ses_events'` via `query_one`.
- **No marker yet → WARN**, detail like `"drain has never run — enable the
  Dokploy cron (*/15 7-18 * * 1-5) when the SES parallel run starts"`. WARN not
  FAIL: the cron is intentionally not enabled yet; a standing WARN in the daily
  GHA report is the nudge, a FAIL would be noise. (Don't gate on EMAIL_PROVIDER
  — the GHA healthcheck env doesn't have it set.)
- **Marker present →** freshness in days with `_tier(d, warn_at=3, fail_at=5)`
  (same weekday-slack rationale as shorts/digest: weekday-only cron, weekend
  gaps expected). Then `if row["status"] != "ok": status = FAIL` — same forced
  FAIL as the other pipeline checks.
- Detail string mirrors the others: last run age, status, detail dict (the
  drain stamps `{received, stored, skipped, batches}`).

**Also:** no change needed to run_email_events.py — its docstring becomes true
once this lands.

**Tests:** `tests/test_status.py` covers the /status surface — check how it
stubs healthcheck checks and add coverage if the pattern makes it cheap
(no-marker → warn, stale marker → fail, fresh ok marker → pass). If the
existing tests don't unit-test individual checks, a small direct test of the
check function via `collect(query_one=stub)` is fine.

**Deploy note:** /status runs the Dokploy image's healthcheck.py, so this only
appears on the panel after the next redeploy (memory: project-healthcheck).

---

## 2. Write `subscribers.bounced_at` from the drain  (HIGH)

**Problem:** `migrations/019_subscribers.sql:20` documents bounced_at /
bounce_reason as "written by the events pipeline", and migrate_subscribers.py:20
repeats it — but `ses_events.py` only inserts into email_events. Nothing writes
those columns. Known live case: info@bioseekers.com migrated across as active
and hard-bounces every digest.

**Change:** in `backend/ses_events.py`:

- Add a helper, e.g. `_record_bounce(recipient: str, occurred_at, reason: str)`
  that runs:
  ```sql
  UPDATE subscribers
     SET bounced_at = %s, bounce_reason = %s
   WHERE email = %s AND bounced_at IS NULL
  ```
  (`bounced_at IS NULL` = keep the FIRST hard bounce; later ones add nothing.)
- Call it from `drain_queue` after a successful `_insert` when
  `row["event_type"] == "email.bounced"` **and** the bounce is permanent:
  `row["detail"]["bounce"].get("bounceType") == "Permanent"`. Transient
  bounces / complaints do NOT set it.
- Reason string: `bouncedRecipients[0].diagnosticCode` when present, else
  `f"{bounceType}/{bounceSubType}"`.
- Recipient is already lowercased by `parse_event`.
- Keep the migration-019 semantics: bounced_at is a *record*, it does not gate
  sends (the provider suppression list does). No digest change.
- Failure of this UPDATE must not lose the SQS message's main row — wrap it so
  an exception is logged and swallowed (the email_events row is already
  committed; the bounce stamp is best-effort).

**Optional (do only if trivial):** same for the Resend webhook path in
`email_events.py` on `email.bounced` — check what `_DETAIL_KEYS` actually
captures for Resend bounces first; if the payload has no usable reason/type,
skip and leave a one-line comment saying the SES drain owns bounced_at.

**Tests:** in `tests/test_ses_events.py` (mock the DB the same way the existing
`_insert` tests do): permanent bounce → UPDATE issued with diagnostic code;
transient bounce (`bounceType: "Transient"`) → no UPDATE; delivery → no UPDATE.

---

## 3. `preflight()` checks SES_CONFIGURATION_SET  (MEDIUM, tiny)

**Problem:** `emailer.py:210` `preflight()` under ses checks only AWS creds. A
missing `SES_CONFIGURATION_SET` means every send succeeds but emits zero
events — "the audit trail silently gone" scenario the module's own docstring
warns about. Only signal today is a print per send in cron logs.

**Change:** in `preflight()`, ses branch: after the creds check, add
```python
if not os.environ.get("SES_CONFIGURATION_SET"):
    return "SES_CONFIGURATION_SET missing — sends would emit no delivery events"
```
Abort-not-warn is deliberate: during the parallel run the event record is the
acceptance gate for cutover, so a misconfigured container should fail fast at
07:30 (surfaces as digest.sent FAIL) rather than send unmonitored mail. Keep
the existing per-send WARNING print in `_send_ses` — feedback/research/
unsubscribe-self don't call preflight.

**Tests:** in `tests/test_emailer.py`:
- Update `test_preflight_passes_when_configured` (line ~236) to also set
  `SES_CONFIGURATION_SET`.
- Also check `test_preflight_does_not_check_resend_key_under_ses` (line ~243) —
  it too must now set SES_CONFIGURATION_SET to keep passing.
- Add `test_preflight_flags_missing_config_set`.

---

## 4. Real plain-text part for the digest  (MEDIUM)

**Problem:** the digest passes `html` only. Under SES, `build_mime`
(`emailer.py:147`) synthesises "This email requires an HTML-capable mail
client." as the text/plain alternative — boilerplate that doesn't match the
HTML is itself a mild spam signal, arguably worse than the html-only mail
Resend sends today.

**Change:** in `backend/email_rns_digest.py`:

- Add `_render_text(rows, total_all, unsub_url="", manage_url="") -> str`:
  read `_render_html` first and reuse exactly the same row fields it renders.
  Minimal shape: a header line (date + item count, mirroring the subject), one
  line per row (score / ticker / headline / category — whatever _render_html
  shows), a "N more below the cutoff" line if total_all > len(rows), and a
  footer with the unsubscribe URL and manage URL in plain text. No markup,
  hard-wrap nothing (long URLs stay on one line).
- `_send_one`: build the text body alongside the html and pass
  `text=` to `send_email`. Same for the DIGEST_TO fallback send near the
  bottom of `_send_digest`.
- Note this changes the **Resend** sends too (Resend body gains a `"text"`
  key): intended — it's an improvement now, and it means cutover isn't the
  first time the text part exists.
- The unsubscribe link must appear in the text part (Gmail cross-checks the
  visible unsubscribe path).

**Tests:** `tests/test_digest_render.py` is the natural home. Add: text render
contains a known ticker + the unsub URL + no HTML tags; `_send_one` passes a
non-empty `text` kwarg to send_email (monkeypatch emailer.send_email, same
style as existing send tests if present).

---

## 5. Preserve unsubscribe history on re-signup  (LOW)

**Problem:** `subscribers.py:114` — the signup upsert does
`SET unsubscribed = FALSE, unsubscribed_at = NULL`. After reactivation the row
is indistinguishable from never-unsubscribed, undercutting migration 019's own
stated rationale ("re-signup after unsubscribe must not look like a fresh
opt-in when a complaint is investigated").

**Change:**

- New migration `backend/migrations/021_subscribers_resubscribed.sql`
  (idempotent, RLS already on the table so nothing needed there):
  ```sql
  ALTER TABLE subscribers
      ADD COLUMN IF NOT EXISTS resubscribed_at TIMESTAMPTZ;
  ```
  Header comment: why (audit trail), and that `unsubscribed_at` now means
  "last time they opted out" and survives re-signup.
- `signup()` upsert becomes:
  ```sql
  ON CONFLICT (email) DO UPDATE
      SET unsubscribed = FALSE,
          resubscribed_at = CASE WHEN subscribers.unsubscribed
                                 THEN NOW()
                                 ELSE subscribers.resubscribed_at END
  ```
  (keep `unsubscribed_at` untouched; keep the `RETURNING (xmax = 0)` trick and
  the "subscribed"/"reactivated" response mapping).
- Nothing reads `unsubscribed_at` as "is currently unsubscribed" — all queries
  key on the `unsubscribed` flag — verified at review time, but re-grep
  `unsubscribed_at` to confirm before changing.

**Ordering:** apply migration 021 to prod (`python backend/run_migration.py
migrations/021_subscribers_resubscribed.sql`) **before** deploying the code —
the new upsert references the column. Additive column, so applying early is
harmless.

**Tests:** `tests/test_subscribers_db.py` — follow its existing mocking
pattern: re-signup of an unsubscribed address keeps `unsubscribed_at` (no NULL
assignment in the SQL) and the response still says "reactivated".

---

## 6. Minor cleanups  (LOW — batch into one commit with the above or skip individually)

a) **Double JSON parse in the drain** — `ses_events.drain_queue` json.loads the
   body for `MessageId`, then `unwrap()` parses it again. Change `unwrap` to
   return `(envelope_id, notification)` (either may be None) and parse once.
   Update the three `unwrap` tests in test_ses_events.py to the new signature.

b) **Count without loading the list** — `subscribers.py`: `signup()` and
   `subscriber_count()` call `list_active_contacts()` and use `len()` /
   membership scan. Add two small helpers backed by single queries:
   `active_count()` → `SELECT COUNT(*) FROM subscribers WHERE NOT unsubscribed`;
   membership → `SELECT unsubscribed FROM subscribers WHERE email = %s`.
   Keep `list_active_contacts()` for the digest. Preserve exact endpoint
   semantics: already-active signup returns `{"ok": true, "status":
   "subscribed"}` without touching the row; count endpoint keeps the floor
   logic, TTL cache, and serve-stale-on-error behaviour (the helpers should
   raise RuntimeError on DB failure like list_active_contacts does, so the
   existing except clauses still catch).

c) **Drop redundant `from_addr` args** — `send_email` already defaults to
   `DIGEST_FROM` → `DEFAULT_FROM`. Remove the explicit
   `from_addr=os.environ.get("DIGEST_FROM", ...)` from
   `subscribers.unsubscribe_self`, `research._notify_new_comment`, and
   `feedback.submit_feedback` (feedback: check whether its local `from_addr` /
   `_DEFAULT_FROM` is used anywhere else in the module before deleting).
   The digest keeps passing its own from_addr (it resolves it once up front).

d) **Partial drain stats survive a crash** — `run_email_events.py` records
   `{"error": str(e)}` and loses whatever the drain stored before failing.
   Restructure `drain_queue` to wrap its loop in try/except and always return
   the stats dict, adding an `"error": "<msg>"` key on failure; `main()` treats
   the presence of `error` as failure (record_run("error", stats), exit 1).
   Update test_ses_events drain tests accordingly (they likely assert the
   return shape).

---

## Verification / wrap-up

1. `cd backend; python -m pytest tests/ -q` — full suite, not just the four
   email files (subscribers helpers touch endpoints other tests may exercise).
2. Frontend untouched — no build needed.
3. Show the user the change summary and **ask before committing** (single
   commit is fine; migration 021 must be applied to prod before the Dokploy
   redeploy that the push triggers — flag this explicitly when asking).
4. After deploy: memory file `project-ses-migration.md` should be updated
   (review fixes shipped; healthcheck WARN for ses_events expected until the
   drain cron is enabled).

## Explicitly out of scope (already tracked elsewhere)

- Dokploy: add the `run_email_events.py` cron (`*/15 7-18 * * 1-5` UTC) and the
  AWS/SES env vars — part of the parallel-run setup, blocked on SES production
  access (AWS case 178464313700575).
- EMAIL_PROVIDER=ses cutover, parallel run, Resend decommission.
- DMARC rua + Resend support ticket (Microsoft deferrals).
