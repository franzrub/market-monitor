#!/usr/bin/env python3
"""Indices + watchlist quotes. Primary: Yahoo Finance chart API (no key).
Fallback: Stooq CSV (currently behind a JS anti-bot challenge)."""
import json, os, csv, io, math, time, random, subprocess, urllib.parse, datetime

def http_get(url, timeout=25):
    """Yahoo fingerprints python's TLS/HTTP stack and answers 429, so fetch via curl."""
    r = subprocess.run(["curl", "-sS", "--max-time", str(timeout), "-A", "Mozilla/5.0", url],
                       capture_output=True)
    if r.returncode != 0:
        raise IOError(f"curl {r.returncode}: {r.stderr.decode()[:120]}")
    return r.stdout


def _root():
    return os.environ.get("MARKET_DASH_ROOT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(_root(), "data", "quotes.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

MACRO = [("^VIX", "VIX", "volatility"), ("^TNX", "US 10Y yield", "rates"),
         ("EURUSD=X", "EUR/USD", "fx"), ("BTC-USD", "Bitcoin", "crypto")]

INDICES = [("^GSPC", "S&P 500", "US"), ("^IXIC", "Nasdaq Composite", "US"),
           ("^DJI", "Dow Jones Industrial Average", "US"), ("FTSEMIB.MI", "FTSE MIB (Italy)", "IT")]
WATCH = [("BRK-B", "Berkshire Hathaway Inc. Class B", "BRK.B"), ("GOOGL", "Alphabet Inc. Class A", None),
         ("NVDA", "NVIDIA Corporation", None), ("PANW", "Palo Alto Networks, Inc.", None),
         ("AMZN", "Amazon.com, Inc.", None), ("AVGO", "Broadcom Inc.", None),
         ("VST", "Vistra Corp.", None), ("AXON", "Axon Enterprise, Inc.", None),
         ("TEM", "Tempus AI, Inc.", None), ("LLY", "Eli Lilly and Company", None),
         ("TXN", "Texas Instruments Incorporated", None), ("INTC", "Intel Corporation", None),
         ("MU", "Micron Technology, Inc.", None), ("USAR", "USA Rare Earth, Inc.", None),
         ("UBER", "Uber Technologies, Inc.", None), ("IBM", "International Business Machines", None)]

def yahoo(symbol):
    last_err = None
    for attempt in range(6):
        host = "query1" if attempt % 2 == 0 else "query2"
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol)
               + "?range=6mo&interval=1d")
        try:
            raw = http_get(url)
            if b'"chart"' not in raw[:200]:
                raise IOError("unexpected payload: " + raw[:120].decode(errors="replace"))
            break
        except Exception as e:
            last_err = e
            time.sleep(1.2 * (attempt + 1) + random.random())
    else:
        raise last_err
    res = json.loads(raw)["chart"]["result"][0]
    meta, q = res["meta"], res["indicators"]["quote"][0]
    vols_raw = q.get("volume") or [None] * len(res["timestamp"])
    bars = [(t, c, v) for t, c, v in zip(res["timestamp"], q["close"], vols_raw) if c is not None]
    closes = [(t, c) for t, c, _ in bars]
    vols = [v for _, _, v in bars]
    last = meta.get("regularMarketPrice") or closes[-1][1]
    # prior *session* close: the second-to-last daily bar when the last bar is today's,
    # else the API's own previous close. (chartPreviousClose is the close before the
    # whole 1-month window, so it must never be used as the daily reference.)
    prev = closes[-2][1] if len(closes) >= 2 else meta.get("chartPreviousClose")
    if abs(last - closes[-1][1]) / closes[-1][1] > 0.25:   # stale/odd meta price
        last = closes[-1][1]
    week_ref = closes[-6][1] if len(closes) >= 6 else closes[0][1]
    month_ref = closes[-22][1] if len(closes) >= 22 else closes[0][1]
    spark = [c for _, c in closes[-30:]]
    hi52, lo52 = meta.get("fiftyTwoWeekHigh"), meta.get("fiftyTwoWeekLow")
    dhi, dlo = meta.get("regularMarketDayHigh"), meta.get("regularMarketDayLow")
    new_high = bool(hi52 and dhi and dhi >= hi52 * 0.9999)
    new_low = bool(lo52 and dlo and dlo <= lo52 * 1.0001)
    rng_pos = None
    if hi52 and lo52 and hi52 > lo52:
        rng_pos = max(0.0, min(1.0, (last - lo52) / (hi52 - lo52))) * 100
    # --- how unusual is today, for THIS name? -------------------------------
    # sigma = std dev of the daily returns of the ~20 sessions BEFORE today, so today's
    # own move can't inflate the yardstick it is measured against.
    LOOKBACK = 20
    rets = [(closes[i][1] / closes[i-1][1] - 1) * 100 for i in range(1, len(closes))]
    z = sigma = rvol = avg_vol = None
    if len(rets) >= LOOKBACK + 1:
        sample = rets[-(LOOKBACK + 1):-1]          # excludes today's return
        mean = sum(sample) / len(sample)
        var = sum((r - mean) ** 2 for r in sample) / (len(sample) - 1)
        sigma = math.sqrt(var)
        today_ret = (last / closes[-2][1] - 1) * 100 if len(closes) >= 2 else None
        if sigma > 1e-9 and today_ret is not None:
            z = today_ret / sigma
    prior_v = [v for v in vols[-(LOOKBACK + 1):-1] if v]
    if len(prior_v) >= LOOKBACK // 2 and vols and vols[-1]:
        avg_vol = sum(prior_v) / len(prior_v)
        if avg_vol > 0:
            rvol = vols[-1] / avg_vol
    return {"symbol": symbol,
            "z": z, "sigma": sigma, "rvol": rvol, "avg_vol": avg_vol,
            "volume": vols[-1] if vols else None, "bars": len(closes),
            "month_pct": (last / month_ref - 1) * 100 if month_ref else None,
            "spark": spark,
            "new_52w_high": new_high, "new_52w_low": new_low,
            "range_pos": rng_pos,
            "from_high_pct": ((last / hi52) - 1) * 100 if hi52 else None,
            "from_low_pct": ((last / lo52) - 1) * 100 if lo52 else None, "name": meta.get("longName") or meta.get("shortName"),
            "exchange": meta.get("fullExchangeName"), "currency": meta.get("currency"),
            "last": last, "prev_close": prev,
            "chg_pct": (last / prev - 1) * 100 if prev else None,
            "week_pct": (last / week_ref - 1) * 100 if week_ref else None,
            "wk52_high": meta.get("fiftyTwoWeekHigh"), "wk52_low": meta.get("fiftyTwoWeekLow"),
            "as_of": datetime.datetime.fromtimestamp(meta["regularMarketTime"],
                        datetime.timezone.utc).isoformat(),
            "market_tz": meta.get("exchangeTimezoneName"), "source": "Yahoo Finance"}

def stooq(symbol):
    s = symbol.lower().replace("^", "").replace("-", ".") + ".us"
    raw = http_get(f"https://stooq.com/q/d/l/?s={s}&i=d").decode(errors="replace")
    if not raw.lstrip().lower().startswith("date"):
        raise ValueError("stooq returned an anti-bot challenge page, not CSV")
    rows = list(csv.DictReader(io.StringIO(raw)))
    if len(rows) < 6: raise ValueError("stooq returned no data")
    c = [float(r["Close"]) for r in rows[-6:]]
    return {"symbol": symbol, "name": None, "exchange": None, "currency": None,
            "last": c[-1], "prev_close": c[-2], "chg_pct": (c[-1]/c[-2]-1)*100,
            "week_pct": (c[-1]/c[0]-1)*100, "wk52_high": None, "wk52_low": None,
            "as_of": rows[-1]["Date"], "market_tz": None, "source": "Stooq CSV (fallback)"}

def fetch(symbol):
    errs = []
    for fn in (yahoo, stooq):
        try:
            return fn(symbol), None
        except Exception as e:
            errs.append(f"{fn.__name__}: {e}")
    return None, "; ".join(errs)

def main():
    out = {"indices": [], "watchlist": [], "macro": [], "errors": [],
           "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    for sym, label, region in INDICES:
        time.sleep(0.7)
        d, err = fetch(sym)
        print("  .", sym, "ok" if d else "FAIL", flush=True)
        if d: d["label"] = label; d["region"] = region; out["indices"].append(d)
        else: out["errors"].append({"symbol": sym, "label": label, "error": err})
    for sym, label, kind in MACRO:
        time.sleep(0.7)
        d, err = fetch(sym)
        print("  .", sym, "ok" if d else "FAIL", flush=True)
        if d:
            d["label"] = label; d["kind"] = kind
            # ^TNX is published as a percentage by this endpoint, but has historically
            # been served as yield x10 — normalise defensively.
            if sym == "^TNX" and d["last"] and d["last"] > 25:
                for k in ("last", "prev_close"): 
                    if d.get(k): d[k] = d[k] / 10
            out["macro"].append(d)
        else:
            out["errors"].append({"symbol": sym, "label": label, "error": err})

    for sym, expect, requested in WATCH:
        time.sleep(0.7)
        d, err = fetch(sym)
        if not d:
            out["errors"].append({"symbol": requested or sym, "error": err}); continue
        d["requested"] = requested or sym
        d["expected"] = expect
        d["verified"] = bool(d["name"] and expect.split()[0].lower() in d["name"].lower())
        out["watchlist"].append(d)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print("indices", len(out["indices"]), "watchlist", len(out["watchlist"]), "errors", out["errors"])
    for w in out["watchlist"]:
        print(f"  {w['requested']:6} -> {w['symbol']:6} {w['name'][:34]:34} {w['last']:>10} {w['chg_pct']:+.2f}% verified={w['verified']}")

main()
