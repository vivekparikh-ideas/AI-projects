"""Record frozen eval inputs from live data (D-045). Free (SEC EDGAR + Yahoo, no model calls).

    python evals/record.py                       # the Phase 1 tickers
    python evals/record.py --tickers AAPL,MSFT   # more (Phase 2)
    python evals/record.py --force               # re-record (resets the baseline: rerun the full eval after)

Snapshots go to evals/snapshots/<TICKER>.json and are committed: they are the golden inputs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.cases import PHASE1_TICKERS, SNAPSHOT_DIR  # noqa: E402
from nexus.data import snapshot  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", help="comma-separated; default: the Phase 1 tickers")
    ap.add_argument("--force", action="store_true", help="overwrite existing snapshots")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    from nexus.data.live import LiveProvider

    live = LiveProvider()
    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else PHASE1_TICKERS
    for t in tickers:
        path = SNAPSHOT_DIR / f"{t}.json"
        if path.exists() and not args.force:
            print(f"  {t:5s} exists ({path.relative_to(ROOT)}); pass --force to re-record")
            continue
        snap = snapshot.record(live, t)
        errors = [k for k, v in snap["calls"].items() if isinstance(v, dict) and "__error__" in v]
        snapshot.save(snap, SNAPSHOT_DIR)
        note = f" · {len(errors)} calls failed and will fail on replay too: {', '.join(errors)}" if errors else ""
        print(f"  {t:5s} recorded as of {snap['as_of']} · sha {snapshot.sha(snap)} · {len(snap['calls'])} calls{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
