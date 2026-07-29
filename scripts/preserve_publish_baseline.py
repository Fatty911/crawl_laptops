#!/usr/bin/env python3
"""Preserve all eligible identities from the previously published payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.merge_data import build_payload, load_records, meets_publish_requirements, merge_records
except ModuleNotFoundError:
    from merge_data import build_payload, load_records, meets_publish_requirements, merge_records


def preserve(candidate: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    candidate_items = candidate.get("items", [])
    baseline_items = (baseline or {}).get("items", [])
    eligible_baseline = [item for item in baseline_items if meets_publish_requirements(item)[0]]
    merged, rejected = merge_records([*candidate_items, *eligible_baseline])
    payload = build_payload(merged, rejected)
    payload["pipeline"]["candidate_count"] = len(candidate_items)
    payload["pipeline"]["baseline_count"] = len(eligible_baseline)
    payload["pipeline"]["preserved_count"] = len(
        {item["identity_key"] for item in merged}
        - {item["identity_key"] for item in candidate_items}
    )
    return payload


def read_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = preserve(
        read_payload(Path(args.candidate)) or {"items": []},
        read_payload(Path(args.baseline)),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"baseline={result['pipeline']['baseline_count']} "
        f"candidate={result['pipeline']['candidate_count']} "
        f"published={result['count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
