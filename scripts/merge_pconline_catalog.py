#!/usr/bin/env python3
"""Merge PConline hot-list + catalog + search artifacts into one raw file."""
import json
import sys
from pathlib import Path

hot_path = Path("data/raw/pconline/latest.json")
cat_path = Path("data/raw/pconline/catalog.json")
search_path = Path("data/raw/pconline/search.json")
out_path = hot_path

if not hot_path.exists():
    print("hot missing; nothing to merge", file=sys.stderr)
    sys.exit(0)

hot = json.loads(hot_path.read_text(encoding="utf-8"))
seen = {str(r.get("source_url") or r.get("source_product_id")) for r in hot}
merged = list(hot)

for name, path in (("catalog", cat_path), ("search", search_path)):
    if not path.exists():
        print(f"{name} merge skipped: missing {path.name}", file=sys.stderr)
        continue
    extra = json.loads(path.read_text(encoding="utf-8"))
    added = 0
    for r in extra:
        key = str(r.get("source_url") or r.get("source_product_id"))
        if key not in seen:
            seen.add(key)
            merged.append(r)
            added += 1
    print(f"merged PConline {name}: +{added} (total {len(merged)})")

out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"final PConline raw: {len(merged)}")
