"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { API, adminHeaders } from "@/lib/api";
import { colors } from "@/lib/theme";
import { useIsAdmin } from "@/hooks/useAdmin";
import PageHeader from "@/components/layout/PageHeader";
import { loadEmailsState, saveEmailsState } from "@/lib/storage";

// ── Response shape (mirrors GET /api/emails(/{email_id}) in backend/email_monitor.py) ──
type MessageStatus = "sent" | "delivered" | "delayed" | "bounced" | "failed" | "complained";

interface EmailMessage {
  email_id: string;
  provider: string | null;
  recipient: string | null;
  recipient_domain: string | null;
  subject: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  last_event_at: string | null;
  status: MessageStatus;
  was_delayed: boolean;
  opened: boolean;
  clicked: boolean;
}

interface EmailsResponse {
  days: number;
  total: number;
  summary: Partial<Record<MessageStatus, number>>;
  messages: EmailMessage[];
}

interface TimelineEvent {
  event_type: string;
  provider: string | null;
  occurred_at: string;
  email_created_at: string | null;
  detail: Record<string, unknown> | null;
}

interface TimelineResponse {
  email_id: string;
  events: TimelineEvent[];
}

const DAY_OPTIONS = [1, 7, 14, 30];
const PROVIDER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All providers" },
  { value: "resend", label: "Resend" },
  { value: "ses", label: "SES" },
];
const STATUS_ORDER: MessageStatus[] = ["sent", "delivered", "delayed", "bounced", "failed", "complained"];
const STATUS_LABEL: Record<MessageStatus, string> = {
  sent: "Sent",
  delivered: "Delivered",
  delayed: "Delayed",
  bounced: "Bounced",
  failed: "Failed",
  complained: "Complained",
};
// bounced/failed/complained are all terminal problems, but a spam complaint
// carries a different (reputation, not deliverability) risk, so it gets its
// own color rather than blending into "bounced".
const STATUS_COLOR: Record<MessageStatus, string> = {
  sent: colors.textDim,
  delivered: colors.green,
  delayed: colors.amber,
  bounced: colors.red,
  failed: colors.red,
  complained: colors.purple,
};

const _isValidDays = (v: unknown): v is number => typeof v === "number" && DAY_OPTIONS.includes(v);
const _isValidStatus = (v: unknown): v is MessageStatus =>
  typeof v === "string" && (STATUS_ORDER as string[]).includes(v);
const _isValidProvider = (v: unknown): v is string =>
  typeof v === "string" && PROVIDER_OPTIONS.some((p) => p.value === v);

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

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
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
const controlBtn = (active: boolean): CSSProperties => ({
  fontFamily: "monospace",
  fontSize: 11,
  color: active ? colors.accent : colors.textMuted,
  border: `1px solid ${active ? colors.accent : colors.border}`,
  background: active ? colors.accentBg : "transparent",
  padding: "5px 12px",
  borderRadius: 2,
  cursor: "pointer",
  whiteSpace: "nowrap",
});
const selectStyle: CSSProperties = {
  fontFamily: "monospace",
  fontSize: 11,
  color: colors.textMuted,
  background: colors.bgCardAlt,
  border: `1px solid ${colors.border}`,
  borderRadius: 2,
  padding: "5px 8px",
  cursor: "pointer",
};
const searchStyle: CSSProperties = {
  fontFamily: "monospace",
  fontSize: 12,
  color: colors.text,
  background: colors.bgCardAlt,
  border: `1px solid ${colors.border}`,
  borderRadius: 2,
  padding: "6px 10px",
  outline: "none",
  minWidth: 220,
};

function StatTile({
  status,
  count,
  active,
  onClick,
}: {
  status: MessageStatus;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: "monospace",
        fontSize: 11,
        textAlign: "left",
        cursor: "pointer",
        border: `1px solid ${active ? STATUS_COLOR[status] : colors.border}`,
        background: active ? `${STATUS_COLOR[status]}18` : colors.bgCardAlt,
        borderRadius: 3,
        padding: "8px 14px",
        minWidth: 100,
      }}
    >
      <div style={{ color: STATUS_COLOR[status], fontWeight: 700, fontSize: 16 }}>{count}</div>
      <div style={{ color: colors.textDim, textTransform: "uppercase", letterSpacing: 0.5, marginTop: 2 }}>
        {STATUS_LABEL[status]}
      </div>
    </button>
  );
}

function EngagementDot({ on, title }: { on: boolean; title: string }) {
  return (
    <span
      title={title}
      style={{
        display: "inline-block",
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: on ? colors.cyan : colors.borderSubtle,
      }}
    />
  );
}

function TimelineDrawer({ emailId, onClose }: { emailId: string; onClose: () => void }) {
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    fetch(`${API}/emails/${encodeURIComponent(emailId)}`, { headers: adminHeaders() })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((json: TimelineResponse) => {
        if (!cancelled) setData(json);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load the event timeline.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [emailId]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.6)",
        zIndex: 300,
        display: "flex",
        justifyContent: "flex-end",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 460,
          maxWidth: "90vw",
          height: "100%",
          overflowY: "auto",
          background: colors.bgCard,
          borderLeft: `1px solid ${colors.border}`,
          padding: 20,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 16 }}>
          <h2 style={{ ...sectionTitle, margin: 0 }}>Timeline</h2>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", color: colors.textDim, cursor: "pointer", fontSize: 16 }}
          >
            ✕
          </button>
        </div>
        <div style={{ color: colors.textMuted, fontFamily: "monospace", fontSize: 11, marginBottom: 16, wordBreak: "break-all" }}>
          {emailId}
        </div>

        {loading && <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 12 }}>Loading…</div>}
        {error && <div style={{ color: colors.red, fontFamily: "monospace", fontSize: 12 }}>{error}</div>}

        {data && data.events.length === 0 && (
          <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 12 }}>No events recorded.</div>
        )}

        {data && data.events.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {data.events.map((e, i) => (
              <div key={i} style={{ borderLeft: `2px solid ${colors.border}`, paddingLeft: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "monospace", fontSize: 12 }}>
                  <span style={{ color: colors.text, fontWeight: 700 }}>{e.event_type}</span>
                  <span style={{ color: colors.textDim }}>{fmtDateTime(e.occurred_at)}</span>
                </div>
                <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 10, marginTop: 2 }}>
                  {e.provider ?? "—"}
                </div>
                {e.detail && (
                  <pre
                    style={{
                      marginTop: 6,
                      fontFamily: "monospace",
                      fontSize: 10,
                      color: colors.textMuted,
                      background: colors.bgCardAlt,
                      padding: 8,
                      borderRadius: 2,
                      overflowX: "auto",
                    }}
                  >
                    {JSON.stringify(e.detail, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function EmailsClient() {
  const isAdmin = useIsAdmin();
  const [data, setData] = useState<EmailsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [days, setDays] = useState(7);
  const [status, setStatus] = useState<MessageStatus | "">("");
  const [provider, setProvider] = useState("");
  const [search, setSearch] = useState("");
  const [openEmailId, setOpenEmailId] = useState<string | null>(null);

  // Gates the sessionStorage write-back until the saved filter set has been
  // restored, so the restore effect below doesn't get immediately overwritten
  // by the pre-restore defaults — same pattern as RnsTab's `hydrated` flag.
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const s = loadEmailsState();
    if (_isValidDays(s.days)) setDays(s.days);
    if (_isValidStatus(s.status)) setStatus(s.status as MessageStatus);
    else if (s.status === "") setStatus("");
    if (_isValidProvider(s.provider)) setProvider(s.provider);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveEmailsState({ days, status, provider });
  }, [hydrated, days, status, provider]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ days: String(days) });
      if (status) qs.set("status", status);
      if (provider) qs.set("provider", provider);
      if (search.trim()) qs.set("q", search.trim());
      const res = await fetch(`${API}/emails?${qs}`, { headers: adminHeaders() });
      if (res.status === 403) {
        setError("Admin token rejected — re-unlock with /?admin=<token>.");
        setData(null);
        return;
      }
      if (!res.ok) {
        setError(`Request failed (HTTP ${res.status}).`);
        return;
      }
      setData(await res.json());
      setError(null);
    } catch {
      setError("Could not reach the emails endpoint.");
    } finally {
      setLoading(false);
    }
  }, [days, status, provider, search]);

  // Debounce the search box only — the other filters are discrete controls
  // that should refetch immediately on click.
  useEffect(() => {
    if (!isAdmin || !hydrated) return;
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin, hydrated, days, status, provider, search]);

  if (!isAdmin) {
    return (
      <div style={{ padding: "80px 24px", textAlign: "center", color: colors.textDim, fontFamily: "monospace", fontSize: 14 }}>
        Admins only. Unlock with <code>/?admin=&lt;token&gt;</code>.
      </div>
    );
  }

  const summary = data?.summary ?? {};

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      <PageHeader
        title="Emails"
        subtitle={
          data
            ? `${data.total} message${data.total === 1 ? "" : "s"} · last ${data.days}d`
            : "Per-message delivery monitor — see /status for the aggregate view"
        }
        right={
          <button onClick={() => load()} disabled={loading} style={{ ...controlBtn(false), opacity: loading ? 0.6 : 1 }}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        }
      />

      {error && (
        <div style={{ ...card, borderColor: colors.red, color: colors.red, fontFamily: "monospace", fontSize: 13 }}>
          {error}
        </div>
      )}

      {/* ── Stat tiles ────────────────────────────────────────────────────── */}
      <div style={{ ...card, display: "flex", gap: 10, flexWrap: "wrap" }}>
        {STATUS_ORDER.map((s) => (
          <StatTile
            key={s}
            status={s}
            count={summary[s] ?? 0}
            active={status === s}
            onClick={() => setStatus((cur) => (cur === s ? "" : s))}
          />
        ))}
      </div>

      {/* ── Filters ───────────────────────────────────────────────────────── */}
      <div style={{ ...card, display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search recipient or subject…"
          style={searchStyle}
        />
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} style={selectStyle}>
          {DAY_OPTIONS.map((d) => (
            <option key={d} value={d}>
              Last {d}d
            </option>
          ))}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value as MessageStatus | "")} style={selectStyle}>
          <option value="">All statuses</option>
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </select>
        <select value={provider} onChange={(e) => setProvider(e.target.value)} style={selectStyle}>
          {PROVIDER_OPTIONS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>

      {/* ── Table ─────────────────────────────────────────────────────────── */}
      <div style={{ ...card, overflowX: "auto" }}>
        {!data || data.messages.length === 0 ? (
          <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 12 }}>
            {loading ? "Loading…" : "No messages for this window/filter set."}
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "monospace", fontSize: 12 }}>
            <thead>
              <tr>
                <Th align="left">To</Th>
                <Th align="left">Status</Th>
                <Th align="center" title="Provider that sent this message">Via</Th>
                <Th align="left">Subject</Th>
                <Th align="center" title="Opened / clicked (dot lit = happened)">Eng.</Th>
                <Th align="right">Sent</Th>
              </tr>
            </thead>
            <tbody>
              {data.messages.map((m) => (
                <tr
                  key={m.email_id}
                  onClick={() => setOpenEmailId(m.email_id)}
                  style={{ borderBottom: `1px solid ${colors.borderSubtle}`, cursor: "pointer" }}
                >
                  <Td>
                    <span style={{ color: colors.text }}>{m.recipient ?? "—"}</span>
                  </Td>
                  <Td>
                    <span style={{ color: STATUS_COLOR[m.status], fontWeight: 700 }}>{STATUS_LABEL[m.status]}</span>
                    {m.was_delayed && m.status !== "delayed" && (
                      <span style={{ color: colors.amber, marginLeft: 6, fontSize: 10 }} title="Was delayed before reaching this status">
                        ⚠ delayed
                      </span>
                    )}
                  </Td>
                  <Td align="center">
                    <span style={{ color: colors.textDim, fontSize: 10, textTransform: "uppercase" }}>{m.provider ?? "—"}</span>
                  </Td>
                  <Td>
                    <span style={{ color: colors.textMuted }}>{m.subject ?? "—"}</span>
                  </Td>
                  <Td align="center">
                    <span style={{ display: "inline-flex", gap: 5 }}>
                      <EngagementDot on={m.opened} title={m.opened ? "Opened" : "Not opened"} />
                      <EngagementDot on={m.clicked} title={m.clicked ? "Clicked" : "Not clicked"} />
                    </span>
                  </Td>
                  <Td align="right">
                    <span style={{ color: colors.textMuted }}>{ago(m.sent_at ?? m.last_event_at)}</span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div style={{ marginTop: 14, color: colors.textDim, fontSize: 11, fontFamily: "monospace" }}>
          Row click opens the event timeline · Eng. dots: opened / clicked &nbsp; ⚠ delayed = reached its status after a
          delivery delay
        </div>
      </div>

      {openEmailId && <TimelineDrawer emailId={openEmailId} onClose={() => setOpenEmailId(null)} />}
    </div>
  );
}

function Th({
  children,
  align = "left",
  title,
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
  title?: string;
}) {
  return (
    <th
      title={title}
      style={{
        textAlign: align,
        padding: "6px 10px",
        color: colors.accent,
        fontSize: 10,
        fontWeight: 700,
        borderBottom: `1px solid ${colors.border}`,
        whiteSpace: "nowrap",
        textTransform: "uppercase",
        letterSpacing: 0.5,
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
}) {
  return (
    <td style={{ textAlign: align, padding: "7px 10px", whiteSpace: "nowrap" }}>
      {children}
    </td>
  );
}
