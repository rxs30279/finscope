# Email monitoring page (`/emails`) — implementation plan

Status: **not started.** Drafted and researched 2026-07-30. All decisions below are settled —
implement, don't re-litigate. See [[project-email-monitor-page]] in memory.

This doc is **untracked on purpose** (same call as `docs/ses-review-fixes-plan.md`) — it is a
to-do list, not documentation. Don't `git add` it. And per standing instruction, **ask before
any commit or push.**

A Resend-style per-message email monitor. It replaces nothing: `/status`'s Deliverability card
stays as the "is anything on fire" glance and gains a link into this page.

---

## Start here (recommended order)

| # | Step | Blocked? | Effort |
|---|---|---|---|
| 0 | ~~Tick `email.opened` + `email.clicked` on the Resend webhook~~ | **DONE 2026-07-30** | — |
| **0b** | **Strip `ipAddress`/`userAgent` from click `detail`** | **No — DO FIRST** | ~3 lines |
| 1 | `backend/email_monitor.py` — list + timeline endpoints | No | ~half day |
| 2 | `frontend/src/app/emails/` — the page | After 1 | ~half day |
| 3 | `ses:no-track` + `{{ses:openTracker}}` in the digest | No | ~30 min |
| 4 | Link `/status` → `/emails` | After 2 | ~10 min |
| 5 | *(optional)* Audience view over `subscribers` | After 1 | ~half day |
| 6 | *(at cutover)* SES config set + privacy notice | Cutover | — |

**Start with 0b — it is time-sensitive.** Opens and clicks went live on the Resend webhook on
2026-07-30, so the first click after tomorrow's 07:30 digest writes a subscriber IP address
into `email_events.detail`. Cheap now, awkward to unpick once rows exist. Steps 1–4 then work
on today's Resend data.

### Step 0b — strip PII from click details

`_DETAIL_KEYS` (`email_events.py:56`) includes `"click"`, and `_row()` copies the sub-object
verbatim:

```python
detail = {k: data[k] for k in _DETAIL_KEYS if k in data}
```

Resend's `data.click` is `{ipAddress, link, timestamp, userAgent}` — confirmed against their
webhook docs. `ipAddress` and `userAgent` are personal data under UK GDPR, `email_events` has
no retention policy, and nothing in this plan uses either field. Keep the link:

```python
# Resend's click sub-object carries ipAddress + userAgent. Keep the link, drop the
# personal data — email_events has no retention policy, so anything stored here is
# stored indefinitely, and the page only ever needs to know WHICH link was clicked.
_CLICK_KEEP = ("link", "timestamp")
```

Apply it to the `click` entry in `_row()`. **Opens need no equivalent** — `_DETAIL_KEYS` has
no `"open"` key, so `email.opened` rows store `detail = NULL` whatever Resend sends. Add a test
asserting a click payload containing `ipAddress`/`userAgent` stores neither.

*Verify after tomorrow's digest:*
```sql
SELECT detail FROM email_events WHERE event_type = 'email.clicked' LIMIT 5;
-- expect {"click": {"link": "...", "timestamp": "..."}} and NO ipAddress/userAgent
```

---

## Why now, not after the cutover

Migration 020's own comment states the case: the `provider` column exists because "a
per-provider delivery comparison — the entire acceptance gate for the cutover — is not
expressible" without it. The SES parallel run is the next step in [[project-ses-migration]],
and this page **is** that instrument. Built after the cutover it is a nice dashboard; built
now it is how you decide whether to cut over at all.

Secondary motive: `/status` answers "is anything on fire" in aggregate. Nothing in the app can
currently answer **"did this specific person get Tuesday's digest?"** — the question that
actually gets asked when a subscriber emails you.

---

## What already exists (this is mostly a read model)

`email_events` (migrations 018 + 020) already stores everything the page needs:

| column | note |
|---|---|
| `email_id` | Resend email id / SES `messageId` — one per message, one recipient each |
| `event_id` | PK; Svix delivery id or SNS MessageId. Idempotency, not display |
| `provider` | `resend` \| `ses` — the parallel-run cut |
| `event_type` | normalised `email.*` vocabulary, **identical across both providers** |
| `recipient`, `recipient_domain`, `subject` | denormalised onto every event row |
| `occurred_at`, `email_created_at`, `received_at` | lag arithmetic without a join |
| `detail` (JSONB) | bounce/complaint diagnostics — the "why" |

Both ingestion paths normalise into the same vocabulary (`ses_events.py` `_EVENT_MAP`,
`email_events.py` `_row`). **No migration is required for any phase in this plan.**

### Verified against prod 2026-07-30

```
provider  event_type                  n     first        last
resend    email.delivered           406     2026-07-21   2026-07-30
resend    email.sent                400     2026-07-21   2026-07-30
resend    email.delivery_delayed     20     2026-07-21   2026-07-21
ses       email.sent                  3     2026-07-21   2026-07-21   } the 7 mailbox-
ses       email.delivered             2     2026-07-21   2026-07-21   } simulator test
ses       email.complained            1     2026-07-21   2026-07-21   } rows — NOT real
ses       email.bounced               1     2026-07-21   2026-07-21   } deliverability
```

- **409 messages / 833 events (2.04 per message).** Trivial to aggregate live.
- **`GROUP BY email_id` is safe.** Checked explicitly: zero `email_id`s span more than one
  recipient, subject, or provider. `MAX(recipient)` in the aggregate is correct, not a guess.
- **6 messages have no `email.sent` event** (hence 406 delivered > 400 sent). So
  `ORDER BY COALESCE(sent_at, last_event_at)` is **load-bearing, not defensive** — ordering on
  `sent_at` alone silently sinks those six to the bottom regardless of age.
- **Zero `email.opened` / `email.clicked` rows** — see step 0.
- History starts 2026-07-21 (webhook config date), so a 30-day window shows ~9 days for now.

Volume is a non-issue: ~150 events/day today; with opens+clicks on, ~110k rows/year. Live
aggregation is fine — **no materialised view, no new index**. `idx_email_events_occurred`
covers the window scan, `idx_email_events_email_id` covers the detail lookup.

---

## Step 0 — Resend webhook — DONE 2026-07-30

Resend was already tracking opens and clicks (42.17% / 5.93% on its dashboard) but the webhook
endpoint `https://api.alphamoveai.co.uk/api/webhooks/resend` was not subscribed to those types,
so `email_events` held zero of them. **Both ticked 2026-07-30 ~15:00.** No code change needed
(`_row()` accepts any `type`), no migration.

The endpoint is healthy — the Resend event log shows `200 - OK`, `ATTEMPTS 1`, and our own
`{"ok":true,"stored":true,"event":"email.delivered"}` response body.

*Verify after the 2026-07-31 07:30 digest:*
```sql
SELECT event_type, COUNT(*) FROM email_events
WHERE occurred_at > NOW() - INTERVAL '1 day' GROUP BY 1 ORDER BY 2 DESC;
```
Expect `email.opened` rows. If only sent/delivered appear the subscription didn't save; if
nothing at all appears, suspect the signing secret.

*Expect:* event throughput roughly triples (from 2.04 events/message). Still trivial.

**No backfill is possible.** Resend's Replay button only replays deliveries that already
happened, and Resend creates a delivery record only for types the endpoint was subscribed to at
the time. Opens/clicks from 2026-07-21 → 2026-07-30 exist in Resend's own dashboard but can
never reach `email_events`. Expect the page to show zero engagement for those first nine days —
that is correct, not a bug.

**Gmail caches tracking pixels**, so re-opening an already-read message often won't fire a
second open event. To test before a real digest, send a *fresh* message and open that.

---

## Step 1 — backend read model

New module **`backend/email_monitor.py`**, registered in `main.py` alongside the other routers.

**Why a new module rather than extending `email_events.py`:** that file is the *Resend
webhook*; `ses_events.py` is the *SES drain*. A query layer belongs to neither. There is
already a noted smell here — `email_events.py` imports `_record_bounce` from `ses_events.py`,
making the Resend module depend on the SES one. Don't deepen it. The new module is read-only
and provider-agnostic; the two ingestion modules keep writing.

### `GET /api/emails` — message list

Admin-gated via `Depends(require_admin_token)`, like `/api/status` and `/api/gates`.

Params: `days` (default 7), `status`, `provider`, `q` (search), `limit` (default 100), `offset`.

```sql
WITH msgs AS (
  SELECT
    email_id,
    MAX(provider)                                    AS provider,
    MAX(recipient)                                   AS recipient,
    MAX(recipient_domain)                            AS recipient_domain,
    MAX(subject)                                     AS subject,
    MIN(occurred_at) FILTER (WHERE event_type = 'email.sent')       AS sent_at,
    MAX(occurred_at) FILTER (WHERE event_type = 'email.delivered')  AS delivered_at,
    MAX(occurred_at)                                 AS last_event_at,
    ARRAY_AGG(DISTINCT event_type)                   AS event_types
  FROM email_events
  WHERE occurred_at >= NOW() - (%(days)s || ' days')::INTERVAL
  GROUP BY email_id
)
SELECT *,
  CASE
    WHEN 'email.complained'       = ANY(event_types) THEN 'complained'
    WHEN 'email.bounced'          = ANY(event_types) THEN 'bounced'
    WHEN 'email.failed'           = ANY(event_types) THEN 'failed'
    WHEN 'email.delivered'        = ANY(event_types) THEN 'delivered'
    WHEN 'email.delivery_delayed' = ANY(event_types) THEN 'delayed'
    ELSE 'sent'
  END                                                AS status,
  'email.delivery_delayed' = ANY(event_types)        AS was_delayed,
  'email.opened'  = ANY(event_types)                 AS opened,
  'email.clicked' = ANY(event_types)                 AS clicked
FROM msgs
-- filters applied HERE, not in the CTE, so LIMIT/OFFSET paginate the filtered set
ORDER BY COALESCE(sent_at, last_event_at) DESC
LIMIT %(limit)s OFFSET %(offset)s
```

**Status is by precedence, not recency — deliberately unlike Resend.** For `sent →
delivery_delayed → delivered`, Resend shows "Delivered" and the lateness disappears. That
late-arrival case is the entire reason `email_events` exists (the 21 Jul Microsoft incident).
So: terminal status *plus* a separate `was_delayed` flag. A message that was delayed and never
delivered stays `delayed` — still stuck, and more alarming than one that recovered.

The response also carries a `summary` block: counts per status over the same window and
filters but **ignoring the status filter**, so the stat tiles stay stable and clickable.

### `GET /api/emails/{email_id}` — timeline

Every event for one message, ascending, with `detail` exposed for bounce diagnostics.
Deliberately **not** time-bounded, so an old message stays reachable by id.

### Tests

The suite is at 593 passed / 1 skipped; keep it green. Add `backend/tests/test_email_monitor.py`
covering at minimum:

- status precedence for each of the six outcomes;
- `was_delayed` true for `sent→delayed→delivered` **and** status still `delivered`;
- a message with no `email.sent` still orders correctly (the 6-row case above);
- status filter + `LIMIT/OFFSET` paginate the *filtered* set, not the raw one;
- `summary` ignores the status filter but honours window/provider/search.

---

## Step 2 — frontend `/emails`

Files: `frontend/src/app/emails/page.tsx` + `_client.tsx`. Mirror `/gates` exactly —
`page.tsx` carries `metadata` with `robots: {index:false, follow:false}`; `_client.tsx` uses
`useIsAdmin()`, `adminHeaders()`, the shared `colors`, monospace.

**Match our dark admin aesthetic, not Resend's light theme.** The reference screenshots are
for *layout and information architecture only* — `/status` and `/gates` set the visual language.

```
Emails

[ SENT 60 ] [ DELIVERED 58 ] [ DELAYED 2 ] [ BOUNCED 0 ] [ COMPLAINED 0 ]

[Search...]  [Last 7 days v]  [All statuses v]  [All providers v]

TO                        STATUS      SUBJECT                        SENT
someone@example.com       Delivered   RNS Digest Thu 30 Jul — 54 …   7h ago
someone@example.net       Bounced     RNS Digest Thu 30 Jul — 54 …   7h ago
```

- Four columns, as Resend has them: **To · Status · Subject · Sent** (relative time).
- Filter row: search, date range, status, and **provider** where Resend has "All API keys".
- Stat tiles above the table, clickable to filter.
- Row click → drawer with the event timeline and bounce diagnostics.
- Persist filters in `sessionStorage`, **excluding** the search box — same pattern and same
  reasoning as [[project-rns-filter-persistence]].
- Desktop-first. Dense admin table, admin-only page.

**One deliberate divergence.** Resend collapses everything into a single chip, so an opened
message reads "Opened" and a delayed-then-delivered one reads "Delivered" — the delay
disappears, and so does whether an opened mail was ever delayed. Those are orthogonal
dimensions. Keep the chip for the *deliverability* outcome and give open/click their own small
indicator column. Same information, nothing hidden.

*Verify:* load `/emails` unauthenticated → "Admins only". Unlock with `/?admin=<token>`, then
confirm a known delayed message from 2026-07-21 shows `delivered` + a delay indicator.

### Optional metrics view (only if wanted later)

From the Resend metrics screenshots: two big tiles (`EMAILS`, `DELIVERABILITY RATE`) over a
multi-series time chart (delivered / opened / clicked / delayed) with a hover tooltip, then
`OPEN RATE` and `CLICK RATE` bar-chart cards below.

**Define the denominators explicitly** — Resend's own two views disagree, the chart legend
reading 61% / 27% while the cards below read 42.17% / 5.93% for the same period. Don't
reproduce that. **Load the `dataviz` skill before writing any chart code.**

---

## Step 3 — digest changes for SES tracking

Both are **inert while Resend is sending**, so they carry zero cutover-day risk and should
ship now rather than on the day.

### 3a. `ses:no-track` on the two footer links

In `_sub_footer()` (`email_rns_digest.py`, ~line 619):

```python
f'<a href="{html.escape(manage_url)}" style="color:#999;" ses:no-track>Subscribe</a>'
f'<a href="{html.escape(unsub_url)}" style="color:#999;" ses:no-track>Unsubscribe</a>'
```

SES click tracking rewrites every `<a href>` in the HTML body; this attribute exempts
individual links. It is **required** on the unsubscribe link: `_render_text()`'s comment
(~line 576) documents that Gmail cross-checks the visible unsubscribe path, and the URL
currently appears identically in the `List-Unsubscribe` header, the HTML body and the text
part. Click tracking rewrites only the HTML one, breaking that match. `ses:no-track` keeps all
three identical.

### 3b. `{{ses:openTracker}}` near the top of the body

SES puts the open pixel at the **bottom** by default, and clients that truncate long messages
never load it — silently undercounting opens. The digest is a long row list, so this bites.

**TRAP: `_render_html()` returns an f-string.** Writing `{{ses:openTracker}}` inside it emits
`{ses:openTracker}` — single braces, silently ignored by SES, pixel stays at the bottom, and
nothing visibly fails. Do **not** hand-escape to `{{{{ses:openTracker}}}}`. Use a module
constant instead:

```python
# SES replaces this with the open-tracking pixel. Placed high in the body because
# SES's default position is the very bottom, which clipped previews never reach.
_OPEN_TRACKER = "{{ses:openTracker}}"
```

then interpolate `{_OPEN_TRACKER}` immediately after `<body>` opens in the returned f-string.

**Exactly one placeholder** — more than one returns `400 BadRequestException`.

*Verify:* render a digest locally and assert the raw HTML contains the literal string
`{{ses:openTracker}}` (double braces) exactly once, and `ses:no-track` twice. Worth an
assertion in the existing digest tests rather than a manual eyeball.

---

## Step 4 — link `/status` → `/emails`

The Deliverability card stays exactly as it is. Add a link so the aggregate view drills into
the detail one.

---

## Step 5 (optional) — audience view

Resend's Audience tab maps cleanly onto our `subscribers` table, which holds every column it
displays and one it doesn't (`bounce_reason`).

```
Audience

ALL 63     SUBSCRIBED 60     UNSUBSCRIBED 3     BOUNCED 0

EMAIL                     STATUS        ADDED
someone@example.com       Subscribed    11d ago
someone@example.net       Bounced       12d ago   mailbox full
```

Columns **Email · Status · Added**, plus bounce reason where set. Derive status from
`_MAILABLE` (`subscribers.py:52`, committed in `4bc9d56`) rather than re-expressing "not
unsubscribed and not bounced" — that constant is deliberately shared by `list_active_contacts()`
and `active_count()` so they can't drift, and this page must join that set, not add a fourth
spelling.

### Resend's Audience is STALE — do not reconcile to it

Measured 2026-07-30:

| | Resend Audience | our `subscribers` |
|---|---|---|
| all contacts | 55 | **63** |
| subscribed | 54 | **60** |
| unsubscribed | 1 | **3** |

Resend is frozen at the 2026-07-21 migration snapshot ([[project-ses-migration]] records "55
rows, 54 active, counts matched Resend exactly"). Since then **8 signups and 2 unsubscribes
went to Postgres only**, because `list_active_contacts()` is the send list and the
`RESEND_SEGMENT_ID` gate was deliberately removed. This is the design working correctly — the
Resend Audience page is a stale copy. **Never treat it as truth, never sync back to it.**
Nothing is lost at decommission.

---

## Step 6 — SES side (at cutover only)

1. Tick Open and Click on config set `alphamove-digest`'s event destination (eu-west-2).
2. Review the privacy notice — a tracking pixel on a UK subscriber list is a consent question,
   and this reverses an earlier deliberate "Opens/Clicks correctly NOT ticked".

**Decided 2026-07-30:** both open and click tracking, using SES's default `awstrack.me`
tracking domain. A custom HTTPS tracking domain was considered and **rejected** — per the AWS
docs it needs a CloudFront distribution and an SSL certificate, not just a CNAME, and the
CNAME-only variant is HTTP-only and warns users on HTTPS links.

Tracking is **free** (verified against the SES pricing page — not a charged component). The
paid engagement product is Virtual Deliverability Manager at $0.07/1,000 emails, already
rejected as redundant given `email_events`. This page is what makes that call hold.

---

## Things to fix along the way

- **`email_events.py`'s module docstring says "nothing reads rows older than the /status
  window"**, and on that basis licenses pruning with a dated `DELETE`. This page makes that
  false — it reads a user-selectable window. **Amend the docstring**, or the next person
  prunes away the page's data.
- **`recent_summary()` is already safe against the new event types.** It counts
  `COUNT(DISTINCT email_id)`, not events, precisely so the rate doesn't dilute "as more event
  types are subscribed" (its own docstring). Opens/clicks change neither numerator nor
  denominator. Confirm, don't re-engineer.
- The 7 mailbox-simulator rows from 2026-07-21 (`bounce@` / `complaint@simulator.amazonses.com`)
  are test data, not real deliverability. Outside a 7-day window now, but they reappear in a
  30-day view — don't misread them, and don't let them tint the stat tiles.
- **Don't paste real subscriber addresses into commits, artifacts or screenshots.** The
  reference screenshots contain the live list; use `someone@example.com` in any mockup.

## Not doing

- **Body storage / rendered-email preview.** Decided against 2026-07-30 — the timeline plus
  bounce diagnostics is the useful part. Cheap to add later: the digest body is identical for
  all recipients, so it is one row per digest *run*, not per recipient.
- Materialised views or new indexes — the volume does not justify them.
- A custom HTTPS tracking domain (CloudFront + cert), per step 6.
- Any change to the `/status` Deliverability card beyond adding a link.
