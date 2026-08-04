"use client";

import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { API, adminHeaders } from "@/lib/api";
import { colors } from "@/lib/theme";
import { useIsAdmin } from "@/hooks/useAdmin";
import { useIsMobile } from "@/hooks/useMediaQuery";
import PageHeader from "@/components/layout/PageHeader";
import { loadEmailMetricsState, saveEmailMetricsState } from "@/lib/storage";

// ── Response shape (mirrors GET /api/emails/metrics in backend/email_monitor.py) ──
type SeriesKey =
  | "delivered"
  | "opened"
  | "clicked"
  | "bounced"
  | "failed"
  | "complained"
  | "delayed";

interface DayPoint {
  day: string; // ISO date, UK day
  messages: number;
  delivered: number;
  bounced: number;
  failed: number;
  complained: number;
  delayed: number;
  // null (not 0) on days before engagement was being recorded — see the
  // engagement note below and _ENGAGEMENT_TRACKED_FROM in email_monitor.py.
  opened: number | null;
  clicked: number | null;
}

interface MetricsResponse {
  days: number;
  start: string;
  end: string;
  series: SeriesKey[];
  points: DayPoint[];
  totals: Record<"messages" | SeriesKey, number>;
  rates: Partial<Record<SeriesKey, number | null>>;
  engagement: {
    tracked_from: string;
    fully_tracked: boolean;
    messages: number;
    delivered: number;
    opened: number;
    clicked: number;
  };
  domains: { domain: string; messages: number }[];
}

const DAY_OPTIONS = [7, 15, 30, 90];
const PROVIDER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All providers" },
  { value: "resend", label: "Resend" },
  { value: "ses", label: "SES" },
];

// Colours are the /emails page's status palette, so a red spike here and a red
// row there mean the same thing. Engagement borrows the cyan already used for
// the opened/clicked dots on /emails.
const SERIES: { key: SeriesKey; label: string; color: string; engagement?: boolean }[] = [
  { key: "delivered", label: "Delivered", color: colors.green },
  { key: "opened", label: "Opened", color: colors.cyan, engagement: true },
  { key: "clicked", label: "Clicked", color: colors.purple, engagement: true },
  { key: "bounced", label: "Bounced", color: colors.red },
  { key: "failed", label: "Failed", color: "#fb923c" },
  { key: "complained", label: "Complained", color: colors.indigo },
  { key: "delayed", label: "Delayed", color: colors.amber },
];
const SERIES_BY_KEY = Object.fromEntries(SERIES.map((s) => [s.key, s])) as Record<
  SeriesKey,
  (typeof SERIES)[number]
>;

// The four Resend draws by default. The rest are one click away and carry their
// count in the chip label, so a non-zero hidden series still announces itself
// rather than hiding behind a folded-away toggle.
const DEFAULT_SERIES: SeriesKey[] = ["delivered", "opened", "clicked", "bounced"];

const _isValidDays = (v: unknown): v is number =>
  typeof v === "number" && DAY_OPTIONS.includes(v);
const _isValidProvider = (v: unknown): v is string =>
  typeof v === "string" && PROVIDER_OPTIONS.some((p) => p.value === v);
const _isValidSeries = (v: unknown): v is SeriesKey[] =>
  Array.isArray(v) && v.every((k) => typeof k === "string" && k in SERIES_BY_KEY);

function fmtDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

function pct(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : `${n}%`;
}

const card: CSSProperties = {
  background: colors.bgCard,
  border: `1px solid ${colors.border}`,
  borderRadius: 4,
  padding: 20,
  marginBottom: 20,
};
const controlBtn: CSSProperties = {
  fontFamily: "monospace",
  fontSize: 11,
  color: colors.textMuted,
  border: `1px solid ${colors.border}`,
  background: "transparent",
  padding: "5px 12px",
  borderRadius: 2,
  cursor: "pointer",
  whiteSpace: "nowrap",
};
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

/** Big number + caption, the pair Resend leads its Metrics card with. */
function Headline({
  label,
  value,
  hint,
  color,
}: {
  label: string;
  value: string;
  hint?: string;
  color?: string;
}) {
  return (
    <div style={{ minWidth: 120 }}>
      <div
        style={{
          fontFamily: "monospace",
          fontSize: 10,
          color: colors.textDim,
          textTransform: "uppercase",
          letterSpacing: 1,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 30,
          fontWeight: 700,
          color: color ?? colors.white,
          lineHeight: 1.2,
          letterSpacing: "-0.02em",
        }}
      >
        {value}
      </div>
      {hint && (
        <div style={{ fontFamily: "monospace", fontSize: 10, color: colors.textDim }}>{hint}</div>
      )}
    </div>
  );
}

function SeriesChip({
  series,
  total,
  active,
  onClick,
}: {
  series: (typeof SERIES)[number];
  total: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 7,
        fontFamily: "monospace",
        fontSize: 11,
        cursor: "pointer",
        border: `1px solid ${active ? series.color : colors.border}`,
        background: active ? `${series.color}18` : colors.bgCardAlt,
        color: active ? colors.text : colors.textDim,
        borderRadius: 999,
        padding: "4px 12px",
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          background: active ? series.color : colors.borderSubtle,
        }}
      />
      {series.label}
      <span style={{ color: active ? series.color : colors.textDim, fontWeight: 700 }}>{total}</span>
    </button>
  );
}

function ChartTooltip({
  active,
  payload,
  label,
  visible,
}: {
  active?: boolean;
  payload?: { dataKey?: string | number; value?: number | null }[];
  label?: string;
  visible: SeriesKey[];
}) {
  if (!active || !payload?.length) return null;
  const point = (payload[0] as unknown as { payload?: DayPoint }).payload;
  return (
    <div
      style={{
        background: colors.bgCard,
        border: `1px solid ${colors.border}`,
        borderRadius: 4,
        padding: "8px 12px",
        fontFamily: "monospace",
        fontSize: 11,
      }}
    >
      <div style={{ color: colors.text, fontWeight: 700, marginBottom: 6 }}>
        {label ? fmtDay(label) : ""}
      </div>
      <div style={{ color: colors.textMuted, marginBottom: 6 }}>
        {point?.messages ?? 0} sent
      </div>
      {visible.map((key) => {
        const s = SERIES_BY_KEY[key];
        const v = point ? point[key] : null;
        return (
          <div key={key} style={{ display: "flex", gap: 10, justifyContent: "space-between" }}>
            <span style={{ color: s.color }}>{s.label}</span>
            <span style={{ color: colors.text }}>{v === null || v === undefined ? "not tracked" : v}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function EmailMetricsClient() {
  const isAdmin = useIsAdmin();
  const isMobile = useIsMobile();
  const [data, setData] = useState<MetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [days, setDays] = useState(15);
  const [domain, setDomain] = useState("");
  const [provider, setProvider] = useState("");
  const [visible, setVisible] = useState<SeriesKey[]>(DEFAULT_SERIES);
  // The response only lists domains that survived the current filters, so a
  // domain-filtered fetch would otherwise shrink the dropdown to the one option
  // already selected and strand the user there. Keep the last unfiltered list.
  const [allDomains, setAllDomains] = useState<{ domain: string; messages: number }[]>([]);

  // Gates the sessionStorage write-back until the saved state has been restored
  // — same `hydrated` pattern as /emails and RnsTab.
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const s = loadEmailMetricsState();
    if (_isValidDays(s.days)) setDays(s.days);
    if (typeof s.domain === "string") setDomain(s.domain);
    if (_isValidProvider(s.provider)) setProvider(s.provider);
    if (_isValidSeries(s.series) && s.series.length) setVisible(s.series);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveEmailMetricsState({ days, domain, provider, series: visible });
  }, [hydrated, days, domain, provider, visible]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ days: String(days) });
      if (domain) qs.set("domain", domain);
      if (provider) qs.set("provider", provider);
      const res = await fetch(`${API}/emails/metrics?${qs}`, { headers: adminHeaders() });
      if (res.status === 403) {
        setError("Admin token rejected — re-unlock with /?admin=<token>.");
        setData(null);
        return;
      }
      if (!res.ok) {
        setError(`Request failed (HTTP ${res.status}).`);
        return;
      }
      const json: MetricsResponse = await res.json();
      setData(json);
      if (!domain) setAllDomains(json.domains);
      setError(null);
    } catch {
      setError("Could not reach the email metrics endpoint.");
    } finally {
      setLoading(false);
    }
  }, [days, domain, provider]);

  useEffect(() => {
    if (!isAdmin || !hydrated) return;
    load();
  }, [isAdmin, hydrated, load]);

  const domainOptions = useMemo(() => {
    // A filtered-to domain that has since dropped out of the window would
    // otherwise vanish from its own dropdown mid-session.
    if (domain && !allDomains.some((d) => d.domain === domain)) {
      return [{ domain, messages: 0 }, ...allDomains];
    }
    return allDomains;
  }, [allDomains, domain]);

  if (!isAdmin) {
    return (
      <div
        style={{
          padding: "80px 24px",
          textAlign: "center",
          color: colors.textDim,
          fontFamily: "monospace",
          fontSize: 14,
        }}
      >
        Admins only. Unlock with <code>/?admin=&lt;token&gt;</code>.
      </div>
    );
  }

  const totals = data?.totals;
  const eng = data?.engagement;
  const openRate = eng && eng.delivered ? Math.round((1000 * eng.opened) / eng.delivered) / 10 : null;
  const clickRate = eng && eng.delivered ? Math.round((1000 * eng.clicked) / eng.delivered) / 10 : null;

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      <PageHeader
        title="Email metrics"
        subtitle={
          data
            ? `${fmtDay(data.start)} – ${fmtDay(data.end)} · UK days · cohort by send date`
            : "Daily delivery and engagement — see /emails for the per-message view"
        }
        right={
          <>
            <a
              href="/emails"
              style={{
                color: colors.textMuted,
                fontFamily: "monospace",
                fontSize: 11,
                textDecoration: "none",
              }}
              title="Per-message delivery monitor"
            >
              Emails →
            </a>
            <select value={domain} onChange={(e) => setDomain(e.target.value)} style={selectStyle}>
              <option value="">All domains</option>
              {domainOptions.map((d) => (
                <option key={d.domain} value={d.domain}>
                  {d.domain}
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
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} style={selectStyle}>
              {DAY_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  Last {d} days
                </option>
              ))}
            </select>
            <button onClick={() => load()} disabled={loading} style={{ ...controlBtn, opacity: loading ? 0.6 : 1 }}>
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

      <div style={card}>
        {/* ── Headline numbers + series toggles ──────────────────────────── */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: isMobile ? 20 : 40,
            alignItems: "flex-start",
            justifyContent: "space-between",
            marginBottom: 18,
          }}
        >
          <div style={{ display: "flex", gap: isMobile ? 20 : 40, flexWrap: "wrap" }}>
            <Headline label="Emails" value={totals ? String(totals.messages) : "—"} />
            <Headline
              label="Deliverability"
              value={pct(data?.rates.delivered)}
              color={
                data?.rates.delivered != null && data.rates.delivered < 97 ? colors.amber : colors.green
              }
              hint={totals ? `${totals.delivered} delivered` : undefined}
            />
            <Headline
              label="Open rate"
              value={pct(openRate)}
              color={colors.cyan}
              hint={eng ? `${eng.opened} of ${eng.delivered}` : undefined}
            />
            <Headline
              label="Click rate"
              value={pct(clickRate)}
              color={colors.purple}
              hint={eng ? `${eng.clicked} of ${eng.delivered}` : undefined}
            />
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
          {SERIES.map((s) => (
            <SeriesChip
              key={s.key}
              series={s}
              total={totals?.[s.key] ?? 0}
              active={visible.includes(s.key)}
              onClick={() =>
                setVisible((cur) =>
                  cur.includes(s.key) ? cur.filter((k) => k !== s.key) : [...cur, s.key],
                )
              }
            />
          ))}
        </div>

        {/* ── Chart ───────────────────────────────────────────────────────── */}
        {!data ? (
          <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 12, padding: "40px 0" }}>
            {loading ? "Loading…" : "No data."}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={isMobile ? 260 : 330}>
            {/* The left margin is load-bearing: the Y axis sits on the right, so
                without it the first day's tick label overflows the plot area and
                Recharts silently drops it — the window's opening day loses its
                label while still being drawn. */}
            <AreaChart data={data.points} margin={{ top: 10, right: 8, bottom: 0, left: 22 }}>
              <defs>
                {SERIES.map((s) => (
                  <linearGradient key={s.key} id={`fill-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={s.color} stopOpacity={0.28} />
                    <stop offset="100%" stopColor={s.color} stopOpacity={0} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid stroke={colors.borderSubtle} strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={fmtDay}
                tick={{ fontSize: 10, fill: colors.textDim, fontFamily: "monospace" }}
                axisLine={{ stroke: colors.border }}
                tickLine={false}
                minTickGap={isMobile ? 40 : 6}
              />
              <YAxis
                orientation="right"
                allowDecimals={false}
                width={38}
                tick={{ fontSize: 10, fill: colors.textDim, fontFamily: "monospace" }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                content={<ChartTooltip visible={visible} />}
                cursor={{ stroke: colors.border, strokeWidth: 1 }}
              />
              {/* Draw in SERIES order so the biggest line (delivered) is painted
                  first and the smaller ones sit on top of its fill. */}
              {SERIES.filter((s) => visible.includes(s.key)).map((s) => (
                <Area
                  key={s.key}
                  type="linear"
                  dataKey={s.key}
                  name={s.label}
                  stroke={s.color}
                  strokeWidth={1.8}
                  fill={`url(#fill-${s.key})`}
                  dot={false}
                  activeDot={{ r: 3, strokeWidth: 0 }}
                  isAnimationActive={false}
                  // Nulls are "not tracked", not zero — leave the gap visible.
                  connectNulls={false}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        )}

        {/* ── Footer legend ───────────────────────────────────────────────── */}
        {data && (
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 14,
              justifyContent: "space-between",
              alignItems: "baseline",
              marginTop: 14,
              paddingTop: 14,
              borderTop: `1px solid ${colors.borderSubtle}`,
              fontFamily: "monospace",
              fontSize: 11,
            }}
          >
            <div style={{ color: colors.textMuted }}>
              {domain || "All recipient domains"}{" "}
              <span style={{ color: colors.textDim }}>({data.totals.messages})</span>
            </div>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              {SERIES.filter((s) => visible.includes(s.key)).map((s) => (
                <span key={s.key} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <span
                    style={{ width: 7, height: 7, borderRadius: "50%", background: s.color }}
                  />
                  <span style={{ color: colors.textMuted }}>
                    {s.key === "opened"
                      ? pct(openRate)
                      : s.key === "clicked"
                        ? pct(clickRate)
                        : pct(data.rates[s.key])}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Caveats ─────────────────────────────────────────────────────────── */}
      <div style={{ ...card, fontFamily: "monospace", fontSize: 11, color: colors.textDim, lineHeight: 1.7 }}>
        {data && !data.engagement.fully_tracked && (
          <div style={{ color: colors.amber, marginBottom: 8 }}>
            ⚠ Opens and clicks were only subscribed on the webhook on{" "}
            {fmtDay(data.engagement.tracked_from)} — earlier days have no engagement rows at all and
            cannot be backfilled, so the lines break rather than sitting at zero. Open/click rates
            above cover the tracked days only.
          </div>
        )}
        Days are UK days. Every event is counted against the day its message was{" "}
        <strong style={{ color: colors.textMuted }}>sent</strong>, not the day the event arrived, so
        a column&rsquo;s opens are a share of that same column&rsquo;s delivered. Each series counts
        messages, not events — one message opened four times is one open. Deliverability, bounce,
        fail, complaint and delay rates are of everything sent; open and click rates are of what was
        delivered.
      </div>
    </div>
  );
}
