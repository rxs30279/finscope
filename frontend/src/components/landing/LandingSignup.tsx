"use client";

import { useEffect, useRef, useState } from "react";
import { usePostHog } from "posthog-js/react";
import { API } from "@/lib/api";
import { DigestSample } from "@/components/DigestSample";

/**
 * Email-digest signup band for the marketing landing ("/"). The landing page
 * itself is a server component (page.tsx) so its copy is crawlable; this is the
 * one interactive island that captures an address inline — no click-through to
 * /subscribe required, which was the main place signup intent was leaking.
 *
 * Posts to the same endpoint as the dedicated /subscribe page
 * (POST /api/subscribers/signup → Resend segment, single opt-in).
 */
type Msg = { kind: "ok" | "err"; text: string } | null;
type Spots = { count: number; cap: number; remaining: number };

export default function LandingSignup() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [spots, setSpots] = useState<Spots | null>(null);

  // Funnel instrumentation (no-op until NEXT_PUBLIC_POSTHOG_KEY is set). All
  // signup events carry source:"landing" so the landing band and the dedicated
  // /subscribe page share one funnel. focusedRef guards a single focus event
  // per mount so re-focusing the input doesn't inflate the step.
  const ph = usePostHog();
  const focusedRef = useRef(false);

  // Live remaining-spots counter. Best-effort: if it fails, we just fall back
  // to the static trust line and the form stays open.
  useEffect(() => {
    let alive = true;
    fetch(`${API}/subscribers/count`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && d && typeof d.remaining === "number") setSpots(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const full = spots != null && spots.remaining <= 0;

  function onFocus() {
    if (focusedRef.current) return;
    focusedRef.current = true;
    ph?.capture("signup_form_focused", { source: "landing" });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    ph?.capture("signup_submitted", { source: "landing" });
    try {
      const res = await fetch(`${API}/subscribers/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        const verb = data.status === "reactivated" ? "back" : "in";
        setMsg({ kind: "ok", text: `You're ${verb} — first briefing lands at 07:30 on the next market day.` });
        setEmail("");
        ph?.capture("signup_completed", { source: "landing", status: verb });
        // Optimistically reflect the taken spot (endpoint is cached ~60s).
        setSpots((s) => (s ? { ...s, count: s.count + 1, remaining: Math.max(0, s.remaining - 1) } : s));
      } else {
        setMsg({ kind: "err", text: data.detail || `Something went wrong (${res.status}). Try again.` });
        ph?.capture("signup_failed", { source: "landing", reason: `http_${res.status}` });
      }
    } catch {
      setMsg({ kind: "err", text: "Network error — please try again." });
      ph?.capture("signup_failed", { source: "landing", reason: "network" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="am-cta" id="subscribe">
      <div className="am-cta-inner am-reveal">
        <div className="am-cta-eyebrow">
          <span className="am-dot" aria-hidden="true" />
          Free email digest
        </div>
        <h2>
          Your UK market, <span className="am-accent">filtered and explained.</span>
        </h2>
        <p className="am-cta-sub">
          One short email at 07:30 every weekday. The notable movers and the RNS
          that actually matters — AI-ranked across the FTSE 100, 250, SmallCap
          and AIM. Cuts the noise to the news that moves prices. The only
          pre-market email you'll need.
        </p>

        {spots && (
          <div className={`am-cta-spots${full ? " full" : ""}`}>
            <span className="am-spots-dot" aria-hidden="true" />
            {full ? (
              <span>All {spots.cap} spots taken — sign-ups are closed for now.</span>
            ) : (
              <span>
                Only <span className="am-spots-num">{spots.remaining}</span> of {spots.cap} free spots left
              </span>
            )}
          </div>
        )}

        <form className="am-cta-form" onSubmit={submit}>
          <input
            className="am-cta-input"
            type="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onFocus={onFocus}
            autoComplete="email"
            aria-label="Email address"
            disabled={busy || full}
          />
          <button type="submit" className="am-btn am-btn-primary am-cta-btn" disabled={busy || full}>
            {full ? "Sign-ups closed" : busy ? "Subscribing…" : "Get the briefing"}
            {!busy && !full && (
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            )}
          </button>
        </form>

        {msg && (
          <p className={`am-cta-msg ${msg.kind}`} role="status">
            {msg.text}
          </p>
        )}

        <div className="am-cta-trust">
          <span><span className="am-tick" aria-hidden="true">●</span> No spam, ever</span>
          <span><span className="am-tick" aria-hidden="true">●</span> Weekday mornings only</span>
          <span><span className="am-tick" aria-hidden="true">●</span> One-click unsubscribe</span>
        </div>

        {/* The sample email, inline — visitors see the product without a click. */}
        <div className="am-cta-sample-inline">
          <div className="am-cta-sample-label">A real morning, exactly as it lands:</div>
          <DigestSample />
        </div>
      </div>
    </section>
  );
}
