"use client";

import { useCallback, useEffect, useRef } from "react";
import { clearScrollPos, loadScrollPos, saveScrollPos } from "@/lib/storage";

// How many frames to keep re-applying the restored offset. The screener measures
// a real row's height on first paint and resizes its virtualization spacers off
// the result, which moves everything underneath a one-shot restore; re-applying
// across a few frames absorbs that without needing to know it happened.
const SETTLE_FRAMES = 6;

/**
 * Put the user back where they were when they return to a list page.
 *
 * Neither the App Router nor the browser does this for us. Next scrolls to the
 * top on navigation, and native back/forward restoration can't help either: these
 * lists arrive from an async fetch, so at the moment the browser would restore,
 * the page is still a spinner with no height to scroll into.
 *
 * NAV RESET — the subtle part, and worth not "simplifying" away. On a client-side
 * route change the App Router scrolls the window to the top *before* the outgoing
 * component unmounts, and that reset fires a real scroll event. So a position read
 * from a scroll listener at unmount time is always 0, and naively saving it stores
 * the router's reset instead of the user's position. Verified in the browser:
 *
 *     [SR] scroll -> 1800     (user)
 *     [SR] scroll -> 0        (router, still mounted)
 *     [SR] save called, pos=0
 *
 * The fix is to also snapshot the offset on any click, in the capture phase, which
 * runs before the router can react, and to prefer that snapshot when the live
 * offset has collapsed to 0 underneath it. Detecting the collapse rather than
 * timing it matters: a slow route change can leave the outgoing page mounted for
 * many seconds, so any "was the click recent?" window is a silent failure waiting
 * for a slow connection. The residual cost is that a user who clicks something at
 * depth, then scrolls to the very top without clicking again, then leaves via the
 * back button is returned to the old depth — a mild wrong answer in a rare case,
 * traded against losing the position outright in a common one.
 *
 * `ready` must only become true once the rows are actually rendered — restoring
 * before that silently lands at 0 and burns the one-shot.
 *
 * `getScroller` returns the element that scrolls. The screener's table lives in
 * an overflow container; /rns scrolls the window. Omit it for the window.
 *
 * Returns `forget()`, for callers whose list can be replaced under the reader —
 * both pages call it when a filter changes. A remembered offset into a list the
 * user has just rebuilt points at nothing.
 */
export function useScrollRestore(
  key: string,
  ready: boolean,
  getScroller?: () => HTMLElement | null,
) {
  // -1 means "nothing measured yet" — distinct from a genuine 0. Without that
  // distinction, navigating away while the list was still loading would write 0
  // over a perfectly good saved offset.
  const posRef = useRef(-1);
  const navPosRef = useRef(-1);
  const restored = useRef(false);
  const getScrollerRef = useRef(getScroller);
  getScrollerRef.current = getScroller;

  useEffect(() => {
    if (!ready) return;
    const el = getScrollerRef.current?.() ?? null;
    const target: HTMLElement | Window = el ?? window;
    const read = () => (el ? el.scrollTop : window.scrollY);

    // Track the live offset in a ref rather than in storage: sessionStorage writes
    // are synchronous, and one per scroll frame is a needless main-thread hit when
    // a single write on the way out says the same thing.
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        posRef.current = read();
      });
    };

    // Capture phase, on the document, so this lands before the router reacts to a
    // <Link> click or a row's router.push. See NAV RESET above.
    const onClick = () => {
      navPosRef.current = read();
    };

    target.addEventListener("scroll", onScroll, { passive: true });
    document.addEventListener("click", onClick, true);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      target.removeEventListener("scroll", onScroll);
      document.removeEventListener("click", onClick, true);
    };
  }, [ready]);

  // Save on the way out. Deliberately its own effect rather than the cleanup of
  // the listener above, which re-runs whenever `ready` flips — saving there would
  // clobber the stored offset in the instant before the restore reads it.
  //
  // Two exits to cover. A client-side route change unmounts the component and runs
  // the cleanup; a full navigation or reload tears the document down without React
  // ever unmounting, so `pagehide` catches that. Both are cheap and idempotent.
  useEffect(() => {
    const save = () => {
      // A live offset of 0 with a click snapshot above it is the router's reset,
      // not the user — see NAV RESET. Anything else, the live offset is the truth.
      const wasReset = posRef.current <= 0 && navPosRef.current > 0;
      const pos = wasReset ? navPosRef.current : posRef.current;
      if (pos >= 0) saveScrollPos(key, pos);
    };
    window.addEventListener("pagehide", save);
    return () => {
      window.removeEventListener("pagehide", save);
      save();
    };
  }, [key]);

  useEffect(() => {
    if (!ready || restored.current) return;
    restored.current = true;
    const saved = loadScrollPos(key);
    // Adopt the value immediately, so an unmount before the frames below still
    // saves where we meant to be rather than 0.
    posRef.current = saved;
    if (saved <= 0) return;

    const el = getScrollerRef.current?.() ?? null;
    let raf = 0;
    let frame = 0;
    const apply = () => {
      if (el) el.scrollTop = saved;
      else window.scrollTo(0, saved);
      if (++frame < SETTLE_FRAMES) raf = requestAnimationFrame(apply);
    };
    raf = requestAnimationFrame(apply);
    return () => cancelAnimationFrame(raf);
  }, [key, ready]);

  // Deliberately a no-op until the restore has run. The screener resets to the
  // top on every filter change, and its filters arrive from localStorage in a
  // mount effect — so the reset fires a couple of times on the way in, before the
  // user has done anything. Honouring those would wipe the offset we came back
  // to use. After the restore, a reset can only be the user changing the list.
  const forget = useCallback(() => {
    if (!restored.current) return;
    posRef.current = 0;
    navPosRef.current = -1;
    clearScrollPos(key);
  }, [key]);

  return forget;
}
