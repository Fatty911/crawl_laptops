#!/usr/bin/env python3
"""Static checks for laptop crawler workflow timing and self-healing rules."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

CRAWLER_LONG_RUN = {"crawl-zol.yml", "crawl-jd.yml"}
TRIGGER = "crawl-trigger.yml"
MERGE = "merge-and-filter.yml"
AI_MONITOR = "AI_Auto_Fix_Monitor.yml"
PCONLINE = "crawl-pconline.yml"

EXPECTED_SCHEDULE_COUNT = 2


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def assert_condition(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def check_base_crawler(path: Path, errors: list[str]) -> None:
    """Check basic shape: triggers, permissions, concurrency, timeout."""
    data = load_yaml(path)
    text = path.read_text(encoding="utf-8")
    name = path.name

    # Triggers: workflow_dispatch + schedule
    event = data.get(True, {})
    triggers = set(event.keys())
    assert_condition(
        triggers >= {"workflow_dispatch", "schedule"},
        f"{name} must have workflow_dispatch + schedule triggers",
        errors,
    )

    # Schedule: exactly 2 cron entries
    schedules = event.get("schedule", [])
    assert_condition(
        len(schedules) == EXPECTED_SCHEDULE_COUNT,
        f"{name} must have exactly {EXPECTED_SCHEDULE_COUNT} schedule entries, got {len(schedules)}",
        errors,
    )
    for s in schedules:
        assert_condition(
            isinstance(s, dict) and "cron" in s and s["cron"],
            f"{name} schedule entry missing cron field",
            errors,
        )

    # Concurrency
    concurrency = data.get("concurrency", {})
    assert_condition(
        concurrency.get("cancel-in-progress") is False,
        f"{name} must have cancel-in-progress: false",
        errors,
    )

    # Jobs section
    jobs = data.get("jobs", {})
    assert_condition(
        len(jobs) == 1 and "crawl" in jobs,
        f"{name} must have exactly one 'crawl' job",
        errors,
    )


def check_long_running_crawler(path: Path, errors: list[str]) -> None:
    """Check that a long-running crawler (zol/jd) has the expected structure."""
    text = path.read_text(encoding="utf-8")
    name = path.name

    # Budget script usage
    assert_condition(
        "scripts/crawl_budget.py configure" in text,
        f"{name} must use shared window budget script",
        errors,
    )
    assert_condition(
        "scripts/crawl_budget.py clamp" in text,
        f"{name} must clamp runtime to workflow budget",
        errors,
    )

    # Window constants
    assert_condition(
        "WINDOW_END_BUFFER_SECONDS" in text,
        f"{name} must define WINDOW_END_BUFFER_SECONDS",
        errors,
    )

    # Debug mode handling
    assert_condition(
        "debug_mode" in text.lower(),
        f"{name} must handle debug_mode input",
        errors,
    )

    # Concurrency group
    crawler = "zol" if name == "crawl-zol.yml" else "jd"
    expected_group = f"{crawler}-crawl-${{{{ github.ref }}}}"
    concurrency_lines = [l for l in text.split("\n") if "group:" in l]
    assert_condition(
        any(expected_group in l for l in concurrency_lines),
        f"{name} concurrency group must be {expected_group}",
        errors,
    )

    # Timeout
    assert_condition(
        "timeout-minutes: 390" in text,
        f"{name} should have 390min timeout",
        errors,
    )

    # Progress state directory
    assert_condition(
        f"crawl_state/{crawler}" in text,
        f"{name} must use crawl_state/{crawler} for progress",
        errors,
    )

    # Artifact with date
    assert_condition(
        f"{crawler}-data-" in text,
        f"{name} must upload artifact with {crawler}-data- prefix",
        errors,
    )

    # Proxy configuration
    assert_condition(
        "setup_proxy_runtime.py" in text,
        f"{name} must configure proxy via setup_proxy_runtime.py",
        errors,
    )


def check_trigger_workflow(path: Path, errors: list[str]) -> None:
    """Check the external trigger workflow."""
    text = path.read_text(encoding="utf-8")
    name = path.name

    assert_condition(
        "scripts/crawl_budget.py configure" in text,
        f"{name} must use shared window budget script",
        errors,
    )
    assert_condition(
        "run_profile" in text,
        f"{name} must dispatch with run_profile",
        errors,
    )


def check_merge_workflow(path: Path, errors: list[str]) -> None:
    """Check the merge and filter workflow."""
    data = load_yaml(path)
    text = path.read_text(encoding="utf-8")
    name = path.name

    # Must exist and have jobs
    jobs = data.get("jobs", {})
    assert_condition(len(jobs) > 0, f"{name} must have at least one job", errors)

    # Check permissions
    perms = data.get("permissions", {})
    assert_condition(
        "contents" in perms if isinstance(perms, dict) else True,
        f"{name} must define permissions",
        errors,
    )


def check_ai_monitor(path: Path, errors: list[str]) -> None:
    """Check the AI auto-fix monitor workflow."""
    if not path.exists():
        errors.append(f"{path.name} must exist")
        return
    data = load_yaml(path)
    text = path.read_text(encoding="utf-8")
    name = path.name

    jobs = data.get("jobs", {})
    assert_condition(len(jobs) > 0, f"{name} must have at least one job", errors)

    # Should reference workflow_failure_diagnosis
    assert_condition(
        "workflow_failure_diagnosis" in text,
        f"{name} must reference workflow_failure_diagnosis",
        errors,
    )


def main() -> int:
    errors: list[str] = []

    workflows_dir = ROOT / ".github/workflows"

    # Check long-running crawlers (zol, jd)
    for wf_name in CRAWLER_LONG_RUN:
        path = workflows_dir / wf_name
        assert_condition(path.exists(), f"{wf_name} must exist", errors)
        if path.exists():
            check_base_crawler(path, errors)
            check_long_running_crawler(path, errors)

    # Check PConline (basic for now, will be expanded in P1-9)
    pconline_path = workflows_dir / PCONLINE
    assert_condition(pconline_path.exists(), f"{PCONLINE} must exist", errors)
    if pconline_path.exists():
        check_base_crawler(pconline_path, errors)

    # Check trigger
    trigger_path = workflows_dir / TRIGGER
    assert_condition(trigger_path.exists(), f"{TRIGGER} must exist", errors)
    if trigger_path.exists():
        check_trigger_workflow(trigger_path, errors)

    # Check merge
    merge_path = workflows_dir / MERGE
    assert_condition(merge_path.exists(), f"{MERGE} must exist", errors)
    if merge_path.exists():
        check_merge_workflow(merge_path, errors)

    # Check AI monitor
    ai_path = workflows_dir / AI_MONITOR
    check_ai_monitor(ai_path, errors)

    if errors:
        print("Workflow expectation check FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("All workflow expectations verified OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
