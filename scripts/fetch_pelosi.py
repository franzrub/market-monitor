#!/usr/bin/env python3
"""Nancy Pelosi's most recent disclosed transactions, from the official
U.S. House Clerk Periodic Transaction Reports (PTR).
Primary source: house-stock-watcher all_transactions.json (currently 403 / offline).
Fallback (used): disclosures-clerk.house.gov FD index + PTR PDFs."""
import json, os, re, io, sys, zipfile, urllib.request, datetime
import xml.etree.ElementTree as ET


def _root():
    return os.environ.get("MARKET_DASH_ROOT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(_root(), "data", "pelosi.json")
UA = {"User-Agent": "Mozilla/5.0"}
HSW = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
MAX_ROWS = 40
TYPE = {"P": "BUY", "S": "SELL", "S (partial)": "SELL (partial)", "E": "EXCHANGE"}

def get(url, timeout=90):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

def try_hsw():
    try:
        data = json.loads(get(HSW, 120))
    except Exception as e:
        return None, f"house-stock-watcher unavailable ({e})"
    rows = [r for r in data if "pelosi" in (r.get("representative") or "").lower()]
    rows.sort(key=lambda r: r.get("transaction_date", ""), reverse=True)
    out = [{"date": r["transaction_date"], "ticker": r.get("ticker", "--"),
            "asset": r.get("asset_description", ""), "type": r.get("type", ""),
            "amount": r.get("amount", ""), "disclosed": r.get("disclosure_date", "")}
           for r in rows[:10]]
    return (out, "House Stock Watcher (all_transactions.json)") if out else (None, "no Pelosi rows")

def clerk():
    filings = []
    year = datetime.date.today().year
    for y in (year, year - 1):
        try:
            z = zipfile.ZipFile(io.BytesIO(get(f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{y}FD.zip")))
        except Exception:
            continue
        xml = [n for n in z.namelist() if n.lower().endswith(".xml")][0]
        for m in ET.fromstring(z.read(xml).decode("utf-8-sig")):
            d = {c.tag: (c.text or "") for c in m}
            if d.get("Last", "").lower() == "pelosi" and d.get("FilingType") == "P":
                filings.append((y, d["DocID"], d["FilingDate"]))
    from pypdf import PdfReader
    txns, report = [], []
    for y, doc, filed in filings:
        try:
            pdf = get(f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{y}/{doc}.pdf")
            text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)
        except Exception as e:
            report.append({"doc": doc, "filed": filed, "rows": 0, "error": f"{type(e).__name__}: {e}"})
            continue
        text = " ".join(text.split())   # flatten PDF line wraps
        # asset block: "... (TICKER) [TYPE] <TXTYPE> MM/DD/YYYYMM/DD/YYYY $lo - $hi"
        # the two dates come out glued ("01/16/202601/16/2026") or spaced depending on the
        # PDF and the pypdf version — accept both. Ticker is optional (LLCs, private funds).
        pat = re.compile(
            r"(?:^|\s)(?:SP|JT|DC)\s+(?P<nm>.{3,140}?)\s*(?:\((?P<tk>[A-Z\.\-]{1,6})\)\s*)?\[(?P<cls>[A-Z]{2})\]\s*"
            r"(?P<tt>S \(partial\)|P|S|E)\s*(?P<d1>\d{2}/\d{2}/\d{4})\s*(?P<d2>\d{2}/\d{2}/\d{4})\s*"
            r"(?P<amt>\$[\d,]+(?:\.\d+)?(?:\s*-\s*\$[\d,]+)?)", re.S)
        found = 0
        for m in pat.finditer(text):
            found += 1
            name = " ".join(m.group("nm").split())
            txns.append({"date": m.group("d1"), "disclosed": filed, "ticker": m.group("tk") or "",
                         "asset": name, "class": m.group("cls"),
                         "class_label": {"ST": "stock", "OP": "options", "AB": "units/partnership",
                                          "MF": "mutual fund", "CS": "corporate securities"}.get(m.group("cls"), m.group("cls")),
                         "type": TYPE.get(m.group("tt"), m.group("tt")),
                         "amount": " ".join(m.group("amt").split()),
                         "doc": f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{y}/{doc}.pdf"})
        report.append({"doc": doc, "filed": filed, "rows": found})
    txns.sort(key=lambda t: datetime.datetime.strptime(t["date"], "%m/%d/%Y"), reverse=True)
    seen, uniq = set(), []
    for t in txns:
        k = (t["date"], t["ticker"] or t["asset"], t["type"], t["amount"], t["class"])
        if k in seen: continue
        seen.add(k); uniq.append(t)
    return uniq[:MAX_ROWS], report, "U.S. House Clerk — official Periodic Transaction Report PDFs (disclosures-clerk.house.gov)"

def main():
    rows, src = try_hsw()
    note, report = "", []
    if not rows:
        note = src
        rows, report, src = clerk()
    # a filing that is listed in the Clerk index but yields zero rows means the parser
    # broke on it: fail loudly (refresh.py keeps the last good file and shows the stale
    # bar) instead of silently reporting "no new filings".
    unparsed = [r for r in report if not r["rows"]]
    out = {"ok": bool(rows) and not unparsed, "member": "Nancy Pelosi (CA-11)", "source": src,
           "primary_source_note": note, "rows": rows, "filings": report, "unparsed_filings": unparsed,
           "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print(src, "|", len(rows), "rows |", len(report), "filings,", len(unparsed), "unparsed")
    for r in rows: print(" ", r["date"], r["ticker"] or r["asset"][:30], r["type"], r["amount"])
    if unparsed:
        sys.exit("unparsed PTR filings: " + ", ".join(f"{u['doc']} ({u['filed']})" for u in unparsed))

main()
