"""Failure classification for the AI auto-fix monitor."""

from pathlib import Path

from scripts.workflow_failure_diagnosis import build_prompt, classify_run


def test_failure_site_breakage_asks_for_diagnosis():
    text = "配置页面加载超时\n403\n"
    classification, reason, should = classify_run("Crawl ZOL", "failure", text)
    assert classification == "site_breakage"
    assert should is True


def test_failure_progress_exit_is_not_a_bug():
    text = "本次运行未完成，提交爬取进度，下次续跑\n"
    classification, _, should = classify_run("Crawl JD", "failure", text)
    assert classification == "progress_exit"
    assert should is False


def test_success_expected_skip_outside_window():
    text = "当前北京时间 03:00 不在 08:00-12:30 或 13:00-22:00 爬取窗口，跳过触发\n"
    classification, _, should = classify_run("Crawl ZOL", "success", text)
    assert classification == "expected_skip"
    assert should is False


def test_success_progress_exit_is_normal():
    text = "ZOL crawl exit code: 10\n本次运行未完成，提交爬取进度，下次续跑\n"
    classification, _, should = classify_run("Crawl ZOL", "success", text)
    assert classification == "expected_progress_exit"
    assert should is False


def test_success_proxy_degradation_is_not_code_change():
    text = "required proxy unavailable: mihomo controller did not become ready\n"
    classification, _, should = classify_run("Crawl JD", "success", text)
    assert classification == "proxy_degraded"
    assert should is False


def test_non_crawler_workflow_is_ignored():
    classification, _, should = classify_run("Merge and Filter", "success", "ok")
    assert classification == "not_crawler"
    assert should is False


def test_prompt_contains_repo_context_and_log_excerpt():
    prompt = build_prompt("Crawl JD", "12345", "failure", "detail_risk_verification")
    assert "Fatty911/crawl_laptops" in prompt
    assert "Run ID: 12345" in prompt
    assert "detail_risk_verification" in prompt
    assert "发布门禁不可绕过" in prompt



def test_monitor_only_files_actionable_diagnoses():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "AI_Auto_Fix_Monitor.yml").read_text(encoding="utf-8")
    assert "if: steps.classify.outputs.should_diagnose == 'true'" in workflow
    assert "|| steps.classify.outputs.classification != ''" not in workflow
    assert 'repos/${GITHUB_REPOSITORY}/issues?state=open&labels=crawl-failure-diagnosis' in workflow
