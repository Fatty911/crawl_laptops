from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def load_workflow(name: str) -> tuple[str, dict]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def triggers(workflow: dict) -> dict:
    # PyYAML 1.1 treats the unquoted GitHub Actions key `on` as boolean true.
    return workflow.get("on", workflow.get(True, {}))


def test_source_schedules_include_staggered_daily_shanghai_afternoon_runs():
    expected = {
        "crawl-zol.yml": {
            "crons": {"17 3 * * 1", "23 5 * * *"},
            "mapping": "05:23 UTC = 13:23 Asia/Shanghai (UTC+8)",
        },
        "crawl-jd.yml": {
            "crons": {"47 3 * * 2", "53 5 * * *"},
            "mapping": "05:53 UTC = 13:53 Asia/Shanghai (UTC+8)",
        },
    }

    for name, contract in expected.items():
        text, workflow = load_workflow(name)
        event_config = triggers(workflow)
        crons = {entry["cron"] for entry in event_config["schedule"]}

        assert crons == contract["crons"]
        assert "workflow_dispatch" in event_config
        assert contract["mapping"] in text
        assert "Scheduled workflows run from the default branch (main)." in text


def test_source_workflows_use_independent_non_cancelling_concurrency_groups():
    # A shared concurrency group cancels pending siblings when the external
    # trigger dispatches all sources back to back; every source must own its
    # group, matching the crawl_cars/crawl_phones naming.
    expected = {
        "crawl-zol.yml": "zol-crawl-${{ github.ref }}",
        "crawl-jd.yml": "jd-crawl-${{ github.ref }}",
        "crawl-pconline.yml": "pconline-crawl-${{ github.ref }}",
    }
    groups = set()
    for name, group in expected.items():
        _, workflow = load_workflow(name)
        assert workflow["concurrency"]["group"] == group
        assert workflow["concurrency"]["cancel-in-progress"] is False
        groups.add(group)

    assert len(groups) == 3


def test_merge_only_runs_for_successful_source_completion_or_manual_dispatch():
    _, workflow = load_workflow("merge-and-filter.yml")
    event_config = triggers(workflow)

    assert event_config["workflow_run"]["workflows"] == ["Crawl ZOL", "Crawl JD", "Crawl PConline"]
    assert event_config["workflow_run"]["types"] == ["completed"]
    assert "workflow_dispatch" in event_config

    condition = workflow["jobs"]["merge"]["if"]
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "github.event.workflow_run.conclusion == 'success'" in condition

    steps = workflow["jobs"]["merge"]["steps"]
    names = [step["name"] for step in steps]
    assert names.index("Wait for sibling crawler artifacts") < names.index(
        "Download latest complete crawler artifacts"
    )
    assert names.index("Create or update rolling data release") < names.index(
        "Trigger Pages deployment"
    )
    trigger_step = steps[names.index("Trigger Pages deployment")]
    assert "gh workflow run deploy-pages.yml --ref main" in trigger_step["run"]
    assert "secrets.ACTION_PAT || github.token" in workflow["jobs"]["merge"]["env"]["GH_TOKEN"]


def test_pages_keeps_manual_and_release_triggers():
    _, workflow = load_workflow("deploy-pages.yml")
    event_config = triggers(workflow)

    assert "workflow_dispatch" in event_config
    assert event_config["release"]["types"] == ["published"]

def test_merge_includes_pconline_source():
    _, workflow = load_workflow("merge-and-filter.yml")
    assert "Crawl PConline" in triggers(workflow)["workflow_run"]["workflows"]
