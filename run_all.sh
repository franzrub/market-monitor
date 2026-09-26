#!/bin/sh
# One safe refresh cycle: fetch -> validate -> promote -> rebuild page.
# A failing source keeps its last good data; a failing build keeps the last good page.
cd "$(dirname "$0")" && exec python3 -u scripts/refresh.py
