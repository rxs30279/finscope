"""Reconstruct AIM 100 membership over time from web-archive snapshots.

Feeds the post-promotion momentum test (aim100_entry_momentum.py). Fetches
archived captures of the HL constituent page, parses each into a member set,
and chains them into entry/exit events.

The sharp edge: **most captures are useless**. Of 22 snapshots the CDX index
reports with status 200, only 5 contain a server-rendered table; the rest are
JS shells, because the page moved to client-side rendering and the Wayback
`id_` flag serves the raw response without executing script. Empty parses are
therefore expected, and are dropped rather than treated as "everybody left" -
chaining them naively invents a 100-company exodus and a 100-company intake.

Usage:
    python aim100_membership_timeline.py --download   # populate snaps/
    python aim100_membership_timeline.py
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from io import StringIO

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND)

import pandas as pd

from universe_common import to_yf_symbol

SNAPS = os.path.join(_HERE, "snaps")
PAGE = "https://www.hl.co.uk/shares/stock-market-summary/ftse-aim-100"
CDX = ("http://web.archive.org/cdx/search/cdx?url="
       "hl.co.uk/shares/stock-market-summary/ftse-aim-100"
       "&from=2023&to=2026&output=json&collapse=timestamp:6&filter=statuscode:200")

# Young & Co's Brewery lists two share classes; HL carries both and they are
# one company. See aim100_asof.DUPES.
DUPES = {"YNGN.L"}


def download():
    """Fetch every archived capture the CDX index knows about."""
    os.makedirs(SNAPS, exist_ok=True)
    req = urllib.request.Request(CDX, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(r.read())
    stamps = [r[1] for r in rows[1:]]
    print(f"CDX reports {len(stamps)} captures")

    for ts in stamps:
        out = os.path.join(SNAPS, f"{ts[:8]}.html")
        if os.path.exists(out):
            continue
        url = f"https://web.archive.org/web/{ts}id_/{PAGE}"
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=45) as r:
                    open(out, "wb").write(r.read())
                print(f"  {ts[:8]} ok")
                break
            except Exception as exc:                      # transient, retry
                print(f"  {ts[:8]} attempt {attempt}: {exc}")
                time.sleep(3)
        time.sleep(1.5)


def parse_snapshot(path):
    """{yf_symbol: name} from one archived page, or {} if it is a JS shell."""
    html = open(path, encoding="utf-8", errors="replace").read()
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        return {}
    best = None
    for t in tables:
        cols = [str(c) for c in t.columns]
        if "EPIC" in cols and "Name" in cols:
            sub = t[["EPIC", "Name"]].dropna()
            sub = sub[sub["EPIC"].astype(str).str.match(r"^[A-Z0-9.&-]{1,7}$")]
            if best is None or len(sub) > len(best):
                best = sub
    if best is None:
        return {}
    return {to_yf_symbol(r.EPIC): str(r.Name).strip()
            for r in best.itertuples() if to_yf_symbol(r.EPIC) not in DUPES}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()
    if args.download:
        download()
    if not os.path.isdir(SNAPS):
        raise SystemExit("no snaps/ - run with --download first")

    timeline = {}
    for f in sorted(os.listdir(SNAPS)):
        if not f.endswith(".html"):
            continue
        ts = f[:-5]
        timeline[ts] = parse_snapshot(os.path.join(SNAPS, f))
        print(f"{ts}  n={len(timeline[ts]):3d}"
              + ("   <- JS shell, dropped" if not timeline[ts] else ""))

    dates = [d for d in sorted(timeline) if timeline[d]]
    print(f"\nusable captures: {len(dates)} of {len(timeline)} -> {dates}")

    transitions = []
    for prev, curr in zip(dates, dates[1:]):
        pm, cm = set(timeline[prev]), set(timeline[curr])
        entrants, leavers = sorted(cm - pm), sorted(pm - cm)
        print(f"{prev} -> {curr}: n={len(cm):3d}  +{len(entrants):2d}  -{len(leavers):2d}")
        transitions.append({"prev": prev, "curr": curr, "entrants": entrants,
                            "incumbents": sorted(cm - set(entrants)),
                            "leavers": leavers})

    json.dump(timeline, open(os.path.join(_HERE, "timeline.json"), "w"), indent=1)
    json.dump(transitions, open(os.path.join(_HERE, "transitions.json"), "w"), indent=1)
    print("\nwrote timeline.json, transitions.json")


if __name__ == "__main__":
    main()
