"""Standalone nightly refresh script for analyst data.

Run directly:    python refresh_analysts.py
Or scheduled:    Windows Task Scheduler → python C:\\...\\refresh_analysts.py

Uses the same _run_refresh() logic as the POST /api/analysts/refresh endpoint.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from analysts import _run_refresh
import time

if __name__ == '__main__':
    print(f"[analysts] starting refresh at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    t0 = time.time()
    result = _run_refresh()
    elapsed = round(time.time() - t0, 1)
    print(f"[analysts] complete in {elapsed}s — {result}")
