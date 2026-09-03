import json
import sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

NIFTY50 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "HCLTECH.NS",
    "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "BAJFINANCE.NS", "WIPRO.NS",
    "ONGC.NS", "NTPC.NS", "POWERGRID.NS", "NESTLEIND.NS", "TECHM.NS",
    "M&M.NS", "ADANIENT.NS", "ADANIPORTS.NS", "COALINDIA.NS", "JSWSTEEL.NS",
    "TVSMOTOR.NS", "TATASTEEL.NS", "BAJAJFINSV.NS", "BPCL.NS", "DRREDDY.NS",
    "CIPLA.NS", "EICHERMOT.NS", "HEROMOTOCO.NS", "INDUSINDBK.NS", "GRASIM.NS",
    "APOLLOHOSP.NS", "BRITANNIA.NS", "DIVISLAB.NS", "TATACONSUM.NS", "SBILIFE.NS",
    "HDFCLIFE.NS", "BAJAJ-AUTO.NS", "UPL.NS", "LTM.NS", "HINDALCO.NS",
]

SHORT_NAMES = {
    "HINDUNILVR.NS": "HINDUNILVR", "BHARTIARTL.NS": "BHARTIARTL",
    "BAJAJFINSV.NS": "BAJAJFINSV", "APOLLOHOSP.NS": "APOLLOHOSP",
    "TATACONSUM.NS": "TATACONSUM", "HEROMOTOCO.NS": "HEROMOTOCO",
    "INDUSINDBK.NS": "INDUSINDBK", "ULTRACEMCO.NS": "ULTRACEMCO",
    "BAJAJ-AUTO.NS": "BAJAJ-AUTO", "ADANIPORTS.NS": "ADANIPORTS",
    "BAJFINANCE.NS": "BAJFINANCE", "COALINDIA.NS": "COALINDIA",
    "TVSMOTOR.NS": "TVSMOTOR",
}


def short_name(ticker):
    if ticker in SHORT_NAMES:
        return SHORT_NAMES[ticker]
    return ticker.replace(".NS", "").replace("-", "")[:10]


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def fetch_one(ticker):
    try:
        sym = "%5ENSEI" if ticker == "^NSEI" else ticker
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        pct = meta.get("regularMarketChangePercent")
        pts = meta.get("fulldayChange")
        return ticker, (price, pct, pts)
    except Exception:
        return ticker, (None, None, None)


def main():
    all_tickers = ["^NSEI"] + NIFTY50
    stocks = {}
    index_data = {}

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_one, t): t for t in all_tickers}
        for future in as_completed(futures):
            ticker, (price, pct, pts) = future.result()
            if ticker == "^NSEI":
                if price is not None:
                    index_data = {"price": price, "pct": pct, "pts": pts}
            else:
                stocks[ticker] = (price, pct, pts)

    rows = []
    for ticker, (price, pct, pts) in stocks.items():
        rows.append({
            "ticker": ticker,
            "name": short_name(ticker),
            "price": price,
            "pct": pct,
            "pts": pts,
        })
    rows.sort(key=lambda r: (r["pct"] if r["pct"] is not None else -999), reverse=True)

    valid = [r for r in rows if r["pct"] is not None]
    gainers = sorted(valid, key=lambda r: r["pct"], reverse=True)[:5]
    losers = sorted(valid, key=lambda r: r["pct"])[:5]

    out = {
        "rows": rows,
        "index": index_data,
        "gainers": gainers,
        "losers": losers,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }

    loaded = sum(1 for r in rows if r["price"] is not None)
    if loaded < 40:
        print(f"Only {loaded}/50 tickers loaded, aborting write to avoid bad snapshot", file=sys.stderr)
        sys.exit(1)

    with open("data.json", "w") as f:
        json.dump(out, f)

    print(f"Wrote data.json with {loaded}/50 stocks, index={index_data}")


if __name__ == "__main__":
    main()
