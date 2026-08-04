"""Crawl trigger workflow contract + budget window/clamp behavior."""

from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import yaml

from scripts import crawl_budget

ROOT = Path(__file__).resolve().parents[1]
CN = ZoneInfo("Asia/Shanghai")


def test_trigger_workflow_declares_repository_dispatch_and_window_gate():
    text = (ROOT / ".github/workflows/crawl-trigger.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    event = workflow.get("on", workflow.get(True, {}))
    assert event["repository_dispatch"]["types"] == ["trigger-crawl"]
    assert "workflow_dispatch" in event
    job_steps = [step["name"] for step in workflow["jobs"]["trigger"]["steps"]]
    assert "Select Beijing-time crawl window" in job_steps
    assert job_steps.index("Select Beijing-time crawl window") < job_steps.index(
        "Trigger source crawlers"
    )
    trigger_step = workflow["jobs"]["trigger"]["steps"][job_steps.index("Trigger source crawlers")]
    assert "steps.window.outputs.skip != 'true'" in trigger_step["if"]
    assert "crawl-zol.yml" in trigger_step["run"]
    assert "crawl-jd.yml" in trigger_step["run"]
    assert "crawl-pconline.yml" in trigger_step["run"]


def test_configure_skips_outside_beijing_windows(tmp_path):
    github_env = tmp_path / "env"
    github_output = tmp_path / "out"
    for hour, expect_skip in ((3, True), (9, False), (12, False), (20, False), (23, True)):
        for file in (github_env, github_output):
            file.unlink(missing_ok=True)
        fake_now = datetime(2026, 8, 4, hour, 0, 0, tzinfo=CN)
        with mock.patch.object(crawl_budget, "cn_now", return_value=fake_now):
            args = mock.Mock(
                schedule_profile="", profile="auto",
                morning_run_time=7200, afternoon_run_time=10800,
                window_end_buffer_seconds=900,
                github_env=str(github_env), github_output=str(github_output),
            )
            assert crawl_budget.configure(args) == 0
        outputs = github_output.read_text(encoding="utf-8")
        if expect_skip:
            assert "skip=true" in outputs, f"hour={hour}"
        else:
            assert "skip=false" in outputs, f"hour={hour}"


def test_configure_clamps_run_time_to_window_end(tmp_path):
    github_env = tmp_path / "env"
    github_output = tmp_path / "out"
    # 11:30 Beijing: 12:30 morning end minus 900s buffer leaves 2700s,
    # which clamps the requested 7200s run time.
    fake_now = datetime(2026, 8, 4, 11, 30, 0, tzinfo=CN)
    with mock.patch.object(crawl_budget, "cn_now", return_value=fake_now):
        args = mock.Mock(
            schedule_profile="", profile="auto",
            morning_run_time=7200, afternoon_run_time=10800,
            window_end_buffer_seconds=900,
            github_env=str(github_env), github_output=str(github_output),
        )
        assert crawl_budget.configure(args) == 0
    env_text = github_env.read_text(encoding="utf-8")
    assert "RUN_TIME=2700" in env_text
    assert "RUN_PROFILE=morning" in env_text

    # 21:55 Beijing: buffer already exceeds the window remainder -> skip.
    for file in (github_env, github_output):
        file.unlink(missing_ok=True)
    fake_now = datetime(2026, 8, 4, 21, 55, 0, tzinfo=CN)
    with mock.patch.object(crawl_budget, "cn_now", return_value=fake_now):
        args = mock.Mock(
            schedule_profile="", profile="auto",
            morning_run_time=7200, afternoon_run_time=10800,
            window_end_buffer_seconds=900,
            github_env=str(github_env), github_output=str(github_output),
        )
        assert crawl_budget.configure(args) == 0
    assert "skip=true" in github_output.read_text(encoding="utf-8")


def test_clamp_reduces_run_time_by_elapsed_budget(tmp_path, monkeypatch):
    github_env = tmp_path / "env"
    fake_now = datetime(2026, 8, 4, 14, 0, 0, tzinfo=CN)
    monkeypatch.setenv("RUN_TIME", "40000")
    monkeypatch.setenv("RUN_PROFILE", "afternoon")
    monkeypatch.setenv("WORKFLOW_START_EPOCH", "0")
    monkeypatch.setenv("MAX_WORKFLOW_SECONDS", "21600")
    monkeypatch.setenv("PROGRESS_COMMIT_BUFFER_SECONDS", "1800")
    with mock.patch.object(crawl_budget, "cn_now", return_value=fake_now):
        args = mock.Mock(
            step_label="step1", skip_env="STEP1_SKIP",
            progress_buffer_seconds=1800, window_end_buffer_seconds=900,
            github_env=str(github_env),
        )
        assert crawl_budget.clamp(args) == 0
    env_text = github_env.read_text(encoding="utf-8")
    # window_safe = 22:00 - 14:00 - 900s = 27900; action_safe = 19800;
    # the minimum budget clamps the oversized RUN_TIME.
    assert "RUN_TIME=19800" in env_text

    # When the remaining budget drops below the minimum, clamp skips the step.
    github_env.unlink(missing_ok=True)
    monkeypatch.setenv("MAX_WORKFLOW_SECONDS", "2000")
    with mock.patch.object(crawl_budget, "cn_now", return_value=fake_now):
        args = mock.Mock(
            step_label="step1", skip_env="STEP1_SKIP",
            progress_buffer_seconds=1800, window_end_buffer_seconds=900,
            github_env=str(github_env),
        )
        assert crawl_budget.clamp(args) == 0
    env_text = github_env.read_text(encoding="utf-8")
    assert "STEP1_SKIP=true" in env_text
