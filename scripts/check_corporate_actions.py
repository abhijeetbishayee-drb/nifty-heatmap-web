"""Weekly check for corporate actions that this board has not accounted for.

Two halves, and the second is the one that finds real problems.

FORWARD  - upcoming gap-creating actions in our universe, so an entry can go
           into CORPORATE_ACTIONS before the ex-date. The live heatmap path
           gets exactly one chance at a name's ex-date, so notice is the whole
           point. NSE's daily file looks about 11 days ahead, so a weekly run
           gives roughly one to two weeks of warning - enough, but not more.

BACK     - actions whose ex-date has just passed, checked against the actual
           price series. This exists because WE CANNOT PREDICT WHETHER YAHOO
           WILL HANDLE AN ACTION. Measured 2026-09-27: Yahoo adjusted PGIL's
           1:1 bonus (ex 2026-09-11) correctly and left no gap, while it left
           MOTILALOFS, PARAS and TRENT gapping in the raw series. Only the
           price series can say which happened, so this looks, and reports a
           miss with the exact ratio to paste in.

DIVIDENDS ARE DELIBERATELY EXCLUDED - see SKIP_PURPOSE below.

Source is NSE's PR archive, which serves the corporate-action file without the
Akamai block that stops the main API. Exits non-zero when something needs a
human, so the weekly workflow fails loudly rather than logging into the void.
"""

import csv
import datetime as dt
import io
import os
import re
import sys
import zipfile

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "nifty-heatmap-core"))

from nifty_heatmap_core import FNO_ALL, NIFTY50, HEADERS, SECTOR_OF
from nifty_heatmap_core.corporate_actions import (
    CORPORATE_ACTIONS, CORP_ACTION_JUMP, RATIO_TOL,
)

PR_URL = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{}.zip"
FILES_WANTED = 14          # trading days of corporate-action files to union
DAYS_TRIED = 24            # calendar days to walk back to find them
BACK_WINDOW = 45           # days after an ex-date to keep re-checking it

# A dividend moves the price on its ex-date too, and it is deliberately NOT
# treated as a corporate action here. Three reasons, in order of weight:
#
#  1. BENCHMARK CONSISTENCY, which is decisive. The RRG measures every name
#     against ^NSEI, and NIFTY 50 is a PRICE index - it does not add dividends
#     back either (that is NIFTY 50 TRI, a different index). Adjusting the
#     constituents for dividends while the benchmark is not adjusted would
#     bias relative strength UPWARD for every high-yield name. Price against
#     price is the only consistent pairing, and Yahoo's `close` is already on
#     that basis.
#  2. It is what the number is supposed to mean. The heatmap shows the session
#     price change, which is what a holder sees in their portfolio and what
#     NSE and every broker quote. Nobody adjusts an intraday % for dividends.
#  3. Size. Measured across our universe on 2026-09-27, the largest dividend
#     was SAIL at 1.27% of price - twelve times below the 15% floor the live
#     detector needs, so it could not fire even if it were listed.
#
# A very large special dividend is the edge case, and it is handled by NOT
# handling it: it would show up in the build's unclassified-gap report for a
# human to judge, rather than being silently rewritten.
SKIP_PURPOSE = ("DIV",)

GAP_KINDS = (
    ("DEMERGER", ("DEMERGER", "SPIN OFF", "SPIN-OFF", "SPINOFF")),
    ("SPLIT", ("SPLIT", "SUB-DIVISION", "SUBDIVISION", "SUB DIVISION")),
    ("BONUS", ("BONUS",)),
)

BONUS_RE = re.compile(r"BONUS\s*(\d+)\s*:\s*(\d+)")
SPLIT_RE = re.compile(r"FROM\s*RS?\.?\s*([\d.]+).*?TO\s*RS?\.?\s*([\d.]+)")


def universe():
    return {t.replace(".NS", ""): t for t in set(FNO_ALL) | set(NIFTY50)}


def classify(purpose):
    """(kind, ratio) for a gap-creating action, else (None, None).

    ratio is the factor the price is multiplied by on the ex-date, taken from
    the ANNOUNCED TERMS - the only ratio worth dividing out. A demerger has
    none: its ex-value is discovered across the resulting entities.
    """
    p = purpose.upper().strip()
    if p.startswith(SKIP_PURPOSE):
        return None, None
    kind = next((k for k, words in GAP_KINDS if any(w in p for w in words)), None)
    if kind is None:
        return None, None
    if kind == "BONUS":
        m = BONUS_RE.search(p)
        # "BONUS a:b" = a new shares for every b held -> b/(a+b)
        return kind, (int(m.group(2)) / (int(m.group(1)) + int(m.group(2)))) if m else None
    if kind == "SPLIT":
        m = SPLIT_RE.search(p)
        return kind, (float(m.group(2)) / float(m.group(1))) if m else None
    return kind, None


def fetch_actions():
    """Union the corporate-action file from the last few trading days."""
    out, day, got, tried = {}, dt.date.today(), 0, 0
    while got < FILES_WANTED and tried < DAYS_TRIED:
        tried += 1
        try:
            r = requests.get(PR_URL.format(day.strftime("%d%m%y")),
                             headers=HEADERS, timeout=40)
            if r.status_code == 200:
                z = zipfile.ZipFile(io.BytesIO(r.content))
                name = next(n for n in z.namelist() if n.startswith("bc"))
                for row in csv.DictReader(io.StringIO(z.read(name).decode("utf-8", "replace"))):
                    if row.get("SERIES", "").strip() == "EQ" and row.get("EX_DT"):
                        out[(row["SYMBOL"], row["EX_DT"], row["PURPOSE"])] = row
                got += 1
        except Exception:
            pass
        day -= dt.timedelta(days=1)
    return out, got


def observed_gap(ticker, ex_date, expect_ratio):
    """The unadjusted gap this action left in the price series, or None.

    None means Yahoo already handled it and there is nothing to add, which is
    the usual outcome - PGIL's 1:1 bonus left no gap at all.

    This does NOT look only around the ex-date, because Yahoo's dating cannot
    be trusted: it puts MOTILALOFS's June bonus on 1 January, five months out.
    So when the announced terms give a ratio, the whole series is searched for
    a gap MATCHING THAT RATIO - the same ratio-over-date discipline the
    adjustment itself uses. A demerger has no announced ratio, so it falls
    back to the largest gap near the ex-date.
    """
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1d&range=2y")
    try:
        d = requests.get(url, headers=HEADERS, timeout=30).json()["chart"]["result"][0]
        bars = [(dt.datetime.fromtimestamp(t, dt.timezone.utc).date(), c)
                for t, c in zip(d["timestamp"], d["indicators"]["quote"][0]["close"]) if c]
    except Exception:
        return None

    best = None
    for i in range(1, len(bars)):
        day, close = bars[i]
        prev = bars[i - 1][1]
        if not prev:
            continue
        ratio = close / prev
        if abs(ratio - 1) < CORP_ACTION_JUMP:
            continue
        if expect_ratio:
            if abs(ratio - expect_ratio) > RATIO_TOL * expect_ratio:
                continue
        elif abs((day - ex_date).days) > 10:
            continue
        if best is None or abs(ratio - 1) > abs(best[1] - 1):
            best = (day, ratio)
    return best


def main():
    today = dt.date.today()
    uni = universe()
    actions, files = fetch_actions()
    print(f"read {files} NSE corporate-action files, {len(actions)} EQ rows")

    mine, upcoming, misses, handled = [], [], [], []
    for row in actions.values():
        sym = row["SYMBOL"]
        if sym not in uni:
            continue
        kind, ratio = classify(row["PURPOSE"])
        if kind is None:
            continue
        ex = dt.date.fromisoformat(row["EX_DT"])
        mine.append((sym, ex, kind, ratio, row["PURPOSE"].strip()))

    for sym, ex, kind, ratio, purpose in sorted(mine, key=lambda x: x[1]):
        ticker = uni[sym]
        listed = ticker in CORPORATE_ACTIONS
        if ex >= today:
            upcoming.append((sym, ticker, ex, kind, ratio, purpose, listed))
        elif (today - ex).days <= BACK_WINDOW and not listed:
            gap = observed_gap(ticker, ex, ratio)
            (misses if gap else handled).append((sym, ticker, ex, kind, ratio, purpose, gap))

    if upcoming:
        print("\nUPCOMING in this board's universe:")
        for sym, ticker, ex, kind, ratio, purpose, listed in upcoming:
            days = (ex - today).days
            mark = "already listed" if listed else "NOT in CORPORATE_ACTIONS"
            rtxt = f"ratio {ratio:.4f}" if ratio else "ratio discovered on the day (demerger)"
            print(f"  {sym:13} ex {ex} (in {days:2}d)  {purpose[:34]:34} {rtxt} — {mark}")
        if any(not u[6] for u in upcoming):
            print("  Add the unlisted ones BEFORE their ex-date; the live board "
                  "gets one chance. A demerger is kind='economic' (reads NA), a "
                  "bonus or split is 'cosmetic' (shows the adjusted %).")

    if handled:
        print("\nRecent actions Yahoo already adjusted — nothing to do:")
        for sym, _t, ex, kind, _r, purpose, _g in handled:
            print(f"  {sym:13} ex {ex}  {purpose[:40]} — no gap in the price series")

    if misses:
        print("\nACTION NEEDED — unadjusted gap in the price series, not in the table:")
        for sym, ticker, ex, kind, ratio, purpose, gap in misses:
            gday, gratio = gap
            econ = kind == "DEMERGER"
            print(f"  {sym:13} ex {ex}  {purpose[:40]}")
            print(f"      gap on {gday}, observed ratio {gratio:.4f}"
                  + (f", announced {ratio:.4f}" if ratio else ""))
            print(f'      "{ticker}": {{"what": "{purpose.title()}", '
                  f'"kind": "{"economic" if econ else "cosmetic"}",\n'
                  f'                   "date": "{ex.strftime("%-d %b %Y")}", '
                  f'"exDate": "{ex}",\n'
                  f'                   "ratio": {ratio if ratio else round(gratio, 4)}}},')
        print(f"\n{len(misses)} action(s) need an entry in CORPORATE_ACTIONS.")
        return 1

    if not upcoming and not handled:
        print("\nNothing in this board's universe in the window. Note the "
              "horizon: NSE's file looks ~11 days ahead, so this gives one to "
              "two weeks of notice, not more.")
    print("\nNo missing corporate actions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
