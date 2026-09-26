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
                 "TEM", "LLY", "TXN", "INTC", "MU", "USAR", "UBER", "IBM", "SNDK"}
ACR = {"Etf": "ETF", "Inc": "Inc.", "Llc": "LLC", "Lp": "LP", "Us": "U.S.", "Spdr": "SPDR",
       "S&p": "S&P", "Nvidia": "NVIDIA", "Ibm": "IBM", "Reit": "REIT", "Corp": "Corp.", "Tr": "Trust"}

def load(name):
    try:
        return json.load(open(os.path.join(ROOT, "data", name)))
    except Exception:
        return None

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

def pct(v, small=False, neutral=False):
    if v is None: return '<span class="muted">n/a</span>'
    c = cls_of(v)
    a = "▲" if c == "up" else ("▼" if c == "down" else "▬")
    if neutral and abs(v) < 2: return f'<span class="chg flat sm"><span class="arw">▬</span>{v:+.2f}%</span>'
    if neutral and abs(v) >= 2: return f'<span class="chg {c} sm"><span class="arw">{"▲" if c=="up" else "▼"}</span>{v:+.2f}%</span>'
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
    return ""

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

def trend_align(w):
    d, w5, m1 = w.get("chg_pct"), w.get("week_pct"), w.get("month_pct")
    if d is None or w5 is None or m1 is None: return 0
    if d > 0 and w5 > 0 and m1 > 0: return 1
    if d < 0 and w5 < 0 and m1 < 0: return -1
    return 0

def stretched(w):
    z = w.get("z"); rv = w.get("rvol")
    if z is None or abs(z) < 2: return False
    return rv is None or rv < 1.5

def classify(w):
    unu = unusual(w); strc = stretched(w); ta = trend_align(w)
    fh = w.get("from_high_pct"); fl = w.get("from_low_pct")
    nh = w.get("new_52w_high"); nl = w.get("new_52w_low")
    if unu:
        if strc:
            return ('<span class="badge stretch">' + chr(8764) + ' Stretched (vol<1.5' + chr(215) + ')</span>', "str")
        z, rv = w.get("z"), w.get("rvol")
        label = ""
        if z and abs(z) >= 2 and rv and rv >= 2:
            label = f'{z:+.1f}' + chr(963) + f' {rv:.1f}' + chr(215)
        elif z and abs(z) >= 2:
            label = f'{z:+.1f}' + chr(963)
        elif rv and rv >= 2:
            label = f'{rv:.1f}' + chr(215)
        return (f'<span class="badge unu">' + chr(9889) + f' Unusual<span class="mini">{label}</span></span>', "unu")
    if ta == 1:
        return ('<span class="badge trend-up">' + chr(9654) + ' In force (Day/5d/1M ' + chr(8593) + ')</span>', "upforce")
    if ta == -1:
        return ('<span class="badge trend-dn">' + chr(9660) + ' Pressure (Day/5d/1M ' + chr(8595) + ')</span>', "dnpress")
    if fh is not None and fh >= -3:
        return ('<span class="badge hi">' + chr(9670) + ' Near high (>= -3% from 52w high)</span>', "nearhi")
    if fl is not None and fl <= 3:
        return ('<span class="badge lo">' + chr(9671) + ' Near low (<= 3% from 52w low)</span>', "nearlo")
    if nh:
        return ('<span class="badge hi">new 52w high</span>', "newhi")
    if nl:
        return ('<span class="badge lo">new 52w low</span>', "newlo")
    return ("", "")

def setup_badges(w, in_pelosi=False):
    badge, _ = classify(w)
    if badge:
        return badge
    if in_pelosi:
        return '<span class="badge pel">' + chr(9733) + ' Insider</span>'
    return ""

def setup_tags(w):
    _, tag = classify(w)
    if not tag and w.get("verified") is False:
        tag = "verify"
    return tag

def build_setups(q):
    if not q or not q.get("watchlist"): return ""
    g = {"unu":[],"str":[],"upforce":[],"dnpress":[],"nearhi":[],"nearlo":[],"newhi":[]}
    for w in q["watchlist"]:
        _, tag = classify(w)
        if tag and tag in g:
            g[tag].append(w["requested"])
    parts = []
    if g["unu"]:
        parts.append('<span class="set-chip set-str"><span class="set-dot" style="background:#c98a00"></span><b>Unusual</b> ' + chr(9889) + ' ' + ", ".join(esc(t) for t in g["unu"][:5]) + '</span>')
    if g["str"]:
        parts.append('<span class="set-chip set-str"><span class="set-dot" style="background:#c98a00"></span><b>Stretched</b> ' + ", ".join(esc(t) for t in g["str"][:5]) + '</span>')
    if g["upforce"]:
        parts.append('<span class="set-chip set-force"><span class="set-dot" style="background:var(--up)"></span><b>In force</b> ' + ", ".join(esc(t) for t in g["upforce"][:5]) + '</span>')
    if g["dnpress"]:
        parts.append('<span class="set-chip set-press"><span class="set-dot" style="background:var(--down)"></span><b>Under pressure</b> ' + ", ".join(esc(t) for t in g["dnpress"][:5]) + '</span>')
    if g["nearhi"]:
        parts.append('<span class="set-chip set-hi"><span class="set-dot" style="background:var(--up)"></span><b>Near high</b> ' + ", ".join(esc(t) for t in g["nearhi"][:5]) + '</span>')
    if g["nearlo"]:
        parts.append('<span class="set-chip set-lo"><span class="set-dot" style="background:var(--down)"></span><b>Near low</b> ' + ", ".join(esc(t) for t in g["nearlo"][:5]) + '</span>')
    if g["newhi"]:
        parts.append('<span class="set-chip set-hi"><span class="set-dot" style="background:var(--up)"></span><b>New highs</b> ' + ", ".join(esc(t) for t in g["newhi"][:5]) + '</span>')
    if not parts:
        return ""
    return '<div class="setups">' + "".join(parts) + '</div>'

def _load_prev():
    try: return json.load(open(os.path.join(ROOT, "data", "prev_state.json")))
    except: return None

def _prev_exists():
    return os.path.exists(os.path.join(ROOT, "data", "prev_state.json"))

def _rkey(r):
    """Identity of a disclosure row; ticker-less assets fall back to the name."""
    return "|".join(str(r.get(k) or (r.get("asset", "") if k == "ticker" else ""))
                    for k in ("date", "ticker", "type", "amount"))

def build_delta(q, p, prev, tr=None):
    if not q or not q.get("watchlist"): return ""
    wl = q["watchlist"]
    nu = {w["requested"] for w in wl if unusual(w)}
    nh = {w["requested"] for w in wl if w.get("new_52w_high")}
    nl = {w["requested"] for w in wl if w.get("new_52w_low")}
    nf = {w["requested"] for w in wl if trend_align(w) == 1}
    np = {w["requested"] for w in wl if trend_align(w) == -1}
    
    pu, ph, pl, pf, pp = set(), set(), set(), set(), set()
    if prev and "watchlist" in prev:
        for w in prev["watchlist"]:
            t = w["requested"]; z = w.get("z"); rv = w.get("rvol")
            if (z is not None and abs(z) >= 2) or (rv is not None and rv >= 2): pu.add(t)
            if w.get("new_52w_high"): ph.add(t)
            if w.get("new_52w_low"): pl.add(t)
            d, w5, m1 = w.get("chg_pct"), w.get("week_pct"), w.get("month_pct")
            if d is not None and w5 is not None and m1 is not None:
                if d > 0 and w5 > 0 and m1 > 0: pf.add(t)
                if d < 0 and w5 < 0 and m1 < 0: pp.add(t)
    
    bullets = []
    nn = nu - pu
    if nn:
        dts = []
        for t in sorted(nn):
            w = next((x for x in wl if x["requested"]==t), None)
            if w: dts.append(f'<b>{esc(t)}</b> {w.get("chg_pct",0):+.2f}% ({w.get("z",0):+.1f}\u03c3)')
        bullets.append(("unu", f"New unusual moves ({len(nn)})", " \u00b7 ".join(dts)))
    ex = pu - nu
    if ex: bullets.append(("quiet", "Returned to normal", ", ".join(sorted(ex))))
    nhh = nh - ph; nll = nl - pl
    if nhh or nll:
        parts = []
        if nhh: parts.append("new highs: " + ", ".join(sorted(nhh)))
        if nll: parts.append("new lows: " + ", ".join(sorted(nll)))
        bullets.append(("flag", "52-week extremes", "; ".join(parts)))
    nff = (nf - pf) - nu
    if nff: bullets.append(("up", "Entered uptrend", ", ".join(sorted(nff))))
    npp = (np - pp) - nu
    if npp: bullets.append(("down", "Entered downtrend", ", ".join(sorted(npp))))
    if p and p.get("new_keys"):
        nk = set(p.get("new_keys") or [])
        fr = [r for r in p.get("rows",[]) if _rkey(r) in nk]
        if fr:
            txt = " \u00b7 ".join(
                f'<b>{esc(r["ticker"])}</b> {esc(r["type"])} {esc(r["amount"])}'
                + (" \u2605" if (r.get("ticker") or "").upper() in WATCH_TICKERS else "")
                for r in fr[:4])
            bullets.append(("new", f"New Pelosi disclosure{'s' if len(fr)>1 else ''}", txt))
    if tr and tr.get("new_reports"):
        nrep = [x for x in (tr.get("transaction_reports") or []) if x["url"] in set(tr["new_reports"])]
        if nrep:
            bullets.append(("new", f"New Trump 278-T report{'s' if len(nrep)>1 else ''} ({len(nrep)})",
                            " \u00b7 ".join(esc(x["filed"]) for x in nrep[:4])))
    if not bullets:
        return '<div class="delta-quiet">\u25c6 No material changes since last run.</div>'
    items = "".join(f'<li class="b-{c}"><span class="bl">{t}</span><span class="bd">{d}</span></li>'
                    for c,t,d in bullets)
    return f'<div class="delta-strip"><h3>\u25b6 Since last run</h3><ul>{items}</ul></div>'

def save_prev_state(q, p, tr):
    if not q or not q.get("watchlist"): return
    snap = {"watchlist": [],
            "pelosi_keys": list({_rkey(r) for r in p.get("rows",[])}) if p and p.get("rows") else [],
            "trump_annual": (tr.get("source_url"), tr.get("annual_date")) if tr else None}
    for w in q["watchlist"]:
        snap["watchlist"].append({k: w[k] for k in ("requested","z","rvol","chg_pct",
            "week_pct","month_pct","from_high_pct","from_low_pct","new_52w_high","new_52w_low")
            if k in w and w[k] is not None})
    json.dump(snap, open(os.path.join(ROOT, "data", "prev_state.json"), "w"))

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
def build_today(q, p, macro):
    if not q or not (q.get("watchlist") or q.get("indices")):
        return ('<div class="hero"><div class="hero-h">Today</div>'
                + unavailable("No market data on this run — see the stale notes below.") + "</div>")
    movers = [dict(m, _n=m.get("label") or m.get("requested")) for m in q.get("indices", [])] + \
             [dict(m, _n=m.get("requested")) for m in q.get("watchlist", [])]
    movers = [m for m in movers if m.get("chg_pct") is not None]
    unu_tickers = {w["requested"] for w in q.get("watchlist",[]) if unusual(w)}
    ups = sorted([m for m in movers if m["chg_pct"] > 0 and m.get("requested",m.get("symbol")) not in unu_tickers and m.get("_n") not in unu_tickers], key=lambda m: -m["chg_pct"])[:3]
    dns = sorted([m for m in movers if m["chg_pct"] < 0 and m.get("requested",m.get("symbol")) not in unu_tickers and m.get("_n") not in unu_tickers], key=lambda m: m["chg_pct"])[:3]
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
        quiet_line = f'<div class="quiet-hero">Quiet session — nothing moved more than {biggest:.2f}%. Check the tables below.</div>'
    else:
        if ups:
            bullets.append(("up", "Leading today", " · ".join(
                f'<b>{esc(m["_n"])}</b> {m["chg_pct"]:+.2f}% <span class="mini">(${abs(m["last"] - m["prev_close"]):,.2f})</span>' for m in ups)))
        if dns:
            bullets.append(("down", "Lagging today", " · ".join(
                f'<b>{esc(m["_n"])}</b> {m["chg_pct"]:+.2f}% <span class="mini">(${abs(m["last"] - m["prev_close"]):,.2f})</span>' for m in dns)))

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

    regime_bar = ""
    vix, tnx, eur, btc = (macro.get(k) for k in ("^VIX", "^TNX", "EURUSD=X", "BTC-USD"))
    if vix or tnx:
        score = 0
        if vix:
            score += 1 if vix["last"] < 16 else (-1 if vix["last"] > 22 else 0)
            score += 1 if vix["chg_pct"] < -3 else (-1 if vix["chg_pct"] > 5 else 0)
        if btc: score += 1 if btc["chg_pct"] > 1 else (-1 if btc["chg_pct"] < -1 else 0)
        spx = next((i for i in q.get("indices", []) if i["symbol"] == "^GSPC"), None)
        if spx: score += 1 if spx["chg_pct"] > 0.3 else (-1 if spx["chg_pct"] < -0.3 else 0)
        read = "risk-on" if score >= 2 else ("risk-off" if score <= -2 else "mixed")
        status_color = "var(--up)" if read == "risk-on" else ("var(--down)" if read == "risk-off" else "var(--mut)")
        why = []
        if vix:
            lvl = "subdued" if vix["last"] < 16 else ("elevated" if vix["last"] > 22 else "middling")
            mv = "falling" if vix["chg_pct"] < -3 else ("spiking" if vix["chg_pct"] > 5 else "steady")
            why.append(f"vol {lvl}, {mv}")
        if spx and spx.get("chg_pct") is not None:
            why.append("S&P " + ("higher" if spx["chg_pct"] > 0.3 else "lower" if spx["chg_pct"] < -0.3 else "flat"))
        if tnx and tnx.get("prev_close"):
            bp = (tnx["last"] - tnx["prev_close"]) * 100
            why.append("yields " + ("higher" if bp > 2 else "lower" if bp < -2 else "flat"))
        regime_bar = (f'<div class="regime-bar"><span class="regime-dot" style="background:{status_color}"></span>'
                      f'<strong>{read.replace("-"," ").title()}</strong>'
                      f'<span class="regime-why"> — {", ".join(why[:2])}</span></div>')

    if p and p.get("ok"):
        newk = set(p.get("new_keys") or [])
        rows = p.get("rows", [])
        def key(r): return "|".join(str(r.get(k, "")) for k in ("date", "ticker", "type", "amount"))
        fresh = [r for r in rows if key(r) in newk]
        if fresh:
            ov = [r for r in fresh if (r.get("ticker") or "").upper() in WATCH_TICKERS]
            txt = " · ".join(f'<b>{esc(r["ticker"])}</b> {esc(r["type"])} {esc(r["amount"])}'
                             + (" ★" if (r.get("ticker") or "").upper() in WATCH_TICKERS else "")
                             for r in fresh[:4])
            bullets.append(("new", f"New Pelosi disclosure{'s' if len(fresh) > 1 else ''}"
                            + (f" — {len(ov)} on your watchlist" if ov else ""), txt))
        else:
            pass

    bullets = bullets[:8]
    items = "".join(
        f'<li class="b-{c}"><span class="bl">{esc(t) if "<" not in t else t}</span>'
        f'<span class="bd">{d}</span></li>' for c, t, d in bullets)
    quiet_line = locals().get("quiet_line", "")
    return (f'<div class="hero"><div class="hero-h">Today <span>— what to look at first</span></div>'
            + (regime_bar if regime_bar else "")
            + (quiet_line if quiet_line else "")
            + (f'<ul class="bullets">{items}</ul>' if items else "")
            + '</div>')

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
        # Percentile badge for VIX and TNX
        pctl_str = None
        if m["symbol"] == "^VIX":
            pctl_str = _pctile_str(m["last"], "vix")
        elif m["symbol"] == "^TNX":
            pctl_str = _pctile_str(m["last"], "tnx")
        pctl_tag = f'<span class="pctl">{esc(pctl_str)}</span>' if pctl_str else ""
        chips += (f'<div class="chip"><span class="cl">{esc(m["label"])}</span>'
                  f'<span class="cv">{v}{pctl_tag}</span>'
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
                 f'<td class="n mono" data-label="Close">{i["last"]:,.0f}</td>'
                 f'<td class="n" data-label="Day">{pct(i.get("chg_pct"))}</td>'
                 f'<td class="n" data-label="5d">{pct(i.get("week_pct"), True, True)}</td>'
                 f'<td class="n" data-label="1M">{pct(i.get("month_pct"), True, True)}</td></tr>')
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
        in_pel = w["requested"].upper() in pel_t
        flags = setup_badges(w, in_pel)
        if not flags:
            if w.get("verified") is False: flags += '<span class="badge warn">verify</span>'
        st = setup_tags(w)
        rows += (f'<tr class="{emph}" data-setup="{st}"><td class="tk"><span class="sym">{esc(w["requested"])}</span>'
                 f'<span class="sub">{esc(w.get("name") or "")}{flags}</span></td>'
                 f'<td class="n mono" data-label="Last">{fmt(w["last"], w.get("currency"))}</td>'
                 f'<td class="n" data-label="Day">{pct(w.get("chg_pct"))}</td>'
                 f'<td class="n" data-label="5d">{pct(w.get("week_pct"), True, True)}</td>'
                 f'<td class="n" data-label="1M">{pct(w.get("month_pct"), True, True)}</td>'
                 f'<td class="n" data-label="z">{zfmt(w)}</td>'
                 f'<td class="n" data-label="Vol">{rvfmt(w)}</td>'
                 f'<td class="n spkc" data-label="30d">{spark(w.get("spark"))}</td>'
                 f'<td class="rbc" data-label="Range">{rangebar(w)}</td></tr>')
    miss = "".join(f'<p class="note warn">⚠ <strong>{esc(e["symbol"])}</strong> did not resolve — no data returned.</p>'
                   for e in q.get("errors", []) if not e.get("label"))
    toolbar = ('<div class="wl-toolbar">'
            '<select class="wl-filter" onchange="var f=this.value;'
            '[].forEach.call(document.querySelectorAll(\'.tw table tbody tr\'),'
            'function(r){if(!f||r.getAttribute(\'data-setup\').indexOf(f)>=0)'
            'r.style.display=\'\';else r.style.display=\'none\'})\">'
            '<option value=\'\'>All</option>'
            '<option value=\'unu\'>\u26a1 Unusual</option>'
            '<option value=\'upforce\'>\u25b2 In force</option>'
            '<option value=\'dnpress\'>\u25bc Under pressure</option>'
            '<option value=\'str\'>\u223c Stretched</option>'
            '<option value=\'nearhi\'>\u25c6 Near high</option>'
            '<option value=\'nearlo\'>\u25c7 Near low</option>'
            '</select>'
            '<select class="wl-mobile-sort" onchange="var c=this.value.split(\',\');'
            'var tbl=this.closest(\'section\').querySelector(\'table\');'
            'if(tbl&&tbl.querySelector(\'th:nth-child(\'+c[0]+\')\'))'
            'tbl.querySelector(\'th:nth-child(\'+c[0]+\')\').click()\">'
            '<option value=\'\'>Sort\u2026</option>'
            '<option value=\'0,asc\'>T \u2191</option>'
            '<option value=\'0,desc\'>T \u2193</option>'
            '<option value=\'1,asc\'>\$ \u2191</option>'
            '<option value=\'1,desc\'>\$ \u2193</option>'
            '<option value=\'2,asc\'>Day \u2191</option>'
            '<option value=\'2,desc\'>Day \u2193</option>'
            '<option value=\'5,asc\'>z \u2191</option>'
            '<option value=\'5,desc\'>z \u2193</option>'
            '</select></div>')
    toggle_btn = '<button class="wl-toggle" onclick="var c=this.parentNode.querySelector(\'.tw\');var h=c.style.maxHeight;if(!h||h===\'0px\'){c.style.maxHeight=c.scrollHeight+1200+\'px\';this.textContent=\'Hide full table\';this.parentNode.querySelector(\'.wl-filter\').disabled=false}else{c.style.maxHeight=\'0px\';this.textContent=\'Show full table\';this.parentNode.querySelector(\'.wl-filter\').disabled=true}">Show full table</button>'
    return (toolbar + toggle_btn + f'<div class="tw tw-collapse"><table><thead><tr><th>Ticker</th><th class="n">Last</th>'
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
    warn = ""
    if p.get("unparsed_filings"):
        warn = ('<div class="stalebar">\u26a0 <strong>' + str(len(p["unparsed_filings"]))
                + ' filing(s) could not be parsed</strong><span>Listed in the Clerk index but no '
                  'transactions were read from the PDF, so this list may be incomplete.</span></div>')
    newk = set(p.get("new_keys") or [])
    fresh = [r for r in rows if _rkey(r) in newk]
    old = [r for r in rows if _rkey(r) not in newk]
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
    return (warn + ovl + head + older +
            '<p class="note">Under the STOCK Act members may file up to 30–45 days after a trade, so these '
            'disclosures <strong>lag the actual transactions by weeks</strong>. Filings marked <em>SP</em> are '
            'the spouse\'s; <em>options</em> means contracts, not shares. Amounts are broad ranges.</p>')

def sec_trump(t):
    if not t or not t.get("ok"):
        return unavailable("No reliable public data available for a current holdings breakdown.")
    prev = _load_prev()
    same_as_before = bool(prev) and prev.get("trump_annual") == [t.get("source_url"), t.get("annual_date")]
    txn = sec_trump_txn(t)
    if same_as_before:
        nxt = _next_trump_update(t.get("annual_date") or t.get("fetched_at"))
        annual = ('<p class="quiet-note">' + chr(9654) + ' Annual disclosure (Form 278e) unchanged since '
                  'last run ' + chr(8212) + ' <em class="muted">next update: ' + nxt + '</em></p>')
        return txn + annual
    return txn + _trump_full(t)

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

def _next_trump_update(fetched_at_str):
    try:
        dt = datetime.datetime.fromisoformat(fetched_at_str)
        return f"May {dt.year + 1}"
    except:
        return "next year"

def _trump_full(t):
    top = t["top_holdings"][:10]
    ov = []
    for h in top:
        d = h["description"].upper()
        for tk, nm in (("NVDA", "NVIDIA"), ("AVGO", "BROADCOM"), ("GOOGL", "ALPHABET"),
                       ("AMZN", "AMAZON"), ("IBM", "IBM"), ("LLY", "LILLY"), ("TXN", "TEXAS INSTRUMENT"),
                       ("INTC", "INTEL"), ("MU", "MICRON"), ("UBER", "UBER")):
            if nm in d and tk not in ov: ov.append(tk)
    ovl = (f'<div class="callout"><strong>\u2605 Watchlist overlap:</strong> {", ".join(ov)}.</div>') if ov else ""
    rows = "".join(
        f'<tr><td class="tk"><span class="sym cap">{esc(nice(h["description"][:56]))}'
        + ('<span class="badge pel">\u2605 watchlist</span>' if any(
            n in h["description"].upper() for n in ("NVIDIA", "BROADCOM", "ALPHABET", "AMAZON",
                                                    "IBM", "LILLY", "TEXAS INSTRUMENT", "INTEL",
                                                    "MICRON", "UBER")) else "")
        + f'</span></td><td class="n mono">${h["lo"]:,} \u2013 ${h["hi"]:,}</td></tr>' for h in top)
    return ('<div class="callout light"><strong>Annual asset disclosure \u2014 not live trades.</strong> '
            'OGE Form 278e reports assets in broad value ranges for the report year; it is not a record of '
            'purchases or sales and does not reflect current market value. It changes once a year.</div>'
            + ovl +
            '<details class="fold" open><summary>Top 10 reported holdings by value range</summary>'
            '<div class="tw"><table><thead><tr><th>Asset</th><th class="n">Reported range</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
            f'<p class="note">Parsed from the certified PDF: {t["line_items_parsed"]:,} asset line items, '
            f'{t["unique_assets"]:,} distinct assets. Ranges for an asset held in several accounts are summed, '
            f'so totals are sums of range endpoints, not valuations. {esc(t["source"])}.</p></details>')

def _save_macro_snapshot(q):
    """Append current VIX/TNX to rolling 1-year history."""
    if not q or not q.get("macro"): return
    macro = {m["symbol"]: m for m in q["macro"]}
    now = datetime.datetime.now(datetime.timezone.utc)
    history_path = os.path.join(ROOT, "data", "macro_history.json")
    try:
        history = json.load(open(history_path))
    except:
        history = []
    entry = {"ts": now.isoformat()}
    if "^VIX" in macro: entry["vix"] = macro["^VIX"]["last"]
    if "^TNX" in macro: entry["tnx"] = macro["^TNX"]["last"]
    history.append(entry)
    cutoff = (now - datetime.timedelta(days=365)).isoformat()
    history = [e for e in history if e.get("ts", "") >= cutoff]
    json.dump(history, open(history_path, "w"))

def _pctile_str(val, series_key):
    """Return percentile string like '92nd pctl' for val vs rolling history."""
    history_path = os.path.join(ROOT, "data", "macro_history.json")
    try:
        history = json.load(open(history_path))
    except:
        return None
    vals = sorted(e[series_key] for e in history if series_key in e and e[series_key] is not None)
    if len(vals) < 3 or val is None: return None
    n = len(vals)
    # percentile of val in vals (interpolated)
    pos = sum(1 for v in vals if v < val) + 0.5 * sum(1 for v in vals if v == val)
    p = pos / n * 100
    if p >= 99: suffix = "st"
    elif p >= 90: suffix = "th"
    elif p >= 80: suffix = "th"
    else: suffix = "th"
    return f"{p:.0f}{suffix}"

SORT_JS = "<script>\n(function(){\n  var tables = document.querySelectorAll('.tw table');\n  [].forEach.call(tables, function(tb) {\n    var headers = tb.querySelectorAll('th');\n    var body = tb.tBodies[0];\n    if (!body || !headers.length) return;\n    [].forEach.call(headers, function(th, i) {\n      var label = th.textContent.trim().toLowerCase();\n      if (!label.match(/^(ticker|last|day|5d|1m|z|vol)$/i)) return;\n      th.style.cursor = 'pointer';\n      th.title = 'Sort by ' + label;\n      th.addEventListener('click', function() {\n        var dir = this._d = (this._d === 'asc') ? 'desc' : 'asc';\n        var rows = [].slice.call(body.rows);\n        rows.sort(function(a, c) {\n          var va = parseCell((a.cells[i] || a).textContent),\n              vc = parseCell((c.cells[i] || c).textContent);\n          if (typeof va === 'number' && typeof vc === 'number') return dir === 'asc' ? va - vc : vc - va;\n          va = String(va); vc = String(vc);\n          return dir === 'asc' ? va.localeCompare(vc) : vc.localeCompare(va);\n        });\n        var frag = document.createDocumentFragment();\n        rows.forEach(function(r) { frag.appendChild(r); });\n        body.appendChild(frag);\n        [].forEach.call(headers, function(x) { x.classList.remove('sort-asc', 'sort-desc'); });\n        this.classList.add(dir === 'asc' ? 'sort-asc' : 'sort-desc');\n      });\n    });\n  });\n  function parseCell(s) {\n    s = (s || '').trim();\n    if (!s) return '';\n    var num = function(x) { return parseFloat(x.replace(/[^0-9.\\-]/g, '')) || 0; };\n    if (s.charAt(0) === '$') return num(s);                       // price\n    if (s.indexOf('\\u03c3') > 0) return num(s);                   // z-score\n    if (s.indexOf('\\u00d7') > 0) return num(s);                   // volume ratio\n    if (s.indexOf('%') > 0) return num(s);                        // percentage\n    return s.toLowerCase();                                       // ticker / text\n  }\n})();\n</script>"# ------------------------------------------------------------------ page
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
tr.calm td{{opacity:.4;font-size:13px}} tr.calm:hover td{{opacity:1}}
tr.pop td{{background:#fffdf5;font-weight:700}}
tr.pop td:first-child{{box-shadow:inset 4px 0 0 #e0b445}}
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
.badge.trend-up{{background:#e8f5f0;color:#0a7d5a}}
.badge.trend-dn{{background:#fceceb;color:#b3261e}}
.badge.stretch{{background:#fff2d6;color:#8a5a00;border:1px solid #efd9ab}}
.setups{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:18px}}
.set-chip{{display:inline-flex;align-items:center;gap:5px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:5px 10px;font-size:12.5px}}
.set-chip b{{font-weight:700;margin-right:2px}}
.set-dot{{width:6px;height:6px;border-radius:50%;display:inline-block;flex-shrink:0}}
.set-force{{border-left:3px solid var(--up)}}
.set-press{{border-left:3px solid var(--down)}}
.set-str{{border-left:3px solid #c98a00}}
.set-hi{{border-left:3px solid var(--up)}}
.set-lo{{border-left:3px solid var(--down)}}
.wl-toolbar{{display:flex;gap:8px;padding:10px 18px;border-bottom:1px solid var(--line);background:#fafbfc}}
.wl-toolbar select{{padding:4px 8px;border:1px solid var(--line);border-radius:6px;font:13px -apple-system,sans-serif;color:var(--ink);background:#fff;cursor:pointer}}
.wl-toolbar select:focus{{outline:none;border-color:var(--accent)}}
.wl-mobile-sort{{display:none}}
@media(max-width:640px){{.wl-mobile-sort{{display:block}}.wl-filter{{flex:1}}.sched-h{{font-size:11px}}}}
.delta-strip{{background:#f0f2f5;border-radius:8px;padding:10px 14px;margin:10px 0 14px;font-size:13.5px}}.delta-strip h3{{margin:0 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}}.delta-strip ul{{list-style:none;margin:0;padding:0}}.delta-strip li{{display:flex;gap:6px;align-items:baseline;padding:2px 0}}.delta-strip .bl{{white-space:nowrap;color:var(--mut);font-size:12px;flex-shrink:0}}.delta-strip .bd{{color:var(--ink)}}.delta-quiet{{background:#f0f2f5;border-radius:8px;padding:8px 14px;margin:10px 0 14px;font-size:13px;color:var(--mut);text-align:center}}.tw-collapse{{max-height:0;overflow:hidden;transition:max-height .35s ease}}.wl-toggle{{display:block;width:100%;padding:6px;margin:2px 0 0;background:none;border:1px dashed var(--line);border-radius:6px;font:12.5px -apple-system,sans-serif;color:var(--mut);cursor:pointer;transition:background .15s}}.wl-toggle:hover{{background:#f0f2f5;color:var(--ink)}}
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
.regime-bar{{display:flex;align-items:center;gap:8px;padding:6px 0 4px;font-size:14px;border-bottom:1px solid var(--line);margin-bottom:6px}}
.regime-bar strong{{font-weight:700;text-transform:capitalize}}
.regime-bar .regime-why{{color:var(--mut);font-size:12.5px}}
.regime-dot{{width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0}}
.quiet-hero{{padding:6px 0;font-size:13px;color:var(--mut);font-style:italic}}
.rbl em{{font-style:normal;opacity:.65}}
.sort-asc:after{{content:" \u25b2";font-size:9px;margin-left:2px}}
.sort-desc:after{{content:" \u25bc";font-size:9px;margin-left:2px}}
@media(max-width:780px){{th:nth-child(4),td:nth-child(4),th:nth-child(5),td:nth-child(5){{display:none}}
th,td{{padding-left:10px;padding-right:8px;font-size:13px}}
.bl{{min-width:100%;font-size:13px}}
.hero-h{{font-size:11px}}
.bullets li{{font-size:13px;padding:7px 0 7px 14px}}
.macro{{gap:5px}}
.chip{{padding:5px 9px;font-size:12px}}
.rbc{{width:80px}}
.spkc{{width:72px;padding-right:4px}}
.spk{{width:72px!important;height:18px!important}}}}
@media(max-width:500px){{.wrap{{padding:0 12px}}
.chip .cv{{font-size:13px}}
td{{padding:7px 6px;font-size:12px}}
.rbc{{width:60px}}
.mini{{font-size:10px}}}}
@media(max-width:640px){{
section .tw table,.tw thead,.tw tbody,.tw th,.tw td,.tw tr{{display:block}}
.tw thead{{display:none!important}}
.tw tr{{margin-bottom:10px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--card);box-shadow:0 1px 2px rgba(15,20,25,.04)}}
.tw td{{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border:none;font-size:13px;text-align:left!important}}
.tw td:before{{content:attr(data-label);font-weight:600;color:var(--mut);font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap;margin-right:8px}}
.tw td.n{{justify-content:space-between}}
.tk .sub{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:140px}}
.tk .sym{{white-space:nowrap}}
.spk{{width:62px!important;height:16px!important}}
.rbc{{width:auto!important;flex:1;min-width:0;padding:4px 0!important;flex-direction:column;align-items:stretch!important}}
.rb{{min-width:0;width:100%}}
.rbl{{font-size:10.5px}}
.mini{{font-size:10px}}}}
</style></head><body>
<header class="top"><div class="wrap">
<h1>Market Monitor</h1>
<div class="updated"><span class="dot"></span>Last updated: {esc(stamp)}</div>
<div class="sub-h">{esc(mkt)}</div>
<div class="sched-h">▶ Auto-refresh: Mon · Wed · Fri — 22:30 {now.strftime("%Z")}</div>
{macro_strip(q)}
</div></header>
<main><div class="wrap">
{build_today(q, p, q.get("macro", {}))}
{build_setups(q)}
{build_setups(q)}
{build_delta(q, p, _load_prev(), tr)}
<div class="legend"><span class="up">▲ + up</span><span class="down">▼ − down</span>
<span>▬ flat</span><span>★ = on your watchlist</span>
<span>Arrows and +/− carry the same meaning as the colours.</span></div>

<section><div class="hd"><h2><span class="n">1</span>Watchlist</h2>{src(bool(q and q.get('watchlist')),'Yahoo Finance')}</div>
{stale_banner("quotes","market")}{sec_watch(q, p)}</section>

<section><div class="hd"><h2><span class="n">2</span>Congress trading — Nancy Pelosi</h2>{src(bool(p and p.get('ok')),'House Clerk PTR filings')}</div>
{stale_banner("pelosi","House disclosure")}{sec_pelosi(p)}</section>

<section><div class="hd"><h2><span class="n">3</span>Trump — annual disclosure</h2>{src(bool(tr and tr.get('ok')),'OGE Form 278e')}</div>
{stale_banner("trump","OGE 278e")}{sec_trump(tr)}</section>

<footer>{esc(runline)}<br>Informational only — not investment advice.

<h2><span class="n">4</span>Indices</h2>{src(bool(q and q.get('indices')),'Yahoo Finance')}</div>
{stale_banner("quotes","market")}{sec_indices(q)}</section>

<section><div class="hd">

</footer>
{SORT_JS}
</div></main></body></html>"""
    try:
        save_prev_state(q, p, tr)
    except Exception as e:
        print(f"prev_state save failed: {e}", file=sys.stderr)
    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    open(OUT_HTML, "w").write(page)
    print("wrote", OUT_HTML, len(page), "bytes")

main()
