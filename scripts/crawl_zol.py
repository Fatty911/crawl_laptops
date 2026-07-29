#!/usr/bin/env python3
"""Crawl ZOL's notebook popularity ranking and enrich items from spec pages."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.crawler_utils import (
        absolute_url,
        clean_text,
        get_html,
        gpu_fields,
        infer_brand,
        keyboard_flags,
        make_session,
        parse_capacity_gb,
        parse_cpu_fields,
        parse_number,
        parse_price,
        text_from_spec,
        utc_now,
    )
    from scripts.merge_data import classify_cpu_voltage, extract_cpu_model
except ModuleNotFoundError:
    from crawler_utils import (
        absolute_url,
        clean_text,
        get_html,
        gpu_fields,
        infer_brand,
        keyboard_flags,
        make_session,
        parse_capacity_gb,
        parse_cpu_fields,
        parse_number,
        parse_price,
        text_from_spec,
        utc_now,
    )
    from merge_data import classify_cpu_voltage, extract_cpu_model

BASE_URL = "https://detail.zol.com.cn"
RANKING_URL = (
    "https://detail.zol.com.cn/notebook_index/"
    "subcate16_0_list_1_0_1_2_0_{page}.html"
)


def parse_specs(html: Any) -> dict[str, str]:
    specs: dict[str, str] = {}
    for row in html.select("tr"):
        cells = row.select("th, td")
        if len(cells) < 2:
            continue
        key = clean_text(cells[0].get_text(" ", strip=True)).replace("纠错", "")
        value = clean_text(cells[1].get_text(" ", strip=True)).replace("纠错", "")
        value = re.sub(r"(更多.*|进入官网.*)$", "", value).strip()
        if key and value and len(key) <= 24:
            specs[key] = value
    return specs


def parse_ranking_page(html: Any, page: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, card in enumerate(html.select("li[data-follow-id]"), start=1):
        link = card.select_one("h3 a[href]") or card.select_one("a.pic[href]")
        if not link:
            continue
        title = clean_text(link.get("title") or link.get_text(" ", strip=True))
        if not title:
            continue
        rank_node = card.select_one(".rank-row span")
        rank = int(rank_node.get_text(strip=True)) if rank_node and rank_node.get_text(strip=True).isdigit() else (page - 1) * 48 + index
        price_node = card.select_one(".price-type") or card.select_one(".price")
        product_id = clean_text(card.get("data-follow-id")).lstrip("p")
        results.append(
            {
                "title": title,
                "model": title,
                "brand": infer_brand(title),
                "price": parse_price(price_node.get_text(" ", strip=True) if price_node else ""),
                "currency": "CNY",
                "source": "ZOL",
                "atomic_source_names": ["ZOL"],
                "source_rank": rank,
                "source_product_id": product_id,
                "source_url": absolute_url(BASE_URL, link.get("href", "")),
            }
        )
    return results


def enrich_item(session: Any, item: dict[str, Any], delay: float) -> dict[str, Any]:
    match = re.search(r"/notebook/index(\d+)\.shtml", item["source_url"])
    if not match:
        return item
    product_id = match.group(1)
    # ZOL buckets product IDs by the ceiling of id / 1000:
    # product 2165921 lives under /2166/2165921/param.shtml.
    product_bucket = (int(product_id) + 999) // 1000
    param_url = f"{BASE_URL}/{product_bucket}/{product_id}/param.shtml"
    try:
        detail, final_url = get_html(session, param_url, encoding="gb18030", delay=delay)
    except Exception as exc:  # a single product must not discard the ranking
        item["crawl_warning"] = f"detail_failed:{type(exc).__name__}"
        return item

    specs = parse_specs(detail)
    cpu_raw = text_from_spec(specs, "CPU型号", "处理器型号") or item["title"]
    cpu = extract_cpu_model(cpu_raw)
    cpu_brand, cpu_family = parse_cpu_fields(cpu_raw)
    keyboard = text_from_spec(specs, "键盘描述", "键盘")
    numeric_keypad, keyboard_backlight = keyboard_flags(keyboard)
    gpu_type_raw = text_from_spec(specs, "显卡类型")
    gpu = text_from_spec(specs, "显卡芯片", "显卡型号")
    gpu_type, dedicated_gpu = gpu_fields(gpu_type_raw, gpu)
    screen = text_from_spec(specs, "屏幕尺寸")
    memory = text_from_spec(specs, "内存容量")
    storage = text_from_spec(specs, "硬盘容量", "存储容量")
    battery = text_from_spec(specs, "电池类型", "电池容量")
    ports_text = "；".join(
        value
        for key, value in specs.items()
        if any(token in key for token in ("数据接口", "视频接口", "音频接口", "其它接口"))
    )
    item.update(
        {
            "cpu": cpu,
            "cpu_brand": cpu_brand,
            "cpu_family": cpu_family,
            "cpu_voltage_type": classify_cpu_voltage(cpu),
            "numeric_keypad": numeric_keypad,
            "keyboard_backlight": keyboard_backlight,
            "gpu": gpu,
            "gpu_type": gpu_type,
            "dedicated_gpu": dedicated_gpu,
            "screen_size": parse_number(screen),
            "resolution": text_from_spec(specs, "屏幕分辨率", "分辨率"),
            "refresh_rate": parse_number(text_from_spec(specs, "屏幕刷新率", "刷新率")),
            "memory_gb": parse_capacity_gb(memory),
            "storage_gb": parse_capacity_gb(storage),
            "battery_wh": parse_number(battery) if "瓦时" in battery or "Wh" in battery else None,
            "ports": [clean_text(part) for part in re.split(r"[；;]", ports_text) if clean_text(part)],
            "spec_url": final_url,
            "evidence": {
                "numeric_keypad": keyboard,
                "keyboard_backlight": keyboard,
                "cpu": cpu_raw,
                "gpu": clean_text(f"{gpu_type_raw} {gpu}"),
            },
        }
    )
    return item


def crawl(pages: int, max_items: int, delay: float) -> list[dict[str, Any]]:
    session = make_session()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        html, _ = get_html(session, RANKING_URL.format(page=page), encoding="gb18030", delay=delay)
        page_items = parse_ranking_page(html, page)
        if not page_items:
            raise RuntimeError(f"ZOL ranking page {page} returned no product cards")
        for item in page_items:
            if item["source_product_id"] not in seen:
                seen.add(item["source_product_id"])
                items.append(item)
            if len(items) >= max_items:
                break
        if len(items) >= max_items:
            break
    for index, item in enumerate(items):
        items[index] = enrich_item(session, item, delay)
        items[index]["fetched_at"] = utc_now()
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/raw/zol/latest.json")
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=120)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--min-records", type=int, default=50)
    args = parser.parse_args()
    try:
        items = crawl(args.pages, args.max_items, args.delay)
    except Exception as exc:
        print(f"ZOL crawl failed: {exc}", file=sys.stderr)
        return 2
    if len(items) < args.min_records:
        print(f"ZOL integrity failure: {len(items)} rows < {args.min_records}", file=sys.stderr)
        return 2
    payload = {
        "schema_version": 1,
        "source": "ZOL",
        "sort": "popularity",
        "fetched_at": utc_now(),
        "count": len(items),
        "items": items,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} ZOL popularity-ranked records to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
