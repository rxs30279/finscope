"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { API, adminHeaders } from "@/lib/api";
import { colors } from "@/lib/theme";
import { useIsAdmin } from "@/hooks/useAdmin";
import PageHeader from "@/components/layout/PageHeader";

// ── Response shape (mirrors GET /api/status in backend/main.py) ────────────────
interface HealthCheck {
  name: string;
  status: "PASS" | "WARN" | "FAIL";
  detail: string;
}
interface CiWorkflow {
  workflow: string;
  status: string | null; // queued | in_progress | completed
  conclusion: string | null; // success | failure | cancelled | null
  run_started_at: string | null;
  html_url: string | null;
}
interface DigestMarker {
  last_run_at: string | null;
  status: string | null; // ok | degraded | failed
  mode: string | null; // segment | fallback | none
  recipients: number | null;
  sent: number | null;
  failed: number | null;
}
interface StatusResponse {
  generated_at: string;
  health: { summary: "pass" | "warn" | "fail"; checks: HealthCheck[] };
  ci: { available: boolean; workflows?: CiWorkflow[]; error?: string };
  digest: DigestMarker | null;
}

const REFRESH_MS = 60_000; // auto-refresh cadence

const HEALTH_COLOR: Record<string, string> = {
  PASS: colors.green,
  WARN: colors.amber,
  FAIL: colors.red,
};
// FAIL first, then WARN, then PASS so problems surface at the top.
const HEALTH_ORDER: Record<string, number> = { FAIL: 0, WARN: 1, PASS: 2 };

const SUMMARY_COLOR: Record<string, string> = {
  fail: colors.red,
  warn: colors.amber,
  pass: colors.green,
};

// Relative "…ago" from an ISO timestamp (like the Sidebar as_of stamp).
function ago(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const s = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

function clockTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Map a CI run to a {label, color}. success→green, failure→red, running→amber,
// anything else (no runs / unknown) → grey.
function ciChip(w: CiWorkflow): { label: string; color: string } {
  if (w.conclusion === "success") return { label: "success", color: colors.green };
  if (w.conclusion && w.conclusion !== "success")
    return { label: w.conclusion, color: colors.red };
  if (w.status === "in_progress" || w.status === "queued")
    return { label: w.status === "queued" ? "queued" : "running", color: colors.amber };
  return { label: "—", color: colors.textDim };
}

const card: CSSProperties = {
  background: colors.bgCard,
  border: `1px solid ${colors.border}`,
  borderRadius: 4,
  padding: 20,
  marginBottom: 20,
};
const sectionTitle: CSSProperties = {
  margin: "0 0 14px",
  fontFamily: "monospace",
  fontSize: 12,
  fontWeight: 700,
  color: colors.accent,
  textTransform: "uppercase",
  letterSpacing: 1,
};
const chip = (bg: string): CSSProperties => ({
  display: "inline-block",
  minWidth: 54,
  textAlign: "center",
  color: "#0a0a0a",
  background: bg,
  fontSize: 10,
  fontWeight: 700,
  padding: "3px 8px",
  borderRadius: 2,
  fontFamily: "monospace",
  textTransform: "uppercase",
  letterSpacing: 0.5,
});
const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 12,
  padding: "9px 0",
  borderBottom: `1px solid ${colors.borderSubtle}`,
  fontFamily: "monospace",
  fontSize: 12,
};

export default function StatusClient() {
  const isAdmin = useIsAdmin();
  const [data, setData] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Re-render the "…ago" stamps on a ticker without refetching.
  const [, setTick] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/status`, { headers: adminHeaders() });
      if (res.status === 403) {
        setError("Admin token rejected — re-unlock with /?admin=<token>.");
        setData(null);
        return;
      }
      if (!res.ok) {
        setError(`Status request failed (HTTP ${res.status}).`);
        return;
      }
      setData(await res.json());
      setError(null);
    } catch {
      setError("Could not reach the status endpoint.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    load();
    timer.current = setInterval(load, REFRESH_MS);
    const tickId = setInterval(() => setTick((t) => t + 1), 15_000);
    return () => {
      if (timer.current) clearInterval(timer.current);
      clearInterval(tickId);
    };
  }, [isAdmin, load]);

  if (!isAdmin) {
    return (
      <div style={{ padding: "80px 24px", textAlign: "center", color: colors.textDim, fontFamily: "monospace", fontSize: 14 }}>
        Admins only. Unlock with <code>/?admin=&lt;token&gt;</code>.
      </div>
    );
  }

  const health = data?.health;
  const checks = health ? [...health.checks].sort((a, b) => HEALTH_ORDER[a.status] - HEALTH_ORDER[b.status]) : [];
  const ci = data?.ci;
  const digest = data?.digest;

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <PageHeader
        title="System status"
        subtitle={data ? `Updated ${ago(data.generated_at)}` : "Admin-only operations dashboard"}
        right={
          <button
            onClick={load}
            disabled={loading}
            style={{
              fontFamily: "monospace",
              fontSize: 12,
              color: colors.accent,
              border: `1px solid ${colors.border}`,
              background: colors.accentBg,
              padding: "8px 14px",
              borderRadius: 2,
              cursor: loading ? "default" : "pointer",
              opacity: loading ? 0.6 : 1,
              whiteSpace: "nowrap",
            }}
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        }
      />

      {error && (
        <div style={{ ...card, borderColor: colors.red, color: colors.red, fontFamily: "monospace", fontSize: 13 }}>
          {error}
        </div>
      )}

      {/* ── Email digest notification ─────────────────────────────────────── */}
      <DigestCard digest={digest} loaded={!!data} />

      {/* ── System health ─────────────────────────────────────────────────── */}
      <div style={card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14 }}>
          <h2 style={{ ...sectionTitle, margin: 0 }}>System health</h2>
          {health && (
            <span style={{ ...chip(SUMMARY_COLOR[health.summary] || colors.textDim), minWidth: 0 }}>
              {health.summary}
            </span>
          )}
        </div>
        {checks.length === 0 && !error && (
          <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 12 }}>
            {loading ? "Loading…" : "No checks."}
          </div>
        )}
        {checks.map((c) => (
          <div key={c.name} style={rowStyle}>
            <span style={chip(HEALTH_COLOR[c.status] || colors.textDim)}>{c.status}</span>
            <span style={{ color: colors.text, minWidth: 190, flexShrink: 0 }}>{c.name}</span>
            <span style={{ color: colors.textMuted, wordBreak: "break-word" }}>{c.detail}</span>
          </div>
        ))}
      </div>

      {/* ── CI workflows ──────────────────────────────────────────────────── */}
      <div style={card}>
        <h2 style={sectionTitle}>CI workflows</h2>
        {!ci || !ci.available ? (
          <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 12 }}>
            CI status unavailable{ci?.error ? ` (${ci.error})` : " (GITHUB_STATUS_TOKEN not set?)"}
          </div>
        ) : (
          (ci.workflows || []).map((w) => {
            const c = ciChip(w);
            return (
              <div key={w.workflow} style={rowStyle}>
                <span style={chip(c.color)}>{c.label}</span>
                <span style={{ color: colors.text, minWidth: 190, flexShrink: 0 }}>{w.workflow}</span>
                <span style={{ color: colors.textMuted, flex: 1 }}>{ago(w.run_started_at)}</span>
                {w.html_url && (
                  <a href={w.html_url} target="_blank" rel="noreferrer" style={{ color: colors.accent, textDecoration: "none" }}>
                    view run →
                  </a>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── Digest card ────────────────────────────────────────────────────────────────
function DigestCard({ digest, loaded }: { digest: DigestMarker | null | undefined; loaded: boolean }) {
  // Tone: ok → green, degraded → amber, failed → red, no record → grey.
  let tone: string = colors.textDim;
  let headline = loaded ? "No digest send recorded yet." : "Loading…";
  let sub: string | null = null;

  if (digest) {
    const sent = digest.sent ?? "?";
    const recips = digest.recipients ?? "?";
    if (digest.status === "ok") {
      tone = colors.green;
      headline = `✓ Digest sent ${clockTime(digest.last_run_at)} · ${digest.mode} · ${sent}/${recips} delivered`;
    } else if (digest.status === "failed") {
      tone = colors.red;
      headline = `✗ Digest FAILED · ${digest.mode ?? "no send"}`;
    } else {
      tone = colors.amber;
      headline = `! Digest degraded · ${digest.mode} · ${sent}/${recips} delivered`;
    }
    sub = `${ago(digest.last_run_at)}${digest.failed ? ` · ${digest.failed} failed` : ""}`;
  }

  return (
    <div style={{ ...card, borderColor: tone, borderLeft: `3px solid ${tone}` }}>
      <h2 style={sectionTitle}>Email digest</h2>
      <div style={{ color: colors.text, fontFamily: "monospace", fontSize: 14, fontWeight: 700 }}>{headline}</div>
      {sub && <div style={{ color: colors.textMuted, fontFamily: "monospace", fontSize: 12, marginTop: 6 }}>{sub}</div>}
    </div>
  );
}
