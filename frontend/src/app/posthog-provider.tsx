"use client";

import { usePathname, useSearchParams } from "next/navigation";
import posthog from "posthog-js";
import type { CaptureResult } from "posthog-js";
import { PostHogProvider as PHProvider, usePostHog } from "posthog-js/react";
import { Suspense, useEffect } from "react";

// Strip the one-time `?admin=<token>` secret from any URL before it reaches
// PostHog. That token unlocks the admin controls (see hooks/useAdmin.ts); it
// sits in the address bar for a single render before useIsAdmin removes it, so
// a pageview / pageleave / autocapture event fired in that window would
// otherwise ship the token to analytics.
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
    posthog.init(key, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || "/ingest",
      ui_host: "https://eu.posthog.com",
      // We track pageviews manually below so SPA route changes are captured;
      // pageleave stays on so bounce/among-page time is measured.
      capture_pageview: false,
      capture_pageleave: true,
      person_profiles: "identified_only",
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
      // Session replay is left at posthog-js's default (disable_session_recording
      // is false), so recordings capture once it's toggled on in PostHog →
      // Settings → Session Replay. The 5-second minimum-duration filter and the
      // billing limit are BOTH server-side settings there, not client init
      // options in this SDK version. Text/inputs are masked by default, which we
      // want for a finance app.
    });
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
    ph.capture("$pageview", { $current_url: url });
  }, [pathname, searchParams, ph]);

  return null;
}
