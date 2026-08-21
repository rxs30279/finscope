"""Render Cron Job entry point — daily price refresh + screener score rebuild.

Fetches missing price history for the whole universe, then rebuilds the
precomputed screener_scores table (momentum/risk read price_history, so scores
must be rebuilt once fresh prices land). Synchronous; the process exits when
done, so a free-tier idle spin-down can never kill it mid-run.

Replaces the /api/prices/run endpoint + cron-job.org trigger. Exits non-zero on
failure so the Render cron run is marked failed.
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from prices import refresh_prices
from main import compute_and_store_scores, compute_and_store_valuations, snapshot_scores
from market import _lse_open, _rebuild_fear_greed_history, warm_price_snapshots


def main() -> int:
    # Guards against a schedule firing before the close: today's bar doesn't
    # exist yet on yfinance while the LSE is still trading, so every active
    # symbol would come back "empty" — and refresh_prices() deactivates a
    # symbol after 3 consecutive empty fetches (see _DEACTIVATE_AFTER in
    # prices.py). Two Dokploy schedules (one tuned for BST, one for GMT) rely
    # on this to make the "wrong season" trigger a safe no-op instead of
    # mass-flagging the universe as delisted.
    if _lse_open():
        print("[prices] LSE still open — skipping this trigger, closed-market run will pick it up")
        return 0

    print(f"[prices] refresh starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = refresh_prices()
        print(f"[prices] refresh done — {result}")
    except Exception as e:
        print(f"[prices] refresh FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    # Rebuild the precomputed scores now that fresh prices have landed. Prices
    # are already committed at this point, so a failure here is reported (red
    # run) but the price data still self-heals — the next run just rebuilds.
    try:
        scores = compute_and_store_scores()
        print(f"[prices] screener scores rebuilt — {scores}")
    except Exception as e:
        print(f"[prices] screener score rebuild FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    # Dated snapshot for the forward-test history table. Non-fatal: scores above
    # are already committed and this self-heals on the next run.
    try:
        snap = snapshot_scores()
        print(f"[prices] score history snapshot recorded — {snap}")
    except Exception as e:
        print(f"[prices] score history snapshot FAILED (non-fatal) — {type(e).__name__}: {e}")
        traceback.print_exc()

    # Peer-relative fair values (Valuation tab). Reads peers' fresh multiples, so
    # rebuild after prices land. Non-fatal: a failure is reported but the prices
    # and scores above are already committed and this self-heals next run.
    try:
        vals = compute_and_store_valuations()
        print(f"[prices] valuation estimates rebuilt — {vals}")
    except Exception as e:
        print(f"[prices] valuation rebuild FAILED (non-fatal) — {type(e).__name__}: {e}")
        traceback.print_exc()

    # Rebuild the Fear & Greed daily history (UK reconstruction + US CNN backfill).
    # Auxiliary display data, so a failure here is logged but does not fail the run
    # — the table self-heals on the next rebuild and old rows are never dropped.
    try:
        fg = _rebuild_fear_greed_history()
        print(f"[prices] fear-greed history rebuilt — {fg}")
    except Exception as e:
        print(f"[prices] fear-greed history rebuild FAILED (non-fatal) — {type(e).__name__}: {e}")
        traceback.print_exc()

    # Refresh the on-disk market price snapshots so freshly-started web workers
    # seed their cache from a recent EOD frame instead of paying a live Yahoo
    # fetch on the first request. Non-fatal: it's a load-time optimisation, and a
    # missing/stale snapshot just means the worker falls back to a live fetch.
    try:
        snap = warm_price_snapshots()
        print(f"[prices] market snapshots warmed — {snap}")
    except Exception as e:
        print(f"[prices] market snapshot warm FAILED (non-fatal) — {type(e).__name__}: {e}")
        traceback.print_exc()

    print("[prices] completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
