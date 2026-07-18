"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePostHog } from "posthog-js/react";

/**
 * Eye-catching CTA banner for non-marketing pages (High Impact RNS, company
 * pages). Alternates between the digest advert and a donations ask every
 * couple of minutes — most traffic is mobile, where the sidebar Donate button
 * is never seen. The rotation is phased off a session-wide clock
 * (sessionStorage), so navigating between companies doesn't reset it and
 * every banner on the site shows the same variant at any given moment.
 *
 * No inline capture — it routes intent to /subscribe or /donate, where the
 * full pitch lives. Clicks are tagged with `source` so the funnel can tell
 * placements apart.
 */

const ROTATE_MS = 2 * 60 * 1000;
const FIRST_SEEN_KEY = "am_cta_first_seen";

export default function EmailDigestCTA({ source }: { source: string }) {
  const ph = usePostHog();
  const [variant, setVariant] = useState<"digest" | "donate">("digest");

  useEffect(() => {
    let firstSeen = Number(sessionStorage.getItem(FIRST_SEEN_KEY));
    if (!firstSeen) {
      firstSeen = Date.now();
      sessionStorage.setItem(FIRST_SEEN_KEY, String(firstSeen));
    }
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const elapsed = Date.now() - firstSeen;
      setVariant(Math.floor(elapsed / ROTATE_MS) % 2 === 0 ? "digest" : "donate");
      timer = setTimeout(tick, ROTATE_MS - (elapsed % ROTATE_MS));
    };
    tick();
    return () => clearTimeout(timer);
  }, []);

  const donate = variant === "donate";

  return (
    <Link
      href={donate ? "/donate" : "/subscribe"}
      onClick={() => ph?.capture(donate ? "donate_cta_clicked" : "digest_cta_clicked", { source })}
      style={{ textDecoration: "none", display: "block", marginBottom: 24 }}
    >
      <div
        key={variant}
        className="digest-cta"
        style={{
          position: "relative",
          overflow: "hidden",
          border: "1px solid #f97316",
          borderRadius: 6,
          background:
            "radial-gradient(130% 180% at 0% 0%, rgba(249,115,22,0.22) 0%, rgba(249,115,22,0.05) 45%, rgba(249,115,22,0) 70%), linear-gradient(135deg, #1a1005 0%, #141414 60%)",
          boxShadow: "0 0 24px rgba(249,115,22,0.12), inset 0 1px 0 rgba(249,115,22,0.25)",
          padding: "18px 22px",
          display: "flex",
          alignItems: "center",
          gap: 18,
          flexWrap: "wrap",
          cursor: "pointer",
          animation: "digestSwap 0.6s ease",
        }}
      >
        {/* Animated sheen sweeping across the card */}
        <span
          aria-hidden="true"
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            width: 90,
            background: "linear-gradient(105deg, transparent 0%, rgba(249,115,22,0.14) 50%, transparent 100%)",
            animation: "digestSheen 4.5s ease-in-out infinite",
            pointerEvents: "none",
          }}
        />

        <div style={{ flex: "1 1 300px", minWidth: 240 }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              color: "#f97316",
              fontSize: 10,
              fontFamily: "monospace",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: 2,
              marginBottom: 6,
            }}
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: "#f97316",
                boxShadow: "0 0 8px #f97316",
                animation: "digestPulse 2s ease-in-out infinite",
              }}
            />
            {donate ? "Reader-supported · No ads · No paywall" : "Free morning briefing · 07:30 weekdays"}
          </div>
          <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 20, color: "#f1f5f9", lineHeight: 1.25 }}>
            {donate ? (
              <>
                Alpha Move is free to use — <span style={{ color: "#f97316" }}>readers keep it running.</span>
              </>
            ) : (
              <>
                The RNS that moves prices, <span style={{ color: "#f97316" }}>in your inbox before the open.</span>
              </>
            )}
          </div>
          <div style={{ color: "#94a3b8", fontSize: 12.5, marginTop: 5, lineHeight: 1.5 }}>
            {donate
              ? "If the screener or the digest has saved you time or sharpened a decision, chip in the price of a coffee. One-off or monthly, entirely optional."
              : "AI-ranked movers and high-impact RNS across the FTSE 100, 250, SmallCap and AIM — one short email, every market day."}
          </div>
        </div>

        <span
          className="digest-cta-btn"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 9,
            background: "#f97316",
            color: "#140a02",
            padding: "12px 22px",
            fontSize: 12,
            fontFamily: "monospace",
            fontWeight: 700,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            borderRadius: 4,
            whiteSpace: "nowrap",
            boxShadow: "0 0 18px rgba(249,115,22,0.35)",
          }}
        >
          {donate ? "♥ Support the site" : "Get the briefing"}
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </span>

        <style>{`
          @keyframes digestSheen {
            0%   { left: -120px; }
            55%  { left: 110%; }
            100% { left: 110%; }
          }
          @keyframes digestPulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50%      { opacity: 0.55; transform: scale(0.8); }
          }
          @keyframes digestSwap {
            from { opacity: 0; }
            to   { opacity: 1; }
          }
          .digest-cta { transition: box-shadow 0.25s ease, border-color 0.25s ease; }
          .digest-cta:hover {
            border-color: #fb923c;
            box-shadow: 0 0 34px rgba(249,115,22,0.28), inset 0 1px 0 rgba(249,115,22,0.35);
          }
          .digest-cta:hover .digest-cta-btn { background: #fb923c; }
          @media (prefers-reduced-motion: reduce) {
            .digest-cta [style*="digestSheen"] { animation: none !important; }
          }
        `}</style>
      </div>
    </Link>
  );
}
