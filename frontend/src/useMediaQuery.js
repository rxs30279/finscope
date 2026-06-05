import { useState, useEffect } from "react";

export function useMediaQuery(query) {
  const [matches, setMatches] = useState(
    typeof window !== "undefined" ? window.matchMedia(query).matches : false,
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const handler = (e) => setMatches(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [query]);
  return matches;
}

export function useIsMobile() {
  return useMediaQuery("(max-width: 767px)");
}

// Desktop, but not wide enough to comfortably fit the full top nav (logo +
// 8 menu groups + utility buttons + search). Used to tighten nav spacing and
// drop non-essential items so nothing overruns the right edge on laptops.
export function useIsNarrowDesktop() {
  return useMediaQuery("(min-width: 768px) and (max-width: 1500px)");
}

export function useIsTablet() {
  return useMediaQuery("(min-width: 768px) and (max-width: 1023px)");
}

export function useIsDesktop() {
  return useMediaQuery("(min-width: 1024px)");
}
