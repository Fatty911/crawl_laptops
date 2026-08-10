#!/usr/bin/env python3
"""Fetch ZOL items from live Pages as fallback for search terms."""
import json
import sys
import urllib.request
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/zol/latest.json")
try:
    d = json.load(urllib.request.urlopen("https://nbs.jiucai.eu.org/data/latest.json", timeout=20))
    items = d.get("items", [])
    zol_items = [r for r in items if "ZOL" in str(r.get("source", ""))]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(zol_items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"fallback: {len(zol_items)} ZOL items from Pages -> {out}")
except Exception as exc:
    print(f"fallback failed: {type(exc).__name__} {exc}", file=sys.stderr)
    sys.exit(1)
