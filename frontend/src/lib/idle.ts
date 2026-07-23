// Thin wrapper around requestIdleCallback with a setTimeout fallback (Safari
// has no requestIdleCallback). Feature-detects via a locally cast window
// reference rather than `"x" in window`, which TS narrows to `never` in the
// non-idle branch since lib.dom already declares the property on Window.
type IdleWindow = Window & {
  requestIdleCallback?: (
    callback: IdleRequestCallback,
    options?: IdleRequestOptions
  ) => number;
  cancelIdleCallback?: (handle: number) => void;
};

export function scheduleIdle(callback: () => void, timeoutMs: number): number {
  const w = window as IdleWindow;
  if (typeof w.requestIdleCallback === "function") {
    return w.requestIdleCallback(callback, { timeout: timeoutMs });
  }
  return window.setTimeout(callback, timeoutMs);
}

export function cancelIdle(handle: number): void {
  const w = window as IdleWindow;
  if (typeof w.cancelIdleCallback === "function") {
    w.cancelIdleCallback(handle);
  } else {
    window.clearTimeout(handle);
  }
}
