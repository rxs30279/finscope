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
  dispatchable?: boolean; // smoke/e2e: can be kicked off via POST /api/ci/run
}
interface DigestMarker {
  last_run_at: string | null;
  status: string | null; // ok | degraded | failed
  mode: string | null; // segment | fallback | none
  recipients: number | null;
  sent: number | null;
  failed: number | null;
}
interface ProviderStats {
  messages: number;
  problems: number;
  problem_rate: number;
  latest_problem: string | null;
}
interface EmailEvents {
  days?: number;
  messages?: number;
  problems?: number;
  latest_event?: string | null;
  by_provider?: Record<string, ProviderStats>;
  available?: false; // present only when the panel failed to load
  error?: string;
}
interface StatusResponse {
  generated_at: string;
  health: { summary: "pass" | "warn" | "fail"; checks: HealthCheck[] };
  ci: { available: boolean; workflows?: CiWorkflow[]; error?: string };
  digest: DigestMarker | null;
  email_events: EmailEvents | null;
}

const REFRESH_MS = 60_000; // auto-refresh cadence
// After dispatching a workflow, re-poll (bypassing the backend CI cache) at
// these offsets — GitHub takes a few seconds to create the run record.
const DISPATCH_POLL_MS = [5_000, 15_000, 30_000, 60_000];
// Treat a dispatch as pending until GitHub shows a newer run or this expires
// (mirrors gh_actions.pipeline_status's 90s "queueing" hold).
const DISPATCH_PENDING_MS = 90_000;

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

// The digest cron fires weekdays at 07:30 UK. A send older than the most
// recent expected slot means today's (or Friday's, over a weekend) send is
// missing — an old "ok" must not show a green tick. Viewer-local time is fine:
// the only admin is in the UK, and the 1h slack absorbs cron drift + BST.
function digestIsStale(iso: string | null): boolean {
  if (!iso) return true;
  const sent = new Date(iso).getTime();
  if (Number.isNaN(sent)) return true;
  const slot = new Date();
  slot.setHours(8, 30, 0, 0); // 07:30 send + 1h slack
  if (slot.getTime() > Date.now()) slot.setDate(slot.getDate() - 1);
  while (slot.getDay() === 0 || slot.getDay() === 6) slot.setDate(slot.getDate() - 1);
  return sent < slot.getTime();
}

// A provider needs at least this many messages before its deferral rate is
// allowed to set the card's tone. Same reasoning as the analyst buy_pct
// shrinkage (k=5): "1 of 1 deferred" is 100% and means nothing.
const MIN_MESSAGES_FOR_TONE = 5;
// Above this share of deferred/bounced messages a provider is throttling us,
// not just having an off day. Today's incident was 0.67; a healthy provider
// sits at 0.
const PROBLEM_RATE_BAD = 0.2;
const PROBLEM_RATE_WARN = 0.05;

function providerTone(p: ProviderStats): string {
  if (p.problems === 0) return colors.green;
  if (p.messages < MIN_MESSAGES_FOR_TONE) return colors.textDim;
  if (p.problem_rate >= PROBLEM_RATE_BAD) return colors.red;
  if (p.problem_rate >= PROBLEM_RATE_WARN) return colors.amber;
  return colors.green;
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
  // workflow file -> dispatch epoch ms; row shows "dispatched" until GitHub
  // reports a run started after this (or it expires).
  const [dispatched, setDispatched] = useState<Record<string, number>>({});
  const pollTimeouts = useRef<ReturnType<typeof setTimeout>[]>([]);

  const load = useCallback(async (freshCi = false) => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/status${freshCi ? "?fresh_ci=true" : ""}`, {
        headers: adminHeaders(),
      });
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

  const runWorkflow = useCallback(async (workflow: string) => {
    setDispatched((d) => ({ ...d, [workflow]: Date.now() }));
    try {
      const res = await fetch(`${API}/ci/run?workflow=${encodeURIComponent(workflow)}`, {
        method: "POST",
        headers: adminHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // GitHub creates the run record a few seconds after the 204; re-poll
      // with the CI cache bypassed so the row flips to queued/running.
      pollTimeouts.current.push(
        ...DISPATCH_POLL_MS.map((ms) => setTimeout(() => load(true), ms)),
      );
    } catch {
      setDispatched((d) => {
        const next = { ...d };
        delete next[workflow];
        return next;
      });
      setError(`Could not dispatch ${workflow}.`);
    }
  }, [load]);

  useEffect(() => {
    if (!isAdmin) return;
    load();
    timer.current = setInterval(() => load(), REFRESH_MS);
    const tickId = setInterval(() => setTick((t) => t + 1), 15_000);
    const timeouts = pollTimeouts.current;
    return () => {
      if (timer.current) clearInterval(timer.current);
      clearInterval(tickId);
      timeouts.forEach(clearTimeout);
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
            onClick={() => load()}
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

      {/* ── Deliverability (delivery events) ──────────────────────────────── */}
      <DeliverabilityCard events={data?.email_events} loaded={!!data} />

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
            // A just-dispatched workflow shows "dispatched" until GitHub
            // reports a run started after the dispatch (then the normal
            // queued/running chip takes over) or the hold expires.
            const dispatchedAt = dispatched[w.workflow];
            const pending =
              !!dispatchedAt &&
              Date.now() - dispatchedAt < DISPATCH_PENDING_MS &&
              (!w.run_started_at || new Date(w.run_started_at).getTime() < dispatchedAt);
            const c = pending ? { label: "dispatched", color: colors.amber } : ciChip(w);
            return (
              <div key={w.workflow} style={rowStyle}>
                <span style={chip(c.color)}>{c.label}</span>
                <span style={{ color: colors.text, minWidth: 190, flexShrink: 0 }}>{w.workflow}</span>
                <span style={{ color: colors.textMuted, flex: 1 }}>{ago(w.run_started_at)}</span>
                {w.dispatchable && (
                  <button
                    onClick={() => runWorkflow(w.workflow)}
                    disabled={pending}
                    style={{
                      fontFamily: "monospace",
                      fontSize: 11,
                      color: pending ? colors.textDim : colors.accent,
                      border: `1px solid ${colors.border}`,
                      background: "transparent",
                      padding: "2px 10px",
                      borderRadius: 2,
                      cursor: pending ? "default" : "pointer",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {pending ? "queued…" : "run now"}
                  </button>
                )}
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
    if (digest.status === "ok" && digestIsStale(digest.last_run_at)) {
      // Last send was clean but a newer one should have happened by now.
      tone = colors.amber;
      headline = `! Digest stale · last send ${ago(digest.last_run_at)} · ${digest.mode} · ${sent}/${recips} delivered`;
    } else if (digest.status === "ok") {
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

// ── Deliverability card ────────────────────────────────────────────────────────
// Per-provider deferral/bounce rates from the delivery-event log (email_events),
// fed by the Resend webhook and/or the SES SQS drain depending on the sender.
// Rates are per *message*, not per event — see email_events.recent_summary.
function DeliverabilityCard({
  events,
  loaded,
}: {
  events: EmailEvents | null | undefined;
  loaded: boolean;
}) {
  const providers = Object.entries(events?.by_provider || {}).sort(
    // Worst rate first so a throttling provider is the first thing read;
    // volume breaks ties so the big providers outrank one-off domains.
    (a, b) => b[1].problem_rate - a[1].problem_rate || b[1].messages - a[1].messages,
  );

  const messages = events?.messages ?? 0;
  const problems = events?.problems ?? 0;
  const days = events?.days ?? 7;

  let tone: string = colors.textDim;
  let headline = loaded ? "No delivery events recorded yet." : "Loading…";
  let sub: string | null = null;

  if (events?.available === false) {
    headline = "Delivery events unavailable.";
    sub = events.error || "Is migration 018 applied?";
  } else if (loaded && messages === 0) {
    // Deliberately grey, never green: zero problems because zero data looks
    // identical to perfect health if you only read the rate.
    sub = "No event source recorded yet — check the Resend webhook, or the ses_events drain cron.";
  } else if (loaded && events) {
    // The event source sees events on every send, so "no events since the last
    // expected digest" means it has stopped delivering, not that all is well.
    const silent = digestIsStale(events.latest_event ?? null);
    const worst = providers.find(
      ([, p]) => p.messages >= MIN_MESSAGES_FOR_TONE && p.problem_rate >= PROBLEM_RATE_WARN,
    );
    if (silent) {
      tone = colors.amber;
      headline = `! No delivery events since ${ago(events.latest_event ?? null)}`;
      sub = "Expected events from the last digest — the event feed may have stopped.";
    } else if (worst) {
      const [name, p] = worst;
      tone = providerTone(p);
      headline = `! ${name} deferring · ${p.problems} of ${p.messages} messages (${Math.round(p.problem_rate * 100)}%)`;
      sub = `${problems} of ${messages} messages affected across all providers · last ${days}d`;
    } else if (problems > 0) {
      // Problems exist but no provider has the volume to call it. Must not
      // render a green tick reading "3 of 3 messages deferred".
      tone = colors.textDim;
      headline = `${problems} of ${messages} messages deferred · last ${days}d`;
      sub = `Under ${MIN_MESSAGES_FOR_TONE} messages per provider — too few to judge yet.`;
    } else {
      tone = colors.green;
      headline = `✓ No delivery problems · ${messages} messages, last ${days}d`;
      sub = `Newest event ${ago(events.latest_event ?? null)}`;
    }
  }

  return (
    <div style={{ ...card, borderColor: tone, borderLeft: `3px solid ${tone}` }}>
      <h2 style={sectionTitle}>Deliverability</h2>
      <div style={{ color: colors.text, fontFamily: "monospace", fontSize: 14, fontWeight: 700 }}>{headline}</div>
      {sub && <div style={{ color: colors.textMuted, fontFamily: "monospace", fontSize: 12, marginTop: 6 }}>{sub}</div>}

      {providers.length > 0 && (
        <div style={{ marginTop: 14 }}>
          {providers.map(([name, p]) => (
            <div key={name} style={rowStyle}>
              <span style={chip(providerTone(p))}>{Math.round(p.problem_rate * 100)}%</span>
              <span style={{ color: colors.text, minWidth: 110, flexShrink: 0 }}>{name}</span>
              <span style={{ color: colors.textMuted, minWidth: 150, flexShrink: 0 }}>
                {p.problems} of {p.messages} messages
              </span>
              <span style={{ color: colors.textDim, flex: 1 }}>
                {p.latest_problem ? `last issue ${ago(p.latest_problem)}` : ""}
                {p.problems > 0 && p.messages < MIN_MESSAGES_FOR_TONE ? " · too few to judge" : ""}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
