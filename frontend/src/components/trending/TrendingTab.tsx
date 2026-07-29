"use client";

import { useState, useEffect } from "react";
import { API } from "@/lib/api";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { S } from "@/lib/theme";
import TrendingList from "./TrendingList";
import TrendingProfile from "./TrendingProfile";
import NewsTab from "@/components/NewsTab";
import PageHeader from "@/components/layout/PageHeader";
import type { Trending } from "@/lib/trending";

interface Props {
  onSelect: (symbol: string) => void;
  // Server-rendered lists from the /trending page. Omitted by any other caller,
  // which keeps the browser-fetch path below as the default.
  initialData?: Trending | null;
}

// The stock the desktop profile panel opens on: top riser, else top faller.
const firstSymbol = (d: Trending | null | undefined): string | null =>
  d?.risers?.[0]?.symbol || d?.fallers?.[0]?.symbol || null;

export default function TrendingTab({ onSelect, initialData }: Props) {
  const [data, setData] = useState<Trending | null>(initialData ?? null);
  const [loading, setLoading] = useState(!initialData);
  // Seeded here, not just in the fetch below — with SSR data the fetch never
  // runs, and an unseeded `sel` leaves the desktop profile panel empty.
  const [sel, setSel] = useState<string | null>(() => firstSymbol(initialData));
  const isMobile = useIsMobile();

  useEffect(() => {
    // SSR gave us the lists already — don't re-fetch what's on screen.
    if (initialData) return;
    let cancelled = false;
    setLoading(true);
    fetch(`${API}/trending`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setSel((cur) => cur || firstSymbol(d));
        setLoading(false);
      })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [initialData]);

  if (loading) return <div style={S.loading}>Loading trending stocks…</div>;

  const risers = data?.risers || [];
  const fallers = data?.fallers || [];
  const colH = isMobile ? "auto" : "calc(100vh - 200px)";
  const listH = isMobile ? "auto" : colH;
  // On mobile, tapping a stock jumps straight to its company page; on desktop it
  // selects the stock to populate the profile + news panels.
  const handleSelect = isMobile ? onSelect : setSel;
  // No persistent selection on mobile — taps navigate away, so nothing stays "active".
  const listSel = isMobile ? null : sel;

  return (
    <div>
      <PageHeader
        title={<>Trending <span style={{ color: "#64748b" }}>— Risers and Fallers</span></>}
        subtitle="Stocks on a run of 3 or more consecutive up or down days, ranked by streak length."
      />
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "minmax(210px,1fr) minmax(210px,1fr) minmax(360px,1.5fr)", gap: 16, alignItems: "start" }}>
        <TrendingList title="Risers" accent="#10b981" up items={risers} selected={listSel} onSelect={handleSelect} height={listH} />
        <TrendingList title="Fallers" accent="#ef4444" up={false} items={fallers} selected={listSel} onSelect={handleSelect} height={listH} />
        {!isMobile && (
          <div>
            {sel ? (
              <div style={{ ...S.card, height: colH, overflowY: "auto", minHeight: 0 }}>
                <TrendingProfile symbol={sel} onOpenFull={onSelect} />
              </div>
            ) : (
              <div style={{ ...S.card, ...S.loading }}>Select a stock to see its profile and news.</div>
            )}
          </div>
        )}
      </div>

      {!isMobile && sel && (
        <div style={{ ...S.card, marginTop: 16 }}>
          <h2 style={{ margin: "0 0 16px", fontFamily: "DM Serif Display,serif", fontSize: 20, color: "#f1f5f9" }}>
            News <span style={{ color: "#64748b", fontSize: 15 }}>— {sel.replace(".L", "")}</span>
          </h2>
          <NewsTab symbol={sel} split />
        </div>
      )}
    </div>
  );
}
