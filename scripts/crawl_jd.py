#!/usr/bin/env python3
"""Crawl JD notebook search results ordered by sales and enrich product specs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

try:
    from scripts.crawler_utils import (
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

SEARCH_URL = "https://search.jd.com/Search"


def sales_url(page: int) -> str:
    # psort=3 is JD's sales order; odd page numbers are its historical paging convention.
    query = {
        "keyword": "笔记本电脑",
        "enc": "utf-8",
        "psort": "3",
        "page": str(page * 2 - 1),
        "click": "0",
    }
    return f"{SEARCH_URL}?{urlencode(query)}"


def is_risk_page(html: Any, final_url: str) -> bool:
    title = clean_text(html.title.get_text() if html.title else "")
    text = clean_text(html.get_text(" ", strip=True))[:500]
    return (
        "risk_handler" in final_url
        or "passport.jd.com" in final_url
        or "京东安全" in title
        or "访问验证" in text
    )


def parse_search_page(html: Any, page: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, card in enumerate(html.select("li.gl-item[data-sku]"), start=1):
        sku = clean_text(card.get("data-sku"))
        name_node = card.select_one(".p-name em") or card.select_one(".p-name")
        title = clean_text(name_node.get_text(" ", strip=True) if name_node else "")
        if not sku or not title:
            continue
        price_node = card.select_one(".p-price i")
        shop_node = card.select_one(".p-shop")
        items.append(
            {
                "title": title,
                "model": title,
                "brand": infer_brand(title),
                "price": parse_price(price_node.get_text(strip=True) if price_node else ""),
                "currency": "CNY",
                "merchant": clean_text(shop_node.get_text(" ", strip=True) if shop_node else ""),
                "source": "JD",
                "atomic_source_names": ["JD"],
                "source_rank": (page - 1) * 30 + index,
                "source_product_id": sku,
                "source_url": f"https://item.jd.com/{sku}.html",
            }
        )
    return items


def parse_product_specs(html: Any) -> dict[str, str]:
    specs: dict[str, str] = {}
    for item in html.select(".Ptable-item, .parameter2 li, ul.parameter2 li"):
        if item.name == "li":
            text = clean_text(item.get_text(" ", strip=True))
            if "：" in text or ":" in text:
                parts = re.split(r"[：:]", text, maxsplit=1)
                specs[clean_text(parts[0])] = clean_text(parts[1])
            continue
        for row in item.select("dl"):
            key_node = row.select_one("dt")
            value_node = row.select_one("dd")
            if key_node and value_node:
                specs[clean_text(key_node.get_text(" ", strip=True))] = clean_text(
                    value_node.get_text(" ", strip=True)
                )
    return specs


def enrich_item(session: Any, item: dict[str, Any], delay: float) -> dict[str, Any]:
    try:
        html, final_url = get_html(session, item["source_url"], delay=delay)
    except Exception as exc:
        item["crawl_warning"] = f"detail_failed:{type(exc).__name__}"
        return item
    specs = parse_product_specs(html)
    page_text = clean_text(html.get_text(" ", strip=True))
    cpu_raw = text_from_spec(specs, "CPU型号", "处理器", "处理器型号") or item["title"]
    cpu = extract_cpu_model(cpu_raw)
    cpu_brand, cpu_family = parse_cpu_fields(cpu_raw)
    keyboard = "；".join(
        value for key, value in specs.items() if "键盘" in key
    )
    # JD sometimes exposes these selling points only in the product description.
    keyboard_probe = keyboard or " ".join(
        re.findall(r".{0,20}(?:数字小键盘|数字键区|背光键盘|键盘背光).{0,20}", page_text)
    )
    numeric_keypad, keyboard_backlight = keyboard_flags(keyboard_probe)
    gpu_type_raw = text_from_spec(specs, "显卡类型")
    gpu = text_from_spec(specs, "显卡型号", "显示芯片")
    gpu_type, dedicated_gpu = gpu_fields(gpu_type_raw, gpu or item["title"])
    screen = text_from_spec(specs, "屏幕尺寸")
    memory = text_from_spec(specs, "内存容量")
    storage = text_from_spec(specs, "固态硬盘", "硬盘容量", "总容量")
    battery = text_from_spec(specs, "电池容量", "电池能量")
    ports = [
        f"{key}: {value}"
        for key, value in specs.items()
        if any(token in key for token in ("接口", "USB", "雷电"))
    ]
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
            "battery_wh": parse_number(battery),
            "ports": ports,
            "spec_url": final_url,
            "evidence": {
                "numeric_keypad": keyboard_probe,
                "keyboard_backlight": keyboard_probe,
                "cpu": cpu_raw,
                "gpu": clean_text(f"{gpu_type_raw} {gpu}"),
            },
        }
    )
    return item


def crawl(pages: int, max_items: int, delay: float, cookie: str | None) -> list[dict[str, Any]]:
    session = make_session(cookie)
    session.headers["Referer"] = "https://www.jd.com/"
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        html, final_url = get_html(session, sales_url(page), delay=delay)
        if is_risk_page(html, final_url):
            raise RuntimeError(
                "JD returned a risk-verification page; configure the JD_COOKIE Actions secret"
            )
        page_items = parse_search_page(html, page)
        if not page_items:
            raise RuntimeError(f"JD sales page {page} returned no product cards")
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
    parser.add_argument("--output", default="data/raw/jd/latest.json")
    parser.add_argument("--pages", type=int, default=4)
    parser.add_argument("--max-items", type=int, default=120)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--min-records", type=int, default=50)
    args = parser.parse_args()
    try:
        items = crawl(args.pages, args.max_items, args.delay, os.getenv("JD_COOKIE"))
    except Exception as exc:
        print(f"JD crawl failed: {exc}", file=sys.stderr)
        return 2
    if len(items) < args.min_records:
        print(f"JD integrity failure: {len(items)} rows < {args.min_records}", file=sys.stderr)
        return 2
    payload = {
        "schema_version": 1,
        "source": "JD",
        "sort": "sales",
        "fetched_at": utc_now(),
        "count": len(items),
        "items": items,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} JD sales-ranked records to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
