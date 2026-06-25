"use client";

import { useState, useEffect, useRef } from "react";
import {
  ComposedChart,
  Line,
  Area,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { API } from "@/lib/api";
import { currSym, fmtUKDate } from "@/lib/format";
import { loadChartPrefs, saveChartPrefs } from "@/lib/storage";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { S } from "@/lib/theme";

interface Props {
  symbol: string;
  fcur?: string;
  simple?: boolean;
}

interface PriceRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export default function PriceChart({ symbol, fcur = "GBP", simple = false }: Props) {
  const [priceData, setPriceData] = useState<PriceRow[]>([]);
  const [liveQuote, setLiveQuote] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [prefs] = useState(loadChartPrefs);
  const [range, setRange] = useState(prefs.range);
  const [showMA20, setShowMA20] = useState(() => {
    // Same as candles: keep the mobile chart clean by defaulting MA20 off.
    if (typeof window !== "undefined" && window.matchMedia("(max-width: 943px)").matches) return false;
    return prefs.showMA20;
  });
  const [showMA50, setShowMA50] = useState(prefs.showMA50);
  const [showVolume, setShowVolume] = useState(prefs.showVolume);
  const [showCandles, setShowCandles] = useState(() => {
    // On phones, default to a cleaner line chart even when candles are the saved
    // (desktop) preference. The user can still toggle candles on per session.
    if (typeof window !== "undefined" && window.matchMedia("(max-width: 943px)").matches) return false;
    return prefs.showCandles;
  });
  const [showMACD, setShowMACD] = useState(prefs.showMACD);
  const [showRSI, setShowRSI] = useState(prefs.showRSI);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const isMobile = useIsMobile();

  // On touch, recharts keeps the tooltip "active" across an orientation change
  // (no mouseleave fires), so after rotating it lingers at the old data point —
  // a different on-screen spot once the chart has re-laid-out. Bumping this key
  // remounts the chart subtree on orientation flip, clearing recharts' internal
  // active-tooltip state so no stale box is shown.
  const [chartKey, setChartKey] = useState(0);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(orientation: portrait)");
    const onChange = () => setChartKey((k) => k + 1);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // In `simple` mode (Trending) force a plain line with volume only — no candles,
  // MAs, MACD or RSI. These derive from state without mutating it, so the persisted
  // prefs stay intact for the full company view.
  const sCandles = simple ? false : showCandles;
  const sMA20 = simple ? false : showMA20;
  const sMA50 = simple ? false : showMA50;
  const sVol = simple ? true : showVolume;
  const sMACD = simple ? false : showMACD;
  const sRSI = simple ? false : showRSI;

  // Reserved width for the Y axis (price labels). The candle overlay mirrors this
  // as its plotLeft, so keep them sourced from one constant. `simple` (Trending)
  // uses a tighter layout; the full company view keeps the original width.
  const Y_AXIS_W = simple ? 44 : 64;

  // Skip the mount run so the mobile line-chart default (above) doesn't overwrite
  // the user's saved candle preference — only actual toggles persist.
  const firstSave = useRef(true);
  useEffect(() => {
    if (firstSave.current) { firstSave.current = false; return; }
    saveChartPrefs({ range, showMA20, showMA50, showVolume, showCandles, showMACD, showRSI });
  }, [range, showMA20, showMA50, showVolume, showCandles, showMACD, showRSI]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setContainerWidth(el.getBoundingClientRect().width);
    const ro = new ResizeObserver(([entry]) => setContainerWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [loading]);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    fetch(`${API}/prices/${symbol}`)
      .then((r) => r.json())
      .then((data) => {
        setPriceData(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [symbol]);

  useEffect(() => {
    if (!symbol) return;
    setLiveQuote(null);
    let cancelled = false;
    const fetchQuote = () => {
      fetch(`${API}/quotes?symbols=${encodeURIComponent(symbol)}`)
        .then((r) => r.json())
        .then((d) => {
          if (cancelled || !d || typeof d !== "object") return;
          const q = d[symbol];
          setLiveQuote(typeof q === "number" ? q : null);
        })
        .catch(() => {});
    };
    fetchQuote();
    const id = setInterval(fetchQuote, 60000);
    return () => { cancelled = true; clearInterval(id); };
  }, [symbol]);

  const computeMA = (data: PriceRow[], n: number) =>
    data.map((_, i) => {
      if (i < n - 1) return null;
      const slice = data.slice(i - n + 1, i + 1);
      return Math.round((slice.reduce((s, d) => s + d.close, 0) / n) * 100) / 100;
    });

  const ma20 = computeMA(priceData, 20);
  const ma50 = computeMA(priceData, 50);

  const emaSeries = (vals: (number | null)[], period: number) => {
    const k = 2 / (period + 1);
    let prev: number | null = null;
    return vals.map((v) => {
      if (v == null) return null;
      prev = prev == null ? v : v * k + prev * (1 - k);
      return prev;
    });
  };

  const closes = priceData.map((d) => d.close);
  const ema12 = emaSeries(closes, 12);
  const ema26 = emaSeries(closes, 26);
  const macdArr = closes.map((_, i) =>
    ema12[i] != null && ema26[i] != null ? ema12[i]! - ema26[i]! : null,
  );
  const signalArr = emaSeries(macdArr, 9);
  const histArr = macdArr.map((v, i) =>
    v != null && signalArr[i] != null ? v - signalArr[i]! : null,
  );

  const computeRSI = (period = 14) => {
    const rsi: (number | null)[] = new Array(closes.length).fill(null);
    let avgGain = 0, avgLoss = 0;
    for (let i = 1; i < closes.length; i++) {
      const ch = closes[i] - closes[i - 1];
      const gain = ch > 0 ? ch : 0;
      const loss = ch < 0 ? -ch : 0;
      if (i <= period) {
        avgGain += gain; avgLoss += loss;
        if (i === period) {
          avgGain /= period; avgLoss /= period;
          rsi[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
        }
      } else {
        avgGain = (avgGain * (period - 1) + gain) / period;
        avgLoss = (avgLoss * (period - 1) + loss) / period;
        rsi[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
      }
    }
    return rsi;
  };
  const rsiArr = computeRSI(14);

  const RANGE_DAYS: Record<string, number> = { "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "3Y": 1095, "5Y": 1825 };
  const cutoffDays = RANGE_DAYS[range];
  const latest = priceData.length ? new Date(priceData[priceData.length - 1].date) : new Date();
  const cutoff = cutoffDays ? new Date(latest.getTime() - cutoffDays * 86400000) : null;

  const chartData = priceData
    .map((d, i) => ({
      date: d.date,
      open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume,
      ma20: ma20[i], ma50: ma50[i],
      macd: macdArr[i], signal: signalArr[i], hist: histArr[i], rsi: rsiArr[i],
    }))
    .filter((d) => !cutoff || new Date(d.date) >= cutoff);

  const tickFormatter = (dateStr: string) => {
    const d = new Date(dateStr);
    const mon = d.toLocaleString("default", { month: "short" });
    if (["3Y", "5Y"].includes(range)) return `${mon} ${d.getFullYear()}`;
    if (["1M", "3M"].includes(range)) return `${d.getDate()} ${mon}`;
    return mon;
  };

  const labelFormatter = (dateStr: string) => fmtUKDate(dateStr);

  const fmtAxisPrice = (v: number) =>
    v == null ? "" : Number(v).toLocaleString("en-GB", { maximumFractionDigits: 2 });

  const fmtVolume = (v: number | null) => {
    if (v == null) return "—";
    if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return String(v);
  };

  const TICK_COUNT = 7;
  const axisTicks = chartData.length <= TICK_COUNT
    ? chartData.map((d) => d.date)
    : Array.from({ length: TICK_COUNT }, (_, i) =>
        chartData[Math.round((i * (chartData.length - 1)) / (TICK_COUNT - 1))].date,
      );

  const UP = "#22c55e", DOWN = "#ef4444";

  const priceDomain = (() => {
    if (!sCandles) return ["auto", "auto"] as ["auto", "auto"];
    const lows = chartData.map((d) => d.low).filter((v) => v != null) as number[];
    const highs = chartData.map((d) => d.high).filter((v) => v != null) as number[];
    if (!lows.length || !highs.length) return ["auto", "auto"] as ["auto", "auto"];
    const lo = Math.min(...lows), hi = Math.max(...highs);
    const span = hi - lo || hi || 1;
    const mag = Math.pow(10, Math.floor(Math.log10(span / 5)));
    const norm = span / 5 / mag;
    const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const domLo = Math.floor((lo - span * 0.05) / step) * step;
    const domHi = Math.ceil((hi + span * 0.05) / step) * step;
    return [Math.max(0, domLo), domHi] as [number, number];
  })();

  // Candle overlay: computed as an absolutely-positioned SVG so we own the coordinate
  // math entirely and don't depend on recharts' Customized/scale internals.
  const PRICE_H = 380;
  // Top margin on the price chart. When the price is overlaid inside the plot
  // (Trending `simple` mode, and the full view on mobile) we add headroom; the
  // desktop company view keeps its original 5px.
  const overlayPrice = simple || isMobile;
  const PRICE_TOP = overlayPrice ? 36 : 5;
  const candleOverlay = (() => {
    if (!sCandles || containerWidth <= 0 || !chartData.length) return null;

    // Layout constants — mirror the chart's margin + axis exactly
    const plotLeft = Y_AXIS_W;                         // YAxis width, margin.left=0
    const plotTop = PRICE_TOP;                          // margin.top
    const plotW = containerWidth - plotLeft - 10;      // margin.right=10
    const xAxisH = sMACD || sRSI ? 4 : 30;
    const plotH = PRICE_H - plotTop - 5 - xAxisH;     // total - top - bottom - xAxis

    const n = chartData.length;
    const step = plotW / n;
    const bodyW = Math.max(1, step * 0.6);
    const toX = (i: number) => plotLeft + (i + 0.5) * step;

    // Compute the Y domain — prefer priceDomain (already matched to YAxis ticks).
    // Fall back to raw OHLC min/max; candles won't render if OHLC is absent but
    // the diagnostic square still will, confirming the overlay position is correct.
    let dLo: number | null = null;
    let dHi: number | null = null;
    if (Array.isArray(priceDomain) && typeof priceDomain[0] === "number") {
      [dLo, dHi] = priceDomain as [number, number];
    } else {
      const ls = chartData.map((d) => d.low).filter((v): v is number => v != null);
      const hs = chartData.map((d) => d.high).filter((v): v is number => v != null);
      if (ls.length && hs.length) { dLo = Math.min(...ls); dHi = Math.max(...hs); }
    }
    const domainOk = dLo != null && dHi != null && (dHi as number) > (dLo as number);
    const toY = (v: number) =>
      domainOk ? plotTop + plotH - ((v - dLo!) / (dHi! - dLo!)) * plotH : 0;

    return (
      <svg
        width={containerWidth}
        height={PRICE_H}
        style={{ position: "absolute", top: 0, left: 0, pointerEvents: "none", zIndex: 10 }}
      >
        {domainOk && chartData.map((d, i) => {
          if (d.open == null || d.high == null || d.low == null || d.close == null) return null;
          const cx = toX(i);
          const color = d.close >= d.open ? UP : DOWN;
          const yHigh = toY(d.high), yLow = toY(d.low);
          const yOpen = toY(d.open), yClose = toY(d.close);
          const bodyTop = Math.min(yOpen, yClose);
          const bodyH = Math.max(1, Math.abs(yClose - yOpen));
          return (
            <g key={i}>
              <line x1={cx} y1={yHigh} x2={cx} y2={yLow} stroke={color} strokeWidth={1} />
              <rect x={cx - bodyW / 2} y={bodyTop} width={bodyW} height={bodyH} fill={color} />
            </g>
          );
        })}
      </svg>
    );
  })();

  const ChartTooltip = ({ active, payload }: any) => {
    if (!active || !payload || !payload.length) return null;
    const d = payload[0].payload;
    if (!d) return null;
    const f = (x: number | null) => (x == null ? "—" : x.toFixed(2));
    const row = (label: string, val: string, color?: string) => (
      <div key={label} style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
        <span style={{ color: color || "#94a3b8" }}>{label}</span>
        <span style={{ color: "#e5e5e5" }}>{val}</span>
      </div>
    );
    return (
      <div style={{ ...S.tooltip, padding: "6px 10px" }}>
        <div style={{ marginBottom: 4, color: "#cbd5e1" }}>{labelFormatter(d.date)}</div>
        {sCandles ? [row("O", f(d.open)), row("H", f(d.high)), row("L", f(d.low)), row("C", f(d.close))]
          : row("Close", f(d.close), "#818cf8")}
        {sMA20 && d.ma20 != null && row("MA20", f(d.ma20), "#f59e0b")}
        {sMA50 && d.ma50 != null && row("MA50", f(d.ma50), "#a855f7")}
        {sVol && d.volume != null && row("Vol", fmtVolume(d.volume), "#22d3ee")}
      </div>
    );
  };

  const MacdTooltip = ({ active, payload }: any) => {
    if (!active || !payload || !payload.length) return null;
    const d = payload[0].payload;
    if (!d) return null;
    const f = (x: number | null) => (x == null ? "—" : x.toFixed(2));
    return (
      <div style={{ ...S.tooltip, padding: "6px 10px" }}>
        <div style={{ marginBottom: 4, color: "#cbd5e1" }}>{labelFormatter(d.date)}</div>
        {[["MACD", f(d.macd), "#38bdf8"], ["Signal", f(d.signal), "#f59e0b"], ["Hist", f(d.hist), d.hist >= 0 ? UP : DOWN]].map(([l, v, c]) => (
          <div key={l} style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
            <span style={{ color: c }}>{l}</span>
            <span style={{ color: "#e5e5e5" }}>{v}</span>
          </div>
        ))}
      </div>
    );
  };

  const RsiTooltip = ({ active, payload }: any) => {
    if (!active || !payload || !payload.length) return null;
    const d = payload[0].payload;
    if (!d || d.rsi == null) return null;
    const status = d.rsi >= 70 ? ["Overbought", DOWN] : d.rsi <= 30 ? ["Oversold", UP] : ["Neutral", "#94a3b8"];
    return (
      <div style={{ ...S.tooltip, padding: "6px 10px" }}>
        <div style={{ marginBottom: 4, color: "#cbd5e1" }}>{labelFormatter(d.date)}</div>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
          <span style={{ color: "#a78bfa" }}>RSI</span>
          <span style={{ color: "#e5e5e5" }}>{d.rsi.toFixed(1)}</span>
        </div>
        <div style={{ marginTop: 2, color: status[1] }}>{status[0]}</div>
      </div>
    );
  };

  const pillBase = { borderWidth: "1px", borderStyle: "solid", borderColor: "#2a2a2a", borderRadius: 4, padding: "3px 10px", fontSize: 12, cursor: "pointer", fontFamily: "monospace", background: "none" };
  const pill = (active: boolean, bg: string, fg: string, bc: string) => ({
    ...pillBase,
    ...(active ? { background: bg, color: fg, borderColor: bc } : { color: "#64748b" }),
  });

  const perfStats = (() => {
    if (!priceData.length) return [] as [string, number | null][];
    const last = priceData[priceData.length - 1];
    const lastClose = last.close;
    const lastDate = new Date(last.date);
    const closeAtOrBefore = (target: Date) => {
      for (let i = priceData.length - 1; i >= 0; i--) {
        if (new Date(priceData[i].date) <= target) return priceData[i].close;
      }
      return null;
    };
    const pct = (base: number | null) => base == null || !base ? null : ((lastClose - base) / base) * 100;
    return [
      ["1Y", pct(closeAtOrBefore(new Date(lastDate.getTime() - 365 * 86400000)))],
      ["YTD", pct(closeAtOrBefore(new Date(lastDate.getFullYear(), 0, 1)))],
      ["3M", pct(closeAtOrBefore(new Date(lastDate.getTime() - 90 * 86400000)))],
    ] as [string, number | null][];
  })();

  const lastClose = priceData.length ? priceData[priceData.length - 1].close : null;
  const prevClose = priceData.length >= 2 ? priceData[priceData.length - 2].close : null;
  const shownPrice = liveQuote != null ? liveQuote : lastClose;
  const dayPct = shownPrice != null && prevClose ? (shownPrice / prevClose - 1) * 100 : null;

  if (loading) return (
    <div style={{ height: 400, display: "flex", alignItems: "center", justifyContent: "center", color: "#64748b", fontFamily: "monospace" }}>
      Loading…
    </div>
  );
  if (!priceData.length) return (
    <div style={{ height: 400, display: "flex", alignItems: "center", justifyContent: "center", color: "#64748b" }}>
      No price history available
    </div>
  );

  const priceContent = shownPrice == null ? null : (
    <>
      <div style={{ fontFamily: "DM Serif Display,serif", fontSize: 28, color: "#f1f5f9", lineHeight: 1.1 }}>
        {currSym(fcur)}{Number(fcur === "GBP" || fcur === "GBp" ? shownPrice / 100 : shownPrice).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </div>
      {dayPct != null && (
        <div style={{ fontFamily: "monospace", fontSize: 14, fontWeight: 600, marginTop: 2, color: dayPct >= 0 ? "#22c55e" : "#ef4444" }}>
          {dayPct >= 0 ? "+" : "−"}{Math.abs(dayPct).toFixed(2)}%
        </div>
      )}
    </>
  );

  return (
    // overflow:hidden clips recharts' absolutely-positioned tooltip wrapper. On
    // touch the tooltip stays "active" (no mouseleave) with a stale translateX
    // from the wider landscape layout; on rotating back to portrait that stale
    // wrapper sits off the right edge and inflates the page width, squashing the
    // whole site left. Recharts keeps tooltips inside the plot area, so this
    // clips nothing legitimate. See investigation 2026-06-25.
    <div style={{ overflow: "hidden" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-start" }}>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {["1M", "3M", "6M", "1Y", "3Y", "5Y"].map((r) => (
              <button key={r} onClick={() => setRange(r)} style={pill(r === range, "#3730a3", "#e0e7ff", "#4338ca")}>
                {r}
              </button>
            ))}
          </div>
          {!simple && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              <button onClick={() => setShowCandles((v) => !v)} style={pill(showCandles, "#14532d", "#bbf7d0", "#166534")}>Candles</button>
              <button onClick={() => setShowMA20((v) => !v)} style={pill(showMA20, "#78350f", "#fde68a", "#92400e")}>MA20</button>
              <button onClick={() => setShowMA50((v) => !v)} style={pill(showMA50, "#4c1d95", "#ddd6fe", "#5b21b6")}>MA50</button>
              <button onClick={() => setShowVolume((v) => !v)} style={pill(showVolume, "#155e75", "#cffafe", "#0e7490")}>Vol</button>
              <button onClick={() => setShowMACD((v) => !v)} style={pill(showMACD, "#0c4a6e", "#bae6fd", "#075985")}>MACD</button>
              <button onClick={() => setShowRSI((v) => !v)} style={pill(showRSI, "#581c87", "#e9d5ff", "#6b21a8")}>RSI</button>
            </div>
          )}
          <div style={{ display: "flex", gap: simple ? 12 : 18, flexWrap: simple ? "nowrap" : "wrap", fontFamily: "monospace", fontSize: 12 }}>
            {perfStats.map(([label, v]) => (
              <span key={label} style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
                <span style={{ color: "#64748b", textTransform: "uppercase", fontSize: 11, letterSpacing: 1 }}>{label}</span>
                <span style={{ color: v == null ? "#64748b" : v >= 0 ? "#22c55e" : "#ef4444", fontWeight: 600 }}>
                  {v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`}
                </span>
              </span>
            ))}
          </div>
        </div>
        {!overlayPrice && priceContent != null && (
          <div style={{ textAlign: "right", flexShrink: 0 }}>{priceContent}</div>
        )}
      </div>

      <div ref={containerRef} style={{ position: "relative" }}>
        {overlayPrice && priceContent != null && (
          <div style={{ position: "absolute", top: PRICE_TOP - 10, right: 5, textAlign: "right", zIndex: 11, pointerEvents: "none", background: "rgba(15,15,15,0.65)", borderRadius: 6, padding: "4px 10px", backdropFilter: "blur(2px)" }}>
            {priceContent}
          </div>
        )}
        <ResponsiveContainer width="100%" height={380}>
          <ComposedChart key={chartKey} data={chartData} margin={{ top: PRICE_TOP, right: 10, bottom: 5, left: 0 }}>
            <defs>
              <linearGradient id="gPrice" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="date" tick={sMACD || sRSI ? false : { fontSize: 10 }} ticks={axisTicks} interval={0} tickFormatter={tickFormatter} height={sMACD || sRSI ? 4 : 30} />
            <YAxis tick={{ fontSize: 10 }} domain={priceDomain} tickFormatter={fmtAxisPrice} width={Y_AXIS_W} />
            {sVol && <YAxis yAxisId="vol" orientation="right" hide domain={[0, (dataMax: number) => (dataMax || 0) * 4]} />}
            <Tooltip content={<ChartTooltip />} />
            {sVol && (
              <Bar yAxisId="vol" dataKey="volume" fill="#0e7490" opacity={0.5} name="Volume" isAnimationActive={false}>
                {["1M", "3M", "6M"].includes(range) && chartData.map((d, i) => (
                  <Cell key={i} fill={d.open != null && d.close < d.open ? DOWN : UP} />
                ))}
              </Bar>
            )}
            {sCandles ? (
              <Line type="monotone" dataKey="close" stroke="transparent" dot={false} name="OHLC" isAnimationActive={false} />
            ) : (
              <Area type="monotone" dataKey="close" stroke="#6366f1" fill="url(#gPrice)" strokeWidth={2} dot={false} name="Close" />
            )}
            {sMA20 && <Line type="monotone" dataKey="ma20" stroke="#f59e0b" strokeWidth={1.5} dot={false} strokeDasharray="4 2" name="MA20" connectNulls={false} />}
            {sMA50 && <Line type="monotone" dataKey="ma50" stroke="#a855f7" strokeWidth={1.5} dot={false} name="MA50" connectNulls={false} />}
          </ComposedChart>
        </ResponsiveContainer>
        {candleOverlay}
      </div>

      {sMACD && (
        <ResponsiveContainer width="100%" height={150}>
          <ComposedChart key={chartKey} data={chartData} margin={{ top: 4, right: 10, bottom: 5, left: 0 }}>
            <text x={70} y={12} fill="#64748b" fontSize={11} fontFamily="monospace">MACD (12, 26, 9)</text>
            <XAxis dataKey="date" tick={sRSI ? false : { fontSize: 10 }} ticks={axisTicks} interval={0} tickFormatter={tickFormatter} height={sRSI ? 4 : 30} />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={fmtAxisPrice} width={Y_AXIS_W} />
            <Tooltip content={<MacdTooltip />} />
            <ReferenceLine y={0} stroke="#334155" />
            <Bar dataKey="hist" name="Hist" isAnimationActive={false}>
              {chartData.map((d, i) => <Cell key={i} fill={d.hist != null && d.hist < 0 ? DOWN : UP} />)}
            </Bar>
            <Line type="monotone" dataKey="macd" stroke="#38bdf8" strokeWidth={1.5} dot={false} name="MACD" connectNulls={false} />
            <Line type="monotone" dataKey="signal" stroke="#f59e0b" strokeWidth={1.5} dot={false} name="Signal" connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {sRSI && (
        <ResponsiveContainer width="100%" height={130}>
          <ComposedChart key={chartKey} data={chartData} margin={{ top: 4, right: 10, bottom: 5, left: 0 }}>
            <text x={70} y={12} fill="#64748b" fontSize={11} fontFamily="monospace">RSI (14)</text>
            <XAxis dataKey="date" tick={{ fontSize: 10 }} ticks={axisTicks} interval={0} tickFormatter={tickFormatter} />
            <YAxis tick={{ fontSize: 10 }} domain={[0, 100]} ticks={[30, 50, 70]} width={Y_AXIS_W} />
            <Tooltip content={<RsiTooltip />} />
            <ReferenceLine y={70} stroke={DOWN} strokeDasharray="4 2" label={{ value: "70", position: "right", fontSize: 9, fill: DOWN }} />
            <ReferenceLine y={30} stroke={UP} strokeDasharray="4 2" label={{ value: "30", position: "right", fontSize: 9, fill: UP }} />
            <Line type="monotone" dataKey="rsi" stroke="#a78bfa" strokeWidth={1.5} dot={false} name="RSI" connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
