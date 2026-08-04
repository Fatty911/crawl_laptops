#!/usr/bin/env python3
"""带代理支持的爬虫启动器（移植自 crawl_cars run_with_proxy.py，适配 laptops 三源）

在配置了 Mihomo 代理环境（HTTP_PROXY 指向 127.0.0.1:7890）的本机/VPS 上，
一次性按顺序运行三个数据源的增量爬取。GitHub Actions 中不使用此脚本——
workflow 各自走 setup_proxy_runtime.py + 独立 job。

用法示例:
  python scripts/run_with_proxy.py --time-limit 7200 --max-items 0
  python scripts/run_with_proxy.py --skip-jd --sources zol pconline
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime


def run_source(label: str, command: list[str]) -> int:
    print(f"\n--- {label}: {' '.join(command)} ---")
    result = subprocess.run(command)
    if result.returncode == 10:
        print(f"{label} 未完成，进度已保存，等待下次运行")
    elif result.returncode != 0:
        print(f"{label} 失败 exit={result.returncode}")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="带代理的笔记本爬虫启动器")
    parser.add_argument("--time-limit", type=int, default=7200, help="每个源的运行时间限制(秒)")
    parser.add_argument("--max-items", type=int, default=0, help="每个源的最大条数(0=不限)")
    parser.add_argument("--proxy", choices=["env", "off"], default="env",
                        help="env=使用当前 HTTP_PROXY 环境（Mihomo）；off=清除代理直连")
    parser.add_argument("--sources", nargs="+", default=["zol", "jd", "pconline"],
                        choices=["zol", "jd", "pconline"], help="要运行的源")
    args = parser.parse_args()

    print(f"=== 开始运行 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"时间限制: {args.time_limit}秒, 每源最大: {args.max_items or '不限'}")

    env = os.environ.copy()
    if args.proxy == "env":
        proxy_url = env.get("HTTP_PROXY") or env.get("HTTPS_PROXY") or ""
        if proxy_url:
            print(f"代理模式: 使用环境代理 {proxy_url}")
        else:
            print("警告: 未设置 HTTP_PROXY，将直连运行（建议先配置 Mihomo）")
    else:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(key, None)
        print("代理模式: off（直连）")

    commands = {
        "zol": ["python", "scripts/crawl_zol.py",
                "--output", "data/raw/zol/latest.json",
                "--progress-dir", "crawl_state/zol",
                "--time-limit", str(args.time_limit),
                "--max-items", str(args.max_items),
                "--min-records", "50"],
        "jd": ["python", "scripts/crawl_jd.py",
               "--output", "data/raw/jd/latest.json",
               "--progress-dir", "crawl_state/jd",
               "--time-limit", str(args.time_limit),
               "--max-items", str(args.max_items),
               "--min-records", "50"],
        "pconline": ["python", "scripts/crawl_pconline.py",
                     "--output", "data/raw/pconline/latest.json",
                     "--time-limit", str(args.time_limit),
                     "--max-items", str(args.max_items) or "120",
                     "--min-records", "50"],
    }

    exit_code = 0
    for source in args.sources:
        code = run_source(source, commands[source])
        if code not in (0, 10):
            exit_code = code

    print(f"\n=== 运行结束 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
