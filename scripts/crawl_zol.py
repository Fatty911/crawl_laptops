#!/usr/bin/env python3
"""Crawl ZOL's notebook popularity ranking and enrich items from spec pages."""

from __future__ import annotations

import argparse
import json
import os
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
        parse_battery_wh,
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
        parse_battery_wh,
        parse_capacity_gb,
        parse_cpu_fields,
        parse_number,
        parse_price,
        text_from_spec,
        utc_now,
    )
    from merge_data import classify_cpu_voltage, extract_cpu_model

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

BASE_URL = "https://detail.zol.com.cn"
# rank.zol.com.cn no longer resolves.  This is ZOL's server-rendered equivalent:
# the notebook catalogue is ordered by its "热门排行" value and exposes the
# same product IDs and detail pages as the retired ranking host.
RANKING_URL = (
    "https://detail.zol.com.cn/notebook_index/"
    "subcate16_0_list_1_0_1_2_0_{page}.html"
)
RANKING_REFERER = f"{BASE_URL}/notebook/"


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
    # The real desktop DOM is <ul id="J_PicMode"><li data-follow-id="p...">.
    for index, card in enumerate(
        html.select("#J_PicMode > li[data-follow-id]"), start=1
    ):
        link = card.select_one("h3 .title-black a[href]") or card.select_one(
            "a.pic[href]"
        )
        if not link:
            continue
        title = clean_text(link.get_text(" ", strip=True) or link.get("title"))
        if not title:
            continue
        # A few legacy products expose stale/duplicated numbers in .rank-row.
        # The server-rendered list order is the authoritative popularity order.
        rank = (page - 1) * 48 + index
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
                "source_category": "ZOL notebook",
                "source_rank": rank,
                "source_product_id": product_id,
                "source_url": absolute_url(BASE_URL, link.get("href", "")),
            }
        )
    return results


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
    memory_match = re.search(r"(\d{1,3})\s*GB(?=[/+\s)]|$)", title, re.I)
    capacity_matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(TB|GB)(?=[/+\s)]|$)", title, re.I
    )
    numeric_keypad, keyboard_backlight = keyboard_flags(title)
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
                int(float(number) * (1024 if unit.upper() == "TB" else 1))
                for number, unit in capacity_matches
            )
            if capacity_matches
            else None
        ),
        "battery_wh": None,
        "weight_kg": None,
        "ports": [],
        "evidence": {
            "numeric_keypad": title,
            "keyboard_backlight": title,
            "cpu": title,
            "gpu": title,
            "product_form": title,
        },
    }


def enrich_item(session: Any, item: dict[str, Any], delay: float) -> dict[str, Any]:
    item.update(title_spec_fields(item["title"]))
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
    gpu = text_from_spec(specs, "显卡芯片", "显卡型号") or item["gpu"]
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
            "ports": [clean_text(part) for part in re.split(r"[；;]", ports_text) if clean_text(part)],
            "product_form": product_form,
            "spec_url": final_url,
            "evidence": {
                "numeric_keypad": keyboard,
                "keyboard_backlight": keyboard,
                "cpu": cpu_raw,
                "gpu": clean_text(f"{gpu_type_raw} {gpu}"),
                "product_form": product_form,
            },
        }
    )
    return item


def crawl(pages: int, max_items: int, delay: float) -> list[dict[str, Any]]:
    session = make_session()
    session.headers["Referer"] = RANKING_REFERER
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        html, final_url = get_html(
            session,
            RANKING_URL.format(page=page),
            encoding="gb18030",
            delay=delay,
        )
        page_items = parse_ranking_page(html, page)
        if not page_items:
            raise RuntimeError(f"ZOL ranking page {page} returned no product cards")
        # ZOL returns a tiny placeholder response for direct deep-page requests.
        # Carrying the previous list page as Referer reproduces normal pagination.
        session.headers["Referer"] = final_url
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


def crawl_incremental(
    output: str,
    progress_dir: str,
    delay: float,
    min_records: int,
    time_limit: float,
    max_pages: int = 0,
    max_items: int = 0,
) -> int:
    """Long-run incremental crawl with a persistent cursor.

    Ported from the crawl_phones architecture: the ranking scan cursor and
    the per-item enrichment state survive across workflow runs, the cursor
    is saved unconditionally after every step, and a wall-clock budget keeps
    the run inside the Actions window.  Exit codes: 0 = scan and enrichment
    complete, 10 = partial progress saved (resume on the next run).
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
    if progress.scan_complete:
        # 榜单每日变化：上次完整跑完的进度已过期，本次运行重新扫描。
        # 全重置（游标/items/enriched），避免输出陈旧榜单（0.2s 缓存重放 bug）。
        print(
            "previous scan complete; restarting scan for fresh ranking",
            file=sys.stderr,
        )
        progress.scan_complete = False
        progress.current_page = 1
        progress.total_items = 0
        progress.processed_ids = []
        progress.save(state_dir)
        items = []
        items_path.write_text("", encoding="utf-8")
        enriched_path.write_text("", encoding="utf-8")
    session = make_session()
    session.headers["Referer"] = RANKING_REFERER

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
                    RANKING_URL.format(page=page),
                    encoding="gb18030",
                    delay=human_delay(delay),
                )
            except Exception as exc:
                print(
                    f"ZOL ranking page {page} fetch failed: "
                    f"{type(exc).__name__}; will resume next run",
                    file=sys.stderr,
                )
                break
            page_items = parse_ranking_page(html, page)
            # Carry the list page as Referer for the next deep request.
            session.headers["Referer"] = final_url
            if not page_items:
                progress.scan_complete = True
                progress.save(state_dir)
                break
            before = len(items)
            items, added = merge_new_items(items, page_items, item_key)
            if max_items and len(items) > max_items:
                # Debug cap: truncate so --max-items is exact, then finish
                # scanning (progress says scan_complete so next run resumes
                # from enrichment without re-fetching pages).
                items = items[:max_items]
                progress.scan_complete = True
            for item in items[before:]:
                append_jsonl(items_path, item)
            progress.current_page = page + 1
            progress.total_items = len(items)
            progress.save(state_dir)
            if progress.scan_complete and len(items) >= max_items and max_items:
                break
            empty_streak = empty_streak + 1 if added == 0 else 0
            if empty_streak >= 3:
                # Fake-pagination guard: repeated duplicate pages mean the
                # ranking has ended; stop instead of looping forever.
                progress.scan_complete = True
                progress.save(state_dir)
                break
            page += 1

    for item in items:
        if budget.expired():
            break
        key = item_key(item)
        if key in enriched:
            continue
        try:
            record = enrich_item(session, dict(item), human_delay(delay))
        except Exception as exc:
            record = dict(item)
            record["crawl_warning"] = f"detail_failed:{type(exc).__name__}"
        record["fetched_at"] = utc_now()
        enriched[key] = record
        if not record.get("crawl_warning") and key not in progress.processed_ids:
            # Failed detail fetches stay retryable on the next run.
            progress.processed_ids.append(key)
        progress.save(state_dir)
        rewrite_jsonl(enriched_path, list(enriched.values()))

    records = list(enriched.values())
    if len(records) >= min_records:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {len(records)} ZOL records to {out}")
    else:
        print(
            f"ZOL has {len(records)} enriched records (< {min_records}); "
            "keeping progress without publishing",
            file=sys.stderr,
        )
    progress.save(state_dir)
    complete = progress.scan_complete and all(
        item_key(item) in enriched for item in items
    )
    return 0 if complete else 10


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/raw/zol/latest.json")
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=120)
    parser.add_argument("--delay", type=float, default=0.25)
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
        )
    try:
        items = crawl(args.pages, args.max_items, args.delay)
    except Exception as exc:
        print(f"ZOL crawl failed: {exc}", file=sys.stderr)
        return 2
    if len(items) < args.min_records:
        print(f"ZOL integrity failure: {len(items)} rows < {args.min_records}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} ZOL popularity-ranked records to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
