"use client";
import { useState, useEffect } from "react";
import { API } from "@/lib/api";
import MetricCard from "./MetricCard";
import InfoDot from "@/components/InfoDot";

interface ShortData {
  symbol: string;
  current_pct: number | null;
  change_1m: number | null;
}

export default function ShortInterestMetric({ symbol }: { symbol: string }) {
  const [data, setData] = useState<ShortData | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API}/shorts?symbol=${encodeURIComponent(symbol)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [symbol]);

  if (!data || data.current_pct === null) {
    return null;
  }

  return (
    <MetricCard
      label={
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          Short Interest
          <InfoDot
            text={"FCA-disclosed Aggregate Net Short Position — the sum of all short positions ≥0.2% of issued share capital, published daily with a ~2 working-day lag."}
          />
        </span>
      }
      value={
        <>
          {data.current_pct.toFixed(2)}%
          {data.change_1m !== null && (
            <span style={{ fontSize: 11, fontWeight: 400, marginLeft: 5, color: data.change_1m > 0 ? "#ef4444" : data.change_1m < 0 ? "#4ade80" : "#666" }}>
              {data.change_1m > 0 ? "+" : ""}{data.change_1m.toFixed(1)}pp
            </span>
          )}
        </>
      }
      color={data.current_pct >= 5 ? "#ef4444" : undefined}
    />
  );
}
