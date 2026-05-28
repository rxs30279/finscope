"""Memory & GC instrumentation for the Render worker.

Emits one structured line per call, greppable with `[mem]`. Designed to let
us pinpoint which pipeline stage hits the 512 MB Render ceiling.

Fields: run, stage, event, rss_mb (current), peak_mb (process lifetime peak),
gc_objs (live Python objects), plus any kwargs.
"""

import gc
import os
import sys
from typing import Optional

try:
    import resource  # Unix-only; absent on Windows
except ImportError:
    resource = None

try:
    import psutil
    _proc = psutil.Process(os.getpid())
except Exception:
    psutil = None
    _proc = None


def snapshot(stage: str, event: str, run_id: Optional[int] = None, **extra) -> None:
    parts = ["[mem]"]
    if run_id is not None:
        parts.append(f"run={run_id}")
    parts.append(f"stage={stage}")
    parts.append(f"event={event}")

    if _proc is not None:
        try:
            mi = _proc.memory_info()
            parts.append(f"rss_mb={mi.rss / 1024 / 1024:.1f}")
        except Exception:
            pass

    if resource is not None:
        try:
            # ru_maxrss is KB on Linux (Render), bytes on macOS.
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak_mb = peak / 1024 / 1024 if sys.platform == "darwin" else peak / 1024
            parts.append(f"peak_mb={peak_mb:.1f}")
        except Exception:
            pass

    try:
        parts.append(f"gc_objs={len(gc.get_objects())}")
    except Exception:
        pass

    for k, v in extra.items():
        parts.append(f"{k}={v}")

    print(" ".join(parts), flush=True)
