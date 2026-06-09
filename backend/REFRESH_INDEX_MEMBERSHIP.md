# Index Membership Refresh — Runbook

Keeps the `company_metadata` universe in step with the live constituents of the
four indices the screener tracks: **FTSE 100, FTSE 250, FTSE SmallCap, FTSE AIM
100**. Run it on a schedule; it adds new constituents, re-tiers ones that moved,
and removes ones that have dropped out of every tracked index.

Script: [`refresh_index_membership.py`](./refresh_index_membership.py)

---

## When to run

**Once a month**, on the **1st** (or any fixed day you'll remember).

The FTSE indices are formally reviewed quarterly — changes take effect after the
close on the **third Friday of March, June, September and December**. Those are
the months you'll see the most movement. Running monthly the rest of the year is
still worth it: it's cheap, it's safe (dry-run first), and it catches the ad-hoc
changes that happen between reviews — fast-entry promotions, takeovers,
delistings, and ticker changes.

A month with no changes just prints zeros and writes nothing.

---

## How to run

Always run from the `backend/` directory (the script reads `backend/.env` for
the database connection).

```bash
cd backend
```

### Step 1 — Dry run (always do this first)

```bash
python refresh_index_membership.py
```

This **writes nothing**. It fetches the current constituents and prints a
reconciliation report:

```
  New                  : 8     <- in an index, not yet in the DB
  Moved (tier change)  : 9     <- e.g. promoted FTSE 250 -> FTSE 100
  Dropped              : 15    <- left every tracked index
```

Read the report. Sanity-check it:

- **NEW** names should be real recent additions/IPOs.
- **MOVED** names should match the latest reshuffle (promotions/relegations).
- **DROPPED** names should be takeovers, delistings, relegations below SmallCap,
  or ticker changes. **These will be permanently deleted** (see below), so make
  sure nothing in this list is a stock you want to keep.

If a stock you want to keep shows up under DROPPED, stop and investigate before
applying — it usually means a ticker change (the old code drops out, the new one
appears under NEW) or a temporary scraping gap.

### Step 2 — Apply

When the dry-run report looks right:

```bash
python refresh_index_membership.py --apply
```

This commits the changes:

| Bucket  | Action |
|---------|--------|
| NEW     | Inserts the row with metadata from yfinance, `financials_updated = NULL`. |
| MOVED   | Updates `ftse_index` to the new tier. |
| DROPPED | **Hard-deletes** the company from `company_metadata` and every dependent table (financials, prices, analyst snapshots, news, RNS, scores) — one transaction per symbol. Permanent and irreversible. |

### Step 3 — Fetch financials for the new constituents

New rows have `financials_updated = NULL`, so the **daily `updater.py` cron picks
them up first** automatically — no action needed if you can wait a day.

To populate them immediately instead, run the updater; it processes oldest-first,
so the new names go first:

```bash
python updater.py
```

(New constituents won't appear in the screener with full ratios until their
financials have been fetched.)

---

## Safety

- **Dry-run is the default.** Nothing is written without `--apply`.
- **Minimum-constituent floor.** If any index scrape comes back implausibly short
  (e.g. Hargreaves Lansdown changes their page layout), the script aborts the
  whole run and writes nothing — it will never mass-delete real stocks because a
  fetch broke. If you see `!! BELOW FLOOR`, the source needs fixing; don't apply.
- **Idempotent.** Re-running is safe — inserts/updates are upserts.

---

## Source & how it works

Constituents are scraped live from Hargreaves Lansdown's market-summary pages
(one EPIC+Name table per index) using `curl_cffi` with Chrome impersonation. EPIC
codes are mapped to Yahoo symbols by rule (`BT.A` → `BT-A.L`, `AV.` → `AV.L`,
`III` → `III.L`), so there is no override table to maintain.

Output is also written to `backend/refresh_index_membership.log`.

---

## Quick reference

```bash
cd backend
python refresh_index_membership.py            # 1. dry run — review the report
python refresh_index_membership.py --apply    # 2. apply the changes
python updater.py                             # 3. (optional) fetch new financials now
```
