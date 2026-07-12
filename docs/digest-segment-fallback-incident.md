# Email digest: silent single-recipient fallback (03 Jun – 10 Jul 2026)

**Date investigated/fixed:** 2026-07-12
**Impact:** every weekday RNS digest for ~5½ weeks went to one address
(`DIGEST_TO`) instead of the Resend segment. No subscriber other than the
owner received a digest in that window.

## Symptom

The Resend Emails dashboard showed each daily digest delivered to
`richard_stephens@hotmail.co.uk` only, even though the Daily Digest segment
contained a second active contact (`alphamoveai@richy13.fmail.fyi`, created
2026-06-25) and an early multi-recipient test was remembered as working.

## How recipients are resolved (unchanged)

`backend/email_rns_digest.py::main()`:

1. **Segment mode** — if `RESEND_SEGMENT_ID` is set, list the segment's
   non-unsubscribed contacts via `subscribers.list_active_contacts()` and send
   one email per contact (per-recipient unsubscribe link + headers).
2. **Fallback** — if the segment env is missing, the contact listing raises,
   or the list comes back empty, send a single email to `DIGEST_TO`.
3. **Nothing** — if neither is configured, log and exit 0.

The cron is external: cron-job.org hits
`GET https://api.alphamoveai.co.uk/api/digest` (token-authed) Mon–Fri at
07:30 UK, and the digest executes inside the Dokploy API container.

## Investigation trail

- The segment itself was healthy: `GET /segments/{sid}/contacts` returned 27
  active contacts (owner + fmail test address + ~25 real signups from
  11–12 Jul).
- Resend's email log (`GET /emails`) was the smoking gun: segment mode fired
  **exactly once ever** — 2026-06-02, three recipients. Every digest from
  2026-06-03 through Fri 2026-07-10 was a single send to `DIGEST_TO`. The
  fmail contact never received any email.
- Because the owner is both a segment contact and `DIGEST_TO`, a fallback
  send is **indistinguishable from a healthy send in the owner's inbox** —
  which is why it went unnoticed for five weeks.
- The prod container on 2026-07-12 was verified healthy: a
  `/api/digest?dry_run=true` run logged
  `would send … to 27 recipient(s)`, and `/api/subscribers/count` returned
  27. First real multi-recipient send expected Mon 2026-07-13 07:30.

## Root cause

Not provable retroactively — the container that ran Friday's digest was
replaced by the 2026-07-12 redeploys and its logs pruned. The breakage
window is consistent with the known Dokploy/Vercel env-migration gotchas
(env vars not landing until a successful full deploy; the Swarm stale-image
pinning bug; the 2026-06-15 project split dropping `RESEND_*` vars): the
executing environment lacked a usable `RESEND_SEGMENT_ID`, so `main()` took
the `DIGEST_TO` fallback every day. This weekend's redeploys restored it.

## Fix: make the send path observable

The gap that let this hide: `/api/digest` returned only
`{"ok": true, "message": "Digest sent"}` regardless of path, and Dokploy
prunes old container logs, so there was no durable record of which branch
ran.

Changes (2026-07-12):

- `email_rns_digest.main()` now returns a stats dict instead of a bare exit
  code: `exit_code` (0 ok / 1 config-or-render failure / 2 partial segment
  send), `mode` (`"segment" | "fallback" | "none" | "dry_run"`),
  `recipients`, and `sent`/`failed` for segment sends. The CLI entry point
  (`python email_rns_digest.py`) still exits with the same codes.
- `/api/digest` surfaces those fields in its JSON response. cron-job.org
  stores response bodies per execution, so its history is now a durable
  audit trail of every send.

Healthy weekday run now looks like:

```json
{"ok": true, "dry_run": false, "mode": "segment", "recipients": 27,
 "sent": 27, "failed": 0, "message": "Digest sent"}
```

A recurrence of this incident would instead show
`"mode": "fallback", "recipients": 1` — visible at a glance.

## How to check the send path (any time)

- **Resend dashboard / `GET /emails`:** count rows per digest day — one row
  per recipient. A single row on a day with >1 active contact = fallback.
- **Container logs:** grep `[digest]` — segment mode logs one
  `sent to <email>` per contact plus a
  `segment send complete: N sent, M failed` summary; the fallback path logs
  `FAILED to list contacts` or `segment configured but empty` first.
- **cron-job.org history:** response body per execution (post-fix).

## Verification

- 16/16 unit tests in `tests/test_digest_render.py` pass.
- Local `python email_rns_digest.py --dry-run` runs the full
  fetch → render → count path, exits 0, reports 27 recipients.
- Note: the local dry run needs a UTF-8 stdout on Windows
  (`PYTHONIOENCODING=utf-8`) because of `≥`/`£` in log lines; the Linux
  container is unaffected.
- The smoke test (`smoke/test_digest_dryrun.py`) only asserts `ok`/`dry_run`,
  so it needed no changes and stays compatible.

## Follow-up

- [ ] Deploy: push → Dokploy build → `ssh root@167.233.123.195 redeploy`
      (a plain Redeploy does not swap the image — see the Dokploy gotchas).
- [ ] Mon 2026-07-13 ~07:35: confirm ~27 digest rows in Resend (including
      `alphamoveai@richy13.fmail.fyi`) and `"mode": "segment"` in the
      cron-job.org execution history.
