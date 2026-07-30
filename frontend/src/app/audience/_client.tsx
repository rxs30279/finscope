"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { API, adminHeaders } from "@/lib/api";
import { colors } from "@/lib/theme";
import { useIsAdmin } from "@/hooks/useAdmin";
import PageHeader from "@/components/layout/PageHeader";
import { loadAudienceState, saveAudienceState } from "@/lib/storage";

// ── Response shape (mirrors GET /api/subscribers/audience in backend/subscribers.py) ──
type AudienceStatus = "subscribed" | "unsubscribed" | "bounced";

interface Subscriber {
  email: string;
  created_at: string;
  unsubscribed_at: string | null;
  resubscribed_at: string | null;
  bounced_at: string | null;
  bounce_reason: string | null;
  status: AudienceStatus;
}

interface AudienceResponse {
  total: number;
  summary: Partial<Record<AudienceStatus, number>>;
  subscribers: Subscriber[];
}

const STATUS_ORDER: AudienceStatus[] = ["subscribed", "unsubscribed", "bounced"];
const STATUS_LABEL: Record<AudienceStatus, string> = {
  subscribed: "Subscribed",
  unsubscribed: "Unsubscribed",
  bounced: "Bounced",
};
const STATUS_COLOR: Record<AudienceStatus, string> = {
  subscribed: colors.green,
  unsubscribed: colors.textDim,
  bounced: colors.red,
};

// Comfortably above MAX_SUBSCRIBERS' current default (100) — no pagination
// UI until the list is large enough to need one.
const PAGE_LIMIT = 500;

const _isValidStatus = (v: unknown): v is AudienceStatus =>
  typeof v === "string" && (STATUS_ORDER as string[]).includes(v);

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

const card: CSSProperties = {
  background: colors.bgCard,
  border: `1px solid ${colors.border}`,
  borderRadius: 4,
  padding: 20,
  marginBottom: 20,
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
  status: AudienceStatus;
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

export default function AudienceClient() {
  const isAdmin = useIsAdmin();
  const [data, setData] = useState<AudienceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [status, setStatus] = useState<AudienceStatus | "">("");
  const [search, setSearch] = useState("");

  // Same hydration-gate pattern as /emails: don't let the pre-restore
  // defaults immediately overwrite the saved filter on first render.
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const s = loadAudienceState();
    if (_isValidStatus(s.status)) setStatus(s.status as AudienceStatus);
    else if (s.status === "") setStatus("");
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveAudienceState({ status });
  }, [hydrated, status]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ limit: String(PAGE_LIMIT) });
      if (status) qs.set("status", status);
      if (search.trim()) qs.set("q", search.trim());
      const res = await fetch(`${API}/subscribers/audience?${qs}`, { headers: adminHeaders() });
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
      setError("Could not reach the audience endpoint.");
    } finally {
      setLoading(false);
    }
  }, [status, search]);

  // Debounce the search box only — status is a discrete control that should
  // refetch immediately on click.
  useEffect(() => {
    if (!isAdmin || !hydrated) return;
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin, hydrated, status, search]);

  if (!isAdmin) {
    return (
      <div style={{ padding: "80px 24px", textAlign: "center", color: colors.textDim, fontFamily: "monospace", fontSize: 14 }}>
        Admins only. Unlock with <code>/?admin=&lt;token&gt;</code>.
      </div>
    );
  }

  const summary = data?.summary ?? {};

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <PageHeader
        title="Audience"
        subtitle={
          data
            ? `${data.total} of ${STATUS_ORDER.reduce((n, s) => n + (summary[s] ?? 0), 0)} subscriber${data.total === 1 ? "" : "s"}`
            : "Digest subscriber list — see /emails for per-message delivery"
        }
        right={
          <>
            <a
              href="/emails"
              style={{ color: colors.textMuted, fontFamily: "monospace", fontSize: 11, textDecoration: "none" }}
              title="Per-message delivery monitor"
            >
              Emails →
            </a>
            <button onClick={() => load()} disabled={loading} style={{ ...controlBtn(false), opacity: loading ? 0.6 : 1 }}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </>
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

      {/* ── Search ────────────────────────────────────────────────────────── */}
      <div style={{ ...card, display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search email…"
          style={searchStyle}
        />
      </div>

      {/* ── Table ─────────────────────────────────────────────────────────── */}
      <div style={{ ...card, overflowX: "auto" }}>
        {!data || data.subscribers.length === 0 ? (
          <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 12 }}>
            {loading ? "Loading…" : "No subscribers for this filter."}
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "monospace", fontSize: 12 }}>
            <thead>
              <tr>
                <Th align="left">Email</Th>
                <Th align="left">Status</Th>
                <Th align="right">Added</Th>
              </tr>
            </thead>
            <tbody>
              {data.subscribers.map((s) => (
                <tr key={s.email} style={{ borderBottom: `1px solid ${colors.borderSubtle}` }}>
                  <Td>
                    <span style={{ color: colors.text }}>{s.email}</span>
                  </Td>
                  <Td>
                    <span style={{ color: STATUS_COLOR[s.status], fontWeight: 700 }}>{STATUS_LABEL[s.status]}</span>
                    {s.status === "bounced" && s.bounce_reason && (
                      <span style={{ color: colors.textDim, marginLeft: 6, fontSize: 10 }} title="Bounce reason">
                        {s.bounce_reason}
                      </span>
                    )}
                  </Td>
                  <Td align="right">
                    <span style={{ color: colors.textMuted }}>{ago(s.created_at)}</span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && data.total >= PAGE_LIMIT && (
          <div style={{ marginTop: 14, color: colors.amber, fontSize: 11, fontFamily: "monospace" }}>
            Showing the first {PAGE_LIMIT} — narrow the search or status filter to see more.
          </div>
        )}
      </div>
    </div>
  );
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" | "center" }) {
  return (
    <th
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

function Td({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" | "center" }) {
  return (
    <td style={{ textAlign: align, padding: "7px 10px", whiteSpace: "nowrap" }}>
      {children}
    </td>
  );
}
