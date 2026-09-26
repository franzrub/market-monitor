#!/usr/bin/env python3
"""Render data/*.json into one self-contained HTML page.
All CSS inline, sparklines are inline SVG, no external assets, no runtime JS calls.
Never fails the whole page on one bad source."""
import json, os, html, datetime, math
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TZ = ZoneInfo("Europe/Rome")
OUT_HTML = os.environ.get("BUILD_OUT") or os.path.join(ROOT, "app", "index.html")
try:
    STATUS = json.loads(os.environ.get("RUN_STATUS") or "{}")
except Exception:
    STATUS = {}

WATCH_TICKERS = {"BRK.B", "BRK-B", "GOOGL", "NVDA", "PANW", "AMZN", "AVGO", "VST", "AXON",
                 "TEM", "LLY", "TXN", "INTC", "MU", "USAR", "UBER", "IBM"}
ACR = {"Etf": "ETF", "Inc": "Inc.", "Llc": "LLC", "Lp": "LP", "Us": "U.S.", "Spdr": "SPDR",
       "S&p": "S&P", "Nvidia": "NVIDIA", "Ibm": "IBM", "Reit": "REIT", "Corp": "Corp.", "Tr": "Trust"}

def load(name):
    try:
        return json.load(open(os.path.join(ROOT, "data", name)))
    except Exception:
        return None

def pkey(r):
    """Identity of a Pelosi transaction; ticker-less assets (LLCs, funds) fall back to the name."""
    return "|".join(str(r.get(k) or (r.get("asset", "") if k == "ticker" else "")) for k in ("date", "ticker", "type", "amount"))

# issuer-name fragments used to spot watchlist names inside OGE free-text descriptions
WATCH_NAMES = {"NVDA": "NVIDIA", "AVGO": "BROADCOM", "GOOGL": "ALPHABET", "AMZN": "AMAZON",
               "IBM": "INTERNATIONAL BUSINESS MACH", "LLY": "LILLY", "TXN": "TEXAS INSTRUMENT",
               "INTC": "INTEL CORP", "MU": "MICRON", "UBER": "UBER TECH", "PANW": "PALO ALTO",
               "VST": "VISTRA", "AXON": "AXON ENTERPRISE", "TEM": "TEMPUS", "USAR": "USA RARE EARTH",
               "BRK.B": "BERKSHIRE"}

def watch_hit(desc):
    d = (desc or "").upper()
    return next((tk for tk, nm in WATCH_NAMES.items() if nm in d), None)

def esc(s): return html.escape(str(s if s is not None else ""))
def nice(s): return " ".join(ACR.get(w, w) for w in s.title().split())

def fmt(v, cur="", idx=False):
    if v is None: return "n/a"
    sym = {"USD": "$", "EUR": "€"}.get(cur, "")
    if idx: return f"{sym}{v:,.0f}"
    return f"{sym}{v:,.2f}" if abs(v) < 10000 else f"{sym}{v:,.0f}"

def cls_of(v, eps=0.0005):
    return "up" if v is not None and v > eps else ("down" if v is not None and v < -eps else "flat")

def pct(v, small=False):
    if v is None: return '<span class="muted">n/a</span>'
    c = cls_of(v)
    a = "▲" if c == "up" else ("▼" if c == "down" else "▬")
    return f'<span class="chg {c}{" sm" if small else ""}"><span class="arw">{a}</span>{v:+.2f}%</span>'

def spark(vals, w=86, h=22):
    """Inline SVG sparkline, no library, no external asset."""
    vals = [v for v in (vals or []) if v is not None]
    if len(vals) < 3:
        return '<span class="muted sm">—</span>'
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    n = len(vals)
    pts = " ".join(f"{i*(w-2)/(n-1)+1:.1f},{h-1-((v-lo)/span)*(h-2):.1f}" for i, v in enumerate(vals))
    up = vals[-1] >= vals[0]
    col = "#0a7d5a" if up else "#b3261e"
    last_x, last_y = (w - 1), h - 1 - ((vals[-1] - lo) / span) * (h - 2)
    return (f'<svg class="spk" width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.5" '
            f'stroke-linejoin="round" stroke-linecap="round" opacity=".85"/>'
            f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="1.9" fill="{col}"/></svg>')

def range_tag(pos):
    if pos is None: return ""
    if pos >= 80: return '<span class="rtag hi">near high</span>'
    if pos <= 20: return '<span class="rtag lo">near low</span>'
    return '<span class="rtag mid">mid-range</span>'

def zfmt(w):
    z = w.get("z")
    if z is None:
        return ('<span class="muted sm" title="not enough history or no variance">n/a</span>')
    c = "unu" if abs(z) >= 2 else ("" if abs(z) >= 1 else "faint")
    return f'<span class="zs {c}">{z:+.1f}\u03c3</span>'

def rvfmt(w):
    r = w.get("rvol")
    if r is None: return '<span class="muted sm">n/a</span>'
    c = "unu" if r >= 2 else ("" if r >= 1 else "faint")
    return f'<span class="zs {c}">{r:.1f}\u00d7</span>'

def unusual(w):
    return (w.get("z") is not None and abs(w["z"]) >= 2) or (w.get("rvol") is not None and w["rvol"] >= 2)

def rangebar(w):
    pos, hi, lo = w.get("range_pos"), w.get("wk52_high"), w.get("wk52_low")
    if pos is None:
        return '<span class="muted sm">n/a</span>'
    frm = w.get("from_high_pct")
    tag = f'{frm:+.1f}%' if frm is not None else ""
    edge = " edge" if pos >= 97 or pos <= 3 else ""
    return (f'<div class="rb{edge}" title="{fmt(lo, w.get("currency"))} – {fmt(hi, w.get("currency"))}">'
            f'<div class="rbt"><i style="left:{pos:.1f}%"></i></div>'
            f'<span class="rbl">{range_tag(pos)} <em>{tag} from high</em></span></div>')

def stale_banner(key, label):
    st = STATUS.get(key)
    if not st or (st.get("ok") and not st.get("stale")): return ""
    age = st.get("age_hours")
    when = f"{age:.0f} h old" if isinstance(age, (int, float)) else "age unknown"
    return ('<div class="stalebar">⚠ <strong>Stale — showing the last good '
            f'{esc(label)} data</strong><span>This section did not refresh on the latest run '
            f'({esc(st.get("detail") or "refresh failed")}); figures below are {when}.</span></div>')

def unavailable(msg):
    return f'<div class="unavail"><strong>Data unavailable</strong><span>{esc(msg)}</span></div>'

# ------------------------------------------------------------------ today strip
def build_today(q, p, tr=None):
    if not q or not (q.get("watchlist") or q.get("indices")):
        return ('<div class="hero"><div class="hero-h">Today</div>'
                + unavailable("No market data on this run — see the stale notes below.") + "</div>")
    movers = [dict(m, _n=m.get("label") or m.get("requested")) for m in q.get("indices", [])] + \
             [dict(m, _n=m.get("requested")) for m in q.get("watchlist", [])]
    movers = [m for m in movers if m.get("chg_pct") is not None]
    ups = sorted([m for m in movers if m["chg_pct"] > 0], key=lambda m: -m["chg_pct"])[:3]
    dns = sorted([m for m in movers if m["chg_pct"] < 0], key=lambda m: m["chg_pct"])[:3]
    wl = q.get("watchlist", [])
    macro = {m["symbol"]: m for m in q.get("macro", [])}
    bullets = []

    unu = [w for w in wl if unusual(w)]
    unu.sort(key=lambda w: -(abs(w["z"]) if w.get("z") is not None else 0))
    if unu:
        bullets.append(("unu", f"Unusual moves ({len(unu)})", " · ".join(
            f'<b>{esc(w["requested"])}</b> {w["chg_pct"]:+.2f}%'
            + (f' <span class="mini">{w["z"]:+.1f}\u03c3</span>' if w.get("z") is not None else '')
            + (f' <span class="mini">{w["rvol"]:.1f}\u00d7 vol</span>' if w.get("rvol") else '')
            for w in unu[:5])))
    else:
        bullets.append(("quiet", "No unusual activity",
                        "Nothing moved beyond 2\u03c3 of its own daily volatility or traded at twice its "
                        "average volume."))

    biggest = max((abs(m["chg_pct"]) for m in movers), default=0)
    if biggest < 0.75:
        bullets.append(("quiet", "Quiet session", "Nothing moved more than "
                        f"{biggest:.2f}% across the indices or the watchlist."))
    else:
        if ups:
            bullets.append(("up", "Leading today", " · ".join(
                f'<b>{esc(m["_n"])}</b> {m["chg_pct"]:+.2f}%' for m in ups)))
        if dns:
            bullets.append(("down", "Lagging today", " · ".join(
                f'<b>{esc(m["_n"])}</b> {m["chg_pct"]:+.2f}%' for m in dns)))

    nh = [w for w in wl if w.get("new_52w_high")]
    nl = [w for w in wl if w.get("new_52w_low")]
    if nh or nl:
        parts = []
        if nh: parts.append("new 52-week <b>highs</b>: " + ", ".join(esc(w["requested"]) for w in nh))
        if nl: parts.append("new 52-week <b>lows</b>: " + ", ".join(esc(w["requested"]) for w in nl))
        bullets.append(("flag", "52-week extremes", "; ".join(parts)))
    near_h = [w for w in wl if not w.get("new_52w_high") and w.get("from_high_pct") is not None
              and w["from_high_pct"] >= -3]
    near_l = [w for w in wl if not w.get("new_52w_low") and w.get("from_low_pct") is not None
              and w["from_low_pct"] <= 3]
    if near_h or near_l:
        parts = []
        if near_h: parts.append("within 3% of the <b>high</b>: " + ", ".join(
            f'{esc(w["requested"])} ({w["from_high_pct"]:+.1f}%)' for w in sorted(near_h, key=lambda w: -w["from_high_pct"])))
        if near_l: parts.append("within 3% of the <b>low</b>: " + ", ".join(
            f'{esc(w["requested"])} ({w["from_low_pct"]:+.1f}%)' for w in sorted(near_l, key=lambda w: w["from_low_pct"])))
        bullets.append(("near", "Pressing the range", "; ".join(parts)))

    vix, tnx, eur, btc = (macro.get(k) for k in ("^VIX", "^TNX", "EURUSD=X", "BTC-USD"))
    if vix or tnx:
        score = 0
        if vix:
            score += 1 if vix["last"] < 16 else (-1 if vix["last"] > 22 else 0)
            score += 1 if vix["chg_pct"] < -3 else (-1 if vix["chg_pct"] > 5 else 0)
        if btc: score += 1 if btc["chg_pct"] > 1 else (-1 if btc["chg_pct"] < -1 else 0)
        spx = next((i for i in q.get("indices", []) if i["symbol"] == "^GSPC"), None)
        _ = spx
        if spx: score += 1 if spx["chg_pct"] > 0.3 else (-1 if spx["chg_pct"] < -0.3 else 0)
        read = "risk-on" if score >= 2 else ("risk-off" if score <= -2 else "mixed")
        # one line of reasoning — the four levels already sit in the strip above,
        # so name the drivers rather than reprinting them.
        why = []
        if vix:
            lvl = "subdued" if vix["last"] < 16 else ("elevated" if vix["last"] > 22 else "middling")
            mv = "falling" if vix["chg_pct"] < -3 else ("spiking" if vix["chg_pct"] > 5 else "steady")
            why.append(f"volatility {lvl} and {mv}")
        if spx and spx.get("chg_pct") is not None:
            why.append("the S&P closed " + ("higher" if spx["chg_pct"] > 0.3 else
                                            "lower" if spx["chg_pct"] < -0.3 else "flat"))
        if btc: why.append("crypto " + ("bid" if btc["chg_pct"] > 1 else
                                        "under pressure" if btc["chg_pct"] < -1 else "quiet"))
        if tnx and tnx.get("prev_close"):
            bp = (tnx["last"] - tnx["prev_close"]) * 100
            why.append("yields " + ("higher" if bp > 2 else "lower" if bp < -2 else "little changed"))
        reason = ", ".join(why[:3]) or "mixed macro signals"
        bullets.append(("regime-" + read.replace("-", ""), f"Risk regime: {read}",
                        reason[0].upper() + reason[1:] + "."))

    if p and p.get("ok"):
        newk = set(p.get("new_keys") or [])
        rows = p.get("rows", [])
        fresh = [r for r in rows if pkey(r) in newk]
        if fresh:
            ov = [r for r in fresh if (r.get("ticker") or "").upper() in WATCH_TICKERS]
            txt = " · ".join(f'<b>{esc(r.get("ticker") or r.get("asset", "")[:24])}</b> {esc(r["type"])} {esc(r["amount"])}'
                             + (" ★" if (r.get("ticker") or "").upper() in WATCH_TICKERS else "")
                             for r in fresh[:4])
            bullets.append(("new", f"New Pelosi disclosure{'s' if len(fresh) > 1 else ''}"
                            + (f" — {len(ov)} on your watchlist" if ov else ""), txt))
        else:
            bullets.append(("quiet", "No new Pelosi filings", "Nothing disclosed since the previous run."))

    newt = [x for x in (tr or {}).get("transaction_reports", []) if x["url"] in set((tr or {}).get("new_reports") or [])]
    if newt:
        hits = sorted({watch_hit(r["description"]) for x in newt for r in x["rows"]} - {None})
        bullets.append(("new", f"New Trump transaction report{'s' if len(newt) > 1 else ''} (278-T)"
                        + (f" — touches {', '.join(hits)} ★" if hits else ""),
                        " · ".join(f'filed {esc(x["filed"])}: {x.get("buys", 0)} buys, {x.get("sells", 0)} sells'
                                   if x["ok"] else f'filed {esc(x["filed"])}: not machine-readable' for x in newt[:3])))

    bullets = bullets[:8]
    items = "".join(
        f'<li class="b-{c}"><span class="bl">{esc(t) if "<" not in t else t}</span>'
        f'<span class="bd">{d}</span></li>' for c, t, d in bullets)
    return (f'<div class="hero"><div class="hero-h">Today <span>— what to look at first</span></div>'
            f'<ul class="bullets">{items}</ul></div>')

# ------------------------------------------------------------------ sections
def macro_strip(q):
    if not q or not q.get("macro"): return ""
    chips = ""
    for m in q["macro"]:
        v = (f'{m["last"]:.2f}%' if m["symbol"] == "^TNX" else
             f'{m["last"]:,.4f}' if m["symbol"] == "EURUSD=X" else
             f'${m["last"]:,.0f}' if m["symbol"] == "BTC-USD" else f'{m["last"]:,.2f}')
        if m["symbol"] == "^TNX" and m.get("prev_close"):
            bp = (m["last"] - m["prev_close"]) * 100
            c = cls_of(bp, 0.05); delta = f"{bp:+.0f} bp"
        else:
            c = cls_of(m.get("chg_pct")); delta = f'{m["chg_pct"]:+.2f}%'
        a = "▲" if c == "up" else ("▼" if c == "down" else "▬")
        chips += (f'<div class="chip"><span class="cl">{esc(m["label"])}</span>'
                  f'<span class="cv">{v}</span>'
                  f'<span class="cc {c}">{a}{delta}</span></div>')
    return f'<div class="macro">{chips}</div>'

def sec_indices(q):
    if not q or not q.get("indices"):
        return unavailable("No index data could be retrieved from Yahoo Finance or Stooq.")
    rows = ""
    for i in q["indices"]:
        emph = "pop" if abs(i.get("chg_pct") or 0) >= 3 else ("calm" if abs(i.get("chg_pct") or 0) < 0.5 else "")
        rows += (f'<tr class="{emph}"><td class="tk"><span class="sym">{esc(i["label"])}</span>'
                 f'<span class="sub">{esc(i["symbol"])}</span></td>'
                 f'<td class="n mono">{i["last"]:,.0f}</td>'
                 f'<td class="n">{pct(i.get("chg_pct"))}</td>'
                 f'<td class="n">{pct(i.get("week_pct"), True)}</td>'
                 f'<td class="n">{pct(i.get("month_pct"), True)}</td></tr>')
    miss = "".join(f'<p class="note warn">⚠ {esc(e["label"])} ({esc(e["symbol"])}) could not be retrieved.</p>'
                   for e in q.get("errors", []) if e.get("label"))
    return (f'<div class="tw"><table><thead><tr><th>Index</th><th class="n">Close</th>'
            f'<th class="n">Day</th><th class="n">5d</th><th class="n">1M</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>{miss}')

def sec_watch(q, pel):
    if not q or not q.get("watchlist"):
        return unavailable("No quote data could be retrieved from Yahoo Finance or Stooq.")
    pel_t = set()
    if pel and pel.get("ok"):
        pel_t = {(r.get("ticker") or "").upper() for r in pel.get("rows", [])}
    rows = ""
    ranked = sorted(q["watchlist"],
                    key=lambda w: (-(abs(w["z"]) if w.get("z") is not None else -1),
                                   -abs(w.get("chg_pct") or 0)))
    for w in ranked:
        d = abs(w.get("chg_pct") or 0)
        unu = unusual(w)
        if unu or w.get("new_52w_high") or w.get("new_52w_low"):
            emph = "pop"
        elif (w.get("z") is not None and abs(w["z"]) < 1) or (w.get("z") is None and d < 0.5):
            emph = "calm"
        else:
            emph = ""
        flags = '<span class="badge unu">⚡ unusual</span>' if unu else ""
        if w.get("new_52w_high"): flags += '<span class="badge hi">new 52w high</span>'
        if w.get("new_52w_low"): flags += '<span class="badge lo">new 52w low</span>'
        if w["requested"].upper() in pel_t: flags += '<span class="badge pel">★ Pelosi</span>'
        if not w.get("verified"): flags += '<span class="badge warn">verify</span>'
        rows += (f'<tr class="{emph}"><td class="tk"><span class="sym">{esc(w["requested"])}</span>'
                 f'<span class="sub">{esc(w.get("name") or "")}{flags}</span></td>'
                 f'<td class="n mono">{fmt(w["last"], w.get("currency"))}</td>'
                 f'<td class="n">{pct(w.get("chg_pct"))}</td>'
                 f'<td class="n">{pct(w.get("week_pct"), True)}</td>'
                 f'<td class="n">{pct(w.get("month_pct"), True)}</td>'
                 f'<td class="n">{zfmt(w)}</td>'
                 f'<td class="n">{rvfmt(w)}</td>'
                 f'<td class="n spkc">{spark(w.get("spark"))}</td>'
                 f'<td class="rbc">{rangebar(w)}</td></tr>')
    miss = "".join(f'<p class="note warn">⚠ <strong>{esc(e["symbol"])}</strong> did not resolve — no data returned.</p>'
                   for e in q.get("errors", []) if not e.get("label"))
    return (f'<div class="tw"><table><thead><tr><th>Ticker</th><th class="n">Last</th>'
            f'<th class="n">Day</th><th class="n">5d</th><th class="n">1M</th>'
            f'<th class="n" title="today\'s move in units of this name\'s own 20-day volatility">z</th>'
            f'<th class="n" title="today\'s volume vs its 20-day average">vol</th>'
            f'<th class="n">30d</th><th>52-week range</th></tr></thead><tbody>{rows}</tbody></table></div>'
            f'<p class="note"><strong>Sorted by how unusual today is for each name</strong>, not by raw %. '
            f'<em>z</em> is today\'s move divided by that stock\'s own daily volatility over the prior 20 '
            f'sessions (today excluded from the yardstick); <em>vol</em> is today\'s volume against its 20-day '
            f'average. Rows with |z| ≥ 2σ or volume ≥ 2× are marked ⚡ unusual and highlighted; quiet rows '
            f'(|z| &lt; 1σ) are dimmed. With fewer than 21 bars or no variance, z shows n/a and the raw % '
            f'is used instead. USAR is <strong>USA Rare Earth, Inc.</strong> (Nasdaq GM), '
            f'not Universal Security Instruments (UUU). BRK.B is quoted as BRK-B.</p>{miss}')

def pel_row(r, new=False):
    ty = r.get("type", "")
    c = "up" if ty.upper().startswith("BUY") else ("down" if "SELL" in ty.upper() else "flat")
    mark = "＋" if c == "up" else ("−" if c == "down" else "=")
    star = '<span class="badge pel">★ watchlist</span>' if (r.get("ticker") or "").upper() in WATCH_TICKERS else ""
    tag = '<span class="badge new">NEW</span>' if new else ""
    return (f'<tr class="{"pop" if new else ""}"><td class="mono nowrap">{esc(r["date"])}</td>'
            f'<td class="tk"><span class="sym">{esc(r.get("ticker") or "—")}{tag}</span>'
            f'<span class="sub">{esc(r.get("asset", ""))[:58]}'
            f'{" · " + esc(r["class_label"]) if r.get("class_label") else ""}{star}</span></td>'
            f'<td><span class="pill {c}">{mark} {esc(ty)}</span></td>'
            f'<td class="n mono nowrap">{esc(r.get("amount"))}</td>'
            f'<td class="n mono muted nowrap">{esc(r.get("disclosed"))}</td></tr>')

def sec_pelosi(p):
    if not p or not p.get("ok") or not p.get("rows"):
        return unavailable("The House disclosure feeds did not return any Pelosi transactions.")
    rows = p["rows"]
    newk = set(p.get("new_keys") or [])
    fresh = [r for r in rows if pkey(r) in newk]
    old = [r for r in rows if pkey(r) not in newk]
    ov = sorted({(r.get("ticker") or "").upper() for r in rows} & WATCH_TICKERS)
    head = ""
    if fresh:
        head = ('<div class="tw"><table><thead><tr><th>Trade date</th><th>Asset</th><th>Type</th>'
                '<th class="n">Amount</th><th class="n">Filed</th></tr></thead><tbody>'
                + "".join(pel_row(r, True) for r in fresh) + "</tbody></table></div>")
    else:
        head = '<p class="quiet-note">No new disclosures since the previous run.</p>'
    older = ('<details class="fold"><summary>Earlier disclosures '
             f'({len(old)})</summary><div class="tw"><table><thead><tr><th>Trade date</th><th>Asset</th>'
             '<th>Type</th><th class="n">Amount</th><th class="n">Filed</th></tr></thead><tbody>'
             + "".join(pel_row(r) for r in old) + "</tbody></table></div></details>") if old else ""
    ovl = (f'<div class="callout"><strong>★ Watchlist overlap:</strong> {len(ov)} of your names appear in '
           f'these filings — {", ".join(esc(t) for t in ov)}.</div>') if ov else ""
    return (ovl + head + older +
            '<p class="note">Under the STOCK Act members may file up to 30–45 days after a trade, so these '
            'disclosures <strong>lag the actual transactions by weeks</strong>. Filings marked <em>SP</em> are '
            'the spouse\'s; <em>options</em> means contracts, not shares. Amounts are broad ranges.</p>')

def sec_trump(t):
    if not t or not t.get("ok"):
        return unavailable("No reliable public data available for a current holdings breakdown.")
    top = t["top_holdings"][:10]
    ov = []
    for h in top:
        d = h["description"].upper()
        for tk, nm in (("NVDA", "NVIDIA"), ("AVGO", "BROADCOM"), ("GOOGL", "ALPHABET"),
                       ("AMZN", "AMAZON"), ("IBM", "IBM"), ("LLY", "LILLY"), ("TXN", "TEXAS INSTRUMENT"),
                       ("INTC", "INTEL"), ("MU", "MICRON"), ("UBER", "UBER")):
            if nm in d and tk not in ov: ov.append(tk)
    rows = "".join(
        f'<tr><td class="tk"><span class="sym cap">{esc(nice(h["description"][:56]))}'
        + ('<span class="badge pel">★ watchlist</span>' if any(
            n in h["description"].upper() for n in ("NVIDIA", "BROADCOM", "ALPHABET", "AMAZON",
                                                    "IBM", "LILLY", "TEXAS INSTRUMENT", "INTEL",
                                                    "MICRON", "UBER")) else "")
        + f'</span></td><td class="n mono">${h["lo"]:,} – ${h["hi"]:,}</td></tr>' for h in top)
    ovl = (f'<div class="callout"><strong>★ Watchlist overlap:</strong> {", ".join(ov)}.</div>') if ov else ""
    return (sec_trump_txn(t) + '<div class="callout light"><strong>Annual asset disclosure — not live trades.</strong> '
            'OGE Form 278e reports assets in broad value ranges for the report year; it is not a record of '
            'purchases or sales and does not reflect current market value. It changes once a year.</div>'
            + ovl +
            '<details class="fold"><summary>Top 10 reported holdings by value range</summary>'
            '<div class="tw"><table><thead><tr><th>Asset</th><th class="n">Reported range</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
            f'<p class="note">Parsed from the certified PDF: {t["line_items_parsed"]:,} asset line items, '
            f'{t["unique_assets"]:,} distinct assets. Ranges for an asset held in several accounts are summed, '
            f'so totals are sums of range endpoints, not valuations. {esc(t["source"])}.</p></details>')

def sec_trump_txn(t):
    reps = t.get("transaction_reports")
    if reps is None:
        return ""
    since = [x for x in reps if x.get("after_annual")] or reps[:2]
    if not since:
        return '<p class="quiet-note">No 278-T transaction reports filed in the last 12 months.</p>'
    newu = set(t.get("new_reports") or [])
    def rng(x): return f'${x["lo"]:,} – ${x["hi"]:,}'
    def cov(x):
        if not x["ok"]:
            return f'<span class="muted">not read — {esc(x.get("error") or "unreadable")}</span>'
        c = x.get("coverage", 0)
        return (f'{len(x["rows"]):,} read' + (f' of ~{x["declared"]:,}' if x.get("declared") else "")
                + (' <span class="badge">partial</span>' if c < 0.8 else ""))
    trs = "".join(
        f'<tr class="{"pop" if x["url"] in newu else ""}"><td class="mono nowrap">{esc(x["filed"])}'
        + ('<span class="badge new">NEW</span>' if x["url"] in newu else "")
        + f'</td><td><a href="{esc(x["url"])}" rel="noopener">{esc(x["name"].replace("%20", " ").replace("%2C", ","))[:44]}</a></td>'
        f'<td class="n mono">{x.get("buys", 0) if x["ok"] else "—"}</td><td class="n mono">{x.get("sells", 0) if x["ok"] else "—"}</td>'
        f'<td class="n mono nowrap">{rng(x) if x["ok"] else "—"}</td>'
        f'<td class="nowrap">{cov(x)}</td></tr>' for x in since)
    rows = [dict(r, filed=x["filed"]) for x in since if x["ok"] for r in x["rows"]]
    hits = {}
    for r in rows:
        tk = watch_hit(r["description"])
        if tk: hits.setdefault(tk, []).append(r)
    ovl = ""
    if hits:
        ovl = ('<div class="callout"><strong>★ Watchlist names traded:</strong> ' + " · ".join(
            f'<b>{tk}</b> ' + ", ".join(sorted({("buy" if r["type"] == "BUY" else "sell" if r["type"].startswith("SELL") else "exch") for r in rs}))
            + f' ({len(rs)})' for tk, rs in sorted(hits.items())) + '</div>')
    big = sorted((r for r in rows if r["hi"]), key=lambda r: (-r["lo"], r["description"]))[:15]
    def trow(r):
        c = "up" if r["type"] == "BUY" else ("down" if r["type"].startswith("SELL") else "flat")
        mark = "＋" if c == "up" else ("−" if c == "down" else "=")
        star = '<span class="badge pel">★ watchlist</span>' if watch_hit(r["description"]) else ""
        return (f'<tr><td class="mono nowrap">{esc(r["date"] or "—")}</td>'
                f'<td class="tk"><span class="sym cap">{esc(nice(r["description"][:60]))}{star}</span></td>'
                f'<td><span class="pill {c}">{mark} {esc(r["type"])}</span></td>'
                f'<td class="n mono nowrap">{esc(r["amount"])}</td><td class="n mono muted nowrap">{esc(r["filed"])}</td></tr>')
    return ('<div class="callout light"><strong>Periodic transaction reports (278-T) — actual purchases and sales</strong>, '
            'filed since the last annual report. Mostly municipal bonds and managed-account equity trades. '
            'They are scanned PDFs read by OCR, so counts are approximate and a few lines are missed.</div>'
            + ovl +
            '<div class="tw"><table><thead><tr><th>Posted</th><th>Report</th><th class="n">Buys</th>'
            '<th class="n">Sells</th><th class="n">Sum of ranges</th><th>Lines</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div>'
            + ('<details class="fold"><summary>Largest transactions in these reports '
               f'({len(big)})</summary><div class="tw"><table><thead><tr><th>Trade date</th><th>Asset</th>'
               '<th>Type</th><th class="n">Amount</th><th class="n">Posted</th></tr></thead><tbody>'
               + "".join(trow(r) for r in big) + '</tbody></table></div></details>' if big else ""))

# ------------------------------------------------------------------ page
def main():
    q, p, tr = load("quotes.json"), load("pelosi.json"), load("trump.json")
    now = datetime.datetime.now(TZ)
    stamp = now.strftime("%A %d %B %Y, %H:%M %Z (UTC%z)")
    mkt = ""
    if q and q.get("indices"):
        a = q["indices"][0].get("as_of")
        if a:
            dt = datetime.datetime.fromisoformat(a).astimezone(ZoneInfo("America/New_York"))
            mkt = f"US market data as of {dt.strftime('%d %b %Y, %H:%M %Z')}"
    if STATUS:
        okn = [k for k, v in STATUS.items() if v.get("ok")]
        badn = [k for k, v in STATUS.items() if not v.get("ok")]
        runline = ("Automatic refresh — refreshed: " + (", ".join(okn) or "none")
                   + ("; not refreshed: " + ", ".join(badn) if badn else ""))
    else:
        runline = "Built manually."
    src = lambda ok, s: f'<span class="src">{"●" if ok else "○"} {esc(s)}</span>'

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Market Monitor</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--ink:#0f1419;--mut:#6a727e;--line:#e4e7eb;
--up:#0a7d5a;--upbg:#e8f5f0;--down:#b3261e;--downbg:#fceceb;--accent:#141d28;--star:#7a4bd6;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,
"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 20px}}
header.top{{background:var(--accent);color:#fff;padding:24px 0 20px}}
h1{{margin:0 0 7px;font-size:21px;font-weight:650;letter-spacing:-.01em}}
.updated{{display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,.13);
border:1px solid rgba(255,255,255,.18);border-radius:999px;padding:5px 13px;font-size:13px;font-weight:600}}
.updated .dot{{width:7px;height:7px;border-radius:50%;background:#5ee0a8}}
.sub-h{{color:#a9b6c4;font-size:12.5px;margin-top:7px}}
.macro{{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}}
.chip{{display:flex;align-items:baseline;gap:7px;background:rgba(255,255,255,.07);
border:1px solid rgba(255,255,255,.13);border-radius:8px;padding:7px 11px}}
.chip .cl{{font-size:11px;color:#a9b6c4;text-transform:uppercase;letter-spacing:.05em;font-weight:650}}
.chip .cv{{font-size:14px;font-weight:650;font-variant-numeric:tabular-nums}}
.chip .cc{{font-size:11.5px;font-weight:650;font-variant-numeric:tabular-nums}}
.chip .cc.up{{color:#5ee0a8}} .chip .cc.down{{color:#ff9d94}} .chip .cc.flat{{color:#a9b6c4}}
main{{padding:22px 0 60px}}
.hero{{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);
border-radius:12px;padding:16px 20px 6px;margin-bottom:20px;box-shadow:0 1px 3px rgba(15,20,25,.06)}}
.hero-h{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;font-weight:700;margin-bottom:10px}}
.hero-h span{{color:var(--mut);font-weight:600;text-transform:none;letter-spacing:0;font-size:12.5px}}
.bullets{{list-style:none;margin:0;padding:0}}
.bullets li{{display:flex;flex-wrap:wrap;gap:4px 12px;padding:9px 0 9px 16px;border-top:1px solid #f0f2f4;
position:relative;font-size:14px}}
.bullets li:first-child{{border-top:none}}
.bullets li:before{{content:"";position:absolute;left:0;top:15px;width:6px;height:6px;border-radius:50%;background:var(--mut)}}
.b-up:before{{background:var(--up)!important}} .b-down:before{{background:var(--down)!important}}
.b-flag:before,.b-near:before{{background:#c98a00!important}}
.b-new:before{{background:var(--star)!important}}
.b-regimeriskon:before{{background:var(--up)!important}}
.b-regimeriskoff:before{{background:var(--down)!important}}
.b-quiet{{opacity:.62}}
.bl{{font-weight:650;min-width:150px}} .bd{{color:#39424d;flex:1;min-width:220px}}
.bd b{{font-weight:650;color:var(--ink)}}
section{{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:18px;
overflow:hidden;box-shadow:0 1px 2px rgba(15,20,25,.04)}}
.hd{{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;justify-content:space-between;
padding:14px 20px;border-bottom:1px solid var(--line)}}
.hd h2{{margin:0;font-size:15px;font-weight:650}}
.hd h2 .n{{color:var(--mut);font-weight:600;margin-right:8px}}
.src{{font-size:11.5px;color:var(--mut)}}
.tw{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);
font-weight:700;padding:9px 18px;background:#fafbfc;border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:9px 18px;border-bottom:1px solid #f2f4f6;vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
td.n,th.n{{text-align:right;white-space:nowrap}} .nowrap{{white-space:nowrap}}
tr.calm td{{opacity:.5}} tr.calm:hover td{{opacity:1}}
tr.pop td{{background:#fffdf5;font-weight:600}}
tr.pop td:first-child{{box-shadow:inset 3px 0 0 #e0b445}}
.tk .sym{{display:block;font-weight:650}} .tk .sym.cap{{font-weight:600}}
.tk .sub{{display:block;font-size:11.5px;color:var(--mut);margin-top:1px}}
.mono{{font-variant-numeric:tabular-nums}}
.chg{{display:inline-flex;align-items:center;gap:4px;font-weight:650;font-variant-numeric:tabular-nums}}
.chg.sm{{font-weight:500;font-size:13px;opacity:.85}} .chg .arw{{font-size:10px}}
.up{{color:var(--up)}} .down{{color:var(--down)}} .flat{{color:var(--mut)}}
.spkc{{width:96px;padding-right:8px}} .spk{{display:block;margin-left:auto}}
.rbc{{width:150px}}
.rb{{display:block;min-width:120px}} .rbt{{position:relative;height:5px;border-radius:3px;
background:linear-gradient(90deg,#e7eaee,#d6dbe1)}}
.rb i{{position:absolute;top:-3px;width:3px;height:11px;border-radius:2px;background:var(--accent);
transform:translateX(-1.5px)}}
.rb.edge i{{background:#c98a00;width:4px}}
.rbl{{display:block;font-size:11px;color:var(--mut);margin-top:3px;font-variant-numeric:tabular-nums}}
.rbl em{{font-style:normal;opacity:.75}}
.badge{{display:inline-block;margin-left:6px;border-radius:4px;padding:1px 6px;font-size:10.5px;font-weight:700;
vertical-align:1px}}
.badge.hi{{background:var(--upbg);color:var(--up)}} .badge.lo{{background:var(--downbg);color:var(--down)}}
.badge.pel{{background:#f2ecfd;color:var(--star)}} .badge.warn{{background:#fff2d6;color:#8a5a00}}
.badge.new{{background:var(--star);color:#fff}}
.badge.unu{{background:#fdf0d9;color:#8a5a00;border:1px solid #efd9ab}}
.zs{{font-variant-numeric:tabular-nums;font-weight:650;font-size:13px}}
.zs.unu{{color:#8a5a00}} .zs.faint{{color:var(--mut);font-weight:500;opacity:.75}}
.rtag{{display:inline-block;border-radius:4px;padding:0 6px;font-size:10.5px;font-weight:700;
text-transform:uppercase;letter-spacing:.03em}}
.rtag.hi{{background:var(--upbg);color:var(--up)}}
.rtag.lo{{background:var(--downbg);color:var(--down)}}
.rtag.mid{{background:#eef0f3;color:var(--mut)}}
.mini{{font-size:11.5px;color:var(--mut);font-variant-numeric:tabular-nums}}
.b-unu:before{{background:#c98a00!important}}
.pill{{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:650;border:1px solid}}
.pill.up{{background:var(--upbg);border-color:#bfe3d4;color:var(--up)}}
.pill.down{{background:var(--downbg);border-color:#f2ccc9;color:var(--down)}}
.pill.flat{{background:#f1f3f5;border-color:var(--line);color:var(--mut)}}
.muted{{color:var(--mut)}} .sm{{font-size:12px}}
.note{{margin:0;padding:11px 18px;font-size:12px;color:var(--mut);background:#fafbfc;border-top:1px solid var(--line)}}
.note.warn{{color:#8a5a00;background:#fff8ea}}
.quiet-note{{margin:0;padding:14px 18px;font-size:13px;color:var(--mut)}}
.callout{{margin:0;padding:11px 18px;background:#f6f4fd;border-bottom:1px solid var(--line);font-size:12.5px;color:#3a3350}}
.callout.light{{background:#f4f7fb;color:#31414f}}
.fold{{border-top:1px solid var(--line)}}
.fold summary{{cursor:pointer;padding:11px 18px;font-size:12.5px;font-weight:650;color:var(--mut);
background:#fafbfc;list-style:none;user-select:none}}
.fold summary::-webkit-details-marker{{display:none}}
.fold summary:before{{content:"▸ ";font-size:11px}}
.fold[open] summary:before{{content:"▾ "}}
.stalebar{{display:flex;flex-direction:column;gap:2px;padding:10px 18px;background:#fff8ea;
border-bottom:1px solid #f0e0bd;color:#7a5200;font-size:12.5px}} .stalebar span{{color:#8a6a2f}}
.unavail{{padding:24px 18px;display:flex;flex-direction:column;gap:4px;color:var(--mut);
background:repeating-linear-gradient(45deg,#fbfcfd,#fbfcfd 10px,#f7f8fa 10px,#f7f8fa 20px)}}
.unavail strong{{color:#8a5a00}}
.legend{{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin:0 0 16px}}
footer{{text-align:center;color:var(--mut);font-size:12px;padding:6px 0 0;line-height:1.7}}
@media(max-width:700px){{th,td{{padding-left:13px;padding-right:13px}}.bl{{min-width:100%}}}}
</style></head><body>
<header class="top"><div class="wrap">
<h1>Market Monitor</h1>
<div class="updated"><span class="dot"></span>Last updated: {esc(stamp)}</div>
<div class="sub-h">{esc(mkt)}</div>
{macro_strip(q)}
</div></header>
<main><div class="wrap">
{build_today(q, p, tr)}
<div class="legend"><span class="up">▲ + up</span><span class="down">▼ − down</span>
<span>▬ flat</span><span>★ = on your watchlist</span>
<span>Arrows and +/− carry the same meaning as the colours.</span></div>

<section><div class="hd"><h2><span class="n">1</span>Indices</h2>{src(bool(q and q.get('indices')),'Yahoo Finance')}</div>
{stale_banner("quotes","market")}{sec_indices(q)}</section>

<section><div class="hd"><h2><span class="n">2</span>Watchlist</h2>{src(bool(q and q.get('watchlist')),'Yahoo Finance')}</div>
{stale_banner("quotes","market")}{sec_watch(q, p)}</section>

<section><div class="hd"><h2><span class="n">3</span>Congress trading — Nancy Pelosi</h2>{src(bool(p and p.get('ok')),'House Clerk PTR filings')}</div>
{stale_banner("pelosi","House disclosure")}{sec_pelosi(p)}</section>

<section><div class="hd"><h2><span class="n">4</span>Trump — OGE disclosures</h2>{src(bool(tr and tr.get('ok')),'OGE 278e + 278-T')}</div>
{stale_banner("trump","OGE 278e")}{sec_trump(tr)}</section>

<footer>{esc(runline)}<br>Informational only — not investment advice.</footer>
</div></main></body></html>"""
    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    open(OUT_HTML, "w").write(page)
    print("wrote", OUT_HTML, len(page), "bytes")

main()
