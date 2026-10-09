#!/usr/bin/env python3
"""Week-to-date and month-to-date ranges for the Nifty 50 tiles.

WHAT "RANGE" MEANS HERE
-----------------------
The range covers ONLY THE SESSIONS THAT HAVE HAPPENED. On a Wednesday the
weekly range is Monday to Wednesday, not a trailing seven days and not a
projected full week, so a tile never shows a high the week has not yet
reached. The tile pairs it with how much of the period has passed, which is
the whole point: a month range on the 2nd and on the 28th are not comparable
numbers, and nothing on the tile said which one you were looking at.

WHY THIS IS A DAILY JOB AND NOT PART OF THE MINUTE SWEEP
--------------------------------------------------------
Completed daily bars cannot change intraday, so fetching 50 histories every
minute would buy nothing. This writes the COMPLETED part once a day and
fetch_data.py folds today's live high/low into it on every refresh -- the
same split that lets the board run a one-minute cadence at all.

TODAY'S BAR IS EXCLUDED, DELIBERATELY
-------------------------------------
Yahoo returns a forming candle for the current session. Including it here
would double-count today against the live quote the minute job already has,
and before the open it would carry yesterday's values under today's date.
Today enters the range exactly once, from the live sweep.
"""
from __future__ import annotations

import json
import os
import sys
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta, date

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "nifty-heatmap-core"))
from nifty_heatmap_core import NIFTY50, HEADERS           # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
OUT = os.path.join(REPO_ROOT, "periods.json")


def fetch(ticker: str):
    """[(ist_date, high, low)] of completed daily bars, newest last."""
    sym = ticker.replace("^", "%5E")
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?interval=1d&range=3mo")
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        d = r.json()["chart"]["result"][0]
        q = d["indicators"]["quote"][0]
        rows = []
        for ts, hi, lo in zip(d["timestamp"], q["high"], q["low"]):
            if hi is None or lo is None:
                continue
            rows.append((datetime.fromtimestamp(ts, IST).date(), float(hi), float(lo)))
        return ticker, rows
    except Exception:
        return ticker, []


def weekdays_between(a: date, b: date) -> int:
    """Mon-Fri days in [a, b] inclusive. NSE holidays are NOT excluded -- this
    stack keeps no holiday calendar, by a decision made elsewhere for good
    reasons, so the TOTAL can overstate a holiday week by a day. The elapsed
    count beside it comes from real bars, so the pair reads as
    'sessions so far / weekdays in the period' and the tooltip says exactly
    that rather than implying a precision we do not have."""
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def main() -> int:
    today = datetime.now(IST).date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    week_end = week_start + timedelta(days=4)
    month_end = today.replace(day=monthrange(today.year, today.month)[1])

    out, got = {}, 0
    with ThreadPoolExecutor(max_workers=20) as ex:
        for f in as_completed([ex.submit(fetch, t) for t in NIFTY50]):
            ticker, rows = f.result()
            if not rows:
                continue
            got += 1
            # `d < today` is the exclusion of the forming bar.
            wk = [(h, l) for d, h, l in rows if week_start <= d < today]
            mo = [(h, l) for d, h, l in rows if month_start <= d < today]
            rec = {}
            if wk:
                rec["wHigh"] = round(max(h for h, _ in wk), 2)
                rec["wLow"] = round(min(l for _, l in wk), 2)
            if mo:
                rec["mHigh"] = round(max(h for h, _ in mo), 2)
                rec["mLow"] = round(min(l for _, l in mo), 2)
            rec["wBars"] = len(wk)
            rec["mBars"] = len(mo)
            out[ticker] = rec

    if got < 0.8 * len(NIFTY50):
        print(f"only {got}/{len(NIFTY50)} histories fetched, refusing to write",
              file=sys.stderr)
        return 1

    doc = {
        "asof": today.isoformat(),
        # Elapsed counts INCLUDE today, which is in progress: the tile is
        # showing today's prices, so today is a session you are looking at.
        # COMPLETED sessions only, and the period each belongs to. The reader
        # adds today and decides whether these still apply -- this file is
        # built after one close and read through the NEXT session, so on a
        # Monday the week stamped here is last week's.
        "week":  {"start": week_start.isoformat(),
                  "bars": max(r["wBars"] for r in out.values()),
                  "total": weekdays_between(week_start, week_end)},
        "month": {"start": month_start.isoformat(),
                  "bars": max(r["mBars"] for r in out.values()),
                  "total": weekdays_between(month_start, month_end)},
        "names": out,
    }
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    print(f"periods.json: {len(out)}/{len(NIFTY50)} names · "
          f"week {doc['week']['bars']}+today/{doc['week']['total']} · "
          f"month {doc['month']['bars']}+today/{doc['month']['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
