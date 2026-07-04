"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { S } from "@/lib/theme";
import PageHeader from "@/components/layout/PageHeader";
import { SCREENER_COLUMN_GROUPS, DEFAULT_SCREENER_COLUMN_PREFS } from "@/lib/screenerColumns";
import { loadScreenerColumns, saveScreenerColumns, type ScreenerColumnPrefs } from "@/lib/storage";

export default function ScreenerColumnSettings() {
  const [prefs, setPrefs] = useState<ScreenerColumnPrefs>(DEFAULT_SCREENER_COLUMN_PREFS);
  // Gate the row list until localStorage has been read, so the initial default
  // paint can't briefly disagree with the client's saved prefs.
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setPrefs(loadScreenerColumns());
    setHydrated(true);
  }, []);

  // Persist immediately on every toggle — the app has no Save button anywhere,
  // preferences write through as they change (chart prefs, filters, watchlists).
  const toggle = (key: string) => {
    setPrefs((p) => {
      const next = { ...p, [key]: !(p[key] ?? DEFAULT_SCREENER_COLUMN_PREFS[key]) };
      saveScreenerColumns(next);
      return next;
    });
  };

  const resetDefaults = () => {
    const next = { ...DEFAULT_SCREENER_COLUMN_PREFS };
    setPrefs(next);
    saveScreenerColumns(next);
  };

  return (
    <div>
      <PageHeader
        title="Screener Settings"
        subtitle="Choose which fundamental columns appear in the Screener's Fundamentals table."
        right={
          <>
            <button
              onClick={resetDefaults}
              style={{ ...S.select, cursor: "pointer", color: "#f97316", borderColor: "#3a2a1a" }}
            >
              ↺ Reset to defaults
            </button>
            <Link
              href="/screener"
              style={{ ...S.select, cursor: "pointer", textDecoration: "none", background: "#f97316", color: "#000", borderColor: "#f97316", fontWeight: 700 }}
            >
              Done →
            </Link>
          </>
        }
      />
      <div style={S.card}>
        <div style={S.cardTitle}>Fundamental Columns</div>
        <div style={{ color: "#64748b", fontSize: 11, marginBottom: 12, fontFamily: "monospace", lineHeight: 1.6 }}>
          Symbol, Name, Sector, Index, and the four composite scores
          (Mom&nbsp;/&nbsp;Qual&nbsp;/&nbsp;Value&nbsp;/&nbsp;Risk) are always shown.
        </div>
        {hydrated &&
          SCREENER_COLUMN_GROUPS.map(({ group, columns }) => (
            <div key={group} style={{ marginBottom: 4 }}>
              <div
                style={{
                  marginTop: 16,
                  marginBottom: 4,
                  fontFamily: "monospace",
                  fontSize: 10,
                  fontWeight: 700,
                  color: "#64748b",
                  textTransform: "uppercase",
                  letterSpacing: 1.5,
                }}
              >
                {group}
              </div>
              {columns.map((c) => {
                const on = prefs[c.key] ?? c.defaultEnabled;
                return (
                  <div
                    key={c.key}
                    onClick={() => toggle(c.key)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "10px 4px",
                      borderBottom: "1px solid #1f1f1f",
                      cursor: "pointer",
                      fontFamily: "monospace",
                      fontSize: 13,
                    }}
                  >
                    <span style={{ width: 14, textAlign: "center", color: "#f97316" }}>{on ? "✓" : ""}</span>
                    <span style={{ width: 90, color: on ? "#f1f5f9" : "#666" }}>{c.label}</span>
                    <span style={{ color: "#64748b", fontSize: 11 }}>{c.title}</span>
                  </div>
                );
              })}
            </div>
          ))}
      </div>
    </div>
  );
}
