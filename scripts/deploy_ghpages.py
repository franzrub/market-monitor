#!/usr/bin/env python3
"""Deploy app/ (just index.html) to GitHub Pages via git push.

Replaces deploy_netlify.py. Same hash gate: if data/*.json hasn't changed,
skips the push. Needs GH_PAGES_TOKEN, GH_USER, GH_REPO in .env.

Repo must exist. Uses a dedicated gh-pages branch.
No Jekyll processing — .nojekyll added.
"""
import os, sys, json, glob, hashlib, shutil, tempfile, subprocess

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP   = os.path.join(ROOT, "app")
DATA  = os.path.join(ROOT, "data")
STATE = os.path.join(ROOT, ".last_deploy_hash")
TOKEN = os.environ.get("GH_PAGES_TOKEN")
USER  = os.environ.get("GH_USER")
REPO  = os.environ.get("GH_REPO")

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
    if not all([TOKEN, USER, REPO]):
        sys.exit("GH_PAGES_TOKEN, GH_USER, GH_REPO must be set in .env.deploy")
    html_path = os.path.join(APP, "index.html")
    if not os.path.exists(html_path):
        sys.exit(f"missing {html_path} — run refresh.py / build.py first")
    url = f"https://{USER}.github.io/{REPO}/"
    origin = f"https://{USER}:{TOKEN}@github.com/{USER}/{REPO}.git"
    tmpdir = tempfile.mkdtemp(prefix="ghpages-")
    try:
        shutil.copy2(html_path, os.path.join(tmpdir, "index.html"))
        with open(os.path.join(tmpdir, ".nojekyll"), "w") as f:
            f.write("")
        subprocess.run(["git", "-C", tmpdir, "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", tmpdir, "checkout", "-b", "gh-pages"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", tmpdir, "-c", "user.name=deploy",
                        "-c", "user.email=deploy@localhost",
                        "add", "--all"], check=True, capture_output=True)
        subprocess.run(["git", "-C", tmpdir, "-c", "user.name=deploy",
                        "-c", "user.email=deploy@localhost",
                        "commit", "-m", f"deploy {os.path.basename(html_path)}"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", tmpdir, "remote", "add", "origin", origin],
                       check=True, capture_output=True)
        r = subprocess.run(["git", "-C", tmpdir, "push", "--force",
                            "-u", "origin", "gh-pages"],
                           capture_output=True, timeout=60, text=True)
        if r.returncode != 0:
            sys.exit(f"git push failed:\n{r.stderr[:500]}")
        print(f"deployed: state=uploaded url={url}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

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
