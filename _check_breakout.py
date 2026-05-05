"""Quick check: verify breakout data was stored."""

import os, sys

sys.path.insert(0, os.path.dirname(__file__))
from backend.breakout import _fetch_all

rows = _fetch_all("SELECT COUNT(*) as cnt FROM breakout_scores")
print(f"Total scores: {rows[0]['cnt']}")

rows = _fetch_all("SELECT COUNT(*) as cnt FROM breakout_signals")
print(f"Total signals: {rows[0]['cnt']}")

rows = _fetch_all(
    "SELECT symbol, breakout_score, layers_passed FROM breakout_scores ORDER BY breakout_score DESC LIMIT 10"
)
print("\nTop 10 by breakout score:")
for r in rows:
    print(
        f"  {r['symbol']:10s}  score={r['breakout_score']:5.1f}  layers={r['layers_passed']}"
    )

# Check algo distribution
rows = _fetch_all("""
    SELECT 
        ROUND(AVG(algo_price_level)::numeric, 1) as avg_price_level,
        ROUND(AVG(algo_consolidation)::numeric, 1) as avg_consolidation,
        ROUND(AVG(algo_volume)::numeric, 1) as avg_volume,
        ROUND(AVG(algo_ma_cross)::numeric, 1) as avg_ma_cross,
        ROUND(AVG(algo_volatility)::numeric, 1) as avg_volatility,
        ROUND(AVG(algo_zscore)::numeric, 1) as avg_zscore,
        ROUND(AVG(breakout_score)::numeric, 1) as avg_composite
    FROM breakout_scores
""")
print("\nAverage algo scores across all stocks:")
for k, v in rows[0].items():
    print(f"  {k}: {v}")
