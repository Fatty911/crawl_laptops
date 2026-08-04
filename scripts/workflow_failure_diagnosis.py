#!/usr/bin/env python3
"""Classify a completed crawler workflow and build an AI diagnosis prompt.

Adapted from crawl_cars' AI_Auto_Fix_Monitor chain.  The laptops repository
keeps its publication gate non-negotiable, so the monitor produces a filed
GitHub issue with the AI diagnosis instead of pushing unreviewed code.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from scripts.classify_crawl_failure import classify
except ModuleNotFoundError:
    from classify_crawl_failure import classify

CRAWLER_WORKFLOWS = {"Crawl ZOL", "Crawl JD", "Crawl PConline"}

EXPECTED_SKIP_MARKERS = (
    "不在 08:00-12:30 或 13:00-22:00 爬取窗口",
    "已因剩余安全时间不足跳过",
    "step1 已因剩余安全时间不足跳过",
    "半月周期",
)
PROGRESS_MARKERS = (
    "本次运行未完成，提交爬取进度",
    "update ZOL crawl progress",
    "update JD crawl progress",
    "Exit code: 10",
    "exit code: 10",
)
PROXY_DIRECT_MARKERS = (
    "required proxy unavailable",
    "无代理，直接运行",
    "proxy unavailable",
)


def read_logs(paths: list[str]) -> str:
    chunks = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.exists() and path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def classify_run(workflow_name: str, conclusion: str, text: str) -> tuple[str, str, bool]:
    if conclusion == "failure":
        classification, reason = classify(text, progress_threshold=200)
        return classification, reason, classification in {"site_breakage", "unknown"}
    if conclusion == "success":
        if workflow_name not in CRAWLER_WORKFLOWS:
            return "not_crawler", "非爬虫 workflow，不做爬虫预期检查", False
        if any(marker in text for marker in EXPECTED_SKIP_MARKERS):
            return "expected_skip", "workflow 在窗口外或预算不足时按预期跳过", False
        if any(marker in text for marker in PROGRESS_MARKERS):
            return "expected_progress_exit", "增量爬取按预期保存进度后结束", False
        if any(marker in text for marker in PROXY_DIRECT_MARKERS):
            return "proxy_degraded", "代理降级或不可用；可能是订阅节点问题，不改代码", False
        return "expected_success", "workflow 成功且未发现明显跑偏迹象", False
    return f"conclusion_{conclusion or 'unknown'}", "workflow 未失败也未成功", False


def build_prompt(workflow_name: str, run_id: str, conclusion: str, text: str) -> str:
    log_excerpt = text[-120000:]
    return f"""你在 GitHub Actions 中作为爬虫工作流故障诊断代理运行。

## 仓库背景
- 仓库：Fatty911/crawl_laptops，聚合 ZOL 热度榜、京东销量榜与 PConline 热门榜的笔记本数据
- 爬虫链：crawl-zol.yml / crawl-jd.yml / crawl-pconline.yml → merge-and-filter.yml → deploy-pages.yml
- 所有爬虫必须走 Mihomo 代理（scripts/setup_proxy_runtime.py --require-proxy）
- ZOL/JD 为增量游标爬取：exit 10 表示保存进度待续，属正常行为
- 发布门禁不可绕过：数字小键盘 + 键盘背光 + 标压/高性能 CPU 证据，未知即拒

## 本次运行
- Workflow: {workflow_name}
- Run ID: {run_id}
- Conclusion: {conclusion}

## 任务
判断失败根因属于以下哪一类，并给出可执行的修复建议（不要输出需要联网才能验证的臆测参数）：
1. 站点结构变化（选择器/页面结构失效）→ 给出需要更新的解析函数与定位思路
2. 代理/网络问题（订阅节点、mihomo、Cloudflare 拦截）→ 说明检查方向
3. 风控问题（京东 risk-verification 等）→ 给出延迟/UA/cookie 调整建议
4. 数据质量门禁（min-records 不足等）→ 分析真实原因
5. 临时故障（runner 抖动、API 限流）→ 建议重试，不改代码

## 输出格式（严格遵守）
第一行：根因分类: <类别编号和名称>
第二行：置信度: <0-1>
第三行起：修复建议（纯文本，不要编造文件内容，不要输出未经验证的代码）

## 日志摘录
```text
{log_excerpt}
```"""


def write_outputs(path: str, classification: str, reason: str, should_diagnose: bool) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"classification={classification}\n")
        handle.write(f"reason={reason}\n")
        handle.write(f"should_diagnose={'true' if should_diagnose else 'false'}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="*")
    parser.add_argument("--prompt-output", required=True)
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    args = parser.parse_args()

    workflow_name = os.environ.get("WORKFLOW_NAME", "")
    conclusion = os.environ.get("WORKFLOW_CONCLUSION", "")
    run_id = os.environ.get("WORKFLOW_RUN_ID", "")
    text = read_logs(args.logs)

    classification, reason, should_diagnose = classify_run(workflow_name, conclusion, text)
    print(f"classification={classification}")
    print(f"should_diagnose={'true' if should_diagnose else 'false'}")
    print(f"reason={reason}")
    write_outputs(args.github_output, classification, reason, should_diagnose)

    if should_diagnose:
        Path(args.prompt_output).write_text(
            build_prompt(workflow_name, run_id, conclusion, text), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
