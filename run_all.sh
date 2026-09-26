#!/bin/sh
# Daily refresh + GitHub Pages deploy cycle.
# A failing source keeps its last good data; a failing build keeps the last good page.
cd "$(dirname "$0")" || exit 1
python3 -u scripts/refresh.py

# --- publish su GitHub Pages (deploy solo se i dati sono cambiati) ---
set -a; . ./.env.deploy; set +a
python3 scripts/deploy_ghpages.py
