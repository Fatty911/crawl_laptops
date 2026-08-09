#!/usr/bin/env python3
"""Merge PConline hot-list + catalog artifacts into one raw file."""
import json
import sys
from pathlib import Path

hot_path = Path("data/raw/pconline/latest.json")
cat_path = Path("data/raw/pconline/catalog.json")
out_path = hot_path

if not hot_path.exists() or not cat_path.exists():
    print("catalog merge skipped: missing hot/catalog file", file=sys.stderr)
    sys.exit(0)

hot = json.loads(hot_path.read_text(encoding="utf-8"))
cat = json.loads(cat_path.read_text(encoding="utf-8"))
seen = {str(r.get("source_url") or r.get("source_product_id")) for r in hot}
merged = list(hot)
for r in cat:
    key = str(r.get("source_url") or r.get("source_product_id"))
    if key not in seen:
        seen.add(key)
        merged.append(r)
out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"merged PConline hot+catalog: {len(hot)} + {len(cat)} -> {len(merged)}")
