"use client";

import { Fragment, useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { API, adminHeaders } from "@/lib/api";
import { colors } from "@/lib/theme";
import { useIsAdmin } from "@/hooks/useAdmin";
import PageHeader from "@/components/layout/PageHeader";
import { companyHref } from "@/lib/company";

// ── Response shape (mirrors GET /api/gates in backend/gates.py) ────────────────
type GateState = "pass" | "block" | "n/a";
type GateMode = "armed" | "shadow";

interface GateInfo {
  name: string;
  description: string;
  mode: GateMode;
}
interface GateCell {
  state: GateState;
  reason: string | null;
  evidence: Record<string, unknown> | null;
  mode: GateMode;
}
type ReturnStatus = "matured" | "open" | "terminated";
interface RowReturns {
  gap: number | null;
  pct_1d: number | null;
  excess_1d: number | null;
  status_1d: ReturnStatus;
  pct_1w: number | null;
  excess_1w: number | null;
  status_1w: ReturnStatus;
}
interface MatrixRow {
  rns_id: number;
  symbol: string;
  company_name: string | null;
  headline: string;
  url: string;
  category: string | null;
  published_at: string;
  llm_score: number | null;
  llm_sentiment: string | null;
  in_universe: boolean;
  vet_verdict: "include" | "caution" | "exclude" | null;
  vet_rationale: string | null;
  public_flag_fail: string[];
  gates: Record<string, GateCell>;
  returns: RowReturns;
}
interface GateHeaderStats {
  mode: GateMode;
  n: number;
  fire_rate: number | null;
  amber_rate: number | null;
  dominant_na_reason: string | null;
  blocked_mean_excess_1d: number | null;
  passed_mean_excess_1d: number | null;
}
interface MatrixResponse {
  generated_at: string;
  window: string;
  cohort: string;
  show_all: boolean;
  gates: GateInfo[];
  floor_labels: Record<string, string>;
  header: Record<string, GateHeaderStats>;
  rows: MatrixRow[];
}

type Window_ = "latest" | "7d" | "30d";
type Cohort = "category" | "in_universe" | "all";

// Mirrors showcase.py's HIGH_IMPACT_MIN_LLM_SCORE — used to color the score
// cell red instead of duplicating "score" in the floor column.
const HIGH_IMPACT_MIN_LLM_SCORE = 75;

const GATE_LABEL: Record<string, string> = {
  sentiment: "sent",
  guidance: "guid",
  earnings_quality: "bank",
};

// Same palette as HighImpactRnsTab's VET_STYLE — keep in sync.
const VET_STYLE: Record<string, { color: string; bg: string }> = {
  include: { color: "#10b981", bg: "#0d2318" },
  caution: { color: "#f59e0b", bg: "#2a1c00" },
  exclude: { color: "#ef4444", bg: "#2a0d0d" },
};

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" });
}

function pct(x: number | null, digits = 1): string {
  return x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`;
}
function pctPoints(x: number | null): string {
  return x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}%`;
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

// ● block  ○ n/a  ▲ pass — same legend the plan doc specifies. Shadow gates
// render hollow/dimmed so a red light that didn't actually block never reads
// as one that did.
function GateMarker({ cell }: { cell: GateCell | undefined }) {
  if (!cell) return <span style={{ color: colors.textDim }}>·</span>;
  const shadow = cell.mode === "shadow";
  const base: CSSProperties = {
    fontSize: 13,
    opacity: shadow ? 0.45 : 1,
    cursor: cell.reason || cell.evidence ? "help" : "default",
  };
  const title = [
    cell.state,
    shadow ? "(shadow — did not block)" : null,
    cell.reason ? `reason: ${cell.reason}` : null,
  ]
    .filter(Boolean)
    .join(" ");
  if (cell.state === "block") return <span style={{ ...base, color: colors.red }} title={title}>{shadow ? "◐" : "●"}</span>;
  if (cell.state === "pass") return <span style={{ ...base, color: colors.green }} title={title}>▲</span>;
  return <span style={{ ...base, color: colors.textDim }} title={title}>○</span>;
}

// Display-only — the vet only ever runs on rows that already cleared every
// gate AND the public flag's own floors, so most rows show a dim dash here.
function VetPill({ verdict, rationale }: { verdict: MatrixRow["vet_verdict"]; rationale: string | null }) {
  if (!verdict) return <span style={{ color: colors.textDim }}>·</span>;
  const style = VET_STYLE[verdict];
  return (
    <span
      title={rationale ?? verdict}
      style={{
        fontSize: 9,
        fontWeight: 700,
        color: style.color,
        background: style.bg,
        border: `1px solid ${style.color}55`,
        borderRadius: 2,
        padding: "1px 5px",
        letterSpacing: 0.3,
        whiteSpace: "nowrap",
        textTransform: "capitalize",
        cursor: rationale ? "help" : "default",
      }}
    >
      {verdict}
    </span>
  );
}

// Which of the public flag's own eligibility floors (score/action/category/
// market-cap/leverage/margin/dedupe) this row fails — why it never reached
// the LLM vet even though no registry gate blocked it. Empty once vet_verdict
// is set (everything already cleared by definition).
function FloorCell({ fails, labels }: { fails: string[]; labels: Record<string, string> }) {
  if (!fails || fails.length === 0) return <span style={{ color: colors.textDim }}>·</span>;
  return (
    <span style={{ fontSize: 10 }}>
      {fails.map((f, i) => (
        <span key={f}>
          {i > 0 && <span style={{ color: colors.textDim }}>,</span>}
          <span style={{ color: colors.red, cursor: "help" }} title={labels[f] ?? f}>
            {f}
          </span>
        </span>
      ))}
    </span>
  );
}

function ReturnCell({ value, status }: { value: number | null; status: ReturnStatus }) {
  if (status !== "matured") {
    return <span style={{ color: colors.textDim }}>{status}</span>;
  }
  const color = value === null ? colors.textMuted : value >= 0 ? colors.green : colors.red;
  return <span style={{ color }}>{pctPoints(value)}</span>;
}

export default function GatesClient() {
  const isAdmin = useIsAdmin();
  const [data, setData] = useState<MatrixResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [win, setWin] = useState<Window_>("latest");
  const [cohort, setCohort] = useState<Cohort>("category");
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ window: win, cohort, show_all: String(showAll) });
      const res = await fetch(`${API}/gates?${qs}`, { headers: adminHeaders() });
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
      setError("Could not reach the gates endpoint.");
    } finally {
      setLoading(false);
    }
  }, [win, cohort, showAll]);

  useEffect(() => {
    if (!isAdmin) return;
    load();
  }, [isAdmin, load]);

  // Recent day first, then score descending within each day.
  const sortedRows = useMemo(() => {
    if (!data) return [];
    return [...data.rows].sort((a, b) => {
      const dayA = a.published_at?.slice(0, 10) ?? "";
      const dayB = b.published_at?.slice(0, 10) ?? "";
      if (dayA !== dayB) return dayA < dayB ? 1 : -1;
      return (b.llm_score ?? -Infinity) - (a.llm_score ?? -Infinity);
    });
  }, [data]);

  if (!isAdmin) {
    return (
      <div style={{ padding: "80px 24px", textAlign: "center", color: colors.textDim, fontFamily: "monospace", fontSize: 14 }}>
        Admins only. Unlock with <code>/?admin=&lt;token&gt;</code>.
      </div>
    );
  }

  const gateNames = data?.gates.map((g) => g.name) ?? [];

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <PageHeader
        title="Gate calibration"
        subtitle={
          data
            ? `${data.rows.length} rows · window=${data.window} · cohort=${data.cohort}`
            : "Traffic-light view of the RNS High Impact gate registry"
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

      {/* ── Controls ──────────────────────────────────────────────────────── */}
      <div style={{ ...card, display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center" }}>
        <ControlGroup label="window">
          {(["latest", "7d", "30d"] as Window_[]).map((w) => (
            <button key={w} style={controlBtn(win === w)} onClick={() => setWin(w)}>{w}</button>
          ))}
        </ControlGroup>
        <ControlGroup label="cohort">
          {([
            ["category", "in-universe + category"],
            ["in_universe", "in-universe"],
            ["all", "all Tier A/B"],
          ] as [Cohort, string][]).map(([c, label]) => (
            <button key={c} style={controlBtn(cohort === c)} onClick={() => setCohort(c)}>{label}</button>
          ))}
        </ControlGroup>
        <ControlGroup label="rows">
          <button style={controlBtn(!showAll)} onClick={() => setShowAll(false)}>adjudicated only</button>
          <button style={controlBtn(showAll)} onClick={() => setShowAll(true)}>show all</button>
        </ControlGroup>
      </div>

      {/* ── Per-gate header stats ────────────────────────────────────────── */}
      {data && (
        <div style={{ ...card, display: "flex", gap: 14, flexWrap: "wrap" }}>
          {data.gates.map((g) => {
            const h = data.header[g.name];
            const harm =
              h?.blocked_mean_excess_1d !== null &&
              h?.blocked_mean_excess_1d !== undefined &&
              h?.passed_mean_excess_1d !== null &&
              h?.passed_mean_excess_1d !== undefined &&
              h.blocked_mean_excess_1d > h.passed_mean_excess_1d;
            return (
              <div
                key={g.name}
                style={{
                  flex: "1 1 220px",
                  minWidth: 220,
                  border: `1px solid ${harm ? colors.red : colors.borderSubtle}`,
                  borderRadius: 4,
                  padding: 12,
                  fontFamily: "monospace",
                  fontSize: 11,
                }}
                title={g.description}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <span style={{ color: colors.text, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
                    {g.name}
                  </span>
                  <span style={{ color: g.mode === "shadow" ? colors.amber : colors.textDim, fontSize: 9 }}>
                    {g.mode}
                  </span>
                </div>
                <div style={{ color: colors.textMuted, marginTop: 8 }}>
                  n={h?.n ?? 0} · fire {pct(h?.fire_rate ?? null)} · amber {pct(h?.amber_rate ?? null)}
                </div>
                {h?.dominant_na_reason && (
                  <div style={{ color: colors.textDim, marginTop: 2 }}>na: {h.dominant_na_reason}</div>
                )}
                {(h?.blocked_mean_excess_1d !== null || h?.passed_mean_excess_1d !== null) && (
                  <div style={{ color: harm ? colors.red : colors.textMuted, marginTop: 6 }}>
                    1d excess — blocked {pctPoints(h?.blocked_mean_excess_1d ?? null)} vs passed{" "}
                    {pctPoints(h?.passed_mean_excess_1d ?? null)}
                    {harm && " ⚠ blocked outperforms passed"}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Matrix ────────────────────────────────────────────────────────── */}
      <div style={{ ...card, overflowX: "auto" }}>
        <h2 style={sectionTitle}>Matrix</h2>
        {!data || data.rows.length === 0 ? (
          <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 12 }}>
            {loading ? "Loading…" : "No rows for this window/cohort."}
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "monospace", fontSize: 12 }}>
            <thead>
              <tr>
                <Th align="left">date</Th>
                <Th align="left">symbol</Th>
                <Th align="left">headline</Th>
                <Th align="right">score</Th>
                {gateNames.map((n) => (
                  <Th key={n} align="center" title={data.gates.find((g) => g.name === n)?.description}>
                    {GATE_LABEL[n] ?? n}
                  </Th>
                ))}
                <Th align="center" title="AI vet verdict — only set for rows that already cleared every gate and the public High Impact flag's own floors">
                  vet
                </Th>
                <Th align="left" title="Which of the public High Impact flag's own eligibility floors (score/action/category/market-cap/leverage/margin/dedupe) this row fails — why it never reached the vet even though no gate blocked it">
                  floor
                </Th>
                <Th align="right">gap</Th>
                <Th align="right">1d</Th>
                <Th align="right">1w</Th>
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row, i) => {
                const prevDay = i > 0 ? sortedRows[i - 1].published_at?.slice(0, 10) : null;
                const dayBoundary = i > 0 && row.published_at?.slice(0, 10) !== prevDay;
                return (
                <Fragment key={row.rns_id}>
                  {dayBoundary && (
                    // A dedicated spacer row, not a border/box-shadow on the <tr> —
                    // both get eaten by borderCollapse's conflict resolution against
                    // the adjacent row's own border, so neither ever rendered.
                    <tr>
                      <td colSpan={9 + gateNames.length} style={{ padding: 0 }}>
                        <div style={{ height: 2, background: colors.border }} />
                      </td>
                    </tr>
                  )}
                  <tr style={{ borderBottom: `1px solid ${colors.borderSubtle}` }}>
                  <Td>
                    <span style={{ color: colors.textMuted }}>{fmtDate(row.published_at)}</span>
                  </Td>
                  <Td>
                    <a
                      href={companyHref(row.symbol)}
                      style={{ color: colors.text, fontWeight: 700, textDecoration: "none" }}
                    >
                      {row.symbol}
                    </a>
                    {!row.in_universe && (
                      <span style={{ color: colors.textDim, fontSize: 10, marginLeft: 4 }} title="out of universe">
                        oou
                      </span>
                    )}
                  </Td>
                  <Td>
                    <a
                      href={row.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: colors.textMuted, textDecoration: "none" }}
                    >
                      {row.headline}
                    </a>
                    <span style={{ color: colors.textDim, fontSize: 10, marginLeft: 6 }}>{row.category ?? ""}</span>
                  </Td>
                  <Td align="right">
                    <span
                      style={{
                        color:
                          row.llm_score !== null && row.llm_score < HIGH_IMPACT_MIN_LLM_SCORE
                            ? colors.red
                            : colors.text,
                      }}
                      title={
                        row.llm_score !== null && row.llm_score < HIGH_IMPACT_MIN_LLM_SCORE
                          ? `below the flag threshold (${HIGH_IMPACT_MIN_LLM_SCORE})`
                          : undefined
                      }
                    >
                      {row.llm_score ?? "—"}
                    </span>
                  </Td>
                  {gateNames.map((n) => (
                    <Td key={n} align="center">
                      <GateMarker cell={row.gates[n]} />
                    </Td>
                  ))}
                  <Td align="center">
                    <VetPill verdict={row.vet_verdict} rationale={row.vet_rationale} />
                  </Td>
                  <Td>
                    <FloorCell
                      fails={row.public_flag_fail.filter((f) => f !== "score")}
                      labels={data.floor_labels}
                    />
                  </Td>
                  <Td align="right">
                    <span style={{ color: colors.textMuted }}>
                      {row.returns.gap === null ? "—" : pctPoints(row.returns.gap)}
                    </span>
                  </Td>
                  <Td align="right">
                    <ReturnCell value={row.returns.excess_1d} status={row.returns.status_1d} />
                  </Td>
                  <Td align="right">
                    <ReturnCell value={row.returns.excess_1w} status={row.returns.status_1w} />
                  </Td>
                  </tr>
                </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
        <div style={{ marginTop: 14, color: colors.textDim, fontSize: 11, fontFamily: "monospace" }}>
          ● block &nbsp; ○ n/a &nbsp; ▲ pass &nbsp; ◐ block (shadow — did not block) &nbsp; oou = out of universe &nbsp; vet = AI vet verdict (display-only, not a gate) &nbsp; floor = public flag eligibility floor(s) failed (hover for detail)
        </div>
      </div>
    </div>
  );
}

function ControlGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 10, textTransform: "uppercase", marginRight: 4 }}>
        {label}
      </span>
      {children}
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
