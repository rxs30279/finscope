import { useState, useEffect } from "react";
import { API } from "../utils";

const SCORE_COLOR = (s) => {
  if (s == null) return "#444";
  if (s >= 80) return "#10b981";
  if (s >= 60) return "#f59e0b";
  if (s >= 40) return "#f97316";
  return "#ef4444";
};

const SCORE_BG = (s) => {
  if (s == null) return "#111";
  if (s >= 80) return "#0d2318";
  if (s >= 60) return "#1a1400";
  if (s >= 40) return "#2a1a00";
  return "#2a0d0d";
};

const TREND_COLOR = (t) => {
  if (t === "rising") return "#10b981";
  if (t === "falling") return "#ef4444";
  return "#666";
};

function ScoreBadge({ score }) {
  return (
    <span
      style={{
        background: SCORE_BG(score),
        color: SCORE_COLOR(score),
        padding: "2px 8px",
        borderRadius: 3,
        fontSize: 11,
        fontFamily: "monospace",
        fontWeight: 700,
      }}
    >
      {score != null ? score.toFixed(0) : "—"}
    </span>
  );
}

function AlgoBar({ label, value, maxVal = 100 }) {
  const pct = value != null ? Math.min((value / maxVal) * 100, 100) : 0;
  return (
    <div style={{ marginBottom: 4 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 9,
          color: "#666",
          fontFamily: "monospace",
          marginBottom: 2,
        }}
      >
        <span>{label}</span>
        <span style={{ color: SCORE_COLOR(value) }}>
          {value != null ? value.toFixed(0) : "—"}
        </span>
      </div>
      <div style={{ background: "#1a1a1a", borderRadius: 2, height: 4 }}>
        <div
          style={{
            background: SCORE_COLOR(value),
            width: `${pct}%`,
            height: 4,
            borderRadius: 2,
          }}
        />
      </div>
    </div>
  );
}

function TrendDot({ trend }) {
  const c = TREND_COLOR(trend);
  return (
    <span style={{ color: c, fontSize: 12 }}>
      {trend === "rising" ? "▲" : trend === "falling" ? "▼" : "—"}
    </span>
  );
}

export default function BreakoutTab({ refreshKey }) {
  const [signals, setSignals] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [filterScore, setFilterScore] = useState(50);
  const [filterLayers, setFilterLayers] = useState(1);
  const [sortCol, setSortCol] = useState("breakout_score");
  const [sortDir, setSortDir] = useState("desc");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(
        `${API}/breakout/signals?min_score=${filterScore}&min_layers=${filterLayers}&limit=200`,
      ).then((r) => r.json()),
      fetch(`${API}/breakout/summary`).then((r) => r.json()),
    ])
      .then(([sigs, summ]) => {
        setSignals(Array.isArray(sigs) ? sigs : []);
        setSummary(summ);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [refreshKey, filterScore, filterLayers]);

  const loadHistory = (symbol) => {
    setSelectedSymbol(symbol);
    setHistoryLoading(true);
    fetch(`${API}/breakout/history/${encodeURIComponent(symbol)}?days=60`)
      .then((r) => r.json())
      .then((d) => {
        setHistory(Array.isArray(d) ? d : []);
        setHistoryLoading(false);
      })
      .catch(() => setHistoryLoading(false));
  };

  const handleSort = (key) => {
    if (sortCol === key) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else {
      setSortCol(key);
      setSortDir("desc");
    }
  };

  const sorted = [...signals].sort((a, b) => {
    const av = a[sortCol],
      bv = b[sortCol];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "string")
      return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortDir === "asc" ? av - bv : bv - av;
  });

  const thStyle = {
    padding: "6px 8px",
    fontSize: 9,
    color: "#666",
    textTransform: "uppercase",
    letterSpacing: "1px",
    fontFamily: "monospace",
    textAlign: "left",
    borderBottom: "1px solid #2a2a2a",
    cursor: "pointer",
    whiteSpace: "nowrap",
  };
  const tdStyle = {
    padding: "6px 8px",
    fontSize: 11,
    fontFamily: "monospace",
    borderBottom: "1px solid #141414",
    color: "#cbd5e1",
  };

  // ── Detail View ──
  if (selectedSymbol) {
    const sig = signals.find((s) => s.symbol === selectedSymbol);
    return (
      <div>
        <button
          onClick={() => setSelectedSymbol(null)}
          style={{
            background: "none",
            border: "1px solid #2a2a2a",
            borderRadius: 4,
            padding: "6px 14px",
            color: "#94a3b8",
            cursor: "pointer",
            fontFamily: "monospace",
            fontSize: 11,
            marginBottom: 16,
          }}
        >
          ← Back to Breakout Signals
        </button>

        <div style={{ display: "flex", gap: 24, marginBottom: 24 }}>
          <div
            style={{
              background: "#111",
              border: "1px solid #1e1e1e",
              borderRadius: 3,
              padding: 20,
              flex: 1,
            }}
          >
            <h3
              style={{
                fontFamily: "monospace",
                fontSize: 14,
                color: "#f1f5f9",
                margin: "0 0 16px 0",
              }}
            >
              {selectedSymbol}
              {sig?.name ? (
                <span
                  style={{
                    color: "#64748b",
                    fontWeight: 400,
                    marginLeft: 8,
                    fontSize: 12,
                  }}
                >
                  {sig.name}
                </span>
              ) : null}
            </h3>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 16,
              }}
            >
              <div>
                <div style={{ fontSize: 10, color: "#666", marginBottom: 4 }}>
                  Breakout Score
                </div>
                <ScoreBadge score={sig?.breakout_score} />
                <div
                  style={{
                    fontSize: 10,
                    color: "#666",
                    marginTop: 8,
                    marginBottom: 4,
                  }}
                >
                  Layers Passed
                </div>
                <span style={{ color: "#94a3b8", fontSize: 13 }}>
                  {sig?.layers_passed ?? "—"} / 6
                </span>
              </div>
              <div>
                <div style={{ fontSize: 10, color: "#666", marginBottom: 4 }}>
                  Close
                </div>
                <div
                  style={{ color: "#e5e5e5", fontSize: 16, fontWeight: 700 }}
                >
                  {sig?.close != null ? sig.close.toFixed(2) : "—"}
                </div>
                <div
                  style={{
                    fontSize: 10,
                    color: "#666",
                    marginTop: 8,
                    marginBottom: 4,
                  }}
                >
                  Volume Ratio
                </div>
                <div
                  style={{
                    color: sig?.volume_ratio > 1.5 ? "#10b981" : "#94a3b8",
                    fontSize: 13,
                  }}
                >
                  {sig?.volume_ratio != null
                    ? `${sig.volume_ratio.toFixed(1)}x`
                    : "—"}
                </div>
              </div>
            </div>
          </div>

          <div
            style={{
              background: "#111",
              border: "1px solid #1e1e1e",
              borderRadius: 3,
              padding: 20,
              flex: 1,
            }}
          >
            <h4
              style={{
                fontFamily: "monospace",
                fontSize: 11,
                color: "#666",
                textTransform: "uppercase",
                letterSpacing: 1,
                margin: "0 0 12px 0",
              }}
            >
              Algorithm Scores
            </h4>
            <AlgoBar label="Price Level" value={sig?.algo_price_level} />
            <AlgoBar label="Consolidation" value={sig?.algo_consolidation} />
            <AlgoBar label="Volume" value={sig?.algo_volume} />
            <AlgoBar label="MA Cross" value={sig?.algo_ma_cross} />
            <AlgoBar label="Volatility" value={sig?.algo_volatility} />
            <AlgoBar label="Z-Score" value={sig?.algo_zscore} />
          </div>

          <div
            style={{
              background: "#111",
              border: "1px solid #1e1e1e",
              borderRadius: 3,
              padding: 20,
              flex: 1,
            }}
          >
            <h4
              style={{
                fontFamily: "monospace",
                fontSize: 11,
                color: "#666",
                textTransform: "uppercase",
                letterSpacing: 1,
                margin: "0 0 12px 0",
              }}
            >
              Supporting Metrics
            </h4>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "6px 16px",
                fontSize: 11,
                fontFamily: "monospace",
              }}
            >
              <span style={{ color: "#666" }}>CMF (20d)</span>
              <span style={{ color: sig?.cmf_20d > 0 ? "#10b981" : "#ef4444" }}>
                {sig?.cmf_20d != null ? sig.cmf_20d.toFixed(3) : "—"}
              </span>
              <span style={{ color: "#666" }}>MFI (14d)</span>
              <span style={{ color: "#94a3b8" }}>
                {sig?.mfi_14d != null ? sig.mfi_14d.toFixed(1) : "—"}
              </span>
              <span style={{ color: "#666" }}>OBV Trend</span>
              <TrendDot trend={sig?.obv_trend} />
              <span style={{ color: "#666" }}>VPT Trend</span>
              <TrendDot trend={sig?.vpt_trend} />
              <span style={{ color: "#666" }}>MA50</span>
              <span style={{ color: "#94a3b8" }}>
                {sig?.ma_50d != null ? sig.ma_50d.toFixed(2) : "—"}
              </span>
              <span style={{ color: "#666" }}>MA200</span>
              <span style={{ color: "#94a3b8" }}>
                {sig?.ma_200d != null ? sig.ma_200d.toFixed(2) : "—"}
              </span>
              <span style={{ color: "#666" }}>20d High</span>
              <span style={{ color: "#94a3b8" }}>
                {sig?.n_day_high_20 != null
                  ? sig.n_day_high_20.toFixed(2)
                  : "—"}
              </span>
              <span style={{ color: "#666" }}>Z-Score</span>
              <span style={{ color: sig?.z_score > 2 ? "#10b981" : "#94a3b8" }}>
                {sig?.z_score != null ? sig.z_score.toFixed(2) : "—"}
              </span>
            </div>
          </div>
        </div>

        {/* History Chart */}
        <div
          style={{
            background: "#111",
            border: "1px solid #1e1e1e",
            borderRadius: 3,
            padding: 20,
          }}
        >
          <h4
            style={{
              fontFamily: "monospace",
              fontSize: 11,
              color: "#666",
              textTransform: "uppercase",
              letterSpacing: 1,
              margin: "0 0 12px 0",
            }}
          >
            Breakout Score History (60 days)
          </h4>
          {historyLoading ? (
            <div
              style={{
                color: "#444",
                padding: 20,
                textAlign: "center",
                fontFamily: "monospace",
                fontSize: 11,
              }}
            >
              Loading history…
            </div>
          ) : history.length === 0 ? (
            <div
              style={{
                color: "#444",
                padding: 20,
                textAlign: "center",
                fontFamily: "monospace",
                fontSize: 11,
              }}
            >
              No history available
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={thStyle}>Date</th>
                    <th style={thStyle}>Score</th>
                    <th style={thStyle}>Layers</th>
                    <th style={thStyle}>Price</th>
                    <th style={thStyle}>Price Lvl</th>
                    <th style={thStyle}>Consol.</th>
                    <th style={thStyle}>Volume</th>
                    <th style={thStyle}>MA Cross</th>
                    <th style={thStyle}>Volatility</th>
                    <th style={thStyle}>Z-Score</th>
                    <th style={thStyle}>Vol Ratio</th>
                    <th style={thStyle}>CMF</th>
                    <th style={thStyle}>MFI</th>
                    <th style={thStyle}>OBV</th>
                    <th style={thStyle}>VPT</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h, i) => (
                    <tr
                      key={i}
                      style={{
                        background:
                          h.breakout_score >= 50 ? "#0d2318" : "transparent",
                      }}
                    >
                      <td style={tdStyle}>{h.date?.slice(0, 10)}</td>
                      <td style={tdStyle}>
                        <ScoreBadge score={h.breakout_score} />
                      </td>
                      <td
                        style={{
                          ...tdStyle,
                          color: h.layers_passed >= 3 ? "#10b981" : "#666",
                        }}
                      >
                        {h.layers_passed}
                      </td>
                      <td style={tdStyle}>
                        {h.close != null ? h.close.toFixed(2) : "—"}
                      </td>
                      <td style={tdStyle}>
                        <ScoreBadge score={h.algo_price_level} />
                      </td>
                      <td style={tdStyle}>
                        <ScoreBadge score={h.algo_consolidation} />
                      </td>
                      <td style={tdStyle}>
                        <ScoreBadge score={h.algo_volume} />
                      </td>
                      <td style={tdStyle}>
                        <ScoreBadge score={h.algo_ma_cross} />
                      </td>
                      <td style={tdStyle}>
                        <ScoreBadge score={h.algo_volatility} />
                      </td>
                      <td style={tdStyle}>
                        <ScoreBadge score={h.algo_zscore} />
                      </td>
                      <td
                        style={{
                          ...tdStyle,
                          color: h.volume_ratio > 1.5 ? "#10b981" : "#666",
                        }}
                      >
                        {h.volume_ratio != null
                          ? `${h.volume_ratio.toFixed(1)}x`
                          : "—"}
                      </td>
                      <td
                        style={{
                          ...tdStyle,
                          color: h.cmf_20d > 0 ? "#10b981" : "#ef4444",
                        }}
                      >
                        {h.cmf_20d != null ? h.cmf_20d.toFixed(3) : "—"}
                      </td>
                      <td style={tdStyle}>
                        {h.mfi_14d != null ? h.mfi_14d.toFixed(1) : "—"}
                      </td>
                      <td style={tdStyle}>
                        <TrendDot trend={h.obv_trend} />
                      </td>
                      <td style={tdStyle}>
                        <TrendDot trend={h.vpt_trend} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Main List View ──
  return (
    <div>
      {/* Summary Bar */}
      {summary && (
        <div
          style={{
            display: "flex",
            gap: 16,
            marginBottom: 20,
            flexWrap: "wrap",
            background: "#111",
            border: "1px solid #1e1e1e",
            borderRadius: 3,
            padding: "12px 16px",
          }}
        >
          <div>
            <div
              style={{
                fontSize: 9,
                color: "#666",
                textTransform: "uppercase",
                letterSpacing: 1,
                fontFamily: "monospace",
                marginBottom: 4,
              }}
            >
              Signals Today
            </div>
            <span
              style={{
                fontSize: 22,
                fontWeight: 700,
                fontFamily: "monospace",
                color: summary.stats?.total_signals > 0 ? "#10b981" : "#666",
              }}
            >
              {summary.stats?.total_signals ?? "—"}
            </span>
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                color: "#666",
                textTransform: "uppercase",
                letterSpacing: 1,
                fontFamily: "monospace",
                marginBottom: 4,
              }}
            >
              Avg Score
            </div>
            <span
              style={{
                fontSize: 18,
                fontWeight: 700,
                fontFamily: "monospace",
                color: SCORE_COLOR(summary.stats?.avg_score),
              }}
            >
              {summary.stats?.avg_score != null
                ? summary.stats.avg_score.toFixed(1)
                : "—"}
            </span>
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                color: "#666",
                textTransform: "uppercase",
                letterSpacing: 1,
                fontFamily: "monospace",
                marginBottom: 4,
              }}
            >
              Strong (≥4 layers)
            </div>
            <span
              style={{
                fontSize: 18,
                fontWeight: 700,
                fontFamily: "monospace",
                color: "#10b981",
              }}
            >
              {summary.stats?.strong_signals ?? "—"}
            </span>
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                color: "#666",
                textTransform: "uppercase",
                letterSpacing: 1,
                fontFamily: "monospace",
                marginBottom: 4,
              }}
            >
              Moderate (2-3 layers)
            </div>
            <span
              style={{
                fontSize: 18,
                fontWeight: 700,
                fontFamily: "monospace",
                color: "#f59e0b",
              }}
            >
              {summary.stats?.moderate_signals ?? "—"}
            </span>
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                color: "#666",
                textTransform: "uppercase",
                letterSpacing: 1,
                fontFamily: "monospace",
                marginBottom: 4,
              }}
            >
              Max Score
            </div>
            <span
              style={{
                fontSize: 18,
                fontWeight: 700,
                fontFamily: "monospace",
                color: SCORE_COLOR(summary.stats?.max_score),
              }}
            >
              {summary.stats?.max_score != null
                ? summary.stats.max_score.toFixed(0)
                : "—"}
            </span>
          </div>
        </div>
      )}

      {/* Filters */}
      <div
        style={{
          display: "flex",
          gap: 10,
          marginBottom: 16,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <div style={{ fontSize: 10, color: "#666", fontFamily: "monospace" }}>
          Min Score:
        </div>
        <select
          style={{
            background: "#111",
            border: "1px solid #2a2a2a",
            borderRadius: 3,
            padding: "4px 8px",
            color: "#cbd5e1",
            fontFamily: "monospace",
            fontSize: 11,
          }}
          value={filterScore}
          onChange={(e) => setFilterScore(Number(e.target.value))}
        >
          <option value={0}>Any</option>
          <option value={50}>50+</option>
          <option value={60}>60+</option>
          <option value={70}>70+</option>
          <option value={80}>80+</option>
        </select>
        <div style={{ fontSize: 10, color: "#666", fontFamily: "monospace" }}>
          Min Layers:
        </div>
        <select
          style={{
            background: "#111",
            border: "1px solid #2a2a2a",
            borderRadius: 3,
            padding: "4px 8px",
            color: "#cbd5e1",
            fontFamily: "monospace",
            fontSize: 11,
          }}
          value={filterLayers}
          onChange={(e) => setFilterLayers(Number(e.target.value))}
        >
          <option value={1}>1+</option>
          <option value={2}>2+</option>
          <option value={3}>3+</option>
          <option value={4}>4+</option>
          <option value={5}>5+</option>
        </select>
        <div
          style={{
            fontSize: 10,
            color: "#666",
            fontFamily: "monospace",
            marginLeft: 8,
          }}
        >
          {signals.length} signal{signals.length !== 1 ? "s" : ""}
        </div>
      </div>

      {/* Signals Table */}
      {loading ? (
        <div
          style={{
            color: "#444",
            padding: 32,
            textAlign: "center",
            fontFamily: "monospace",
          }}
        >
          Loading breakout signals…
        </div>
      ) : signals.length === 0 ? (
        <div
          style={{
            background: "#111",
            border: "1px solid #1e1e1e",
            borderRadius: 3,
            padding: 40,
            textAlign: "center",
            color: "#444",
            fontFamily: "monospace",
            fontSize: 12,
          }}
        >
          No breakout signals detected today.
        </div>
      ) : (
        <div
          style={{
            background: "#111",
            border: "1px solid #1e1e1e",
            borderRadius: 3,
            overflowX: "auto",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle} onClick={() => handleSort("symbol")}>
                  Symbol{" "}
                  {sortCol === "symbol" ? (sortDir === "asc" ? "↑" : "↓") : ""}
                </th>
                <th style={thStyle} onClick={() => handleSort("name")}>
                  Name{" "}
                  {sortCol === "name" ? (sortDir === "asc" ? "↑" : "↓") : ""}
                </th>
                <th
                  style={thStyle}
                  onClick={() => handleSort("breakout_score")}
                >
                  Score{" "}
                  {sortCol === "breakout_score"
                    ? sortDir === "asc"
                      ? "↑"
                      : "↓"
                    : ""}
                </th>
                <th style={thStyle} onClick={() => handleSort("layers_passed")}>
                  Layers{" "}
                  {sortCol === "layers_passed"
                    ? sortDir === "asc"
                      ? "↑"
                      : "↓"
                    : ""}
                </th>
                <th style={thStyle} onClick={() => handleSort("close")}>
                  Price{" "}
                  {sortCol === "close" ? (sortDir === "asc" ? "↑" : "↓") : ""}
                </th>
                <th style={thStyle} onClick={() => handleSort("volume_ratio")}>
                  Vol Ratio{" "}
                  {sortCol === "volume_ratio"
                    ? sortDir === "asc"
                      ? "↑"
                      : "↓"
                    : ""}
                </th>
                <th style={thStyle} onClick={() => handleSort("cmf_20d")}>
                  CMF{" "}
                  {sortCol === "cmf_20d" ? (sortDir === "asc" ? "↑" : "↓") : ""}
                </th>
                <th style={thStyle} onClick={() => handleSort("mfi_14d")}>
                  MFI{" "}
                  {sortCol === "mfi_14d" ? (sortDir === "asc" ? "↑" : "↓") : ""}
                </th>
                <th style={thStyle}>OBV</th>
                <th style={thStyle}>VPT</th>
                <th
                  style={thStyle}
                  onClick={() => handleSort("algo_price_level")}
                >
                  Price Lvl{" "}
                  {sortCol === "algo_price_level"
                    ? sortDir === "asc"
                      ? "↑"
                      : "↓"
                    : ""}
                </th>
                <th
                  style={thStyle}
                  onClick={() => handleSort("algo_consolidation")}
                >
                  Consol.{" "}
                  {sortCol === "algo_consolidation"
                    ? sortDir === "asc"
                      ? "↑"
                      : "↓"
                    : ""}
                </th>
                <th style={thStyle} onClick={() => handleSort("algo_volume")}>
                  Volume{" "}
                  {sortCol === "algo_volume"
                    ? sortDir === "asc"
                      ? "↑"
                      : "↓"
                    : ""}
                </th>
                <th style={thStyle} onClick={() => handleSort("algo_ma_cross")}>
                  MA Cross{" "}
                  {sortCol === "algo_ma_cross"
                    ? sortDir === "asc"
                      ? "↑"
                      : "↓"
                    : ""}
                </th>
                <th
                  style={thStyle}
                  onClick={() => handleSort("algo_volatility")}
                >
                  Volatility{" "}
                  {sortCol === "algo_volatility"
                    ? sortDir === "asc"
                      ? "↑"
                      : "↓"
                    : ""}
                </th>
                <th style={thStyle} onClick={() => handleSort("algo_zscore")}>
                  Z-Score{" "}
                  {sortCol === "algo_zscore"
                    ? sortDir === "asc"
                      ? "↑"
                      : "↓"
                    : ""}
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s, i) => (
                <tr
                  key={i}
                  onClick={() => loadHistory(s.symbol)}
                  style={{
                    cursor: "pointer",
                    background: i % 2 === 0 ? "transparent" : "#0a0a0a",
                    transition: "background 0.15s",
                  }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.background = "#1a1a1a")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background =
                      i % 2 === 0 ? "transparent" : "#0a0a0a")
                  }
                >
                  <td style={{ ...tdStyle, color: "#f97316", fontWeight: 700 }}>
                    {s.symbol}
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      color: "#94a3b8",
                      maxWidth: 180,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {s.name || "—"}
                  </td>
                  <td style={tdStyle}>
                    <ScoreBadge score={s.breakout_score} />
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      color:
                        s.layers_passed >= 4
                          ? "#10b981"
                          : s.layers_passed >= 2
                            ? "#f59e0b"
                            : "#666",
                    }}
                  >
                    {s.layers_passed}
                  </td>
                  <td style={tdStyle}>
                    {s.close != null ? s.close.toFixed(2) : "—"}
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      color: s.volume_ratio > 1.5 ? "#10b981" : "#666",
                    }}
                  >
                    {s.volume_ratio != null
                      ? `${s.volume_ratio.toFixed(1)}x`
                      : "—"}
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      color: s.cmf_20d > 0 ? "#10b981" : "#ef4444",
                    }}
                  >
                    {s.cmf_20d != null ? s.cmf_20d.toFixed(3) : "—"}
                  </td>
                  <td style={tdStyle}>
                    {s.mfi_14d != null ? s.mfi_14d.toFixed(1) : "—"}
                  </td>
                  <td style={tdStyle}>
                    <TrendDot trend={s.obv_trend} />
                  </td>
                  <td style={tdStyle}>
                    <TrendDot trend={s.vpt_trend} />
                  </td>
                  <td style={tdStyle}>
                    <ScoreBadge score={s.algo_price_level} />
                  </td>
                  <td style={tdStyle}>
                    <ScoreBadge score={s.algo_consolidation} />
                  </td>
                  <td style={tdStyle}>
                    <ScoreBadge score={s.algo_volume} />
                  </td>
                  <td style={tdStyle}>
                    <ScoreBadge score={s.algo_ma_cross} />
                  </td>
                  <td style={tdStyle}>
                    <ScoreBadge score={s.algo_volatility} />
                  </td>
                  <td style={tdStyle}>
                    <ScoreBadge score={s.algo_zscore} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
