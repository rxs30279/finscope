"use client";

import { useState, useEffect } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(query);
    setMatches(mq.matches);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [query]);
  return matches;
}

export function useIsMobile(): boolean {
  // Collapse to the mobile layout (hamburger nav + drawer) at <=943px: that's
  // where the inline desktop nav starts to overlap the right-hand Tools/search
  // cluster on tablet-width screens. In landscape, phones get wider than that
  // but stay very short, so also treat short landscape viewports as mobile —
  // otherwise the app flips to the desktop layout (no hamburger, sidebar
  // benchmarks visible) when a phone is turned sideways.
  return useMediaQuery(
    "(max-width: 943px), (max-height: 500px) and (orientation: landscape)",
  );
}

// True on narrow phones (≤640px / Tailwind sm). Use alongside useIsUnderMd to
// add a 2-column middle state for tablets wide enough to fit two cards.
export function useIsNarrowMobile(): boolean {
  return useMediaQuery("(max-width: 640px)");
}

// True below Tailwind's md breakpoint (≤767px). Use for content grids that
// should go 3-column at 768px, independent of the nav's 943px mobile cutoff.
export function useIsUnderMd(): boolean {
  return useMediaQuery("(max-width: 767px)");
}

// Desktop, but not wide enough to comfortably fit the full top nav (logo +
// 8 menu groups + utility buttons + search). Used to tighten nav spacing and
// drop non-essential items so nothing overruns the right edge on laptops.
export function useIsNarrowDesktop(): boolean {
  return useMediaQuery("(min-width: 944px) and (max-width: 1500px)");
}

export function useIsTablet(): boolean {
  return useMediaQuery("(min-width: 768px) and (max-width: 1023px)");
}

export function useIsDesktop(): boolean {
  return useMediaQuery("(min-width: 1024px)");
}
