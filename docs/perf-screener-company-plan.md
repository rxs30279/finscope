# Perf plan — screener + company page (post-virtualization follow-ups)

**Status:** WS1 + WS2 done (2026-07-23, uncommitted). WS3 (CLS) not started.
**Owner context:** follows the screener virtualization/memoization + company scroll-snap
removal already shipped in commit `8958311`.

## Why

Lighthouse (mobile profile, 4× CPU throttle — mirrors Core Web Vitals) after the
virtualization deploy:

| Metric | /screener | /company/shel | Target |
|---|---|---|---|
| Perf score | 59 | 57 | ≥90 |
| LCP | 1.8s | 2.6s | <2.5s |
| FCP | 1.5s | 1.6s | <1.8s |
| **CLS** | **0.183** | **0.176** | <0.1 |
| **TBT** | **3,010ms** | **3,710ms** | <200ms |
| Script transfer | 478 KB / 21 reqs | 611 KB / 30 reqs | — |

Virtualization worked: the screener LCP element is now the `<h1>` title (not the
700-row table), LCP is healthy. The score is now held down by **TBT (main-thread
blocking → poor INP)** and **CLS**, which come from third-party analytics and
recharts, NOT from our table. These three workstreams target that.

TBT breakdown from the audit (`bootup-time` / `third-party-summary`):
- **Google Tag Manager / GA `gtag.js`** — ~1,000ms main + ~1,000ms blocking on BOTH
  pages, 62 KB unused. Already `strategy="lazyOnload"` but still lands in the TBT
  window because TTI is ~7.6s (load event fires before TTI).
- **PostHog recorder + surveys** — ~600ms + unused bytes, initialised at mount.
- **Shared vendor chunk `1255-*.js` (recharts)** — 1.7s on /screener but **7s
  (throttled) on the company page** — the dashboard's charts.

---

## Workstream 1 — Defer third-party analytics (biggest cross-page win) — DONE

Implemented as specced: `DeferredGA.tsx` loads gtag.js on first
pointerdown/keydown/scroll or a 5s idle fallback; `layout.tsx`'s two `<Script>`
tags replaced with `<DeferredGA />` in the body. PostHog's `posthog.init` in
`posthog-provider.tsx` deferred the same way (2s idle fallback) via a shared
`frontend/src/lib/idle.ts` helper (`scheduleIdle`/`cancelIdle`, feature-detects
`requestIdleCallback` without the `"x" in window` pattern — that narrows
`window` to `never` in the `else` branch under this TS/lib.dom version).
`disable_surveys: true` and `disable_session_recording: true` added per
product decision (surveys unused; replay wasn't being watched).

**Gotcha found + fixed:** deferring `posthog.init` means `posthog.capture()`
is a silent no-op (checks `__loaded` internally, no queueing) until init runs
— `PageViewTracker`'s mount-time `$pageview` would otherwise be dropped for
every session. Fixed with a `posthog-ready` window event: capture waits for
it if not yet ready, fires immediately once it is.

Typecheck + `next build` both clean.

## Workstream 1 (original spec, for reference)

Goal: keep GA + PostHog off the critical path so they don't add to TBT during load.

### 1a. Google Analytics — `frontend/src/app/layout.tsx` (lines ~88–100)
Currently two `<Script strategy="lazyOnload">` tags for `gtag/js` + `ga4-init`.
`lazyOnload` fires on window `load`, which is still inside the TBT window here.

**Change:** load GA only on the **first user interaction** (or a long idle timeout),
not on `load`. Extract into a small client component, e.g.
`frontend/src/components/analytics/DeferredGA.tsx`:
- On mount, attach one-time listeners: `pointerdown`, `keydown`, `scroll`
  (`{ once: true, passive: true }`), plus a `setTimeout` fallback (~5s) /
  `requestIdleCallback`.
- On the first of those, inject the gtag script + run the init snippet, then
  remove listeners.
- Render `<DeferredGA />` in `layout.tsx` body (remove the two `<Script>` tags from
  `<head>`).
- Keep the GA id `G-4D7NSXL95B`.

### 1b. PostHog — `frontend/src/app/posthog-provider.tsx` (`posthog.init` in useEffect, line ~34)
Currently inits synchronously in a mount `useEffect`.

**Changes:**
- Defer `posthog.init(...)` to `requestIdleCallback` (fallback `setTimeout ~2s`) or
  first interaction, so it's off the hydration path.
- Consider `disable_session_recording: true` and/or `disable_surveys: true` in the
  init options — the audit showed `posthog-recorder.js` + `surveys.js` loading and
  costing main-thread time. **Product decision:** only disable session replay if the
  user isn't actively using it (the current comment says it's left at default,
  enabled when toggled server-side). Ask before disabling replay; surveys are safe
  to disable if unused.
- Preserve the existing `before_send` admin-token scrub and manual `$pageview`
  tracking (`PageViewTracker`) exactly.

**Expected:** ~1.5s TBT off both pages.

---

## Workstream 2 — Code-split recharts on the company page — DONE

All 9 recharts-using blocks in `CompanyDetail.tsx` extracted to leaf
components under `frontend/src/components/company/charts/` (OverviewChart,
WaterfallChart incl. WrapTick, RevenueEbitdaFcfChart, EpsChart,
QuarterlyRevenueChart, ReturnOnCapitalChart, DebtEquityChart,
CurrentRatioChart, ProfitMarginsChart), each loaded via
`next/dynamic(..., { ssr: false, loading: () => <div style={{height:H}}/> })`
with H matching the chart's own `ResponsiveContainer` height (S.card/title
wrappers stay inline in CompanyDetail — no recharts dependency, so no need to
defer them). `PriceChart` (already ssr:false-imported by `_client.tsx` one
level up) is now also dynamic from CompanyDetail itself, with a `minHeight:400`
placeholder matching its own internal loading state.

**Gotcha:** `next/dynamic`'s options arg must be an object *literal* — a
shared `const noSsr = {ssr:false}` variable fails the build
("next/dynamic options must be an object literal"), so `{ ssr: false }` is
repeated at each call site.

Confirmed via `.next/react-loadable-manifest.json` that CompanyDetail's own
chunk no longer contains recharts (`grep recharts` on its chunk files is
empty); recharts now lives in a shared async chunk fetched only when a chart
tab actually renders, deduped once across all 9 leaf components + PriceChart
since they're all reachable from the same parent. Typecheck + `next build`
clean; verified live via the `verify` skill (backend :8001 / frontend :3005,
Playwright headless) — all 5 non-chart tabs (overview/financials/valuation/
health/growth) plus the default chart tab render correctly with zero console
errors, `/screener` unaffected (682 companies, virtualized).

## Workstream 2 (original spec, for reference)

Goal: stop the recharts chunk (7s throttled) from executing on the dashboard's
initial paint.

Current state:
- `frontend/src/app/company/_client.tsx` already `dynamic(() => import(CompanyDetail),
  { ssr:false, loading: <div minHeight:400> })`. Good — keep.
- `frontend/src/components/company/CompanyDetail.tsx` imports recharts **statically**
  at the top (lines ~4–7) AND uses it inline for the financial-history charts
  (BarChart etc. around line ~231). `PriceChart.tsx` (the default "chart" tab, line
  ~175) also uses recharts. So recharts is bundled into CompanyDetail's chunk and
  parsed on mount regardless of active tab.

**Changes:**
1. Extract every recharts-using block out of `CompanyDetail.tsx` into leaf
   components (PriceChart already is one; pull the inline financials BarChart into a
   new `FinancialsChart.tsx`). Remove the top-level `from "recharts"` import from
   `CompanyDetail.tsx` so its own chunk no longer contains recharts.
2. Load each chart component via `next/dynamic` with `{ ssr:false }` and a
   fixed-height placeholder matching the chart's rendered height (prevents CLS on
   tab switch). PriceChart placeholder height should match its current chart height.
3. Net effect: the dashboard shell (tab bar + metric cards + header) paints and
   becomes interactive without waiting on recharts; recharts loads per-chart-tab.
   The default "chart" tab still needs it, but it now streams in behind a
   placeholder instead of blocking the whole dashboard mount.

**Optional bigger win (separate, don't do in this pass):** the Speed-Insights memory
notes /markets replaced recharts with a lighter split (221→113 kB). Consider a
lighter chart lib for the company page later. Out of scope here.

**Expected:** company-page TBT down substantially; TTI earlier.

---

## Workstream 3 — CLS (both pages)

Audit `layout-shifts` culprits:
- **/screener: `<main>` shifts 0.183.** Client-only screener: renders the short
  "Screening…" loading state then swaps in the full-viewport table. Reserve the
  results area so nothing jumps.
- **/company: the `<section style="margin-bottom:24px">` (CompanyHeader) shifts
  0.143.** Likely font swap-in (self-hosted Inter/Mulish `display:"swap"` in
  `layout.tsx`) and/or the CTA banner above resizing. (NOT caused by the snap
  removal — those props don't affect flow.)

**Changes:**
1. **Screener** (`frontend/src/components/screener/Screener.tsx`): wrap the loading
   state so it reserves the same height the table will occupy — give the
   `loading ? <Screening…>` branch a container with `minHeight: tableMaxH` (the same
   measured value the scroll container uses). Verify the shift is gone; if `<main>`
   still shifts, the cause is elsewhere (font/hydration) — see #3.
2. **Company CTA banner** (`frontend/src/components/EmailDigestCTA.tsx`, rendered in
   `company/[symbol]/page.tsx` above the header): give it a fixed/min height so it
   can't resize the header section under it.
3. **Fonts** (`frontend/src/app/layout.tsx`, `Inter`/`Mulish` `next/font`): if the
   header still shifts, switch `display: "swap"` → `display: "optional"` (or add
   explicit `adjustFontFallback`/`size-adjust`). `optional` removes the swap-in
   reflow at the cost of occasionally showing the fallback font on a cold load —
   acceptable for CWV. Verify CLS on both pages after.

CLS needs a measure→fix→re-measure loop; treat the culprit nodes above as the
starting hypotheses, confirm with a fresh Lighthouse run each time.

---

## Verification — how to re-run Lighthouse (reproduce before/after)

Chrome is at `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`.
Scratchpad dir used for outputs last time (any writable dir is fine).

```powershell
$env:CHROME_PATH = "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
$out = "<scratchpad-or-any-dir>"
npx --yes lighthouse "https://app.alphamoveai.co.uk/screener" --quiet `
  --only-categories=performance `
  --chrome-flags="--headless=new --no-sandbox --disable-gpu" `
  --output=json --output=html --output-path="$out\lh-screener"
npx --yes lighthouse "https://app.alphamoveai.co.uk/company/shel" --quiet `
  --only-categories=performance `
  --chrome-flags="--headless=new --no-sandbox --disable-gpu" `
  --output=json --output=html --output-path="$out\lh-company"
```

Parse key metrics from `*.report.json`: `categories.performance.score` and
`audits.{first-contentful-paint,largest-contentful-paint,total-blocking-time,
cumulative-layout-shift,speed-index,interactive}.displayValue`. Deeper diagnostics:
`audits.{bootup-time,third-party-summary,layout-shifts,unused-javascript}.details.items`.

Also confirm with real-user **Speed Insights** on Vercel over ~2–4 days
(LCP/INP/CLS for `/screener` and `/company/*`). Note `sampleRate={0.25}` in
`layout.tsx`, so RUM volume is quartered.

## Gotchas / house rules
- **Typecheck after edits:** `cd frontend; npx tsc --noEmit` (was clean).
- **Windows Next build/dev CWD lock** (see memory `project-windows-next-cwd-lock`):
  next build/dev hangs silently if a process CWD sits inside `.next`; PS 5.1 `cd`
  doesn't move the process CWD. Run node tooling from the `frontend` dir.
- **Git:** always ask before commit/push (memory `feedback-git-confirm`). This repo
  commits directly to `main`; Dokploy auto-deploys on push. `/api` is an external
  rewrite so it's never edge-cached — irrelevant to these client-side fixes.
- Suggested sequencing: WS1 (analytics, cross-page, low risk) → WS2 (company
  recharts) → WS3 (CLS, needs measure loop). Can be separate commits.
```
