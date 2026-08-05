#!/usr/bin/env python3
"""Decide whether a completed crawler workflow needs a code-level auto-fix."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from classify_crawl_failure import classify


CN_OFFSET = timedelta(hours=8)
MORNING_START = 8 * 60
MORNING_END = 12 * 60 + 30
AFTERNOON_START = 13 * 60
AFTERNOON_END = 22 * 60
CRAWLER_WORKFLOWS = {"Crawl ZOL", "Crawl JD", "Crawl PConline"}
EXPECTED_SKIP_MARKERS = (
    "不在 08:00-12:30 或 13:00-22:00 爬取窗口",
    "已因剩余安全时间不足跳过",
    "step1 已因剩余安全时间不足跳过",
)


def read_logs(paths: list[str]) -> str:
    chunks = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.exists() and path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None


def cn_minutes(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    cn_time = dt.astimezone(UTC) + CN_OFFSET
    return cn_time.hour * 60 + cn_time.minute


def inside_expected_window(minutes: int | None) -> bool:
    if minutes is None:
        return True
    return MORNING_START <= minutes <= MORNING_END or AFTERNOON_START <= minutes <= AFTERNOON_END


def detect_success_drift(
    workflow_name: str, event_name: str, text: str, started_at: datetime | None
) -> tuple[str, str, bool]:
    if workflow_name not in CRAWLER_WORKFLOWS:
        return "not_crawler", "非主爬虫 workflow，不做爬虫预期检查", False

    if any(marker in text for marker in EXPECTED_SKIP_MARKERS):
        return "expected_skip", "workflow 在窗口外按预期跳过", False

    if re.search(r"爬取|crawl|step1|Crawl popularity", text, re.IGNORECASE):
        minutes = cn_minutes(started_at)
        if not inside_expected_window(minutes):
            return (
                "crawler_ran_outside_window",
                f"workflow 在北京时间窗口外启动了爬虫步骤，event={event_name}, cn_minutes={minutes}",
                True,
            )

    if "无代理，直接运行" in text:
        return "proxy_direct_fallback", "本次为无代理直连；可能是 Secret 或订阅节点问题，不自动改代码", False

    return "expected_success", "workflow 成功且未发现明显跑偏迹象", False


def write_outputs(path: str, classification: str, reason: str, should_fix: bool) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"classification={classification}\n")
        f.write(f"reason={reason}\n")
        f.write(f"should_fix={'true' if should_fix else 'false'}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 workflow 完成结果是否需要自动修复")
    parser.add_argument("logs", nargs="*", help="workflow 日志文件")
    parser.add_argument("--github-output", default="", help="GitHub Actions output 文件路径")
    parser.add_argument("--progress-threshold", type=int, default=200)
    args = parser.parse_args()

    text = read_logs(args.logs)
    workflow_name = os.environ.get("WORKFLOW_NAME", "")
    conclusion = os.environ.get("WORKFLOW_CONCLUSION", "")
    event_name = os.environ.get("WORKFLOW_EVENT", "")
    started_at = parse_utc(os.environ.get("WORKFLOW_STARTED_AT", "")) or parse_utc(
        os.environ.get("WORKFLOW_CREATED_AT", "")
    )

    if conclusion == "failure":
        classification, reason = classify(text, args.progress_threshold)
        should_fix = classification in {"site_breakage", "unknown"}
    elif conclusion == "success":
        classification, reason, should_fix = detect_success_drift(workflow_name, event_name, text, started_at)
    else:
        classification = f"conclusion_{conclusion or 'unknown'}"
        reason = "workflow 未失败也未成功，通常不代表需要代码修复"
        should_fix = False

    print(f"classification={classification}")
    print(f"should_fix={'true' if should_fix else 'false'}")
    print(f"reason={reason}")
    write_outputs(args.github_output, classification, reason, should_fix)
    return 0


if __name__ == "__main__":
    main()
