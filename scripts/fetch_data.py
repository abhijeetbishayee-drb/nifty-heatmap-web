import json
import os
import sys
from calendar import monthrange
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
PERIODS_FILE = "periods.json"


def _weekdays(a, b):
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def attach_periods(rows):
    """Fold today's live high/low into the committed week- and month-to-date
    ranges, and hand the tile the elapsed tenure.

    build_periods.py writes the COMPLETED sessions once a day and deliberately
    leaves today out; today enters here, exactly once, from the live sweep.
    That split is why a 50-name history fetch does not have to run every
    minute.

    THE STORED PERIOD IS CHECKED, NOT TRUSTED. periods.json is built after one
    close and read through the next session, so on a Monday the week it stamps
    is LAST week's -- folding today into that range would show a weekly high
    the week had not reached, every Monday, and on the 1st of a month the same
    for the month. When the stored period is not the current one it is dropped
    and the range starts from today alone, which is exactly what a first
    session of a period is.

    A name with no record -- a fresh constituent whose history did not come
    back -- gets no block at all and the tile falls back to the day bar, rather
    than showing today's range labelled as a month.
    """
    try:
        with open(PERIODS_FILE) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None

    today = datetime.now(IST).date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    cur = {
        "week": (week_start, week_start + timedelta(days=4)),
        "month": (month_start,
                  today.replace(day=monthrange(today.year, today.month)[1])),
    }
    fresh = {k: (doc.get(k, {}).get("start") == cur[k][0].isoformat())
             for k in cur}

    names = doc.get("names", {})
    for r in rows:
        rec = names.get(r["ticker"])
        if r.get("price") is None:
            continue
        hi_today = r.get("dayHigh") or r["price"]
        lo_today = r.get("dayLow") or r["price"]
        for pfx, key in (("w", "week"), ("m", "month")):
            hi = rec.get(pfx + "High") if (rec and fresh[key]) else None
            lo = rec.get(pfx + "Low") if (rec and fresh[key]) else None
            hi = max(hi, hi_today) if hi is not None else hi_today
            lo = min(lo, lo_today) if lo is not None else lo_today
            if hi > lo:
                r[key] = {"high": round(hi, 2), "low": round(lo, 2)}

    return {k: {"start": cur[k][0].isoformat(),
                "elapsed": (doc.get(k, {}).get("bars", 0) if fresh[k] else 0) + 1,
                "total": _weekdays(*cur[k])}
            for k in cur} | {"asof": today.isoformat()}


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

    # Must run BEFORE the write: it adds the week/month blocks to the rows.
    tenure = attach_periods(n50_rows)

    with open("data.json", "w") as f:
        json.dump({
            "rows": n50_rows,
            "indices": indices,
            "gainers": n50_gainers,
            "losers": n50_losers,
            "tenure": tenure,
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
    )


if __name__ == "__main__":
    main()
