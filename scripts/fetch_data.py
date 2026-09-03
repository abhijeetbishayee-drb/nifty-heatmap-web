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


INDICES = {
    "^NSEI": "nifty",
    "^NSEBANK": "banknifty",
}


def fetch_one(ticker):
    try:
        sym = ticker.replace("^", "%5E")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        pct = meta.get("regularMarketChangePercent")
        pts = meta.get("fulldayChange")
        day_high = meta.get("regularMarketDayHigh")
        day_low = meta.get("regularMarketDayLow")
        return ticker, (price, pct, pts, day_high, day_low)
    except Exception:
        return ticker, (None, None, None, None, None)


def main():
    all_tickers = list(INDICES.keys()) + NIFTY50
    stocks = {}
    indices = {}

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_one, t): t for t in all_tickers}
        for future in as_completed(futures):
            ticker, (price, pct, pts, day_high, day_low) = future.result()
            if ticker in INDICES:
                if price is not None:
                    indices[INDICES[ticker]] = {
                        "price": price, "pct": pct, "pts": pts,
                        "dayHigh": day_high, "dayLow": day_low,
                    }
            else:
                stocks[ticker] = (price, pct, pts, day_high, day_low)

    rows = []
    for ticker, (price, pct, pts, day_high, day_low) in stocks.items():
        off_low = None
        if price is not None and day_low:
            off_low = (price - day_low) / day_low * 100
        off_high = None
        if price is not None and day_high:
            off_high = (price - day_high) / day_high * 100
        rows.append({
            "ticker": ticker,
            "name": short_name(ticker),
            "price": price,
            "pct": pct,
            "pts": pts,
            "offLow": off_low,
            "offHigh": off_high,
            "dayHigh": day_high,
            "dayLow": day_low,
        })
    rows.sort(key=lambda r: (r["pct"] if r["pct"] is not None else -999), reverse=True)

    # Top gainers: biggest bounce off the day's low. Top losers: biggest drop off the day's high.
    valid_low = [r for r in rows if r["offLow"] is not None]
    valid_high = [r for r in rows if r["offHigh"] is not None]
    gainers = sorted(valid_low, key=lambda r: r["offLow"], reverse=True)[:5]
    losers = sorted(valid_high, key=lambda r: r["offHigh"])[:5]

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
