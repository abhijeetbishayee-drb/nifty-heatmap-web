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
    DAILY, WEEKLY, to_weekly, rrg_tail, equal_weight_series, min_bars, vol_tail,
    ret_tail, apply_corporate_actions, CORPORATE_ACTIONS,
)
from nifty_heatmap_core.corporate_actions import table_status, upcoming

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


def prepare(ticker_vals, bench_vals, weekly, dates):
    """Resample one aligned series and the benchmark onto the RRG timeframe.

    Returns (values, benchmark, dates) - the dates come back because the note
    about back-adjusted history has to be counted in the bars of whichever
    timeframe is being drawn, not always in trading days.
    """
    if ticker_vals is None:
        return None
    vals, first = ticker_vals
    bench = bench_vals[first:]
    d = dates[first:]
    if weekly:
        wd, vals = to_weekly(d, vals)
        _, bench = to_weekly(d, bench)
        d = wd
    return vals, bench, d


def points(prepped, cfg):
    """Compute the RRG tail for one prepared series."""
    if prepped is None:
        return None
    vals, bench = prepped[0], prepped[1]
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
    # The daily job is the right place to say whether the table is armed: its
    # log is short and read, unlike the per-minute price build.
    print(f"  {table_status()}")
    for ticker, spec, days in upcoming():
        print(f"  UPCOMING: {ticker} goes ex {spec['what']} in {days} day(s) "
              f"({spec['exDate']}) — confirm the ratio {spec['ratio']:.4f} "
              "before the date, the live board gets only one chance at it")

    print(f"fetching 5y daily history for {len(universe)} symbols…")
    hist = fetch_all(universe)

    bench_pairs = hist.get(BENCHMARK, [])
    if len(bench_pairs) < 300:
        print("benchmark history missing/too short, aborting", file=sys.stderr)
        sys.exit(1)
    dates = [t for t, _ in bench_pairs]
    bench_vals = [c for _, c in bench_pairs]

    aligned = {t: series_for(t, hist, dates) for t in universe}

    # Repair corporate-action gaps BEFORE anything downstream reads a price:
    # a raw demerger cliff distorts volatility, absolute return, relative
    # strength and every basket the name sits in, so it is fixed once, here.
    ca, unreviewed = {}, {}
    for t, a in aligned.items():
        if a is None:
            continue
        vals, first = a
        fixed, off, note, unrev = apply_corporate_actions(
            dates[first:], vals, CORPORATE_ACTIONS.get(t))
        aligned[t] = (fixed, first + off)
        if note:
            ca[t] = note
        if unrev:
            unreviewed[t] = unrev
    for t, note in sorted(ca.items()):
        kind = note["kind"]
        print(f"  {short_name(t):12} {note['what']} ({note['date']}) — "
              + ("history truncated to the event; usable bars: "
                 f"{note['since']}" if kind == "economic"
                 else "back-adjusted"))
    # Anything large and unclassified is REPORTED, never guessed at: it cannot
    # be told from a real move without external data, and most of these are
    # real (ADANIENT/Hindenburg, INDUSINDBK, IEX). Review adds it to
    # CORPORATE_ACTIONS or leaves it alone.
    if unreviewed:
        print(f"  note: {len(unreviewed)} symbol(s) have large unclassified "
              "gaps, left untouched: "
              + ", ".join(f"{short_name(t)}({','.join(d for d, _ in v)})"
                          for t, v in sorted(unreviewed.items())))

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "benchmark": {"ticker": BENCHMARK, "label": BENCH_LABEL},
        "note": ("Approximation of JdK RS-Ratio/RS-Momentum, not the licensed "
                 "formula. Every symbol is z-scored over an identical window; "
                 "symbols with less history are excluded, not rescaled. "
                 "vol is trailing annualised realised volatility in percent, "
                 "one value per tail point; ret is the trailing absolute "
                 "return in percent over the same stretch the tail covers. "
                 "Either can be the Z axis of the 3D view. Corporate-action "
                 "gaps are back-adjusted onto the post-event basis; adj marks "
                 "a record whose window still spans one, and disappears once "
                 "the window holds only genuine post-event bars. Cosmetic "
                 "corporate actions (splits, bonuses) are back-adjusted; after "
                 "an economic one (a demerger) usable history starts at the "
                 "event, because the pre-event bars belong to a larger "
                 "company and are not comparable with the name's peers."),
        "config": {"daily": DAILY, "weekly": WEEKLY},
        "sectors": {}, "stocks": {}, "excluded": {},
    }

    for period, cfg, weekly in (("daily", DAILY, False), ("weekly", WEEKLY, True)):
        excluded = []

        # ── stocks ──────────────────────────────────────────────────────
        stocks = []
        for sector, tickers in FNO_SECTORS.items():
            for t in tickers:
                prepped = prepare(aligned.get(t), bench_vals, weekly, dates)
                tail = points(prepped, cfg)
                if tail is None:
                    note = ca.get(t)
                    if note and note["kind"] == "economic":
                        have = len(prepped[2]) if prepped else 0
                        reason = (f"{note['what']} on {note['date']} — only "
                                  f"{have} of {min_bars(cfg)} bars are "
                                  "post-event, so there is not yet enough of "
                                  "this company's own history to compare it "
                                  "with its peers")
                    else:
                        reason = "insufficient history"
                    excluded.append({"name": short_name(t), "ticker": t,
                                     "sector": sector, "reason": reason,
                                     "ca": bool(note and note["kind"] == "economic")})
                    continue
                stocks.append({"name": short_name(t), "ticker": t, "sector": sector,
                               "cashOnly": t in CASH_ONLY, "tail": tail,
                               "vol": vol_tail(prepped[0], cfg, len(tail)),
                               "ret": ret_tail(prepped[0], cfg, len(tail))})

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
            tail, prepped = None, None
            if cons:
                synth = equal_weight_series(cons)
                if synth:
                    prepped = prepare((synth, start), bench_vals, weekly, dates)
                    tail = points(prepped, cfg)
            if tail is None:
                excluded.append({"name": sector, "kind": "sector",
                                 "reason": "no constituent covers the window"})
                continue
            sectors.append({"name": sector, "kind": "synthetic",
                            "label": f"{sector} (equal-weight)",
                            "count": len(tickers), "basis": len(used),
                            "dropped": dropped, "tail": tail,
                            "vol": vol_tail(prepped[0], cfg, len(tail)),
                            "ret": ret_tail(prepped[0], cfg, len(tail))})

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
