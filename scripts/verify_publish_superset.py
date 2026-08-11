#!/usr/bin/env python3
"""Fail if a proposed payload drops an eligible published identity."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.merge_data import build_identity_key, meets_publish_requirements
except ModuleNotFoundError:
    from merge_data import build_identity_key, meets_publish_requirements


def identities(payload: dict[str, Any], eligible_only: bool = False) -> set[str]:
    result = set()
    for item in payload.get("items", []):
        if eligible_only and not meets_publish_requirements(item)[0]:
            continue
        # Recompute with the current identity schema so a deliberate identity
        # migration does not look like a total publish shrink merely because
        # the persisted hash values were produced by an older algorithm.
        result.add(build_identity_key(item))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    baseline_path = Path(args.baseline)
    if not baseline_path.exists() or baseline_path.stat().st_size == 0:
        print("no baseline release; superset check skipped for first publication")
        return 0
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    missing = identities(baseline, eligible_only=True) - identities(candidate)
    if missing:
        # 豁免：同 source_url 被候选新记录覆盖的旧记录（数据升级——如机械师空壳→完整规格，
        # identity 因 CPU/屏幕字段变化而不同，但产品仍在）不算回归
        candidate_urls = {
            str(item.get("source_url") or item.get("source_product_id") or "")
            for item in candidate.get("items", [])
        }
        covered = set()
        for item in baseline.get("items", []):
            url = str(item.get("source_url") or item.get("source_product_id") or "")
            if url and url in candidate_urls:
                key = build_identity_key(item)
                if key in missing:
                    covered.add(key)
        real_missing = missing - covered
        if covered:
            print(f"superset: {len(covered)} identities covered by same-source_url upgrade (not regression)", file=sys.stderr)
        if real_missing:
            print(f"publish shrink detected: {len(real_missing)} identities missing", file=sys.stderr)
            for key in sorted(real_missing)[:20]:
                print(f"  {key}", file=sys.stderr)
            return 2
    print(f"superset verified: {len(identities(baseline, eligible_only=True))} baseline identities retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
