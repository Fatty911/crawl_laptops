import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_storage_policy import (
    classify_artifact,
    stages_data_directory,
    upload_artifact_indexes,
    validate_artifact_policy,
)


ROOT = Path(__file__).resolve().parents[1]


def test_current_repository_storage_policy_passes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_storage_policy.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "storage policy valid" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "git add -A",
        "git add --all",
        "git add .",
        "git add data/latest.json",
        "git add -- $(git diff --name-only)",
        "git add -- `git diff --name-only`",
    ],
)
def test_staging_runtime_data_or_dynamic_paths_fails_closed(command):
    assert stages_data_directory(command)


def test_fixed_non_data_staging_is_allowed():
    assert not stages_data_directory(
        "git add -- scripts/merge_data.py scripts/crawl_zol.py"
    )


def test_pages_artifact_is_not_classified_as_a_data_artifact():
    assert classify_artifact("zol-data-20260803") == 30
    with pytest.raises(ValueError, match="unknown artifact"):
        classify_artifact("pages-artifact")
    pages_lines = (ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8").splitlines()
    assert any("upload-pages-artifact@" in line for line in pages_lines)
    assert upload_artifact_indexes(pages_lines) == []


@pytest.mark.parametrize(
    ("name", "retention"),
    [
        ("zol-data-20260803", 30),
        ("pconline-ai-patch-123", 7),
        ("pconline-final-validation-123", 14),
        ("single-source-repair-proposal-123", 3),
    ],
)
def test_known_artifact_policies(name, retention):
    validate_artifact_policy(name, retention)


@pytest.mark.parametrize(
    ("name", "retention"),
    [
        ("unknown-123", 3),
        ("zol-data-20260803", None),
        ("zol-data-20260803", 3),
    ],
)
def test_unknown_missing_or_wrong_retention_fails(name, retention):
    with pytest.raises(ValueError):
        validate_artifact_policy(name, retention)


def test_unterminated_shell_continuation_fails_closed():
    assert stages_data_directory("git add -- scripts/merge_data.py \\")
