"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import LogoBadge from "@/components/company/LogoBadge";
import { companyHref } from "@/lib/company";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { API } from "@/lib/api";
import { S, colors } from "@/lib/theme";
import type { CalendarCompany, CalendarDay, ResultsCalendar } from "@/lib/resultsCalendar";

// Event type -> accent. Deliberately only three colours: the distinction that
// matters to a reader is "results" vs "just an update", not which flavour of
// quarterly it is.
const EVENT_COLOUR: Record<string, string> = {
  finals: colors.accent,
  interims: colors.blue,
  q1: colors.indigo,
  q2: colors.indigo,
  q3: colors.indigo,
  q4: colors.indigo,
  trading_update: colors.textFaint,
};

// company_metadata names carry legal and share-class tails that add nothing in a
// tile this size: "Clarkson PLC", "Allianz Technology Trust Ord", and par-value
// forms like "WINVIA ENTERTAINMENT ORD 0.01". Everything from the first tail
// token onwards goes — matching how the backend indexes these names — so the
// trailing par value cannot survive on its own.
function shortName(name: string): string {
  return name
    .replace(/\s+(PLC|LTD|LIMITED|ORD|ORDINARY|SHS|NPV|CDI|DI)\b.*$/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

function formatRange(startISO: string, endISO: string): string {
  const start = new Date(`${startISO}T00:00:00Z`);
  const end = new Date(`${endISO}T00:00:00Z`);
  const opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "long", timeZone: "UTC" };
  const sameMonth = start.getUTCMonth() === end.getUTCMonth();
  const left = start.toLocaleDateString("en-GB", sameMonth ? { day: "numeric", timeZone: "UTC" } : opts);
  return `${left} – ${end.toLocaleDateString("en-GB", opts)} ${end.getUTCFullYear()}`;
}

function CompanyTile({ c, isToday }: { c: CalendarCompany; isToday: boolean }) {
  return (
    <Link
      href={companyHref(c.symbol)}
      title={`${c.name} — ${c.event_label}`}
      style={{
        display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
        borderRadius: 10, textDecoration: "none",
        background: colors.bgCard,
        border: `1px solid ${isToday ? colors.border : colors.borderSubtle}`,
        borderLeft: `3px solid ${EVENT_COLOUR[c.event_type] ?? colors.textFaint}`,
      }}
    >
      {/* White plate behind the logo: logo.dev serves logos drawn for light
          backgrounds, and a dark tile swallows the dark-inked ones entirely. */}
      <LogoBadge symbol={c.symbol} size={34} fit="contain" background="#fff" />
      <span style={{ minWidth: 0 }}>
        <span style={{
          display: "block", color: colors.white, fontSize: 12, fontWeight: 600,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {shortName(c.name)}
        </span>
        <span style={{ display: "block", color: colors.textFaint, fontSize: 10.5 }}>
          {c.symbol.replace(".L", "")} · {c.event_label}
        </span>
      </span>
    </Link>
  );
}

function DayColumn({ day, todayISO, isMobile }: { day: CalendarDay; todayISO: string; isMobile: boolean }) {
  const isToday = day.date === todayISO;
  const date = new Date(`${day.date}T00:00:00Z`);
  // An empty weekday keeps its column rather than being dropped — a Friday with
  // nothing on it is information, and collapsing it would silently reshape the
  // grid from week to week.
  return (
    <div style={{ flex: 1, minWidth: isMobile ? "100%" : 0, display: "flex", flexDirection: "column" }}>
      <div style={{
        padding: "8px 10px", borderRadius: "10px 10px 0 0",
        background: isToday ? colors.accentBg : colors.bgCardAlt,
        borderBottom: `2px solid ${isToday ? colors.accent : colors.border}`,
      }}>
        <div style={{ color: isToday ? colors.accent : colors.white, fontSize: 13, fontWeight: 700 }}>
          {day.weekday}
        </div>
        <div style={{ color: colors.textFaint, fontSize: 11 }}>
          {date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })}
          {day.companies.length > 0 && ` · ${day.companies.length}`}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "8px 4px" }}>
        {day.companies.length === 0 ? (
          <div style={{ color: colors.textDim, fontSize: 11, padding: "12px 8px", textAlign: "center" }}>
            Nothing scheduled
          </div>
        ) : (
          day.companies.map((c) => (
            <CompanyTile key={`${c.symbol}-${c.event_type}`} c={c} isToday={isToday} />
          ))
        )}
      </div>
    </div>
  );
}

export default function ResultsCalendarClient({
  initialData,
  initialWeek,
}: {
  initialData: ResultsCalendar | null;
  initialWeek?: string;
}) {
  const router = useRouter();
  const isMobile = useIsMobile();
  const [data, setData] = useState<ResultsCalendar | null>(initialData);
  const [loading, setLoading] = useState(false);
  const [week, setWeek] = useState<string | undefined>(initialWeek);

  // Only fetches when SSR handed us nothing (API unreachable) or the reader has
  // paged to another week; the first paint normally uses the server's data.
  useEffect(() => {
    if (initialData && week === initialWeek) return;
    setLoading(true);
    fetch(`${API}/results-calendar${week ? `?week=${encodeURIComponent(week)}` : ""}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d?.days && setData(d))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [week, initialData, initialWeek]);

  const go = (target: string) => {
    setWeek(target);
    // Keep the URL shareable without a full navigation.
    router.replace(`/results-calendar?week=${target}`, { scroll: false });
  };

  if (!data) {
    return <div style={S.loading}>{loading ? "Loading results calendar…" : "Results calendar unavailable."}</div>;
  }

  const todayISO = new Date().toISOString().slice(0, 10);

  return (
    <div style={{ padding: isMobile ? "12px 10px 40px" : "16px 20px 48px", maxWidth: 1500, margin: "0 auto" }}>
      <div style={{
        display: "flex", flexWrap: "wrap", alignItems: "baseline",
        justifyContent: "space-between", gap: 10, marginBottom: 4,
      }}>
        <h1 style={{ margin: 0, color: colors.white, fontSize: isMobile ? 20 : 26, fontWeight: 700 }}>
          Results Calendar
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button onClick={() => go(data.prev_week)} style={S.navBtn} aria-label="Previous week">←</button>
          <span style={{ color: colors.text, fontSize: 13, fontWeight: 600, minWidth: isMobile ? 0 : 190, textAlign: "center" }}>
            {formatRange(data.week_start, data.week_end)}
          </span>
          <button onClick={() => go(data.next_week)} style={S.navBtn} aria-label="Next week">→</button>
        </div>
      </div>

      <p style={{ color: colors.textMuted, fontSize: 13, margin: "0 0 14px", maxWidth: 760 }}>
        {data.is_current_week ? "This week" : "The week"} {data.total} London-listed{" "}
        {data.total === 1 ? "company reports" : "companies report"} — full-year and interim
        results, quarterlies and trading updates.
      </p>

      <div style={{
        display: "flex", flexDirection: isMobile ? "column" : "row",
        gap: isMobile ? 14 : 8, alignItems: "stretch",
        opacity: loading ? 0.55 : 1, transition: "opacity .15s",
      }}>
        {data.days.map((day) => (
          <DayColumn key={day.date} day={day} todayISO={todayISO} isMobile={isMobile} />
        ))}
      </div>

      <div style={{ marginTop: 18, color: colors.textDim, fontSize: 11.5, lineHeight: 1.6 }}>
        <div>
          Scheduled dates, not confirmations — companies do move them, so the calendar is
          refreshed daily.
        </div>
        {data.updated_at && (
          <div>Updated {new Date(data.updated_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}.</div>
        )}
      </div>
    </div>
  );
}
