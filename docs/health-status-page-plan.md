# Plan: Admin health/status page (live health + CI test report)

## Context

We now have a layered test/monitoring suite (commit e978115): a daily
`healthcheck` (DB freshness + API liveness), `smoke` (prod API shape + digest
dry-run), `e2e` (Playwright), `backend-tests` (unit), plus Dokploy refresh crons.
Their results are scattered — healthcheck freshness only lives in a daily GitHub
Actions log, CI status lives across separate Actions workflows, and the Dokploy
crons' health is only implicit in the data. This builds one **admin-only page**
that answers "is everything working right now?" at a glance, combining two
things that are deliberately different:

1. **Live system health** — computed on request from the DB, reusing the
   existing `healthcheck.py` checks. This is live operational truth and is the
   only view of the Dokploy crons' health (prices/RNS/dividends/shorts/index).
2. **CI test report** — the latest run status of each GitHub Actions workflow
   (tests + monitoring + the GHA refresh crons), pulled from the GitHub API.

Panel 1 is live; panel 2 is a thin mirror of the Actions tab folded in so it's
all in one place. They don't overlap: the GHA refresh crons show in panel 2,
the Dokploy crons show (as freshness) in panel 1.

## Design decisions (already settled)

- **Admin-only**, same gate as `research/admin`: frontend `useIsAdmin()` +
  backend `require_admin_token`. Unlock a browser with `/?admin=<token>` then
  visit `/status`. `noindex`, not in the public nav.
- **Route:** new `/status` page; new `GET /api/status` endpoint.
- **CI data source:** GitHub REST API (`/actions/workflows/{file}/runs`), called
  **server-side only** with a read-only token (`GITHUB_STATUS_TOKEN`) so the
  token never reaches the browser. Cached in-process (~5 min TTL) to avoid rate
  limits and latency. Repo is `rxs30279/finscope` (private → token required).
- **Health data source:** reuse `healthcheck.py` — do NOT reimplement the checks
  or thresholds.
- Graceful degradation: if the GitHub call fails or the token is unset, the CI
  panel shows "unavailable" and the health panel still renders (independent).

## Backend

### 1. Refactor `backend/healthcheck.py` to be callable in-process

Today the `@check` decorator runs each check at decoration time and appends to a
module-global `_results`; `run_db_checks()`/`run_http_checks()` mutate that
global. The CLI (`main()`) depends on this and must keep working unchanged.

Add a reentrant collector without breaking the CLI:

- Add `collect(query_one=None) -> list[dict]` that:
  - clears `_results` (fresh per call),
  - runs `run_db_checks()` + `run_http_checks()`,
  - returns `[{"name", "status", "detail"}, ...]` (structured, not the tuple).
- Thread an optional `query_one` callable through `run_db_checks()` so the API
  can inject a **pooled** query (see below) instead of `healthcheck._query_one`
  opening ~8 fresh SSL connections per request. Default stays the standalone
  `_query_one` so the GHA CLI is untouched.
  - Minimal version: `run_db_checks(query_one=_query_one)` and have each check
    call the passed-in `query_one`. The checks already funnel through
    `_query_one`, so this is a mechanical parameter thread-through.
- `main()` / `report()` keep using the tuple list; have `collect()` build dicts
  from the same `_results`. Keep `record()`/`check()`/thresholds as-is.

Reuse existing helpers: `record`, `check`, `_tier`, `_age_hours`, `_age_days`,
`API_BASE_URL`.

### 2. Pooled query adapter

In the endpoint module, build a `query_one` backed by `backend/db.py`'s pool
(`from db import query` → `query(sql, params)` returns `list[dict]`; take
`rows[0]`). Pass it into `collect()`. This keeps the admin page snappy and uses
the connection pool the rest of the app shares (see the DB consolidation in
commit 1eec0e2).

### 3. GitHub Actions client — new `backend/ci_status.py`

- `WORKFLOWS = ["healthcheck.yml", "backend-tests.yml", "smoke.yml", "e2e.yml",
  "refresh-analysts.yml", "refresh-financials.yml"]` (the GHA set; Dokploy crons
  are covered by panel 1).
- `latest_runs() -> list[dict]`: for each workflow file, GET
  `https://api.github.com/repos/rxs30279/finscope/actions/workflows/{file}/runs?per_page=1&exclude_pull_requests=true`
  with headers `Authorization: Bearer $GITHUB_STATUS_TOKEN`,
  `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`.
  Return `{workflow, status, conclusion, run_started_at, html_url}` per file
  (`conclusion` is success/failure/null; `status` is queued/in_progress/completed).
- In-process cache with ~300s TTL (mirror the pattern used by other cached
  endpoints, e.g. market cache / `_screener_cache`). Single-flight not required
  at this traffic level.
- If `GITHUB_STATUS_TOKEN` is unset or any request errors: return a sentinel
  `{"available": false, "error": "..."}` rather than raising — the endpoint must
  never 500 because GitHub is down.

### 4. Endpoint `GET /api/status` in `backend/main.py`

- Guard with `Depends(require_admin_token)` (same as the other admin routes).
- Body:
  ```json
  {
    "generated_at": "<utc iso>",
    "health": { "summary": "pass|warn|fail", "checks": [ {name,status,detail}, ... ] },
    "ci": { "available": true, "workflows": [ {workflow,conclusion,status,run_started_at,html_url}, ... ] }
  }
  ```
- `health.summary` = fail if any FAIL, else warn if any WARN, else pass (reuse
  the reduce logic from `report()`).
- Health is computed live each call; CI comes from the cached client.

### 5. Digest send notification (data source)

Goal: the page shows "this morning's digest emails went out (N recipients)"
without depending on cron-job.org's UI. Today the send stats only exist in
cron-job.org's stored HTTP responses — no DB trace — so there is nothing for
the page to read. Fix with the existing migration-008 convention:

- **Stamp `pipeline_runs` on every real send.** In `email_rns_digest.main()`,
  after a non-dry-run send completes, upsert `pipeline = 'rns_digest'` with
  `status` = `ok` (clean segment send) / `degraded` (fallback mode, partial
  failures, or nothing to send) / `failed`, and `detail` =
  `{"mode", "recipients", "sent", "failed"}`. Mirror `record_run()` in
  `dividends.py` (uses the shared pool + `ON CONFLICT (pipeline) DO UPDATE`).
  Best-effort `try/except` — a marker failure must never fail the send.
  `dry_run` never stamps.
- **New healthcheck** `@check("digest.sent")` reading that row (same shape as
  `shorts.refresh`, healthcheck.py): weekday 07:30 cron with weekend gaps →
  `_tier(days, warn_at=3, fail_at=5)`; force FAIL if `status != 'ok'` —
  which now catches the silent-fallback failure mode (the 03 Jun–10 Jul
  incident) from the daily GHA healthcheck, not just this page. Detail line
  includes mode + sent/failed counts.
- **Endpoint extra:** `/api/status` also returns a top-level
  `digest: {last_run_at, status, mode, recipients, sent, failed} | null`
  (one pooled query on `pipeline_runs`), so the frontend can render a
  dedicated card rather than parsing the check's detail string.

### 6. Env var

- `GITHUB_STATUS_TOKEN` — fine-grained PAT, **read-only**, scoped to the single
  `finscope` repo, permission **Actions: read** (+ Contents/Metadata: read as
  GitHub requires). Add to Dokploy backend env (see the env-redeploy gotcha in
  the Hetzner/Dokploy note — a redeploy is needed to pick it up). Not needed in
  GHA. Never referenced by the frontend.

## Frontend

Follow the `research/admin` pattern exactly.

### Files
- `frontend/src/app/status/page.tsx` — server wrapper: `metadata` with
  `robots: { index: false }`, renders `<StatusClient />`.
- `frontend/src/app/status/_client.tsx` — `"use client"`:
  - Gate on `useIsAdmin()` (from `@/hooks/useAdmin`); if not admin, render a
    short "Admin only — unlock with `/?admin=<token>`" message (mirror how
    `research/admin` handles the locked state).
  - `useEffect` → `fetch(`${API}/status`, { headers: adminHeaders() })`
    (`API`, `adminHeaders` from `@/lib/api`). Handle 403 (bad/absent token) with
    a clear "token rejected" message.
  - Poll/refresh: a manual "Refresh" button + optional 60s auto-refresh.
  - Render with `PageHeader` + the `colors`/`S` theme from `@/lib/theme`.

### Rendering
- **Email digest** card (top of page): headline notification — "Digest sent
  HH:MM · segment · 27/27 delivered" with a green tick when `status = ok` and
  the send is from today (or last Friday's on a weekend); amber/red banner
  with the detail when degraded/failed/stale; muted "no send recorded yet" if
  `digest` is null. Data comes from the `digest` object in `/api/status`.
- **System Health** section: one row per check — status chip
  (PASS green `#10b981` / WARN amber / FAIL red `#ef4444`, reuse the sentiment
  colors already in the codebase), check name, detail text. Sort FAIL→WARN→PASS
  so problems surface at the top. Header shows the overall `summary` and
  `generated_at` ("Updated Ns ago", like the Sidebar `as_of` stamp).
- **CI Workflows** section: one row per workflow — conclusion chip
  (success green / failure red / in_progress amber / null grey), workflow name,
  relative run time, and a link out to `html_url` ("view run"). If
  `ci.available` is false, show a single muted "CI status unavailable
  (GITHUB_STATUS_TOKEN not set?)" line.

No `data-testid` needed; the e2e suite doesn't have to cover this admin page
(optional: add a `status.spec.ts` that just asserts the locked state renders for
an anonymous visitor).

## Verification

1. **Backend unit**: add `backend/tests/test_status.py` — mock `collect()` and
   the CI client, assert `/api/status` shape + that it 403s without the admin
   header (extend the `test_admin_auth.py` pattern; `conftest.py` already sends
   `X-Admin-Token`). Run `python -m pytest` (stays hermetic — mock the GitHub
   call and the DB).
2. **healthcheck CLI unchanged**: `python healthcheck.py --verbose` still prints
   the same table (guards the refactor).
3. **Local endpoint**: with real `.env` (DB creds) + `GITHUB_STATUS_TOKEN` set,
   `GET /api/status` with `X-Admin-Token` returns both panels populated. Verify
   the health panel matches `healthcheck.py --verbose` output.
4. **Page**: `npm run dev`, unlock via `/?admin=<token>`, open `/status`; confirm
   both panels render, a forced FAIL (e.g. point a check at an empty table)
   shows red, and an anonymous browser sees the locked state.
5. **Digest marker**: run `/api/digest?dry_run=true` (must NOT stamp), then a
   real send (or wait for the next 07:30 cron) and confirm the `rns_digest`
   row lands in `pipeline_runs`, `healthcheck.py --verbose` shows
   `digest.sent`, and the card renders on `/status`. Unit-test the stamp
   status mapping (ok/degraded/failed) with the send mocked.
6. Add `GITHUB_STATUS_TOKEN` to Dokploy, redeploy, and load `/status` on prod.

## Build order

1. `healthcheck.py` `collect()` refactor + pooled `query_one` (+ CLI regression check).
2. Digest `pipeline_runs` stamp in `email_rns_digest.py` + `digest.sent` check
   (independently valuable: alerts on silent-fallback regressions via the
   daily GHA healthcheck even before the page exists).
3. `ci_status.py` (GitHub client + cache + graceful degrade).
4. `GET /api/status` endpoint (health + ci + digest) + `test_status.py`.
5. Frontend `/status` page (digest card + health + CI panels).
6. `GITHUB_STATUS_TOKEN` PAT → Dokploy env → redeploy → verify on prod.

## Build session decisions (resolved 2026-07-12)

Built in commit-pending form; open questions settled as:

- **Auto-refresh:** 60s auto-refresh **and** a manual Refresh button; the
  "Updated Ns ago" stamps re-tick every 15s without refetching.
- **CI panel scope:** GHA workflows only, as planned. Dokploy cron freshness
  stays in the health panel (the `*.refresh` / `digest.sent` checks) — not
  duplicated as a labelled group.
- **e2e `status.spec.ts`:** skipped (low value); the endpoint's 403-gate and
  the digest status mapping are covered by `backend/tests/test_status.py`.

### What shipped
- `healthcheck.py`: `collect(query_one)` + `summarize()`; `run_db_checks()`
  takes an injectable `query_one`; new `digest.sent` check. CLI unchanged.
- `email_rns_digest.py`: `main()` now wraps `_send_digest()` and stamps
  `pipeline_runs('rns_digest')` on real sends; pure `_send_status()` helper.
- `ci_status.py`: cached GitHub Actions client, fails soft.
- `main.py`: `GET /api/status` (admin-guarded) → health + ci + digest.
- `frontend/src/app/status/{page,_client}.tsx`: admin-gated page, noindex,
  not in nav/sitemap.
- Tests: `backend/tests/test_status.py`. Full backend suite green; `tsc` clean.

### Still manual (not done in the build session)
- ~~Provision `GITHUB_STATUS_TOKEN`~~ — done 2026-07-12: PAT created, added to
  Dokploy backend env, redeployed; CI panel populates in prod.
- First real digest send (next weekday 07:30, or a manual trigger) will write
  the first `rns_digest` marker; until then `digest.sent` reads FAIL and the
  card shows "no send recorded yet" — expected.

### Post-build fixes (2026-07-12 review)
- `_record_send` had an undefined-name bug (`mode` instead of
  `stats.get("mode")`) that would have crashed `main()` *after* a successful
  send — 500 back to cron-job.org, marker never stamped. Fixed; the stamp path
  and its never-raises contract are now covered in `tests/test_status.py`.
- `healthcheck.collect()` serialised with a lock (concurrent /api/status calls
  interleaved the module-global results).
- `ci_status`: parallel workflow fetches with a 5s timeout (was 6×15s
  sequential worst case); failures cached 60s instead of 300s.
- Digest card: an "ok" send older than the most recent expected weekday-07:30
  slot now renders amber "stale" instead of a green tick.

The `pipeline_runs('rns_digest')` marker convention exists because of the
silent single-recipient fallback incident — background and detection playbook
in [digest-segment-fallback-incident.md](digest-segment-fallback-incident.md).
