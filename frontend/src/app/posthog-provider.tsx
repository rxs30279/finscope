"use client";

import { usePathname, useSearchParams } from "next/navigation";
import posthog from "posthog-js";
import type { CaptureResult } from "posthog-js";
import { PostHogProvider as PHProvider, usePostHog } from "posthog-js/react";
import { Suspense, useEffect } from "react";
import { scheduleIdle, cancelIdle } from "@/lib/idle";

// Strip the one-time `?admin=<token>` secret from any URL before it reaches
// PostHog. That token unlocks the admin controls (see hooks/useAdmin.ts); it
// sits in the address bar for a single render before useIsAdmin removes it, so
// a pageview / pageleave / autocapture event fired in that window would
// otherwise ship the token to analytics.
// posthog.capture() is a silent no-op until posthog.init() has run — since
// init is now deferred (see PostHogProvider below), PageViewTracker's
// mount-time pageview would otherwise be dropped while waiting for the
// idle/interaction trigger. This event lets it wait for init instead.
const POSTHOG_READY_EVENT = "posthog-ready";
let posthogReady = false;

function scrubAdminParam(url: unknown): unknown {
  if (typeof url !== "string" || !url.includes("admin=")) return url;
  try {
    const u = new URL(url);
    if (u.searchParams.has("admin")) {
      u.searchParams.delete("admin");
      return u.toString();
    }
  } catch {
    /* not a parseable absolute URL — leave untouched */
  }
  return url;
}

// Initialises PostHog once on the client and mounts the React provider so any
// component can call usePostHog(). The key/host come from NEXT_PUBLIC_ env vars;
// api_host points at our same-origin /ingest reverse proxy (see next.config.ts)
// so ad blockers can't drop the requests, while ui_host lets the toolbar link
// back to the real EU dashboard.
export function PostHogProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
    if (!key) return; // no key configured (e.g. local dev) — stay a no-op

    let initialised = false;
    const init = () => {
      if (initialised) return;
      initialised = true;
      cleanup();
      posthog.init(key, {
        api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || "/ingest",
        ui_host: "https://eu.posthog.com",
        // We track pageviews manually below so SPA route changes are captured;
        // pageleave stays on so bounce/among-page time is measured.
        capture_pageview: false,
        capture_pageleave: true,
        person_profiles: "identified_only",
        // Not in use — skip loading surveys.js entirely (perf: cuts main-thread
        // cost seen in the 2026-07-23 Lighthouse audit).
        disable_surveys: true,
        // Session replay disabled — recorder.js was loading (and costing main-
        // thread time) regardless of whether replay was toggled on server-side.
        disable_session_recording: true,
        // Safety net covering every event type (pageview, pageleave, autocapture,
        // session replay meta): scrub the admin token out of any URL property.
        before_send: (event: CaptureResult | null) => {
          if (event?.properties) {
            for (const k of [
              "$current_url",
              "$referrer",
              "$initial_current_url",
              "$initial_referrer",
            ]) {
              if (event.properties[k]) {
                event.properties[k] = scrubAdminParam(event.properties[k]);
              }
            }
          }
          return event;
        },
      });
      posthogReady = true;
      window.dispatchEvent(new Event(POSTHOG_READY_EVENT));
    };

    // Deferred off the hydration path (perf: 2026-07-23 Lighthouse audit showed
    // posthog.init on mount contributing to TBT). First interaction or idle
    // timeout triggers init instead of `load`.
    const events: (keyof WindowEventMap)[] = ["pointerdown", "keydown", "scroll"];
    const opts = { once: true, passive: true } as const;
    events.forEach((event) => window.addEventListener(event, init, opts));

    const idleId = scheduleIdle(init, 2000);

    function cleanup() {
      events.forEach((event) => window.removeEventListener(event, init));
      cancelIdle(idleId);
    }

    return cleanup;
  }, []);

  return (
    <PHProvider client={posthog}>
      <Suspense fallback={null}>
        <PageViewTracker />
      </Suspense>
      {children}
    </PHProvider>
  );
}

// App Router does no full page loads on navigation, so we emit $pageview
// ourselves whenever the path or query string changes. useSearchParams must
// live under a Suspense boundary (above) to avoid opting the whole tree out of
// static rendering.
function PageViewTracker() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const ph = usePostHog();

  useEffect(() => {
    if (!pathname || !ph) return;
    let url = window.origin + pathname;
    // Drop the admin token at the source so it never enters the event.
    const params = new URLSearchParams(searchParams?.toString() || "");
    params.delete("admin");
    const qs = params.toString();
    if (qs) url += `?${qs}`;

    const capture = () => ph.capture("$pageview", { $current_url: url });

    if (posthogReady) {
      capture();
      return;
    }
    // Init hasn't happened yet (deferred to idle/interaction) — wait for it
    // so this pageview isn't silently dropped by the uninitialised client.
    window.addEventListener(POSTHOG_READY_EVENT, capture, { once: true });
    return () => window.removeEventListener(POSTHOG_READY_EVENT, capture);
  }, [pathname, searchParams, ph]);

  return null;
}
