import json
import os
import sys
from datetime import datetime, timezone, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "nifty-heatmap-core"))

from nifty_heatmap_core import (
    NIFTY50, INDICES, FNO_ALL, SECTOR_INDEX_TICKERS,
    fetch_all, build_rows, compute_movers, build_sectors, attach_sector_indices,
    build_pinned_groups,
)
from nifty_heatmap_core.corporate_actions import live_warnings


def sort_by_pct(rows):
    return sorted(
        rows, key=lambda r: (r["pct"] if r["pct"] is not None else -999), reverse=True
    )


IST = timezone(timedelta(hours=5, minutes=30))
BREADTH_FILE = "breadth_today.json"
OPEN_MIN, CLOSE_MIN = 9 * 60 + 15, 15 * 60 + 30


def record_breadth(advancers, decliners, total):
    """Append today's advance/decline counts to an intraday series.

    The board already knew breadth, but only as a snapshot -- the number was
    there and its SHAPE was not, so you could see 190 up / 44 down without
    seeing that it had been 120/110 an hour earlier. This keeps one point per
    minute for the current session, which is what the floating tracker draws.

    Deliberately TODAY only. The file resets on the first run of a new IST
    date, so it cannot grow without bound, and a full session is ~375 points
    (~10 KB) rather than a history nobody asked for.

    Outside 09:15-15:30 IST nothing is appended, so after the close the series
    keeps the shape it ended with instead of flat-lining through the evening
    on repeated snapshots of the same closing prices.

    Keyed by minute and REPLACED rather than appended within the same minute:
    the refresh runs about once a minute but not exactly, and two points for
    09:47 would put a vertical step in a line that is meant to read as time.
    """
    now = datetime.now(IST)
    mins = now.hour * 60 + now.minute
    today = now.strftime("%Y-%m-%d")

    doc = {"date": today, "total": total, "points": []}
    if os.path.exists(BREADTH_FILE):
        try:
            with open(BREADTH_FILE) as f:
                prev = json.load(f)
            if prev.get("date") == today:
                doc = prev
        except (OSError, ValueError):
            pass                      # a corrupt file is not worth a dead board

    if OPEN_MIN <= mins <= CLOSE_MIN:
        pts = doc["points"]
        if pts and pts[-1][0] == mins:
            pts[-1] = [mins, advancers, decliners]
        else:
            pts.append([mins, advancers, decliners])
        doc["total"] = total

    with open(BREADTH_FILE, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    return doc


def main():
    # Nifty 50 is a strict subset of the F&O universe, so one sweep feeds both
    # boards: data.json (Nifty 50, shape unchanged for the Android app) and
    # sector_data.json (all F&O names grouped by sector).
    # One sweep covers the stocks, the two headline indices and the sectoral
    # indices. Fetch them keyed BY TICKER, because a single ticker can serve
    # more than one consumer - ^NSEBANK backs both the pinned BANK NIFTY group
    # and the Banks sector, and a ticker->name dict would silently drop one.
    all_index_tickers = set(INDICES) | set(SECTOR_INDEX_TICKERS)
    stocks, by_ticker = fetch_all(
        FNO_ALL, {t: t for t in all_index_tickers}, max_workers=25)

    indices = {name: by_ticker[t] for t, name in INDICES.items() if t in by_ticker}
    sector_snaps = {sec: by_ticker[t]
                    for t, sec in SECTOR_INDEX_TICKERS.items() if t in by_ticker}
    fetched = indices
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
    sectors = attach_sector_indices(build_sectors(fno_rows), sector_snaps)
    sectors.sort(key=lambda s: (s["avgPct"] if s["avgPct"] is not None else -999), reverse=True)
    for s in sectors:
        s["pinned"] = False
    with_index = sum(1 for s in sectors if s["index"])

    # NIFTY 50 and BANK NIFTY ride above the sectors and never re-sort.
    pinned = build_pinned_groups(fno_rows, fetched)
    sectors = pinned + sectors

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

    breadth_doc = record_breadth(advancers, decliners, fno_loaded)

    # Silent on an ordinary day; speaks up only when a corporate action is
    # near, has just been applied, or was listed for today and did NOT fire -
    # the last of which means the table is wrong and the board is showing a
    # raw cliff right now.
    for line in live_warnings(fno_rows):
        print(line)

    print(
        f"Wrote data.json ({n50_loaded}/{len(NIFTY50)}) and "
        f"sector_data.json ({fno_loaded}/{len(FNO_ALL)} across {len(sectors) - len(pinned)} sectors "
        f"+ {len(pinned)} pinned, "
        f"{with_index} with a live sectoral index); breadth {advancers} up / {decliners} down"
        f" ({len(breadth_doc['points'])} pts today)"
    )


if __name__ == "__main__":
    main()
