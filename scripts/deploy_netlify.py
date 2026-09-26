#!/usr/bin/env python3
"""Deploy app/ directory to Netlify, but only when the underlying data changed.

We hash data/*.json (the inputs), NOT index.html: the page embeds a "last run"
timestamp that changes every run, so hashing the HTML would always look changed.
Volatile timestamp-ish keys inside the JSON are stripped before hashing, so a
re-fetch with identical numbers is a no-op. Fails safe toward deploying.

Env: NETLIFY_TOKEN, NETLIFY_SITE_ID.  Use --force to deploy regardless.
"""
import io, os, sys, json, glob, hashlib, zipfile, urllib.request, urllib.error

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP   = os.path.join(ROOT, "app")
DATA  = os.path.join(ROOT, "data")
STATE = os.path.join(ROOT, ".last_deploy_hash")
TOKEN = os.environ.get("NETLIFY_TOKEN")
SITE  = os.environ.get("NETLIFY_SITE_ID")

VOLATILE_KEYS = {"fetched_at", "generated_at", "as_of", "asof", "timestamp",
                 "updated_at", "last_run", "run_at", "retrieved_at", "ts"}

def strip_volatile(o):
    if isinstance(o, dict):
        return {k: strip_volatile(v) for k, v in o.items() if k not in VOLATILE_KEYS}
    if isinstance(o, list):
        return [strip_volatile(v) for v in o]
    return o

def data_hash():
    h = hashlib.sha256()
    for path in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        with open(path, "rb") as f:
            raw = f.read()
        h.update(os.path.basename(path).encode())
        try:
            h.update(json.dumps(strip_volatile(json.loads(raw)),
                                sort_keys=True, separators=(",", ":")).encode())
        except Exception:
            h.update(raw)
    return h.hexdigest()

def deploy():
    if not TOKEN or not SITE:
        sys.exit("NETLIFY_TOKEN and NETLIFY_SITE_ID must be set")
    if not os.path.exists(os.path.join(APP, "index.html")):
        sys.exit(f"missing {APP}/index.html — run refresh.py first")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(APP):
            for fn in files:
                path = os.path.join(root, fn)
                arcname = os.path.relpath(path, APP)
                z.write(path, arcname)
    req = urllib.request.Request(
        f"https://api.netlify.com/api/v1/sites/{SITE}/deploys",
        data=buf.getvalue(), method="POST")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/zip")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            info = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Netlify API {e.code}: {e.read().decode('utf-8','replace')[:500]}")
    except urllib.error.URLError as e:
        sys.exit(f"network error: {e}")
    print(f"deployed: state={info.get('state')} url={info.get('ssl_url') or info.get('url')}")

def main():
    force = "--force" in sys.argv
    cur = data_hash()
    prev = open(STATE).read().strip() if os.path.exists(STATE) else ""
    if cur == prev and not force:
        print("no data change — skipping deploy")
        return
    deploy()
    with open(STATE, "w") as f:
        f.write(cur)

if __name__ == "__main__":
    main()
