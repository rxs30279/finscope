"use client";

import { useEffect } from "react";
import { scheduleIdle, cancelIdle } from "@/lib/idle";

const GA_ID = "G-4D7NSXL95B";

// Loads GA4 only once the user actually engages with the page (or after an
// idle fallback), so gtag.js's ~1s main-thread cost lands outside the
// pre-interaction TBT window instead of piggybacking on window `load`.
export default function DeferredGA() {
  useEffect(() => {
    let loaded = false;

    const load = () => {
      if (loaded) return;
      loaded = true;
      cleanup();

      const script = document.createElement("script");
      script.src = `https://www.googletagmanager.com/gtag/js?id=${GA_ID}`;
      script.async = true;
      document.head.appendChild(script);

      const w = window as unknown as { dataLayer?: unknown[] };
      w.dataLayer = w.dataLayer || [];
      function gtag(...args: unknown[]) {
        w.dataLayer!.push(args);
      }
      gtag("js", new Date());
      gtag("config", GA_ID);
    };

    const events: (keyof WindowEventMap)[] = ["pointerdown", "keydown", "scroll"];
    const opts = { once: true, passive: true } as const;
    events.forEach((event) => window.addEventListener(event, load, opts));

    const idleId = scheduleIdle(load, 5000);

    function cleanup() {
      events.forEach((event) => window.removeEventListener(event, load));
      cancelIdle(idleId);
    }

    return cleanup;
  }, []);

  return null;
}
