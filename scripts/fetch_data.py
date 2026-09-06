import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "nifty-heatmap-core"))

from nifty_heatmap_core import NIFTY50, INDICES, fetch_all, build_rows, compute_movers


def main():
    stocks, indices = fetch_all(NIFTY50, INDICES)
    rows = build_rows(NIFTY50, stocks)
    rows.sort(key=lambda r: (r["pct"] if r["pct"] is not None else -999), reverse=True)
    gainers, losers = compute_movers(rows)

    out = {
        "rows": rows,
        "indices": indices,
        "gainers": gainers,
        "losers": losers,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }

    loaded = sum(1 for r in rows if r["price"] is not None)
    if loaded < 40:
        print(f"Only {loaded}/50 tickers loaded, aborting write to avoid bad snapshot", file=sys.stderr)
        sys.exit(1)
    if "nifty" not in indices:
        print("Nifty 50 index missing, aborting write to avoid bad snapshot", file=sys.stderr)
        sys.exit(1)

    with open("data.json", "w") as f:
        json.dump(out, f)

    print(f"Wrote data.json with {loaded}/50 stocks, indices={indices}")


if __name__ == "__main__":
    main()
