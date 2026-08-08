"""workflow_failure_diagnosis 低产出检测测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.workflow_failure_diagnosis import classify_run


def test_pcl_low_output_detected():
    text = "wrote 124 PConline popularity-ranked records to /out/latest.json\nsome log"
    cls, reason, actionable = classify_run("Crawl PConline", "success", text)
    assert cls == "low_output"
    assert actionable is True
    assert "124" in reason


def test_pcl_normal_output_not_flagged():
    text = "wrote 512 PConline popularity-ranked records to /out/latest.json"
    cls, reason, actionable = classify_run("Crawl PConline", "success", text)
    assert cls == "expected_success"


def test_pcl_no_records_line_not_flagged():
    text = "some unrelated log without records"
    cls, _, _ = classify_run("Crawl PConline", "success", text)
    assert cls == "expected_success"


def test_zol_success_unchanged():
    text = "wrote 1257 ZOL records"
    cls, _, _ = classify_run("Crawl ZOL", "success", text)
    assert cls == "expected_success"
