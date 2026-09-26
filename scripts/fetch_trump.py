#!/usr/bin/env python3
"""Trump's OGE disclosures:
  * the most recent Form 278e ANNUAL (holdings in value ranges, once a year), and
  * every Form 278-T PERIODIC TRANSACTION report filed since then (actual purchases/sales).
Both are discovered through OGE's own index API instead of hard-coded URLs, which change
with every filing. 278-Ts are scanned PDFs: the text layer is OCR-noisy and some have none
at all, in which case we OCR them with tesseract when it is installed."""
import json, re, os, time, subprocess, datetime, hashlib, shutil, tempfile

OGE_API = "https://extapps2.oge.gov/201/Presiden.nsf/API.xsp/v2/rest?start=0&length=100000&search%5Bvalue%5D=Trump"
# last known annual — used only if the OGE index API is unreachable
FALLBACK_ANNUAL = {"url": "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index/69AEAA9D7455ACD585258E27002DDEE1/$FILE/Donald-J-Trump-2026-278ANNUAL.pdf",
                   "label": "Annual (2026)", "date": "2026-07-01"}
T_LOOKBACK_DAYS = 365      # 278-T reports shown: filed within the last year...
T_MAX_FILINGS = 8          # ...and at most this many
OCR_BUDGET_S = int(os.environ.get("OCR_BUDGET_S", "780"))   # per-run OCR wall clock
OCR_DPI = int(os.environ.get("OCR_DPI", "200"))            # native scan resolution
OCR_PSM = os.environ.get("OCR_PSM", "4")                   # 278-T pages are wide tables
_ocr_spent = [0.0]

def _root():
    return os.environ.get("MARKET_DASH_ROOT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(_root(), "data", "trump.json")
CACHE = os.path.join(_root(), "data", "cache", "trump278.pdf")
CACHE_URL = CACHE + ".url"
TCACHE = os.path.join(_root(), "data", "cache", "278t")
os.makedirs(TCACHE, exist_ok=True)

RANGE = r"(?:None \(or less than \$[\d,]+\)|Over \$[\d,]+|\$[\d,]+ ?- ?\$[\d,]+)"
RANGE_RE = re.compile(RANGE)

def lo_hi(s):
    if s.startswith("None"):
        return 0, 1000
    if s.startswith("Over"):
        v = int(re.sub(r"[^\d]", "", s)); return v, v * 2
    a, b = re.findall(r"\$[\d,]+", s)
    return int(a[1:].replace(",", "")), int(b[1:].replace(",", ""))

MAX_CACHE_AGE = 7 * 86400   # the 278e is an ANNUAL filing: re-download weekly, not daily

def curl(url, dest, timeout=300):
    tmp = dest + ".new"
    r = subprocess.run(["curl", "-sS", "-L", "--max-time", str(timeout), "-A", "Mozilla/5.0",
                        "-o", tmp, url], capture_output=True)
    ok = r.returncode == 0 and os.path.exists(tmp) and open(tmp, "rb").read(5) == b"%PDF-"
    if ok:
        os.replace(tmp, dest)
    elif os.path.exists(tmp):
        os.remove(tmp)
    return ok

# ------------------------------------------------------------------ discovery
def discover():
    """All of Trump's filings from the OGE index: [{label, url, date}] newest first.
    The index is a ~7 MB JSON document, so a short read can truncate it: retry, and
    ignore anything in it that is not a well-formed row."""
    last = ""
    for attempt in range(3):
        r = subprocess.run(["curl", "-sS", "-L", "--max-time", "300", "--retry", "2",
                            "-A", "Mozilla/5.0", OGE_API], capture_output=True)
        if r.returncode != 0:
            last = f"curl exit {r.returncode}: {r.stderr.decode()[-120:]}"
            continue
        try:
            doc = json.loads(r.stdout)
        except Exception as e:
            last = f"malformed index ({len(r.stdout)} bytes): {type(e).__name__}"
            continue
        rows = doc.get("data") if isinstance(doc, dict) else doc
        if not isinstance(rows, list) or not rows:
            last = "index contained no rows"
            continue
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not str(row.get("name", "")).lower().startswith("trump, donald"):
                continue
            m = re.search(r"href='([^']*)'>([^<]*)", str(row.get("type", "")))
            if m and ".pdf" in m.group(1).lower():
                out.append({"url": m.group(1), "label": m.group(2).strip(),
                            "date": str(row.get("docDate", ""))[:10]})
        if out:
            out.sort(key=lambda f: f["date"], reverse=True)
            return out
        last = "no Trump filings found in the index"
    raise IOError(f"OGE index API unusable: {last}")

# ------------------------------------------------------------------ 278-T
T_RANGES = [(1001, 15000), (15001, 50000), (50001, 100000), (100001, 250000), (250001, 500000),
            (500001, 1000000), (1000001, 5000000), (5000001, 25000000), (25000001, 50000000)]
# "lourchaso", "l ourchaso", "lpUrchaSO", "IDUrchaso", "salo", "Sale (partial)", "Exchanao"...
T_LINE = re.compile(
    r"^(?P<n>\d{1,4})\s+(?P<desc>.+?)\s+(?P<tt>[A-Za-z]{0,3}\s?[a-zA-Z]{0,2}u?rcha\w*|sal[eo]\w*(?:\s*\(partial\))?|[Ee]xchan\w*)"
    r"\s+(?P<rest>.*)$", re.I)

def t_type(tt):
    t = tt.lower()
    if "rcha" in t: return "BUY"
    if "xchan" in t: return "EXCHANGE"
    return "SELL (partial)" if "partial" in t else "SELL"

def t_date(rest):
    """OCR turns '/' into '1' and splits digits ('717/2026', '7/812026', '7/22/20 26')."""
    m = re.match(r"([\d/ ]{6,12}\d)", rest)
    if not m: return ""
    raw = m.group(1).replace(" ", "")
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", raw): return raw
    m2 = re.fullmatch(r"(\d{1,2})/(\d)1(\d{4})", raw)         # 7/812026 -> 7/8/2026
    if m2: return f"{m2.group(1)}/{m2.group(2)}/{m2.group(3)}"
    return ""                                                    # ambiguous: don't guess

def t_amount(rest):
    """Lower bound of the reported range, snapped to the standard OGE brackets."""
    m = re.search(r"\$?\s?S?(\d[\d,\. ]{2,12}\d)\s*[-–•·]", rest)
    if not m: return "", 0, 0
    lo = int(re.sub(r"\D", "", m.group(1)))
    for a, b in T_RANGES:
        if lo == a: return f"${a:,} – ${b:,}", a, b
    if lo == 50000001: return "Over $50,000,000", 50000001, 50000001
    return "", 0, 0

def have_ocr():
    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))

def text_layer(path):
    from pypdf import PdfReader
    pages = [(p.extract_text() or "") for p in PdfReader(path).pages]
    return "\n".join(pages) if sum(len(p.strip()) for p in pages) > 50 * len(pages) else ""

_TESS_ENV = {**os.environ, "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1"}

def ocr(path):
    """OCR a scanned filing. The text is cached beside the PDF and keyed by the PDF's
    own bytes, so a filing is only ever OCR'd once; pages run in parallel."""
    cache = path + ".ocr.txt"
    stamp = hashlib.sha1(open(path, "rb").read()).hexdigest()
    if os.path.exists(cache):
        head, _, body = open(cache, encoding="utf-8", errors="replace").read().partition("\n")
        if head == stamp:
            return body
    if _ocr_spent[0] >= OCR_BUDGET_S:
        raise TimeoutError("OCR budget for this run is spent")
    t0 = time.time()
    d = tempfile.mkdtemp(prefix="ocr-")
    try:
        subprocess.run(["pdftoppm", "-r", str(OCR_DPI), "-gray", "-png", path, os.path.join(d, "p")],
                       check=True, capture_output=True, timeout=600)
        pages = [os.path.join(d, f) for f in sorted(os.listdir(d))]
        workers = max(1, min(len(pages), (os.cpu_count() or 2)))
        procs = [(p, subprocess.Popen(["tesseract", p, "-", "--psm", OCR_PSM],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_TESS_ENV))
                 for p in pages[:workers]]
        queue, out = pages[workers:], {}
        while procs:
            p, pr = procs.pop(0)
            try:
                so, _ = pr.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                pr.kill(); so = b""
            out[p] = so.decode(errors="replace")
            if queue:
                nxt = queue.pop(0)
                procs.append((nxt, subprocess.Popen(["tesseract", nxt, "-", "--psm", OCR_PSM],
                                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_TESS_ENV)))
        text = "\n".join(out[p] for p in pages)
        try:
            open(cache, "w", encoding="utf-8").write(stamp + "\n" + text)
        except Exception:
            pass
        return text
    finally:
        _ocr_spent[0] += time.time() - t0
        shutil.rmtree(d, ignore_errors=True)

def parse_278t(text):
    rows, seen = [], set()
    for line in text.splitlines():
        line = " ".join(line.split())
        m = T_LINE.match(line)
        if not m: continue
        desc = m.group("desc").strip(" .-")
        if len(desc) < 3 or desc.lower().startswith(("page", "transactions")): continue
        amt, lo, hi = t_amount(m.group("rest"))
        r = {"n": int(m.group("n")), "description": desc, "type": t_type(m.group("tt")),
             "date": t_date(m.group("rest")), "amount": amt, "lo": lo, "hi": hi}
        k = (r["n"], desc.upper()[:40], r["type"])
        if k in seen: continue
        seen.add(k); rows.append(r)
    return rows

def declared(rows):
    """Line items the report numbers (1..N): a robust max of the parsed item numbers."""
    ns = sorted(r["n"] for r in rows)
    return ns[int(len(ns) * 0.97)] if ns else 0

def coverage(rows):
    return min(1.0, len(rows) / declared(rows)) if rows else 0.0

def transactions(filings, annual_date):
    since = (datetime.date.today() - datetime.timedelta(days=T_LOOKBACK_DAYS)).isoformat()
    picked = [f for f in filings if f["label"].startswith("278 Transaction") and f["date"] >= since][:T_MAX_FILINGS]
    out = []
    for f in picked:
        path = os.path.join(TCACHE, hashlib.sha1(f["url"].encode()).hexdigest()[:16] + ".pdf")
        entry = {"url": f["url"], "filed": f["date"], "name": f["url"].split("$FILE/")[-1],
                 "after_annual": f["date"] >= annual_date}
        if not (os.path.exists(path) or curl(f["url"], path, 180)):
            out.append({**entry, "ok": False, "method": "", "error": "download failed", "rows": []}); continue
        try:
            text, method = text_layer(path), "text layer"
            rows = parse_278t(text) if text else []
            # the embedded OCR layer of some filings is garbage: re-OCR when coverage is poor
            if coverage(rows) < 0.5 and have_ocr():
                try:
                    o_rows = parse_278t(ocr(path))
                except TimeoutError:
                    out.append({**entry, "ok": False, "method": "OCR deferred",
                                "error": "scanned filing, OCR deferred to the next run",
                                "rows": []})
                    print(f"  278-T {f['date']} {entry['name'][:48]:48} OCR deferred (budget spent)")
                    continue
                if len(o_rows) > len(rows):
                    text, rows, method = "x", o_rows, "tesseract OCR"
            if not text and not rows:
                method = "image-only PDF" + ("" if have_ocr() else ", tesseract not installed")
        except Exception as e:
            out.append({**entry, "ok": False, "method": "", "error": f"{type(e).__name__}: {e}", "rows": []}); continue
        out.append({**entry, "ok": bool(rows), "method": method,
                    "error": "" if rows else (method if not text else "no transaction lines recognised"),
                    "rows": rows,
                    "buys": sum(r["type"] == "BUY" for r in rows),
                    "sells": sum(r["type"].startswith("SELL") for r in rows),
                    "lo": sum(r["lo"] for r in rows), "hi": sum(r["hi"] for r in rows),
                    "unpriced": sum(not r["amount"] for r in rows),
                    "declared": declared(rows), "coverage": round(coverage(rows), 2)})
        print(f"  278-T {f['date']} {entry['name'][:48]:48} {method:14} {len(rows)} rows, coverage {coverage(rows):.0%}")
    return out

def main():
    try:
        filings, disc_err = discover(), ""
    except Exception as e:
        filings, disc_err = [], f"{type(e).__name__}: {e}"
    annual = next((f for f in filings if f["label"].lower().startswith("annual")), None) or FALLBACK_ANNUAL
    cached_url = open(CACHE_URL).read().strip() if os.path.exists(CACHE_URL) else ""
    fresh = os.path.exists(CACHE) and cached_url == annual["url"] and os.path.getsize(CACHE) > 1_000_000 \
            and (time.time() - os.path.getmtime(CACHE)) < MAX_CACHE_AGE
    if not fresh:
        if curl(annual["url"], CACHE) and os.path.getsize(CACHE) > 1_000_000:
            open(CACHE_URL, "w").write(annual["url"])
        elif not os.path.exists(CACHE):
            raise IOError("could not download the OGE 278e PDF and no cached copy exists")
        else:
            annual = {**annual, "url": cached_url or annual["url"]}
    from pypdf import PdfReader
    reader = PdfReader(CACHE)
    account, rows = None, []
    line_re = re.compile(r"^(\d{1,4})\s+(.{3,220}?)\s+(N/A|EIF|Yes|No)\s+(" + RANGE + r")\s*(.*)$")
    for page in reader.pages:
        for line in (page.extract_text() or "").splitlines():
            line = " ".join(line.split())
            if re.match(r"^(INVESTMENT ACCOUNT #\d+|SCHEDULE \d+\b.*)$", line):
                account = line; continue
            m = line_re.match(line)
            if not m: continue
            desc, val, tail = m.group(2).strip(), m.group(4), m.group(5).strip()
            inc = RANGE_RE.search(tail)
            lo, hi = lo_hi(val)
            rows.append({"account": account, "description": desc, "value_range": val,
                         "income_type": RANGE_RE.sub("", tail).strip(" -") or "None",
                         "income_range": inc.group(0) if inc else "", "lo": lo, "hi": hi})
    agg = {}
    for r in rows:
        a = agg.setdefault(r["description"].upper(),
                           {"description": r["description"], "lo": 0, "hi": 0, "lots": 0})
        a["lo"] += r["lo"]; a["hi"] += r["hi"]; a["lots"] += 1
    top = sorted(agg.values(), key=lambda x: -x["lo"])[:25]
    txns = transactions(filings, annual["date"])
    ry = re.search(r"\((\d{4})\)", annual["label"])
    out = {"source": f"U.S. Office of Government Ethics — OGE Form 278e ({annual['label']}"
                     f"{', report year ' + str(int(ry.group(1)) - 1) if ry else ''}; posted by OGE {annual['date']})",
           "source_url": annual["url"], "annual_date": annual["date"],
           "discovery_error": disc_err, "transaction_reports": txns, "filer": "Donald J. Trump, President of the United States",
           "report_type": "ANNUAL ASSET DISCLOSURE — value ranges only, not live trades",
           "line_items_parsed": len(rows), "unique_assets": len(agg), "top_holdings": top,
           "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "ok": len(rows) > 0}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print("parsed", len(rows), "line items;", len(agg), "unique assets")
    if disc_err: print("  discovery failed, used fallback annual URL:", disc_err)
    for t in top[:12]: print(f"  {t['description'][:60]:60} ${t['lo']:,}-{t['hi']:,} ({t['lots']} lots)")

main()
