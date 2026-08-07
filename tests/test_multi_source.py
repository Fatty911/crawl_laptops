"""multi_source_enhance 测试：raw 层跨源重叠扫描与兼容性分类。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.multi_source_enhance import (
    classify_overlap,
    index_by_identity,
    scan,
)


def make_row(title, source, **kw):
    r = {"title": title, "model": title, "source": source, "brand": "测试"}
    r.update(kw)
    return r


def test_classify_overlap_compatible_same_config():
    a = make_row("测试本 Pro(i7 14650HX/16GB/1TB/RTX5060)", "ZOL",
                 cpu="i7-14650HX", memory_gb=16, storage_gb=1024)
    b = make_row("测试本 Pro(酷睿i7-14650HX/16GB/1TB/RTX5060)", "PConline",
                 cpu="i7-14650HX", memory_gb=16, storage_gb=1024)
    kind, reason = classify_overlap(a, b)
    assert kind == "compatible"


def test_classify_overlap_incompatible_storage():
    a = make_row("华为本 Pro(32GB/1TB)", "ZOL", memory_gb=32, storage_gb=1024)
    b = make_row("华为本 Pro(32GB/2TB)", "PConline", memory_gb=32, storage_gb=2048)
    kind, reason = classify_overlap(a, b)
    assert kind == "incompatible"
    assert "storage" in reason or "存储" in reason


def test_classify_overlap_incompatible_memory():
    a = make_row("联想本(64GB/2TB)", "ZOL", memory_gb=64, storage_gb=2048)
    b = make_row("联想本(192GB/4TB)", "PConline", memory_gb=192, storage_gb=4096)
    kind, reason = classify_overlap(a, b)
    assert kind == "incompatible"


def test_classify_overlap_unknown_fields():
    a = make_row("神舟本(i9 14900HX/32GB/1TB)", "ZOL")
    b = make_row("神舟本(酷睿i9-14900HX/32GB/1TB)", "PConline")
    kind, reason = classify_overlap(a, b)
    assert kind in ("compatible", "unknown")


def test_scan_reports_overlap(tmp_path):
    zol = [make_row("灵耀14 2025(Ultra9 285H/32GB/1TB)", "ZOL",
                    cpu="Ultra 9 285H", memory_gb=32, storage_gb=1024)]
    pcl = [make_row("灵耀14 2025(酷睿Ultra9 285H/32GB/1TB/2.8K)", "PConline",
                    cpu="Ultra 9 285H", memory_gb=32, storage_gb=1024)]
    pages = [make_row("灵耀14 2025(Ultra9 285H/32GB/1TB)", "ZOL", source_count=1)]
    report = scan(pages, {"ZOL": zol, "PConline": pcl})
    # 单源行在 raw 层有匹配
    assert report["summary"]["raw_overlap_count"] >= 1
    assert report["summary"]["compatible_overlap_count"] >= 1


def test_index_by_identity_dedupes():
    rows = [
        make_row("本 A(i7 14650HX/16GB/1TB)", "ZOL"),
        make_row("本 A(i7 14650HX/16GB/1TB)", "PConline"),
    ]
    idx = index_by_identity(rows)
    assert len(idx) == 1  # 同 identity 归一组


def test_scan_empty_pages():
    report = scan([], {"ZOL": [], "PConline": []})
    assert report["total_pages_rows"] == 0
    assert report["single_rows"] == 0
    assert report["summary"]["raw_overlap_count"] == 0
