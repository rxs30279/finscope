"use client";
import { useState } from "react";
import { API } from "@/lib/api";

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

const INPUT = {
  flex: 1,
  background: "#0d0d0d",
  border: "1px solid #2a2a2a",
  color: "#e5e5e5",
  padding: "10px 12px",
  fontSize: 13,
  fontFamily: "monospace",
  borderRadius: 3,
  outline: "none",
};

const BTN = {
  background: "linear-gradient(135deg, #2a1a00 0%, #1a1200 100%)",
  border: "1px solid #f97316",
  color: "#f97316",
  padding: "10px 20px",
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

export default function SubscribeTab() {
  const [signupEmail, setSignupEmail] = useState("");
  const [signupBusy, setSignupBusy]   = useState(false);
  const [signupMsg, setSignupMsg]     = useState(null);

  const [unsubEmail, setUnsubEmail]   = useState("");
  const [unsubBusy, setUnsubBusy]     = useState(false);
  const [unsubMsg, setUnsubMsg]       = useState(null);

  async function submitSignup(e) {
    e.preventDefault();
    setSignupBusy(true); setSignupMsg(null);
    try {
      const res = await fetch(`${API}/subscribers/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: signupEmail }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        const verb = data.status === "reactivated" ? "Re-subscribed" : "Subscribed";
        setSignupMsg({ kind: "ok", text: `✓ ${verb} — ${signupEmail}` });
        setSignupEmail("");
      } else {
        setSignupMsg({ kind: "err", text: data.detail || `Error (${res.status})` });
      }
    } catch {
      setSignupMsg({ kind: "err", text: "Network error" });
    } finally {
      setSignupBusy(false);
    }
  }

  async function submitUnsub(e) {
    e.preventDefault();
    setUnsubBusy(true); setUnsubMsg(null);
    // The public unsubscribe endpoint requires an HMAC token that only the
    // backend can compute, so the form posts to /subscribers/unsubscribe-self
    // — a thin helper that re-derives the token server-side from the email.
    try {
      const res = await fetch(`${API}/subscribers/unsubscribe-self`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: unsubEmail }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setUnsubMsg({ kind: "ok", text: `✓ Unsubscribed — ${unsubEmail}` });
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
      <h2 style={{
        margin: "0 0 4px",
        fontFamily: "monospace",
        color: "#f97316",
        fontSize: 18,
        letterSpacing: 2,
        textTransform: "uppercase",
      }}>
        Daily RNS Digest
      </h2>
      <div style={{ color: "#666", fontSize: 12, fontFamily: "monospace", marginBottom: 24 }}>
        AI-ranked UK RNS announcements · 07:30 GMT/BST · Mon–Fri
      </div>

      <div style={CARD}>
        <div style={LABEL}>What you'll get</div>
        <div style={{ color: "#94a3b8", fontSize: 13, lineHeight: 1.6 }}>
          A morning email covering the last 24h of Tier&nbsp;A (high-impact) and
          Tier&nbsp;B RNS announcements from FTSE&nbsp;100, FTSE&nbsp;250 and
          SmallCap/AIM. Each item carries an AI thesis, risk flag, and a
          research/watch/ignore action. Free, no commitment.
        </div>
      </div>

      <div style={CARD}>
        <div style={LABEL}>Subscribe</div>
        <form onSubmit={submitSignup} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            type="email"
            required
            placeholder="you@example.com"
            value={signupEmail}
            onChange={(e) => setSignupEmail(e.target.value)}
            style={{ ...INPUT, minWidth: 220 }}
            autoComplete="email"
          />
          <button type="submit" disabled={signupBusy} style={{ ...BTN, opacity: signupBusy ? 0.5 : 1 }}>
            {signupBusy ? "Subscribing…" : "Subscribe"}
          </button>
        </form>
        <Message kind={signupMsg?.kind} text={signupMsg?.text} />
      </div>

      <div style={CARD}>
        <div style={{ ...LABEL, color: "#94a3b8" }}>Unsubscribe</div>
        <div style={{ color: "#666", fontSize: 12, fontFamily: "monospace", marginBottom: 12 }}>
          Or use the one-click link in any digest email footer.
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
      </div>
    </div>
  );
}
