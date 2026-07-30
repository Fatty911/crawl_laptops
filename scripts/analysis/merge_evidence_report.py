#!/usr/bin/env python3
"""Produce a machine-readable report tracing merge and admission evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    return payload.get("items", [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", nargs="+", required=True)
    parser.add_argument("--merged", required=True)
    parser.add_argument("--rejected", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    raw_summaries = []
    for path in args.raw:
        payload = load(path)
        rows = items(payload)
        source = (
            payload.get("source")
            if isinstance(payload, dict)
            else None
        )
        if not source:
            row_sources = sorted(
                {
                    str(row.get("source")).strip()
                    for row in rows
                    if str(row.get("source") or "").strip()
                }
            )
            source = "+".join(row_sources) or "unknown"
        raw_summaries.append(
            {
                "path": path,
                "source": source,
                "count": len(rows),
                "positive_evidence": {
                    "numeric_keypad": sum(row.get("numeric_keypad") is True for row in rows),
                    "keyboard_backlight": sum(row.get("keyboard_backlight") is True for row in rows),
                    "allowed_cpu": sum(
                        row.get("cpu_voltage_type")
                        in {
                            "standard_performance",
                            "high_performance",
                            "desktop_performance",
                        }
                        for row in rows
                    ),
                    "desktop_cpu_exception": sum(
                        row.get("cpu_voltage_type") == "desktop_performance"
                        for row in rows
                    ),
                },
            }
        )
    merged = load(args.merged)
    rejected = load(args.rejected)
    rejection_reasons = Counter(
        reason for row in rejected for reason in row.get("reasons", [])
    )
    source_combinations = Counter(
        "+".join(row.get("atomic_source_names", [])) for row in items(merged)
    )
    report = {
        "raw": raw_summaries,
        "published_count": len(items(merged)),
        "rejected_count": len(rejected),
        "multi_source_count": sum(
            len(row.get("atomic_source_names", [])) >= 2 for row in items(merged)
        ),
        "source_combinations": dict(sorted(source_combinations.items())),
        "rejection_reasons": dict(rejection_reasons.most_common()),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
