"""Tests for scripts/validate_syntax.py (multi-language syntax validator)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_syntax.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import validate_syntax as vs  # noqa: E402


def _validator(tmp_path):
    return vs.SyntaxValidator(str(tmp_path))


def test_valid_python_passes(tmp_path):
    f = tmp_path / "good.py"
    f.write_text("x = 1\n", encoding="utf-8")
    result = _validator(tmp_path).validate_file(f)
    assert result["passed"] is True


def test_broken_python_fails(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def broken(:\n", encoding="utf-8")
    result = _validator(tmp_path).validate_file(f)
    assert result["passed"] is False
    assert result["language"] == "Python"


def test_valid_json_passes(tmp_path):
    f = tmp_path / "good.json"
    f.write_text(json.dumps({"a": [1, 2]}), encoding="utf-8")
    assert _validator(tmp_path).validate_file(f)["passed"] is True


def test_broken_json_fails(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{broken", encoding="utf-8")
    assert _validator(tmp_path).validate_file(f)["passed"] is False


def test_valid_yaml_passes(tmp_path):
    f = tmp_path / "good.yml"
    f.write_text("name: CI\non: push\n", encoding="utf-8")
    assert _validator(tmp_path).validate_file(f)["passed"] is True


def test_broken_yaml_fails(tmp_path):
    f = tmp_path / "bad.yml"
    f.write_text("name: [unclosed\n  - broken:\n", encoding="utf-8")
    assert _validator(tmp_path).validate_file(f)["passed"] is False


def test_shell_script_validated_with_bash(tmp_path):
    f = tmp_path / "good.sh"
    f.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
    assert _validator(tmp_path).validate_file(f)["passed"] is True
    bad = tmp_path / "bad.sh"
    bad.write_text("if then fi fi (\n", encoding="utf-8")
    result = _validator(tmp_path).validate_file(bad)
    assert result["passed"] is False


def test_skip_patterns_exclude_minified_and_lockfiles(tmp_path):
    v = _validator(tmp_path)
    assert v._should_skip(tmp_path / "package-lock.json") is True
    assert v._should_skip(tmp_path / "node_modules" / "x.js") is True
    assert v._should_skip(tmp_path / "app.min.js") is True
    assert v._should_skip(tmp_path / "scripts" / "app.py") is False


def test_unknown_extension_passes_through(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00\x01\x02")
    result = _validator(tmp_path).validate_file(f)
    assert result["passed"] is True
    assert "SKIPPED" in result["message"]


def test_cli_exit_code_nonzero_on_failure(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(tmp_path), str(bad)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 1


def test_cli_exit_code_zero_on_success(tmp_path):
    good = tmp_path / "good.py"
    good.write_text("x = 1\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(tmp_path), str(good)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0


def test_repo_workflows_and_scripts_are_valid():
    """The validator must pass on this repository's own workflows/scripts/docs."""
    targets = sorted((REPO_ROOT / ".github/workflows").glob("*.yml"))
    targets += sorted((REPO_ROOT / "scripts").glob("*.py"))
    targets += sorted((REPO_ROOT / "docs").glob("*.html"))
    assert targets, "expected workflow/script/doc files to validate"
    v = vs.SyntaxValidator(str(REPO_ROOT))
    failures = [r for r in (v.validate_file(t) for t in targets) if not r["passed"]]
    assert failures == []
