"use client";

import { useEffect } from "react";

// Arms the company-page scroll snap (see the `html.company-snap` rule in
// globals.css). The snap settles the reader at the company name, just under the
// sticky nav, skipping the breadcrumb + CTA banner above it.
//
// It must NOT be active at load: the header snap point is only ~120px down, so a
// live snap-type would snap to it immediately on first layout and hide the ad
// before the reader scrolls. So we add the class on the first real scroll gesture
// only. We listen for `wheel`/`touchmove` (genuine user intent) rather than the
// `scroll` event, because Next's scroll-to-top on navigation fires `scroll`
// programmatically and would arm — and therefore snap — on load all over again.
export default function CompanySnap() {
  useEffect(() => {
    const root = document.documentElement;
    const arm = () => {
      root.classList.add("company-snap");
      window.removeEventListener("wheel", arm);
      window.removeEventListener("touchmove", arm);
    };
    const opts: AddEventListenerOptions = { passive: true, once: true };
    window.addEventListener("wheel", arm, opts);
    window.addEventListener("touchmove", arm, opts);
    return () => {
      window.removeEventListener("wheel", arm);
      window.removeEventListener("touchmove", arm);
      // Disarm on leaving the company page so the class never bleeds onto other
      // routes (the rule is company-only, but keep <html> clean).
      root.classList.remove("company-snap");
    };
  }, []);

  return null;
}
