#!/usr/bin/env python3
"""Keep runtime laptop data out of Git and bound Actions artifact retention."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ARTIFACT_POLICIES = (
    ("zol-data-", 30),
    ("pconline-data-", 30),
    ("jd-data-", 30),
    ("pconline-ai-patch-", 7),
    ("pconline-validation-", 14),
    ("pconline-review-", 14),
    ("pconline-final-validation-", 14),
    ("single-source-repair-proposal-", 3),
)


def stages_data_directory(text: str) -> bool:
    """Return True when a shell block can stage runtime data or dynamic paths."""
    logical_lines: list[str] = []
    pending = ""
    for physical_line in text.splitlines():
        line = physical_line.strip()
        pending = f"{pending} {line}".strip() if pending else line
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical_lines.append(pending)
        pending = ""
    if pending:
        return True

    for line in logical_lines:
        stripped = line.strip()
        if not stripped.startswith("git add"):
            continue
        if stripped == "git add" or not re.match(r"^git\s+add(?:\s|$)", stripped):
            continue
        if "$((" in stripped or "$(`" in stripped or "$({" in stripped or "$([" in stripped:
            return True
        if "$((" in stripped or "$(" in stripped or "`" in stripped:
            return True
        try:
            arguments = shlex.split(stripped)
        except ValueError:
            return True
        for value in arguments[2:]:
            normalized = value.replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
            if value in {"-A", "--all", "-u", "--update", ".", "./"}:
                return True
            if normalized == "data" or normalized.startswith("data/"):
                return True
    return False


def upload_step_block(lines: list[str], upload_index: int) -> tuple[int, str]:
    """Return the YAML list item containing an upload-artifact action."""
    step_pattern = re.compile(r"^(\s*)-\s+(?:name|uses):")
    step_start = next(
        (
            candidate
            for candidate in range(upload_index, -1, -1)
            if step_pattern.match(lines[candidate])
        ),
        None,
    )
    if step_start is None:
        raise ValueError("upload-artifact action is not inside a recognizable step")
    step_indent = len(step_pattern.match(lines[step_start]).group(1))  # type: ignore[union-attr]
    step_end = len(lines)
    for candidate in range(step_start + 1, len(lines)):
        line = lines[candidate]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent < step_indent or (indent == step_indent and re.match(r"^\s*-\s+", line)):
            step_end = candidate
            break
    return step_start, "\n".join(lines[step_start:step_end])


def upload_artifact_indexes(lines: list[str]) -> list[int]:
    """Find upload-artifact steps without matching upload-pages-artifact."""
    return [
        index for index, line in enumerate(lines) if "uses: actions/upload-artifact@" in line
    ]


def classify_artifact(artifact_name: str) -> int:
    """Return the only permitted retention for an exact artifact prefix."""
    for prefix, retention in ARTIFACT_POLICIES:
        if artifact_name.startswith(prefix):
            return retention
    raise ValueError(f"unknown artifact name: {artifact_name}")


def validate_artifact_policy(artifact_name: str, retention: int | None) -> None:
    expected = classify_artifact(artifact_name)
    if retention is None:
        raise ValueError(f"{artifact_name}: retention-days is missing")
    if retention != expected:
        raise ValueError(f"{artifact_name}: retention must be {expected}, got {retention}")


def _artifact_name_and_retention(block: str) -> tuple[str, int | None]:
    name_match = re.search(r"(?m)^\s+name:\s*(.+?)\s*$", block)
    retention_match = re.search(r"retention-days:\s*(\d+)", block)
    if not name_match:
        raise ValueError("upload-artifact step lacks name")
    return name_match.group(1).strip().strip('"\''), int(retention_match.group(1)) if retention_match else None


def main() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "data"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.splitlines()
    if tracked:
        raise SystemExit(f"runtime data paths must not be tracked: {tracked[:10]}")

    errors: list[str] = []
    for workflow in sorted((ROOT / ".github/workflows").glob("*.y*ml")):
        text = workflow.read_text(encoding="utf-8")
        if stages_data_directory(text):
            errors.append(f"{workflow.name}: dynamic, broad, or runtime-data git add is forbidden")
        lines = text.splitlines()
        upload_indexes = upload_artifact_indexes(lines)
        for index in upload_indexes:
            try:
                _, block = upload_step_block(lines, index)
                artifact_name, retention = _artifact_name_and_retention(block)
                validate_artifact_policy(artifact_name, retention)
            except ValueError as exc:
                errors.append(f"{workflow.name}: {exc}")
    if errors:
        raise SystemExit("\n".join(errors))
    print("storage policy valid")


if __name__ == "__main__":
    main()
