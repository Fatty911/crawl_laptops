# -*- coding: utf-8 -*-
"""process_zol.py —— 从 ZOL 原始 HTML 重新提取字段（处理与爬虫分离）。

用法: python3 scripts/process_zol.py --raw-dir data/raw_html --items data/zol_items.json --output data/zol_processed.json

爬虫只负责抓取并保存原始 HTML（data/raw_html/{product_id}.html）与列表页原始记录；
本脚本从原始 HTML 重新运行规格解析/字段提取——处理逻辑变更时只需重跑本脚本，无需重爬。
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.crawler_utils import clean_text, gpu_fields, keyboard_flags, parse_cpu_fields, text_from_spec
    from scripts.merge_data import classify_cpu_voltage, extract_cpu_model
except ModuleNotFoundError:
    from crawler_utils import clean_text, gpu_fields, keyboard_flags, parse_cpu_fields, text_from_spec
    from merge_data import classify_cpu_voltage, extract_cpu_model

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("需要 bs4: pip install beautifulsoup4", file=sys.stderr)
    sys.exit(1)


def parse_specs(html: str) -> dict[str, str]:
    """从原始 HTML 解析规格表（与 crawl_zol.parse_specs 同逻辑，独立实现保证可重跑）。"""
    soup = BeautifulSoup(html, "html.parser")
    specs: dict[str, str] = {}
    for row in soup.select("tr"):
        cells = row.select("th, td")
        if len(cells) < 2:
            continue
        key = clean_text(cells[0].get_text(" ", strip=True)).replace("纠错", "")
        value = clean_text(cells[1].get_text(" ", strip=True)).replace("纠错", "")
        value = re.sub(r"(更多.*|进入官网.*)$", "", value).strip()
        if key and value and len(key) <= 24:
            specs[key] = value
    return specs


def enrich_from_specs(specs: dict[str, str], item: dict[str, Any]) -> dict[str, Any]:
    """从规格表提取字段（与 crawl_zol.enrich_item 的提取段同逻辑）。"""
    cpu_raw = text_from_spec(specs, "CPU型号", "处理器型号") or item.get("title", "")
    cpu = extract_cpu_model(cpu_raw)
    cpu_brand, cpu_family = parse_cpu_fields(cpu_raw)
    keyboard = text_from_spec(specs, "键盘描述", "键盘")
    numeric_keypad, keyboard_backlight = keyboard_flags(keyboard)
    gpu_type_raw = text_from_spec(specs, "显卡类型")
    gpu = text_from_spec(specs, "显卡芯片", "显卡型号") or item.get("gpu", "")
    gpu_type, dedicated_gpu = gpu_fields(gpu_type_raw, gpu)
    screen = text_from_spec(specs, "屏幕尺寸")
    memory = text_from_spec(specs, "内存容量")
    storage = text_from_spec(specs, "硬盘容量", "存储容量")
    battery = text_from_spec(specs, "电池容量", "电池类型")
    weight = text_from_spec(specs, "笔记本重量", "产品重量", "重量")
    ports_text = "；".join(
        value
        for key, value in specs.items()
        if any(token in key for token in ("数据接口", "视频接口", "音频接口", "其它接口"))
    )
    product_form = clean_text(
        "；".join(
            value
            for key, value in specs.items()
            if key in {"产品类型", "产品定位", "包装清单"}
        )
    )
    item.update(
        {
            "cpu": cpu,
            "cpu_brand": cpu_brand,
            "cpu_family": cpu_family,
            "cpu_voltage_type": classify_cpu_voltage(cpu),
            "numeric_keypad": numeric_keypad if numeric_keypad is not None else item.get("numeric_keypad"),
            "keyboard_backlight": keyboard_backlight if keyboard_backlight is not None else item.get("keyboard_backlight"),
            "dedicated_gpu": dedicated_gpu if dedicated_gpu is not None else item.get("dedicated_gpu"),
            "gpu_type": gpu_type or item.get("gpu_type"),
            "gpu": gpu or item.get("gpu"),
            "screen_size": screen or item.get("screen_size"),
            "memory_size": memory or item.get("memory_size"),
            "storage_size": storage or item.get("storage_size"),
            "battery_capacity": battery or item.get("battery_capacity"),
            "weight": weight or item.get("weight"),
            "ports": ports_text or item.get("ports"),
            "product_form": product_form or item.get("product_form"),
        }
    )
    return item


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="data/raw_html", help="原始 HTML 目录")
    ap.add_argument("--items", required=True, help="列表页原始记录 JSON（crawl 输出）")
    ap.add_argument("--output", default="data/zol_processed.json")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("items", items)

    ok = missing = 0
    for item in items:
        match = re.search(r"/notebook/index(\d+)\.shtml", str(item.get("source_url", "")))
        if not match:
            continue
        product_id = match.group(1)
        html_path = raw_dir / f"{product_id}.html"
        if not html_path.exists():
            missing += 1
            continue
        html = html_path.read_text(encoding="utf-8", errors="replace")
        specs = parse_specs(html)
        enrich_from_specs(specs, item)
        item["processed_from_raw"] = True
        ok += 1

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"items": items, "processed_count": ok, "missing_html": missing},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"processed: {ok} | missing_html: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
