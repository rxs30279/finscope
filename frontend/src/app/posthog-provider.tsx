"use client";

import { usePathname, useSearchParams } from "next/navigation";
import posthog from "posthog-js";
import { PostHogProvider as PHProvider, usePostHog } from "posthog-js/react";
import { Suspense, useEffect } from "react";

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
    const qs = searchParams?.toString();
    if (qs) url += `?${qs}`;
    ph.capture("$pageview", { $current_url: url });
  }, [pathname, searchParams, ph]);

  return null;
}
