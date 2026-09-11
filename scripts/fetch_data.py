import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "nifty-heatmap-core"))

from nifty_heatmap_core import (
    NIFTY50, INDICES, FNO_ALL, fetch_all, build_rows, compute_movers, build_sectors,
)


def sort_by_pct(rows):
    return sorted(
        rows, key=lambda r: (r["pct"] if r["pct"] is not None else -999), reverse=True
    )


def main():
    # Nifty 50 is a strict subset of the F&O universe, so one sweep feeds both
    # boards: data.json (Nifty 50, shape unchanged for the Android app) and
    # sector_data.json (all F&O names grouped by sector).
    stocks, indices = fetch_all(FNO_ALL, INDICES, max_workers=25)
    generated_at = datetime.now(timezone.utc).isoformat()

    if "nifty" not in indices:
        print("Nifty 50 index missing, aborting write to avoid bad snapshot", file=sys.stderr)
        sys.exit(1)

    # ── data.json — Nifty 50 board (unchanged schema) ────────────────────────
    n50_rows = sort_by_pct(build_rows(NIFTY50, stocks))
    n50_gainers, n50_losers = compute_movers(n50_rows)
    n50_loaded = sum(1 for r in n50_rows if r["price"] is not None)
    if n50_loaded < 40:
        print(f"Only {n50_loaded}/50 Nifty tickers loaded, aborting", file=sys.stderr)
        sys.exit(1)

    with open("data.json", "w") as f:
        json.dump({
            "rows": n50_rows,
            "indices": indices,
            "gainers": n50_gainers,
            "losers": n50_losers,
            "generatedAt": generated_at,
        }, f)

    # ── sector_data.json — full F&O board, grouped by sector ─────────────────
    fno_rows = sort_by_pct(build_rows(FNO_ALL, stocks))
    fno_loaded = sum(1 for r in fno_rows if r["price"] is not None)
    if fno_loaded < 0.8 * len(FNO_ALL):
        print(f"Only {fno_loaded}/{len(FNO_ALL)} F&O tickers loaded, aborting", file=sys.stderr)
        sys.exit(1)

    fno_gainers, fno_losers = compute_movers(fno_rows)
    sectors = build_sectors(fno_rows)
    sectors.sort(key=lambda s: (s["avgPct"] if s["avgPct"] is not None else -999), reverse=True)

    advancers = sum(1 for r in fno_rows if r.get("pct") is not None and r["pct"] > 0)
    decliners = sum(1 for r in fno_rows if r.get("pct") is not None and r["pct"] < 0)

    with open("sector_data.json", "w") as f:
        json.dump({
            "sectors": sectors,
            "indices": indices,
            "gainers": fno_gainers,
            "losers": fno_losers,
            "breadth": {"advancers": advancers, "decliners": decliners, "total": fno_loaded},
            "generatedAt": generated_at,
        }, f)

    print(
        f"Wrote data.json ({n50_loaded}/{len(NIFTY50)}) and "
        f"sector_data.json ({fno_loaded}/{len(FNO_ALL)} across {len(sectors)} sectors); "
        f"breadth {advancers} up / {decliners} down"
    )


if __name__ == "__main__":
    main()
