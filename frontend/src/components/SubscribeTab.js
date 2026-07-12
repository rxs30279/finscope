"use client";
import { useEffect, useRef, useState } from "react";
import { usePostHog } from "posthog-js/react";
import { API } from "@/lib/api";
import PageHeader from "@/components/layout/PageHeader";
import { DigestSample } from "@/components/DigestSample";

const LABEL = {
  color: "#f97316",
  fontSize: 10,
  fontFamily: "monospace",
  textTransform: "uppercase",
  letterSpacing: 2,
  marginBottom: 8,
};

const CARD = {
  background: "#141414",
  border: "1px solid #2a2a2a",
  borderRadius: 4,
  padding: 24,
  marginBottom: 24,
};

// Prominent variant for the primary subscribe action.
const HERO_CARD = {
  ...CARD,
  border: "1px solid #f9731655",
  background:
    "radial-gradient(120% 140% at 0% 0%, rgba(249,115,22,0.10) 0%, rgba(249,115,22,0) 55%), #141414",
};

const INPUT = {
  flex: 1,
  background: "#0d0d0d",
  border: "1px solid #2a2a2a",
  color: "#e5e5e5",
  padding: "12px 14px",
  fontSize: 14,
  fontFamily: "monospace",
  borderRadius: 3,
  outline: "none",
};

const BTN = {
  background: "linear-gradient(135deg, #2a1a00 0%, #1a1200 100%)",
  border: "1px solid #f97316",
  color: "#f97316",
  padding: "12px 22px",
  fontSize: 12,
  fontFamily: "monospace",
  fontWeight: 700,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  borderRadius: 3,
  cursor: "pointer",
};

function Message({ kind, text }) {
  if (!text) return null;
  const color = kind === "ok" ? "#10b981" : "#ef4444";
  const bg    = kind === "ok" ? "#0d2318" : "#2a0d0d";
  return (
    <div style={{
      marginTop: 12, padding: "8px 12px", border: `1px solid ${color}55`,
      background: bg, color, fontFamily: "monospace", fontSize: 12, borderRadius: 3,
    }}>
      {text}
    </div>
  );
}

// Trust signals shown directly under the subscribe form. (Scarcity is conveyed
// by the live spots counter above the form, so it's not repeated here.)
const TRUST = [
  "Weekday mornings only",
  "One-click unsubscribe",
  "No spam, no sharing",
];

function TrustRow() {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 18px", marginTop: 16 }}>
      {TRUST.map((t) => (
        <span key={t} style={{ display: "flex", alignItems: "center", gap: 7, color: "#94a3b8", fontFamily: "monospace", fontSize: 11 }}>
          <span style={{ color: "#10b981" }}>✓</span>
          {t}
        </span>
      ))}
    </div>
  );
}

// Live remaining-spots counter. Hidden until the count loads (and on any fetch
// failure), mirroring the landing band.
function SpotsPill({ spots }) {
  if (!spots) return null;
  const full = spots.remaining <= 0;
  const accent = full ? "#ef4444" : "#f97316";
  const bg = full ? "#2a0d0d" : "#1f1400";
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 8,
      padding: "7px 14px", marginBottom: 16, borderRadius: 100,
      border: `1px solid ${accent}55`, background: bg,
      fontFamily: "monospace", fontSize: 12, color: "#e5e5e5",
    }}>
      <span style={{
        width: 7, height: 7, borderRadius: "50%", background: accent,
        boxShadow: full ? "none" : `0 0 8px ${accent}`,
      }} />
      {full ? (
        <span>All {spots.cap} spots taken — sign-ups closed for now.</span>
      ) : (
        <span>Only <strong style={{ color: accent }}>{spots.remaining}</strong> of {spots.cap} free spots left</span>
      )}
    </div>
  );
}

export default function SubscribeTab() {
  const [signupEmail, setSignupEmail] = useState("");
  const [signupBusy, setSignupBusy]   = useState(false);
  const [signupMsg, setSignupMsg]     = useState(null);
  const [spots, setSpots]             = useState(null);

  // Funnel instrumentation (no-op until NEXT_PUBLIC_POSTHOG_KEY is set). Shares
  // event names with LandingSignup, tagged source:"subscribe_page".
  const ph = usePostHog();
  const focusedRef = useRef(false);

  function onSignupFocus() {
    if (focusedRef.current) return;
    focusedRef.current = true;
    ph?.capture("signup_form_focused", { source: "subscribe_page" });
  }

  const [unsubOpen, setUnsubOpen]     = useState(false);
  const [unsubEmail, setUnsubEmail]   = useState("");
  const [unsubBusy, setUnsubBusy]     = useState(false);
  const [unsubMsg, setUnsubMsg]       = useState(null);

  // Live remaining-spots counter. Best-effort: on failure the pill just hides
  // and the form stays open.
  useEffect(() => {
    let alive = true;
    fetch(`${API}/subscribers/count`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && d && typeof d.remaining === "number") setSpots(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const full = spots != null && spots.remaining <= 0;

  async function submitSignup(e) {
    e.preventDefault();
    setSignupBusy(true); setSignupMsg(null);
    ph?.capture("signup_submitted", { source: "subscribe_page" });
    try {
      const res = await fetch(`${API}/subscribers/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: signupEmail }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        const verb = data.status === "reactivated" ? "back" : "in";
        setSignupMsg({ kind: "ok", text: `✓ You're ${verb} — your first briefing lands at 07:30 on the next market day.` });
        setSignupEmail("");
        ph?.capture("signup_completed", { source: "subscribe_page", status: verb });
        // Optimistically reflect the taken spot (endpoint is cached ~60s).
        setSpots((s) => (s ? { ...s, count: s.count + 1, remaining: Math.max(0, s.remaining - 1) } : s));
      } else {
        setSignupMsg({ kind: "err", text: data.detail || `Error (${res.status})` });
        ph?.capture("signup_failed", { source: "subscribe_page", reason: `http_${res.status}` });
      }
    } catch {
      setSignupMsg({ kind: "err", text: "Network error" });
      ph?.capture("signup_failed", { source: "subscribe_page", reason: "network" });
    } finally {
      setSignupBusy(false);
    }
  }

  async function submitUnsub(e) {
    e.preventDefault();
    setUnsubBusy(true); setUnsubMsg(null);
    // Typing an email proves nothing, so the backend doesn't unsubscribe
    // directly — it emails the address its signed unsubscribe link, and only
    // the inbox owner can complete it. The response is the same whether or
    // not the address is subscribed.
    try {
      const res = await fetch(`${API}/subscribers/unsubscribe-self`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: unsubEmail }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setUnsubMsg({ kind: "ok", text: `✓ If ${unsubEmail} is subscribed, a confirmation link is on its way — click it to finish unsubscribing.` });
        setUnsubEmail("");
      } else {
        setUnsubMsg({ kind: "err", text: data.detail || `Error (${res.status})` });
      }
    } catch {
      setUnsubMsg({ kind: "err", text: "Network error" });
    } finally {
      setUnsubBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 640 }}>
      <PageHeader
        title="Your UK market, before the open"
        subtitle="One short email every weekday at 07:30 GMT/BST — AI-ranked movers and the RNS news that actually matters. Free."
      />

      {/* Primary: subscribe */}
      <div style={HERO_CARD}>
        <div style={LABEL}>Get the morning briefing</div>
        <div style={{ color: "#cbd5e1", fontSize: 14, lineHeight: 1.6, marginBottom: 16 }}>
          Read your market with your coffee, not your lunch. Each weekday at
          07:30 we send the last 24h of notable movers and high-impact RNS from
          FTSE&nbsp;100, 250 and SmallCap/AIM — each item carrying an AI thesis,
          a risk flag, and a research / watch / ignore call.
        </div>
        <div><SpotsPill spots={spots} /></div>
        <form onSubmit={submitSignup} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            type="email"
            required
            placeholder="you@example.com"
            value={signupEmail}
            onChange={(e) => setSignupEmail(e.target.value)}
            onFocus={onSignupFocus}
            style={{ ...INPUT, minWidth: 220 }}
            autoComplete="email"
            disabled={signupBusy || full}
          />
          <button type="submit" disabled={signupBusy || full} style={{ ...BTN, opacity: (signupBusy || full) ? 0.5 : 1 }}>
            {full ? "Sign-ups closed" : signupBusy ? "Subscribing…" : "Get the briefing"}
          </button>
        </form>
        <Message kind={signupMsg?.kind} text={signupMsg?.text} />
        <TrustRow />
      </div>

      {/* Sample of the email */}
      <div style={CARD}>
        <div style={LABEL}>What a morning looks like</div>
        <div style={{ color: "#94a3b8", fontSize: 13, lineHeight: 1.6, marginBottom: 12 }}>
          Items are grouped by market cap and led by the highest-ranked, so what&apos;s
          worth your attention sits at the top.
        </div>
        <DigestSample />
      </div>

      {/* Unsubscribe — demoted, collapsed by default */}
      <div style={CARD}>
        {!unsubOpen ? (
          <button
            onClick={() => setUnsubOpen(true)}
            style={{
              background: "none", border: "none", color: "#666",
              fontFamily: "monospace", fontSize: 12, cursor: "pointer", padding: 0,
            }}
          >
            Already subscribed and want out? Unsubscribe →
          </button>
        ) : (
          <>
            <div style={{ ...LABEL, color: "#94a3b8" }}>Unsubscribe</div>
            <div style={{ color: "#666", fontSize: 12, fontFamily: "monospace", marginBottom: 12 }}>
              We&apos;ll email you a confirmation link — or use the one-click
              link in any digest email footer.
            </div>
            <form onSubmit={submitUnsub} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <input
                type="email"
                required
                placeholder="you@example.com"
                value={unsubEmail}
                onChange={(e) => setUnsubEmail(e.target.value)}
                style={{ ...INPUT, minWidth: 220 }}
                autoComplete="email"
              />
              <button
                type="submit"
                disabled={unsubBusy}
                style={{
                  ...BTN,
                  border: "1px solid #555",
                  color: "#94a3b8",
                  background: "#1a1a1a",
                  opacity: unsubBusy ? 0.5 : 1,
                }}
              >
                {unsubBusy ? "Working…" : "Unsubscribe"}
              </button>
            </form>
            <Message kind={unsubMsg?.kind} text={unsubMsg?.text} />
          </>
        )}
      </div>
    </div>
  );
}
