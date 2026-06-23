"use client";

import { useEffect, useRef, useState } from "react";

/**
 * "Install app" button for the landing hero. Lets visitors add Alpha Move AI to
 * their phone home screen / desktop as a PWA (manifest + icons live in /public,
 * and we register a minimal service worker so the browser treats the site as
 * installable).
 *
 * There is no single cross-browser install API, so the button has two paths:
 *
 *   • Chrome / Edge / Android fire `beforeinstallprompt` only when the site is
 *     installable AND not already installed. We show the button just for that
 *     window and call prompt() on click for the real native dialog. Because the
 *     event stops firing once installed, the button correctly disappears after
 *     install — there's no reliable way to query install state otherwise.
 *   • iOS Safari has no install event (and no way to detect install state), so
 *     we always offer the manual Share → "Add to Home Screen" steps there.
 *
 * The button also hides whenever the app is already running standalone.
 */
type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

type Mode = "hidden" | "prompt" | "ios";

function isIosSafari(): boolean {
  const ua = window.navigator.userAgent;
  const isIos =
    /iphone|ipad|ipod/i.test(ua) ||
    // iPadOS 13+ reports as a Mac; sniff for the touch capability.
    (/macintosh/i.test(ua) && "ontouchend" in document);
  // Exclude the in-app Chrome/Firefox/Edge iOS browsers — only Safari can add
  // to the home screen on iOS.
  const isSafari = /^((?!chrome|android|crios|fxios|edgios).)*safari/i.test(ua);
  return isIos && isSafari;
}

export default function InstallButton() {
  const [mode, setMode] = useState<Mode>("hidden");
  const [showHint, setShowHint] = useState(false);
  const deferred = useRef<BeforeInstallPromptEvent | null>(null);

  useEffect(() => {
    // Already installed / launched from the home screen — nothing to offer.
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      // iOS Safari exposes this non-standard flag instead of display-mode.
      (window.navigator as unknown as { standalone?: boolean }).standalone === true;
    if (standalone) return;

    // iOS Safari: no install event and no install-state query — always show the
    // manual steps.
    if (isIosSafari()) setMode("ios");

    // Register the service worker — required for Chrome/Edge to consider the
    // site installable and fire `beforeinstallprompt`.
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }

    const onPrompt = (e: Event) => {
      e.preventDefault(); // stop Chrome's mini-infobar; we drive it from the button
      deferred.current = e as BeforeInstallPromptEvent;
      setMode("prompt");
    };
    const onInstalled = () => {
      deferred.current = null;
      setMode("hidden");
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (mode === "hidden") return null;

  const handleClick = async () => {
    if (mode === "ios") {
      setShowHint((v) => !v);
      return;
    }
    const evt = deferred.current;
    if (!evt) return;
    await evt.prompt();
    const { outcome } = await evt.userChoice;
    if (outcome === "accepted") {
      deferred.current = null;
      setMode("hidden");
    }
  };

  return (
    <div className="am-install">
      <button
        type="button"
        className="am-btn am-btn-ghost"
        onClick={handleClick}
        aria-expanded={mode === "ios" ? showHint : undefined}
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 3v12M7 10l5 5 5-5" /><path d="M4 21h16" />
        </svg>
        Install app
      </button>
      {mode === "ios" && showHint && (
        <div className="am-install-hint" role="status">
          Tap the <strong>Share</strong> button in Safari, then choose{" "}
          <strong>Add to Home Screen</strong>.
        </div>
      )}
    </div>
  );
}
