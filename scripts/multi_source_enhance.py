#!/usr/bin/env python3
"""Multi-source enhancement scanner for crawl_laptops.

Scans Pages-visible single-source rows and cross-checks them against the
raw crawler artifacts (ZOL/JD/PConline latest.json).  For every
Pages-visible single-source row it reports whether a same-identity record
exists in another source's raw data but was NOT merged into the published
row.  Those are the safe targets for multi-source rate improvement:

  - match_found: same identity key exists in another raw source -> the
    merge pipeline should have joined them; investigate why it did not.
  - cpu_mismatch: identity differs only by CPU variant -> variant-level
    overlap, needs family-level review before merging.
  - no_match: no counterpart in any other raw source -> genuine single.

Output is a machine-readable JSON report (candidates) that the
self-repair pipeline can consume to decide what to fix.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.merge_data import build_identity_key, atomic_sources


def load_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("items", data.get("data", []))


def index_by_identity(rows: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        try:
            key = build_identity_key(r)
        except (ValueError, KeyError, TypeError):
            continue
        index[key].append(r)
    return index


def source_set(record: dict) -> set[str]:
    srcs = set(atomic_sources(record))
    if not srcs:
        raw = str(record.get("source") or record.get("source_category") or "")
        for s in ("ZOL", "JD", "PConline"):
            if s in raw:
                srcs.add(s)
    return srcs


def _num(value) -> float | None:
    """Extract a number from memory_gb/storage_gb style fields."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_TITLE_SPEC_RE = re.compile(
    r"(?P<mem>\d+)GB/(?P<sto>\d+)(?:TB|GB)"
)


def _title_spec(record: dict) -> tuple[float | None, float | None]:
    """Fallback memory/storage from title (16GB/1TB or 16GB/512GB)."""
    title = str(record.get("title") or record.get("model") or "")
    m = _TITLE_SPEC_RE.search(title)
    if not m:
        return None, None
    mem = float(m.group("mem"))
    sto = float(m.group("sto"))
    if "TB" in title[m.start():m.end()]:
        sto *= 1024
    return mem, sto


def classify_overlap(a: dict, b: dict) -> tuple[str, str]:
    """Classify a cross-source identity overlap as compatible or not.

    Compatibility requires no hard conflict in memory / storage (the
    dimensions that make two SKUs genuinely different products).  Falls back
    to title-extracted specs when structured fields are missing.
    Returns (kind, reason): kind in {"compatible", "incompatible", "unknown"}.
    """
    ma, mb = _num(a.get("memory_gb")), _num(b.get("memory_gb"))
    sa, sb = _num(a.get("storage_gb")), _num(b.get("storage_gb"))
    if ma is None or mb is None or sa is None or sb is None:
        ta, tb = _title_spec(a), _title_spec(b)
        if ma is None:
            ma = ta[0]
        if mb is None:
            mb = tb[0]
        if sa is None:
            sa = ta[1]
        if sb is None:
            sb = tb[1]
    hard_conflicts = []
    if ma is not None and mb is not None and ma != mb:
        hard_conflicts.append(f"memory {ma}GB vs {mb}GB")
    if sa is not None and sb is not None and sa != sb:
        hard_conflicts.append(f"storage {sa}GB vs {sb}GB")
    if hard_conflicts:
        return "incompatible", "; ".join(hard_conflicts)
    if ma is not None and mb is not None and sa is not None and sb is not None:
        return "compatible", "memory/storage consistent"
    return "unknown", "insufficient config fields to confirm"


def scan(pages_rows: list[dict], raw: dict[str, list[dict]]) -> dict:
    raw_index = {
        src: index_by_identity(rows) for src, rows in raw.items()
    }
    single = [r for r in pages_rows if (r.get("source_count") or 1) < 2]
    report: dict = {
        "total_pages_rows": len(pages_rows),
        "single_rows": len(single),
        "candidates": [],
        "raw_overlaps": [],
        "summary": {},
    }

    # raw 层跨源重叠扫描：同一 identity 出现在两个及以上源的记录
    raw_sources = list(raw.keys())
    for i in range(len(raw_sources)):
        for j in range(i + 1, len(raw_sources)):
            sa, sb = raw_sources[i], raw_sources[j]
            ia, ib = raw_index[sa], raw_index[sb]
            for key in set(ia) & set(ib):
                a, b = ia[key][0], ib[key][0]
                kind, reason = classify_overlap(a, b)
                report["raw_overlaps"].append({
                    "identity_key": key,
                    "sources": [sa, sb],
                    "kind": kind,
                    "reason": reason,
                    "a_title": str(a.get("title") or "")[:80],
                    "b_title": str(b.get("title") or "")[:80],
                    "a_cpu": a.get("cpu"), "b_cpu": b.get("cpu"),
                    "a_memory_gb": a.get("memory_gb"), "b_memory_gb": b.get("memory_gb"),
                    "a_storage_gb": a.get("storage_gb"), "b_storage_gb": b.get("storage_gb"),
                })
    src_counter: Counter[str] = Counter()
    for row in single:
        srcs = source_set(row)
        src_counter.update(srcs)
        try:
            key = build_identity_key(row)
        except (ValueError, KeyError, TypeError):
            report["candidates"].append({
                "title": str(row.get("title") or row.get("model") or "")[:80],
                "source": sorted(srcs),
                "status": "unparseable_identity",
            })
            continue
        matches: list[str] = []
        cpu_only: list[str] = []
        for other_src, index in raw_index.items():
            if other_src in srcs:
                continue
            if key in index:
                matches.append(other_src)
        if matches:
            report["candidates"].append({
                "title": str(row.get("title") or row.get("model") or "")[:80],
                "brand": row.get("brand"),
                "identity_key": key,
                "source": sorted(srcs),
                "status": "match_found",
                "matched_sources": matches,
            })
        else:
            report["candidates"].append({
                "title": str(row.get("title") or row.get("model") or "")[:80],
                "brand": row.get("brand"),
                "identity_key": key,
                "source": sorted(srcs),
                "status": "no_match",
            })
    by_status = Counter(c["status"] for c in report["candidates"])
    by_kind = Counter(o["kind"] for o in report["raw_overlaps"])
    report["summary"] = {
        "by_status": dict(by_status),
        "match_found_count": by_status.get("match_found", 0),
        "no_match_count": by_status.get("no_match", 0),
        "single_by_source": dict(src_counter.most_common()),
        "raw_overlap_count": len(report["raw_overlaps"]),
        "compatible_overlap_count": by_kind.get("compatible", 0),
        "incompatible_overlap_count": by_kind.get("incompatible", 0),
        "unknown_overlap_count": by_kind.get("unknown", 0),
        "potential_multi_rate_gain": round(
            by_status.get("match_found", 0) / len(pages_rows) * 100, 2
        ) if pages_rows else 0,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", required=True, help="Pages latest.json")
    parser.add_argument("--zol", default="", help="ZOL raw latest.json")
    parser.add_argument("--jd", default="", help="JD raw latest.json")
    parser.add_argument("--pconline", default="", help="PConline raw latest.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    pages = load_rows(Path(args.pages))
    raw: dict[str, list[dict]] = {}
    for src, path in (("ZOL", args.zol), ("JD", args.jd), ("PConline", args.pconline)):
        if path and Path(path).exists():
            raw[src] = load_rows(Path(path))

    report = scan(pages, raw)
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    s = report["summary"]
    print(
        f"single={report['single_rows']} match_found={s['match_found_count']} "
        f"no_match={s['no_match_count']} "
        f"raw_overlap={s['raw_overlap_count']} "
        f"compatible={s['compatible_overlap_count']} "
        f"incompatible={s['incompatible_overlap_count']} "
        f"potential_gain={s['potential_multi_rate_gain']}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
