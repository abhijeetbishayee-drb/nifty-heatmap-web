"""Build rrg_data.json - Relative Rotation Graph points for the whole board.

Runs once a day after the close, not on the per-minute cadence: it pulls 5y of
daily history for ~230 symbols (~25 MB) and RRG is read off daily/weekly bars,
so minute refreshes would buy nothing.

Staleness is decided here rather than by a GitHub cron, because GitHub throttles
scheduled workflows hard (observed 1-2h late). The per-minute pinger that already
drives the price workflow calls this with --if-stale; it exits immediately unless
the file predates the most recent post-close boundary.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "nifty-heatmap-core"))

from nifty_heatmap_core import (
    HEADERS, FNO_SECTORS, FNO_ALL, SECTOR_INDICES, CASH_ONLY, short_name,
)
from nifty_heatmap_core.rrg import (
    DAILY, WEEKLY, to_weekly, rrg_tail, equal_weight_series, min_bars,
)

BENCHMARK = "^NSEI"
BENCH_LABEL = "NIFTY 50"
OUT = "rrg_data.json"

IST = timezone(timedelta(hours=5, minutes=30))
POST_CLOSE_HOUR = 16  # IST; NSE cash closes 15:30, derivatives 15:40


def last_post_close(now_ist):
    """Most recent 16:00 IST boundary."""
    boundary = now_ist.replace(hour=POST_CLOSE_HOUR, minute=0, second=0, microsecond=0)
    if now_ist < boundary:
        boundary -= timedelta(days=1)
    return boundary


def is_stale(path):
    if not os.path.exists(path):
        return True
    try:
        with open(path) as f:
            gen = datetime.fromisoformat(json.load(f)["generatedAt"])
    except Exception:
        return True
    return gen.astimezone(IST) < last_post_close(datetime.now(IST))


def fetch(ticker, rng="5y"):
    sym = ticker.replace("^", "%5E")
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?interval=1d&range={rng}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        d = r.json()["chart"]["result"][0]
        pairs = [(t, c) for t, c in zip(d["timestamp"],
                                        d["indicators"]["quote"][0]["close"]) if c is not None]
        return ticker, pairs
    except Exception:
        return ticker, []


def fetch_all(tickers, workers=20):
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(fetch, t) for t in tickers]):
            t, pairs = f.result()
            out[t] = pairs
    return out


def align(pairs, dates):
    """Project a series onto `dates`, carrying the last known close forward.
    Returns None if the series never covers the window."""
    if not pairs:
        return None
    m = dict(pairs)
    out, last = [], None
    for d in dates:
        if d in m:
            last = m[d]
        out.append(last)
    first = next((i for i, v in enumerate(out) if v is not None), None)
    if first is None:
        return None
    return out, first


def series_for(ticker, hist, dates):
    got = align(hist.get(ticker, []), dates)
    if got is None:
        return None
    vals, first = got
    return vals[first:], first


def points(ticker_vals, bench_vals, cfg, weekly, dates):
    """Compute the RRG tail for one aligned series."""
    if ticker_vals is None:
        return None
    vals, first = ticker_vals
    bench = bench_vals[first:]
    if weekly:
        wd = dates[first:]
        _, vals = to_weekly(wd, vals)
        _, bench = to_weekly(wd, bench)
    if len(vals) < min_bars(cfg):
        return None
    return rrg_tail(vals, bench, cfg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-stale", action="store_true",
                    help="exit without fetching unless the file predates the last post-close")
    args = ap.parse_args()

    if args.if_stale and not is_stale(OUT):
        print("rrg_data.json is current for the latest close; skipping")
        return

    sector_index_tickers = [v["ticker"] for v in SECTOR_INDICES.values()]
    universe = sorted(set(FNO_ALL) | set(sector_index_tickers) | {BENCHMARK})
    print(f"fetching 5y daily history for {len(universe)} symbols…")
    hist = fetch_all(universe)

    bench_pairs = hist.get(BENCHMARK, [])
    if len(bench_pairs) < 300:
        print("benchmark history missing/too short, aborting", file=sys.stderr)
        sys.exit(1)
    dates = [t for t, _ in bench_pairs]
    bench_vals = [c for _, c in bench_pairs]

    aligned = {t: series_for(t, hist, dates) for t in universe}

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "benchmark": {"ticker": BENCHMARK, "label": BENCH_LABEL},
        "note": ("Approximation of JdK RS-Ratio/RS-Momentum, not the licensed "
                 "formula. Every symbol is z-scored over an identical window; "
                 "symbols with less history are excluded, not rescaled."),
        "config": {"daily": DAILY, "weekly": WEEKLY},
        "sectors": {}, "stocks": {}, "excluded": {},
    }

    for period, cfg, weekly in (("daily", DAILY, False), ("weekly", WEEKLY, True)):
        excluded = []

        # ── stocks ──────────────────────────────────────────────────────
        stocks = []
        for sector, tickers in FNO_SECTORS.items():
            for t in tickers:
                tail = points(aligned.get(t), bench_vals, cfg, weekly, dates)
                if tail is None:
                    excluded.append({"name": short_name(t), "ticker": t,
                                     "sector": sector, "reason": "insufficient history"})
                    continue
                stocks.append({"name": short_name(t), "ticker": t, "sector": sector,
                               "cashOnly": t in CASH_ONLY, "tail": tail})

        # ── sectors: equal-weighted synthetic, uniformly ────────────────
        # Yahoo serves NO history for 10 of the 12 NSE sectoral indices
        # (verified 2026-09-26 across 1mo..5y: ^CNXAUTO, ^CNXMETAL, ^CNXREALTY,
        # ^CNXFMCG, NIFTY_IND_DEFENCE, NIFTY_HEALTHCARE, NIFTY_CEMENT,
        # NIFTY_CHEMICALS, NIFTY_CONSR_DURBL, NIFTY_OIL_AND_GAS all return a
        # single bar); only ^CNXIT and ^NSEBANK carry a real series. Rather
        # than mix two float-weighted indices with 21 equal-weighted synthetics
        # - which would put non-comparable points on one chart, the same error
        # as mixing normalisation windows - EVERY sector uses the same
        # equal-weighted construction.
        need = min_bars(cfg) + 20 if not weekly else min_bars(cfg) * 5 + 60
        sectors = []
        for sector, tickers in FNO_SECTORS.items():
            start = max(0, len(dates) - need)
            cons, used, dropped = [], [], []
            for t in tickers:
                a = aligned.get(t)
                # keep only constituents present across the WHOLE window: a
                # recent listing would otherwise truncate the entire sector
                # (VAML alone shortened Metals & Mining to 75 bars).
                if a is not None and a[1] <= start:
                    cons.append(a[0][start - a[1]:])
                    used.append(short_name(t))
                else:
                    dropped.append(short_name(t))
            tail = None
            if cons:
                synth = equal_weight_series(cons)
                if synth:
                    tail = points((synth, start), bench_vals, cfg, weekly, dates)
            if tail is None:
                excluded.append({"name": sector, "kind": "sector",
                                 "reason": "no constituent covers the window"})
                continue
            sectors.append({"name": sector, "kind": "synthetic",
                            "label": f"{sector} (equal-weight)",
                            "count": len(tickers), "basis": len(used),
                            "dropped": dropped, "tail": tail})

        out["stocks"][period] = stocks
        out["sectors"][period] = sectors
        out["excluded"][period] = excluded
        print(f"  {period:6}: {len(sectors)} sectors, {len(stocks)} stocks, "
              f"{len(excluded)} excluded")

    with open(OUT, "w") as f:
        json.dump(out, f)
    print(f"wrote {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
