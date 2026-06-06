import { useState } from "react";
import { API } from "../utils";

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
  background: "#0d0d0d",
  border: "1px solid #2a2a2a",
  color: "#e5e5e5",
  padding: "10px 12px",
  fontSize: 13,
  fontFamily: "monospace",
  borderRadius: 3,
  outline: "none",
  boxSizing: "border-box",
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

const KOFI_URL = "https://ko-fi.com/alphamoveai";

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

export default function FeedbackTab() {
  const [message, setMessage] = useState("");
  const [email, setEmail]     = useState("");
  const [company, setCompany] = useState(""); // honeypot — hidden from users
  const [busy, setBusy]       = useState(false);
  const [msg, setMsg]         = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (!message.trim()) return;
    setBusy(true); setMsg(null);
    try {
      const res = await fetch(`${API}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, email, company }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setMsg({ kind: "ok", text: "✓ Thanks — your feedback has been sent." });
        setMessage("");
        setEmail("");
      } else {
        setMsg({ kind: "err", text: data.detail || `Error (${res.status})` });
      }
    } catch {
      setMsg({ kind: "err", text: "Network error" });
    } finally {
      setBusy(false);
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
        Feedback
      </h2>
      <div style={{ color: "#666", fontSize: 12, fontFamily: "monospace", marginBottom: 24 }}>
        Spotted a bug, want a feature, or just have a thought? Tell me.
      </div>

      <div style={CARD}>
        <div style={LABEL}>Your message</div>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <textarea
            required
            placeholder="What's on your mind?"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={6}
            maxLength={5000}
            style={{ ...INPUT, width: "100%", resize: "vertical", lineHeight: 1.5 }}
          />
          <input
            type="email"
            placeholder="you@example.com (optional — so I can reply)"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{ ...INPUT, width: "100%" }}
            autoComplete="email"
          />
          {/* Honeypot: visually hidden, off-screen; bots fill it, humans don't. */}
          <input
            type="text"
            name="company"
            tabIndex={-1}
            autoComplete="off"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            style={{ position: "absolute", left: "-9999px", width: 1, height: 1, opacity: 0 }}
            aria-hidden="true"
          />
          <div>
            <button type="submit" disabled={busy} style={{ ...BTN, opacity: busy ? 0.5 : 1 }}>
              {busy ? "Sending…" : "Send feedback"}
            </button>
          </div>
        </form>
        <Message kind={msg?.kind} text={msg?.text} />
      </div>

      <div style={{ color: "#666", fontSize: 12, fontFamily: "monospace", lineHeight: 1.7 }}>
        Prefer Ko-fi?{" "}
        <a href={KOFI_URL} target="_blank" rel="noopener noreferrer" style={{ color: "#f97316" }}>
          Message me there
        </a>{" "}
        instead.
      </div>
    </div>
  );
}
