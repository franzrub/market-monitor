#!/usr/bin/env python3
"""One daily refresh cycle, safely.

Rules:
  * every fetcher runs into a SCRATCH copy of data/; a source is only promoted to
    data/ if its output validates. A failed source keeps the last good file.
  * the page is only replaced if the build succeeds, so app/index.html is never
    left broken/half-written; the previous good page stays served.
  * writes data/run_status.json + logs/runs.log and prints a one-line summary.
"""
import json, os, shutil, subprocess, sys, datetime, tempfile
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA, APP, LOGS = (os.path.join(ROOT, d) for d in ("data", "app", "logs"))
TZ = ZoneInfo("Europe/Rome")
STALE_AFTER_H = 30          # a section older than this is flagged stale on the page

SOURCES = [
    ("quotes", "fetch_quotes.py", "quotes.json", 420,
     lambda d: bool(d.get("indices")) and bool(d.get("watchlist"))),
    ("pelosi", "fetch_pelosi.py", "pelosi.json", 420,
     lambda d: bool(d.get("ok")) and bool(d.get("rows"))),
    ("trump",  "fetch_trump.py",  "trump.json",  600,
     lambda d: bool(d.get("ok")) and bool(d.get("top_holdings"))),
]

def r_key(r):
    return "|".join(str(r.get(k) or (r.get("asset", "") if k == "ticker" else "")) for k in ("date", "ticker", "type", "amount"))

def run_one(name, script, out, timeout, validate):
    """Run a fetcher in a scratch dir; promote its output only if it validates."""
    scratch = tempfile.mkdtemp(prefix=f"refresh-{name}-")
    scratch_data = os.path.join(scratch, "data")
    os.makedirs(scratch_data, exist_ok=True)
    # the trump fetcher reuses a cached PDF; link it so we don't redownload 8 MB
    cache_src = os.path.join(DATA, "cache")
    if os.path.isdir(cache_src):
        shutil.copytree(cache_src, os.path.join(scratch_data, "cache"))
    try:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", script)],
                           capture_output=True, timeout=timeout,
                           env={**os.environ, "MARKET_DASH_ROOT": scratch})
        if r.returncode != 0:
            return False, f"exit {r.returncode}: {r.stderr.decode()[-160:].strip()}"
        path = os.path.join(scratch_data, out)
        d = json.load(open(path))
        if not validate(d):
            return False, "output failed validation (empty or incomplete)"
        # promote atomically, and keep any refreshed cache
        tmp = os.path.join(DATA, out + ".new")
        shutil.copyfile(path, tmp)
        os.replace(tmp, os.path.join(DATA, out))
        sc = os.path.join(scratch_data, "cache")
        if os.path.isdir(sc):
            shutil.copytree(sc, cache_src, dirs_exist_ok=True)
        partial = [e.get("symbol") for e in d.get("errors", [])]
        return True, ("partial: " + ", ".join(partial)) if partial else "ok"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

def main():
    started = datetime.datetime.now(TZ)
    os.makedirs(LOGS, exist_ok=True)
    results = {}
    for name, script, out, timeout, validate in SOURCES:
        ok, detail = run_one(name, script, out, timeout, validate)
        # how old is the data we will actually render?
        age_h = None
        try:
            d = json.load(open(os.path.join(DATA, out)))
            f = datetime.datetime.fromisoformat(d["fetched_at"])
            age_h = (datetime.datetime.now(datetime.timezone.utc) - f).total_seconds() / 3600
        except Exception:
            pass
        results[name] = {"ok": ok, "detail": detail, "age_hours": age_h,
                         "stale": (age_h is None or age_h > STALE_AFTER_H)}

    # --- which Pelosi disclosures are new since the previous run? -------------
    seen_path = os.path.join(DATA, "pelosi_seen.json")
    try:
        pel = json.load(open(os.path.join(DATA, "pelosi.json")))
        try:
            seen = set(json.load(open(seen_path)))
        except Exception:
            seen = set()          # first ever run: nothing is "new", avoid a false alarm
            seen = {r_key(r) for r in pel.get("rows", [])}
        pel["new_keys"] = [r_key(r) for r in pel.get("rows", []) if r_key(r) not in seen]
        json.dump(pel, open(os.path.join(DATA, "pelosi.json"), "w"), indent=1)
        new_seen = sorted(seen | {r_key(r) for r in pel.get("rows", [])})
    except Exception:
        new_seen = None

    # --- which Trump 278-T reports are new since the previous run? -------------
    tseen_path = os.path.join(DATA, "trump_seen.json")
    try:
        tr = json.load(open(os.path.join(DATA, "trump.json")))
        urls = [x["url"] for x in tr.get("transaction_reports", [])]
        try:
            tseen = set(json.load(open(tseen_path)))
        except Exception:
            tseen = set(urls)     # first run: seed, don't flag the whole history as new
        tr["new_reports"] = [u for u in urls if u not in tseen]
        json.dump(tr, open(os.path.join(DATA, "trump.json"), "w"), indent=1)
        new_tseen = sorted(tseen | set(urls))
    except Exception:
        new_tseen = None

    # build into a scratch file, replace the live page only on success
    build_ok, build_err = True, ""
    try:
        tmp_html = os.path.join(APP, "index.html.new")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build.py")],
                           capture_output=True, timeout=180,
                           env={**os.environ, "BUILD_OUT": tmp_html,
                                "RUN_STATUS": json.dumps(results)})
        if r.returncode != 0 or not os.path.exists(tmp_html) or os.path.getsize(tmp_html) < 4000:
            build_ok, build_err = False, r.stderr.decode()[-200:].strip() or "page too small"
        else:
            os.replace(tmp_html, os.path.join(APP, "index.html"))
    except Exception as e:
        build_ok, build_err = False, f"{type(e).__name__}: {e}"

    if build_ok and new_seen is not None:
        json.dump(new_seen, open(seen_path, "w"))
    if build_ok and new_tseen is not None:
        json.dump(new_tseen, open(tseen_path, "w"))

    status = {"run_at": started.isoformat(), "run_at_human": started.strftime("%Y-%m-%d %H:%M %Z"),
              "sources": results, "build_ok": build_ok, "build_error": build_err,
              "any_failure": (not build_ok) or any(not v["ok"] for v in results.values())}
    json.dump(status, open(os.path.join(DATA, "run_status.json"), "w"), indent=1)

    ok_names = [n for n, v in results.items() if v["ok"]]
    bad = [f"{n} ({v['detail']})" for n, v in results.items() if not v["ok"]]
    line = (f"{started.strftime('%Y-%m-%d %H:%M %Z')} — ok: {', '.join(ok_names) or 'none'}"
            f"{' | FAILED: ' + '; '.join(bad) if bad else ''}"
            f"{'' if build_ok else ' | BUILD FAILED: ' + build_err}")
    with open(os.path.join(LOGS, "runs.log"), "a") as f:
        f.write(line + "\n")
    print(line)
    print(json.dumps(status))

main()
