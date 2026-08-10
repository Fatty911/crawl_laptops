#!/usr/bin/env python3
"""Audit Pages data for eligibility, duplicate identities, and source regressions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.merge_data import atomic_sources, meets_publish_requirements, normalize_source_name
except ModuleNotFoundError:
    from merge_data import atomic_sources, meets_publish_requirements, normalize_source_name


def payload_sources(payload: dict[str, Any]) -> set[str]:
    sources = {
        normalize_source_name(value)
        for value in payload.get("sources", [])
        if str(value).strip()
    }
    for item in payload.get("items", []):
        sources.update(atomic_sources(item))
    return sources - {"UNKNOWN"}


def audit_payload(
    current: dict[str, Any], baseline: dict[str, Any] | None = None
) -> list[str]:
    errors: list[str] = []
    items = current.get("items")
    if not isinstance(items, list):
        return ["items must be an array"]
    if current.get("count") != len(items):
        errors.append(f"count mismatch: metadata={current.get('count')} actual={len(items)}")
    keys = [item.get("identity_key") for item in items]
    if any(not key for key in keys):
        errors.append("every item must have identity_key")
    # 允许同 identity 多 SKU 行（集显版/独显版等不同配置拆分展示）；
    # 但同 identity 行必须配置可区分（GPU/内存/存储不同），否则是重复噪音
    from collections import Counter
    key_counts = Counter(keys)
    for key, count in key_counts.items():
        if count <= 1:
            continue
        dup_items = [item for item in items if item.get("identity_key") == key]
        sigs = {
            (
                str(item.get("gpu") or ""),
                item.get("memory_gb"),
                item.get("storage_gb"),
            )
            for item in dup_items
        }
        if len(sigs) < len(dup_items):
            errors.append(f"duplicate identity_key {key} with identical config")
    for item in items:
        allowed, reasons = meets_publish_requirements(item)
        if not allowed:
            errors.append(f"ineligible item {item.get('identity_key')}: {','.join(reasons)}")
        sources = atomic_sources(item)
        if not sources:
            errors.append(f"item {item.get('identity_key')} has no atomic source")
        if item.get("source_count") != len(sources):
            errors.append(f"item {item.get('identity_key')} source_count mismatch")
    if baseline:
        missing_sources = payload_sources(baseline) - payload_sources(current)
        if missing_sources:
            errors.append(f"source regression: missing {','.join(sorted(missing_sources))}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    parser.add_argument("--baseline")
    args = parser.parse_args()
    current = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    baseline = None
    if args.baseline:
        path = Path(args.baseline)
        if path.exists() and path.stat().st_size:
            baseline = json.loads(path.read_text(encoding="utf-8"))
    errors = audit_payload(current, baseline)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"audit passed: {len(current['items'])} items, sources={sorted(payload_sources(current))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
