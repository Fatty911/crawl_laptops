"""Tests for scripts/validate_workflow_expectations.py and check_workflow_expectations.py."""

import os
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_workflow_expectations as vwe
import check_workflow_expectations as cwe


class TestValidateWorkflowExpectations:
    def test_long_running_zol_has_correct_structure(self):
        """crawl-zol.yml must pass all checks."""
        errors = []
        path = REPO_ROOT / ".github/workflows/crawl-zol.yml"
        assert path.exists()
        vwe.check_base_crawler(path, errors)
        vwe.check_long_running_crawler(path, errors)
        assert errors == [], f"ZOL workflow check failed: {errors}"

    def test_long_running_jd_has_correct_structure(self):
        """crawl-jd.yml must pass all checks."""
        errors = []
        path = REPO_ROOT / ".github/workflows/crawl-jd.yml"
        assert path.exists()
        vwe.check_base_crawler(path, errors)
        vwe.check_long_running_crawler(path, errors)
        assert errors == [], f"JD workflow check failed: {errors}"

    def test_pconline_passes_base_checks(self):
        """crawl-pconline.yml must pass base checks."""
        errors = []
        path = REPO_ROOT / ".github/workflows/crawl-pconline.yml"
        assert path.exists()
        vwe.check_base_crawler(path, errors)
        assert errors == [], f"PConline base check failed: {errors}"

    def test_trigger_workflow_has_correct_structure(self):
        errors = []
        path = REPO_ROOT / ".github/workflows/crawl-trigger.yml"
        assert path.exists()
        vwe.check_trigger_workflow(path, errors)
        assert errors == [], f"Trigger check failed: {errors}"

    def test_merge_workflow_exists(self):
        errors = []
        path = REPO_ROOT / ".github/workflows/merge-and-filter.yml"
        assert path.exists()
        vwe.check_merge_workflow(path, errors)
        assert errors == [], f"Merge check failed: {errors}"

    def test_ai_monitor_exists(self):
        errors = []
        path = REPO_ROOT / ".github/workflows/AI_Auto_Fix_Monitor.yml"
        assert path.exists()
        vwe.check_ai_monitor(path, errors)
        assert errors == [], f"AI Monitor check failed: {errors}"

    def test_cli_returns_zero_on_pass(self, tmp_path):
        """Running the script as CLI returns exit code 0."""
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts/validate_workflow_expectations.py")],
            capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, f"CLI failed: {proc.stdout} {proc.stderr}"


class TestCheckWorkflowExpectations:
    def test_detect_success_drift_expected_skip(self):
        classification, reason, should_fix = cwe.detect_success_drift(
            "Crawl ZOL", "workflow_dispatch",
            "不在 08:00-12:30 或 13:00-22:00 爬取窗口", None,
        )
        assert classification == "expected_skip"
        assert should_fix is False

    def test_detect_success_drift_expected_success(self):
        classification, reason, should_fix = cwe.detect_success_drift(
            "Crawl ZOL", "workflow_dispatch",
            "Run step1 loop\nCrawl popularity ranking\n数据爬取完成", None,
        )
        assert classification == "expected_success"
        assert should_fix is False

    def test_detect_success_drift_not_crawler(self):
        classification, reason, should_fix = cwe.detect_success_drift(
            "CI", "push", "test output", None,
        )
        assert classification == "not_crawler"

    def test_detect_success_drift_proxy_direct(self):
        classification, reason, should_fix = cwe.detect_success_drift(
            "Crawl JD", "schedule",
            "无代理，直接运行\n数据爬取完成", None,
        )
        assert classification == "proxy_direct_fallback"
        assert should_fix is False
