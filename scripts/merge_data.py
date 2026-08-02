#!/usr/bin/env python3
"""Merge crawler outputs, deduplicate identities, and enforce publication rules."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SOURCE_ALIASES = {
    "zol": "ZOL",
    "中关村": "ZOL",
    "中关村在线": "ZOL",
    "zol中关村在线": "ZOL",
    "detail.zol.com.cn": "ZOL",
    "jd": "JD",
    "jd.com": "JD",
    "京东": "JD",
    "京东商城": "JD",
    "京东自营": "JD",
    "pconline": "PConline",
    "太平洋电脑网": "PConline",
    "太平洋": "PConline",
}

BRAND_ALIASES = {
    "lenovo": "联想",
    "thinkpad": "ThinkPad",
    "asus": "华硕",
    "acer": "宏碁",
    "dell": "戴尔",
    "hp": "惠普",
    "huawei": "华为",
    "honor": "荣耀",
    "xiaomi": "小米",
    "msi": "微星",
    "microsoft": "微软",
    "机械革命": "机械革命",
    "apple": "苹果",
}

LOW_POWER_SUFFIXES = ("UL", "UP", "G1", "G4", "G7", "U", "Y")
PERFORMANCE_SUFFIXES = ("HX", "HS", "HK", "H")
PORTABLE_CATEGORY_PATTERN = re.compile(
    r"(?:notebook|laptop|笔记本|游戏本|移动工作站|barebone|准系统)",
    re.I,
)
PORTABLE_FORM_PATTERN = re.compile(
    r"(?:notebook|laptop|笔记本|游戏本|移动工作站|便携电脑|barebone|准系统)",
    re.I,
)
ODM_PATTERN = re.compile(r"(?:CLEVO|蓝天|COMPAL|仁宝)", re.I)
CHASSIS_PATTERN = re.compile(r"(?:模具|机模|chassis|barebone|准系统)", re.I)
DESKTOP_PRODUCT_PATTERN = re.compile(
    r"(?:台式(?:机|电脑|整机)|桌上型电脑|desktop\s+(?:computer|PC|tower)|"
    r"mini\s*PC|迷你主机|\bNUC\b|一体机)",
    re.I,
)
DESKTOP_CPU_EVIDENCE_PATTERN = re.compile(
    r"(?:desktop[- ](?:range|class|grade)?\s*(?:CPU|processor|Ryzen)?|"
    r"桌面级(?:CPU|处理器)|台式(?:机)?CPU|socketed\s+(?:desktop\s+)?CPU|"
    r"\bLGA\s*\d{3,4}\b|\bAM[45]\b)",
    re.I,
)
POSSIBLE_SUFFIXLESS_DESKTOP_CPU_PATTERN = re.compile(
    r"(?:i[3579][-\s]?\d{4,5}|(?:Ryzen|锐龙|R)\s*[3579]?\s*[- ]?\d{4,5})",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_records(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "laptops", "records", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError(f"{path}: expected a JSON array or an object containing items")


def normalize_source_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    compact = re.sub(r"[\s_-]+", "", text).lower()
    for alias, canonical in SOURCE_ALIASES.items():
        if compact == re.sub(r"[\s_-]+", "", alias).lower():
            return canonical
    return text.upper() if text else "UNKNOWN"


def atomic_sources(record: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    raw = record.get("atomic_source_names")
    if isinstance(raw, list):
        values.extend(raw)
    elif raw:
        values.append(raw)
    raw_source = record.get("source")
    if isinstance(raw_source, list):
        values.extend(raw_source)
    elif raw_source:
        values.extend(re.split(r"[,，+|/]", str(raw_source)))
    return sorted(
        {normalize_source_name(value) for value in values if str(value).strip()}
        - {"UNKNOWN"}
    )


def normalize_brand(value: Any, title: str = "") -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    probe = (text or title).lower()
    for alias, canonical in BRAND_ALIASES.items():
        if alias.lower() in probe:
            return canonical
    return text


def _identity_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"\b(?:16|24|32|64)gb\b", "", text)
    text = re.sub(r"\b(?:512gb|[124]tb)\b", "", text)
    text = re.sub(r"\b(?:rtx|gtx)\s*\d{3,4}(?:\s*ti)?\b", "", text)
    text = re.sub(r"[\W_]+", "", text)
    return text


def canonical_model_family(record: dict[str, Any]) -> str:
    """Return the source-independent product family used for identity.

    Catalog sources put configuration details after a parenthesis, but those
    details differ in ordering and completeness between sites.  Keeping the
    whole display title therefore prevents the same model and CPU from ever
    meeting in one merge group.  Strip only a leading, verified brand label
    and the parenthesized configuration suffix; model tokens such as Y7000P
    remain intact.
    """

    raw = (
        record.get("model_identity")
        or record.get("model")
        or record.get("title")
        or record.get("name")
    )
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    sources = set(atomic_sources(record))
    if not record.get("model_identity") and sources.intersection({"ZOL", "PConline"}):
        text = re.split(r"[（(]", text, maxsplit=1)[0].strip()

    family = _identity_text(text)
    canonical_brand = normalize_brand(
        record.get("brand"), str(record.get("title", ""))
    )
    brand_labels = {str(record.get("brand") or ""), canonical_brand}
    brand_labels.update(
        alias for alias, canonical in BRAND_ALIASES.items() if canonical == canonical_brand
    )
    for label in sorted(brand_labels, key=len, reverse=True):
        prefix = _identity_text(label)
        if prefix and family.startswith(prefix):
            family = family[len(prefix):]
            break
    return family or _identity_text(text)


def build_identity_key(record: dict[str, Any]) -> str:
    """Build a stable cross-source key from brand and model.

    Source-specific product/SKU IDs are intentionally excluded, because they
    cannot deduplicate the same configuration across ZOL and JD.
    """

    brand = normalize_brand(record.get("brand"), str(record.get("title", "")))
    model = canonical_model_family(record)
    cpu = record.get("cpu") or ""
    base = "|".join((_identity_text(brand), model, _identity_text(cpu)))
    if base.replace("|", ""):
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]
    raise ValueError("record has no usable brand/model/title identity")


def extract_cpu_model(text: Any) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    patterns = (
        r"\b(?:i[3579]|Ultra\s*[3579])[-\s]?\d{3,5}(?:HX|HS|HK|H|UL|UP|U|Y|G[147])\b",
        r"\b(?:Ryzen|锐龙)\s*[3579]?\s*\d{4,5}(?:HX|HS|HK|H|UL|UP|U|Y)\b",
        r"\b\d{4,5}(?:HX|HS|HK|H|UL|UP|U|Y)\b",
        r"(?<![A-Za-z0-9])i[3579][-\s]?\d{4,5}(?:KS|KF|K|F)\b",
        r"\b(?:Ryzen|锐龙|R)\s*[3579]?\s*[- ]?\d{4,5}(?:X3D|XT|X|G)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.I)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()
    return value


def classify_cpu_voltage(cpu: Any) -> str:
    """Classify CPU conservatively. Unknown/bare models are never publishable."""

    model = extract_cpu_model(cpu).upper().replace(" ", "")
    for suffix in LOW_POWER_SUFFIXES:
        if re.search(rf"{re.escape(suffix)}(?:\b|$)", model):
            return "low_power"
    for suffix in PERFORMANCE_SUFFIXES:
        if re.search(rf"{re.escape(suffix)}(?:\b|$)", model):
            return "high_performance" if suffix in {"HX", "HK"} else "standard_performance"
    if re.search(
        r"(?<![A-Z0-9])I[3579][-\s]?\d{4,5}(?:KS|KF|K|F)\b", model
    ):
        return "desktop_performance"
    if re.search(
        r"\b(?:RYZEN|锐龙|R)\s*[3579]?\s*[- ]?\d{4,5}(?:X3D|XT|X|G)\b",
        model,
    ):
        return "desktop_performance"
    return "unknown"


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "是", "有", "支持"}:
        return True
    if normalized in {"false", "0", "no", "n", "否", "无", "不支持"}:
        return False
    return None


def _desktop_cpu_has_portable_product_form(record: dict[str, Any]) -> bool:
    evidence = record.get("evidence")
    evidence_text = (
        " ".join(str(value) for value in evidence.values() if value)
        if isinstance(evidence, dict)
        else ""
    )
    category = str(record.get("source_category") or "")
    form = " ".join(
        str(value)
        for value in (
            record.get("title"),
            record.get("model"),
            record.get("product_form"),
            evidence_text,
        )
        if value
    )
    if DESKTOP_PRODUCT_PATTERN.search(form):
        return False
    category_confirmed = bool(PORTABLE_CATEGORY_PATTERN.search(category))
    explicit_form = bool(PORTABLE_FORM_PATTERN.search(form))
    odm_chassis_form = bool(
        ODM_PATTERN.search(form) and CHASSIS_PATTERN.search(form)
    )
    return category_confirmed and (explicit_form or odm_chassis_form)


def _record_cpu_voltage(record: dict[str, Any]) -> str:
    voltage = record.get("cpu_voltage_type") or classify_cpu_voltage(
        record.get("cpu")
    )
    if voltage != "unknown":
        return str(voltage)
    evidence = record.get("evidence")
    cpu_evidence = (
        str(evidence.get("cpu") or "") if isinstance(evidence, dict) else ""
    )
    cpu_text = str(record.get("cpu") or "")
    if (
        POSSIBLE_SUFFIXLESS_DESKTOP_CPU_PATTERN.search(cpu_text)
        and DESKTOP_CPU_EVIDENCE_PATTERN.search(cpu_evidence)
    ):
        return "desktop_performance"
    return "unknown"


def meets_publish_requirements(record: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if _coerce_bool(record.get("numeric_keypad")) is not True:
        reasons.append("numeric_keypad_not_confirmed")
    if _coerce_bool(record.get("keyboard_backlight")) is not True:
        reasons.append("keyboard_backlight_not_confirmed")
    voltage = _record_cpu_voltage(record)
    if voltage == "desktop_performance":
        if not _desktop_cpu_has_portable_product_form(record):
            reasons.append("desktop_cpu_product_form_not_confirmed")
    elif voltage not in {"standard_performance", "high_performance"}:
        reasons.append(f"cpu_voltage_not_allowed:{voltage}")
    return not reasons, reasons


def _quality(value: Any) -> int:
    if value is None or value == "" or value == []:
        return 0
    if isinstance(value, bool):
        return 4
    if isinstance(value, (int, float)):
        return 3
    if isinstance(value, list):
        return min(5, len(value) + 1)
    return min(10, len(str(value)))


def _merged_bool(records: list[dict[str, Any]], field: str) -> bool | None:
    values = {_coerce_bool(record.get(field)) for record in records}
    values.discard(None)
    if False in values:
        return False
    return True if True in values else None


def merge_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda item: (len(atomic_sources(item)), len(item)), reverse=True)
    merged = deepcopy(ordered[0])
    protected = {
        "source",
        "atomic_source_names",
        "source_url",
        "source_urls",
        "source_rank",
        "source_ranks",
        "numeric_keypad",
        "keyboard_backlight",
    }
    for record in ordered[1:]:
        for key, value in record.items():
            if key not in protected and _quality(value) > _quality(merged.get(key)):
                merged[key] = deepcopy(value)

    sources = sorted({source for record in records for source in atomic_sources(record)})
    source_urls: dict[str, str] = {}
    source_ranks: dict[str, int] = {}
    evidence: dict[str, Any] = {}
    for record in records:
        record_sources = atomic_sources(record)
        existing_urls = record.get("source_urls")
        if isinstance(existing_urls, dict):
            for source, value in existing_urls.items():
                canonical = normalize_source_name(source)
                if value and canonical not in source_urls:
                    source_urls[canonical] = str(value)
        existing_ranks = record.get("source_ranks")
        if isinstance(existing_ranks, dict):
            for source, value in existing_ranks.items():
                canonical = normalize_source_name(source)
                if isinstance(value, int):
                    source_ranks[canonical] = min(
                        value, source_ranks.get(canonical, value)
                    )
        url = record.get("source_url")
        rank = record.get("source_rank")
        for source in record_sources:
            if url and source not in source_urls:
                source_urls[source] = str(url)
            if isinstance(rank, int):
                source_ranks[source] = min(rank, source_ranks.get(source, rank))
        if isinstance(record.get("evidence"), dict):
            evidence.update(record["evidence"])

    merged["numeric_keypad"] = _merged_bool(records, "numeric_keypad")
    merged["keyboard_backlight"] = _merged_bool(records, "keyboard_backlight")
    merged["atomic_source_names"] = sources
    merged["source"] = "+".join(sources)
    merged["source_count"] = len(sources)
    merged["source_urls"] = source_urls
    merged["source_ranks"] = source_ranks
    merged["source_rank"] = min(source_ranks.values()) if source_ranks else None
    merged["evidence"] = evidence
    merged["brand"] = normalize_brand(merged.get("brand"), str(merged.get("title", "")))
    merged["cpu"] = extract_cpu_model(merged.get("cpu"))
    merged["cpu_voltage_type"] = _record_cpu_voltage(merged)
    merged["identity_key"] = build_identity_key(merged)
    return merged


def merge_records(
    records: Iterable[dict[str, Any]], *, publish_only: bool = True
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for raw in records:
        record = deepcopy(raw)
        record["atomic_source_names"] = atomic_sources(record)
        # Always derive the cross-source identity from normalized product data.
        # Crawler IDs and previously supplied keys are source-local evidence only.
        key = build_identity_key(record)
        groups.setdefault(str(key), []).append(record)

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for group in groups.values():
        merged = merge_group(group)
        allowed, reasons = meets_publish_requirements(merged)
        if allowed or not publish_only:
            merged["publish_eligible"] = allowed
            if reasons:
                merged["rejection_reasons"] = reasons
            accepted.append(merged)
        else:
            rejected.append(
                {
                    "identity_key": merged["identity_key"],
                    "title": merged.get("title"),
                    "atomic_source_names": merged["atomic_source_names"],
                    "reasons": reasons,
                }
            )

    accepted.sort(
        key=lambda item: (
            -(item.get("source_count") or 0),
            item.get("source_rank") if isinstance(item.get("source_rank"), int) else 10**9,
            str(item.get("title", "")),
        )
    )
    return accepted, rejected


def build_payload(items: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> dict[str, Any]:
    sources = sorted({source for item in items for source in atomic_sources(item)})
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "count": len(items),
        "sources": sources,
        "items": items,
        "pipeline": {
            "rejected_count": len(rejected),
            "requirements": {
                "numeric_keypad": True,
                "keyboard_backlight": True,
                "cpu_voltage_types": [
                    "standard_performance",
                    "high_performance",
                    "desktop_performance",
                ],
                "desktop_cpu_exception": "portable_product_form_evidence_required",
            },
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", help="crawler JSON files")
    parser.add_argument("--output", required=True)
    parser.add_argument("--rejected-output")
    parser.add_argument("--min-source-records", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records: list[dict[str, Any]] = []
    for input_path in args.inputs:
        source_records = load_records(input_path)
        if len(source_records) < args.min_source_records:
            print(
                f"refusing merge: {input_path} has {len(source_records)} rows; "
                f"minimum is {args.min_source_records}",
                file=sys.stderr,
            )
            return 2
        records.extend(source_records)

    items, rejected = merge_records(records)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_payload(items, rejected), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.rejected_output:
        rejected_path = Path(args.rejected_output)
        rejected_path.parent.mkdir(parents=True, exist_ok=True)
        rejected_path.write_text(
            json.dumps(rejected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"merged {len(records)} raw rows into {len(items)} publishable rows; rejected {len(rejected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
