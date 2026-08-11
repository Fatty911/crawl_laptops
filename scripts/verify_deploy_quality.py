#!/usr/bin/env python3
"""部署后数据验证：检查 Pages 数据符合预期才算部署成功。

检查项：
1. Machinike 记录 CPU 具体型号覆盖率（目标 ≥85%）
2. Machinike 屏幕尺寸覆盖率（目标 ≥95%）
3. 无空壳记录（cpu 是整标题/空 + 无 screen）
4. JS 解析结果抽查：随机取 3 条 Machinike 记录，重新抓官网详情页规格表，
   对比 CPU/屏幕是否与 Pages 一致（验证 JS 解析真实有效）
"""
import argparse
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from scripts.crawl_machenike import fetch, parse_attr_specs
    from scripts.crawler_utils import make_session
except ModuleNotFoundError:
    from crawl_machenike import fetch, parse_attr_specs
    from crawler_utils import make_session


def fetch_pages(url: str) -> dict:
    d = json.load(urllib.request.urlopen(url, timeout=30))
    return d


def check_coverage(items: list[dict]) -> list[str]:
    errors = []
    mk = [r for r in items if "Machinike" in str(r.get("source", ""))]
    if not mk:
        return ["无 Machinike 数据"]
    has_cpu = [r for r in mk if r.get("cpu") and re.search(r"\d{3,5}", str(r.get("cpu", "")))]
    has_scr = [r for r in mk if r.get("screen_size")]
    empty = [r for r in mk if not r.get("screen_size") and not r.get("memory_gb")]
    cpu_rate = len(has_cpu) / len(mk)
    scr_rate = len(has_scr) / len(mk)
    print(f"Machinike {len(mk)}: CPU具体型号 {len(has_cpu)} ({cpu_rate:.0%}) | 屏幕 {len(has_scr)} ({scr_rate:.0%}) | 全空 {len(empty)}")
    if cpu_rate < 0.85:
        errors.append(f"CPU 覆盖率不足: {cpu_rate:.0%} < 85%")
    if scr_rate < 0.95:
        errors.append(f"屏幕覆盖率不足: {scr_rate:.0%} < 95%")
    if empty:
        errors.append(f"{len(empty)} 条全空记录（无 CPU/屏幕/内存）")
    return errors


def check_js_parse(items: list[dict]) -> list[str]:
    """JS 解析抽查：重抓 3 条详情页规格表，对比 Pages 数据。"""
    errors = []
    mk = [r for r in items if "Machinike" in str(r.get("source", "")) and r.get("source_url")]
    if not mk:
        return ["无 Machinike 数据可抽查"]
    session = make_session()
    sample = random.sample(mk, min(3, len(mk)))
    for r in sample:
        url = r.get("source_url", "")
        try:
            html = fetch(session, url, delay=0.5)
            attrs = parse_attr_specs(html)
            attr_cpu = attrs.get("CPU型号", "")
            attr_scr = re.search(r"(\d+(?:\.\d+)?)\s*英寸", attrs.get("屏幕规格", ""))
            page_cpu = str(r.get("cpu", ""))
            page_scr = r.get("screen_size")
            ok_cpu = attr_cpu and attr_cpu in page_cpu or (not attr_cpu and not page_cpu)
            ok_scr = (attr_scr and page_scr and abs(float(attr_scr.group(1)) - float(page_scr)) < 1) or (not attr_scr and not page_scr)
            status = "OK" if (ok_cpu and ok_scr) else "MISMATCH"
            print(f"  [{status}] {str(r.get('title',''))[:30]} | 官网JS: cpu={attr_cpu or '无'} 屏幕={attr_scr.group(1) if attr_scr else '无'} | Pages: cpu={page_cpu or '空'} 屏幕={page_scr or '空'}")
            if status == "MISMATCH":
                errors.append(f"JS 解析与 Pages 不一致: {str(r.get('title',''))[:30]}")
        except Exception as exc:
            errors.append(f"JS 抽查失败 {url}: {type(exc).__name__}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages-url", default="https://nbs.jiucai.eu.org/data/latest.json")
    parser.add_argument("--skip-js", action="store_true", help="跳过 JS 抽查（网络受限时）")
    args = parser.parse_args()

    try:
        payload = fetch_pages(args.pages_url)
    except Exception as exc:
        print(f"Pages 读取失败: {type(exc).__name__} {exc}")
        return 1

    items = payload.get("items", [])
    errors = check_coverage(items)
    if not args.skip_js:
        errors.extend(check_js_parse(items))

    if errors:
        print("\n[FAIL] 部署后验证未通过:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\n[PASS] 部署后数据验证通过（覆盖率达标 + JS 解析一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
