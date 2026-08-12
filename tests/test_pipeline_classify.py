from __future__ import annotations

from scripts.workflow_failure_diagnosis import classify_run


def test_failure_merge_pipeline_shrink_classified_as_pipeline():
    text = (
        "merged 625 raw rows into 112 publishable rows; rejected 378\n"
        "publish shrink detected: 2 identities missing\n"
        "Process completed with exit code 2"
    )
    classification, reason, should = classify_run("Merge and Filter", "failure", text)
    assert classification == "merge_pipeline_failure"
    assert should is True
    assert "merge/deploy" in reason


def test_failure_merge_artifact_download_classified_as_pipeline():
    text = (
        "artifact download failed: no unexpired artifact starting with 'jd-data-'\n"
        "Process completed with exit code 2"
    )
    classification, _, should = classify_run("Merge and Filter", "failure", text)
    assert classification == "merge_pipeline_failure"
    assert should is True


def test_failure_tee_race_classified_as_pipeline():
    text = (
        "replayed shell line in mutable merge step Download latest complete crawler artifacts\n"
        "Process completed with exit code 2"
    )
    classification, _, should = classify_run("Merge and Filter", "failure", text)
    assert classification == "merge_pipeline_failure"
    assert should is True


def test_crawler_http_status_still_site_breakage():
    """爬虫源日志的 403/404 仍是站点风控信号（不能被管道分类误夺）。"""
    text = "HTTP 403 Forbidden on detail page fetch; no progress saved"
    classification, _, should = classify_run("Crawl ZOL", "failure", text)
    assert classification == "site_breakage"
    assert should is True
