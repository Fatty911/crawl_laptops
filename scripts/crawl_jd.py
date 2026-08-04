#!/usr/bin/env python3
"""Crawl JD notebook search results ordered by sales and enrich product specs."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.parse import urlparse

try:
    from scripts.crawler_utils import (
        USER_AGENTS,
        clean_text,
        get_html,
        gpu_fields,
        infer_brand,
        keyboard_flags,
        make_session,
        parse_battery_wh,
        parse_capacity_gb,
        parse_cpu_fields,
        parse_number,
        parse_price,
        text_from_spec,
        utc_now,
    )
    from scripts.merge_data import (
        classify_cpu_voltage,
        clean_jd_title_identity,
        extract_cpu_model,
    )
except ModuleNotFoundError:
    from crawler_utils import (
        USER_AGENTS,
        clean_text,
        get_html,
        gpu_fields,
        infer_brand,
        keyboard_flags,
        make_session,
        parse_battery_wh,
        parse_capacity_gb,
        parse_cpu_fields,
        parse_number,
        parse_price,
        text_from_spec,
        utc_now,
    )
    from merge_data import (
        classify_cpu_voltage,
        clean_jd_title_identity,
        extract_cpu_model,
    )

try:
    from scripts.crawl_runtime import (
        Budget,
        Progress,
        append_jsonl,
        human_delay,
        item_key,
        merge_new_items,
        read_jsonl,
        rewrite_jsonl,
    )
except ModuleNotFoundError:
    from crawl_runtime import (
        Budget,
        Progress,
        append_jsonl,
        human_delay,
        item_key,
        merge_new_items,
        read_jsonl,
        rewrite_jsonl,
    )

SALES_RANKING_URL = "https://www.jd.com/hotitem/670a86a27721a2eeea8.html"


def sales_url(page: int) -> str:
    # JD's React search page no longer contains products in response HTML.  Its
    # official server-rendered hotitem page supports the same 15-day sales sort.
    query = {
        "extAttrValue": "expand_name,",
        "electedExtAttrSet": "",
        "sort_type": "sort_totalsales15_desc",
        "page": str(page),
    }
    return f"{SALES_RANKING_URL}?{urlencode(query)}"


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
    # The real sales-ranking DOM is <li class="sku-detail"><div class="pad-sku">.
    for index, card in enumerate(html.select("li.sku-detail"), start=1):
        name_node = card.select_one(".p-name a[href]")
        title = clean_text(
            (name_node.get("title") if name_node else "")
            or (name_node.get_text(" ", strip=True) if name_node else "")
        )
        price_box = card.select_one(".p-price[data-skuid]")
        sku = clean_text(price_box.get("data-skuid") if price_box else "")
        if not sku and name_node:
            sku_match = re.search(r"/(\d+)\.html", urlparse(name_node.get("href", "")).path)
            sku = sku_match.group(1) if sku_match else ""
        if not sku or not title:
            continue
        price_node = card.select_one(".p-price strong")
        shop_node = card.select_one(".p-merchant")
        items.append(
            {
                "title": title,
                "model": title,
                "model_identity": clean_jd_title_identity(title),
                "brand": infer_brand(title),
                "price": parse_price(price_node.get_text(strip=True) if price_node else ""),
                "currency": "CNY",
                "merchant": clean_text(shop_node.get_text(" ", strip=True) if shop_node else ""),
                "source": "JD",
                "atomic_source_names": ["JD"],
                "source_category": "JD notebook 15-day sales ranking",
                "source_rank": (page - 1) * 60 + index,
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


def title_spec_fields(title: str) -> dict[str, Any]:
    cpu = extract_cpu_model(title)
    cpu_brand, cpu_family = parse_cpu_fields(cpu)
    gpu_match = re.search(
        r"\b((?:RTX|GTX)\s*\d{3,4}(?:\s*Ti)?|Radeon\s+RX\s*\d{3,4}\w*)\b",
        title,
        re.I,
    )
    gpu = clean_text(gpu_match.group(1)) if gpu_match else ""
    gpu_type, dedicated_gpu = gpu_fields("", gpu or title)
    screen_match = re.search(r"(\d{2}(?:\.\d+)?)\s*(?:英寸|吋|寸)", title)
    memory_match = re.search(
        r"(\d{1,3})\s*G(?:B)?\s*(?:内存|运行内存|RAM)?(?=[/+\s]|$)",
        title,
        re.I,
    )
    capacity_matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(TB|T|GB|G)\s*(?:SSD|固态硬盘|固态|硬盘)?(?=[/+\s【(]|$)",
        title,
        re.I,
    )
    numeric_keypad, keyboard_backlight = keyboard_flags(title)
    weight_match = re.search(r"(\d(?:\.\d+)?)\s*kg\b", title, re.I)
    return {
        "cpu": cpu,
        "cpu_brand": cpu_brand,
        "cpu_family": cpu_family,
        "cpu_voltage_type": classify_cpu_voltage(cpu),
        "numeric_keypad": numeric_keypad,
        "keyboard_backlight": keyboard_backlight,
        "gpu": gpu,
        "gpu_type": gpu_type,
        "dedicated_gpu": dedicated_gpu,
        "screen_size": float(screen_match.group(1)) if screen_match else None,
        "resolution": "",
        "refresh_rate": None,
        "memory_gb": int(memory_match.group(1)) if memory_match else None,
        "storage_gb": (
            max(
                int(
                    float(number)
                    * (1024 if unit.upper().startswith("T") else 1)
                )
                for number, unit in capacity_matches
            )
            if capacity_matches
            else None
        ),
        "battery_wh": None,
        "weight_kg": float(weight_match.group(1)) if weight_match else None,
        "ports": [],
        "evidence": {
            "numeric_keypad": title,
            "keyboard_backlight": title,
            "cpu": title,
            "gpu": title,
            "product_form": title,
        },
    }


def enrich_item(
    session: Any,
    item: dict[str, Any],
    delay: float,
    detail_delay: float | None = None,
) -> dict[str, Any]:
    item.update(title_spec_fields(item["title"]))
    try:
        # Rotate the UA per detail request and use the longer detail delay:
        # JD risk control correlates repeated identical UA bursts.
        session.headers["User-Agent"] = random.choice(USER_AGENTS)
        effective_delay = detail_delay if detail_delay is not None else delay
        html, final_url = get_html(session, item["source_url"], delay=effective_delay)
    except Exception as exc:
        item["crawl_warning"] = f"detail_failed:{type(exc).__name__}"
        return item
    if is_risk_page(html, final_url):
        item["crawl_warning"] = "detail_risk_verification"
        item["spec_url"] = item["source_url"]
        return item
    specs = parse_product_specs(html)
    if not specs:
        item["crawl_warning"] = "detail_specs_unavailable"
        item["spec_url"] = item["source_url"]
        return item
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
    gpu = text_from_spec(specs, "显卡型号", "显示芯片") or item["gpu"]
    gpu_type, dedicated_gpu = gpu_fields(gpu_type_raw, gpu or item["title"])
    screen = text_from_spec(specs, "屏幕尺寸")
    memory = text_from_spec(specs, "内存容量")
    storage = text_from_spec(specs, "固态硬盘", "硬盘容量", "总容量")
    battery = text_from_spec(specs, "电池容量", "电池能量")
    weight = text_from_spec(specs, "产品净重", "笔记本重量", "产品重量", "重量")
    ports = [
        f"{key}: {value}"
        for key, value in specs.items()
        if any(token in key for token in ("接口", "USB", "雷电"))
    ]
    product_form = clean_text(
        "；".join(
            value
            for key, value in specs.items()
            if key in {"产品类型", "产品定位", "商品类别", "类型"}
        )
        or item["title"]
    )
    item.update(
        {
            "cpu": cpu,
            "cpu_brand": cpu_brand,
            "cpu_family": cpu_family,
            "cpu_voltage_type": classify_cpu_voltage(cpu),
            "numeric_keypad": (
                numeric_keypad if numeric_keypad is not None else item["numeric_keypad"]
            ),
            "keyboard_backlight": (
                keyboard_backlight
                if keyboard_backlight is not None
                else item["keyboard_backlight"]
            ),
            "gpu": gpu,
            "gpu_type": gpu_type,
            "dedicated_gpu": dedicated_gpu,
            "screen_size": parse_number(screen) or item["screen_size"],
            "resolution": (
                text_from_spec(specs, "屏幕分辨率", "分辨率") or item["resolution"]
            ),
            "refresh_rate": (
                parse_number(text_from_spec(specs, "屏幕刷新率", "刷新率"))
                or item["refresh_rate"]
            ),
            "memory_gb": parse_capacity_gb(memory) or item["memory_gb"],
            "storage_gb": parse_capacity_gb(storage) or item["storage_gb"],
            "battery_wh": parse_battery_wh(battery) or item["battery_wh"],
            "weight_kg": parse_number(weight) or item["weight_kg"],
            "ports": ports,
            "product_form": product_form,
            "spec_url": final_url,
            "evidence": {
                "numeric_keypad": keyboard_probe,
                "keyboard_backlight": keyboard_probe,
                "cpu": cpu_raw,
                "gpu": clean_text(f"{gpu_type_raw} {gpu}"),
                "product_form": product_form,
            },
        }
    )
    return item


def crawl(
    pages: int,
    max_items: int,
    delay: float,
    cookie: str | None,
    detail_delay: float | None = None,
) -> list[dict[str, Any]]:
    session = make_session(cookie)
    session.headers["Referer"] = "https://www.jd.com/"
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        html, final_url = get_html(session, sales_url(page), delay=delay)
        if is_risk_page(html, final_url):
            raise RuntimeError(
                "JD returned a risk-verification page for its sales ranking"
            )
        page_items = parse_search_page(html, page)
        if not page_items:
            if items:
                # JD occasionally serves an empty later page even though the
                # first sales-ranking page is complete.  Keep the valid prefix;
                # the caller's min-records gate still rejects undersized runs.
                break
            raise RuntimeError(f"JD sales page {page} returned no product cards")
        for item in page_items:
            if item["source_product_id"] not in seen:
                seen.add(item["source_product_id"])
                items.append(item)
            if len(items) >= max_items:
                break
        if len(items) >= max_items:
            break
        session.headers["Referer"] = final_url
    for index, item in enumerate(items):
        items[index] = enrich_item(session, item, delay, detail_delay)
        items[index]["fetched_at"] = utc_now()
    return items


def crawl_incremental(
    output: str,
    progress_dir: str,
    delay: float,
    min_records: int,
    time_limit: float,
    max_pages: int = 0,
    max_items: int = 0,
    cookie: str | None = None,
    detail_delay: float | None = None,
) -> int:
    """Long-run incremental JD sales-ranking crawl with a persistent cursor.

    Same cursor architecture as the ZOL incremental mode.  When JD returns a
    risk-verification page during detail enrichment the item keeps its
    title-derived fields; the merge gate then publishes it only if another
    source supplies the missing keyboard evidence.  Exit codes: 0 = scan
    and enrichment complete, 10 = partial progress saved.
    """

    budget = Budget(time_limit)
    state_dir = Path(progress_dir)
    progress = Progress.load(state_dir)
    items_path = state_dir / "items.jsonl"
    enriched_path = state_dir / "enriched.jsonl"
    items = read_jsonl(items_path)
    enriched: dict[str, dict[str, Any]] = {
        item_key(record): record
        for record in read_jsonl(enriched_path)
        if item_key(record)
    }
    session = make_session(cookie)
    session.headers["Referer"] = "https://www.jd.com/"
    risk_seen = False

    empty_streak = 0
    if not progress.scan_complete:
        page = max(progress.current_page, 1)
        while not budget.expired():
            if max_pages and page > max_pages:
                break
            if max_items and len(items) >= max_items:
                progress.scan_complete = True
                break
            try:
                html, final_url = get_html(
                    session,
                    sales_url(page),
                    delay=human_delay(delay),
                )
            except Exception as exc:
                print(
                    f"JD sales page {page} fetch failed: "
                    f"{type(exc).__name__}; will resume next run",
                    file=sys.stderr,
                )
                break
            if is_risk_page(html, final_url):
                print(
                    f"JD sales page {page} returned a risk-verification "
                    "page; keeping scanned progress and retrying next run",
                    file=sys.stderr,
                )
                risk_seen = True
                break
            page_items = parse_search_page(html, page)
            session.headers["Referer"] = final_url
            if not page_items:
                if items:
                    progress.scan_complete = True
                    progress.save(state_dir)
                    break
                print(
                    f"JD sales page {page} returned no product cards on an "
                    "empty scan; will retry next run",
                    file=sys.stderr,
                )
                break
            before = len(items)
            items, added = merge_new_items(items, page_items, item_key)
            for item in items[before:]:
                append_jsonl(items_path, item)
            progress.current_page = page + 1
            progress.total_items = len(items)
            progress.save(state_dir)
            empty_streak = empty_streak + 1 if added == 0 else 0
            if empty_streak >= 3:
                progress.scan_complete = True
                progress.save(state_dir)
                break
            page += 1

    for item in items:
        if budget.expired() or risk_seen:
            break
        key = item_key(item)
        if key in enriched:
            continue
        try:
            record = enrich_item(session, dict(item), human_delay(delay), detail_delay)
        except Exception as exc:
            record = dict(item)
            record["crawl_warning"] = f"detail_failed:{type(exc).__name__}"
        record["fetched_at"] = utc_now()
        enriched[key] = record
        if key not in progress.processed_ids:
            progress.processed_ids.append(key)
        progress.save(state_dir)
        rewrite_jsonl(enriched_path, list(enriched.values()))
        if record.get("crawl_warning") == "detail_risk_verification":
            # Risk control is burning budget pointlessly; stop enriching and
            # resume from this cursor on the next run.
            risk_seen = True
            break

    records = list(enriched.values())
    if len(records) >= min_records:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {len(records)} JD sales-ranked records to {out}")
    else:
        print(
            f"JD has {len(records)} enriched records (< {min_records}); "
            "keeping progress without publishing",
            file=sys.stderr,
        )
    progress.save(state_dir)
    complete = (
        progress.scan_complete
        and not risk_seen
        and all(item_key(item) in enriched for item in items)
    )
    return 0 if complete else 10


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/raw/jd/latest.json")
    parser.add_argument("--pages", type=int, default=4)
    parser.add_argument("--max-items", type=int, default=120)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument(
        "--detail-delay",
        type=float,
        default=0.8,
        help="extra pacing for JD detail pages to reduce risk verification",
    )
    parser.add_argument("--min-records", type=int, default=50)
    parser.add_argument(
        "--time-limit",
        type=float,
        default=0,
        help="incremental mode wall-clock budget in seconds (0 = unlimited)",
    )
    parser.add_argument(
        "--progress-dir",
        default="",
        help="incremental cursor directory; enables long-run mode",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="incremental mode page cap (0 = unlimited)",
    )
    args = parser.parse_args()
    if args.progress_dir:
        return crawl_incremental(
            args.output,
            args.progress_dir,
            args.delay,
            args.min_records,
            args.time_limit,
            args.max_pages,
            args.max_items,
            os.getenv("JD_COOKIE"),
            args.detail_delay,
        )
    try:
        items = crawl(
            args.pages,
            args.max_items,
            args.delay,
            os.getenv("JD_COOKIE"),
            args.detail_delay,
        )
    except Exception as exc:
        print(f"JD crawl failed: {exc}", file=sys.stderr)
        return 2
    if len(items) < args.min_records:
        print(f"JD integrity failure: {len(items)} rows < {args.min_records}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} JD sales-ranked records to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
