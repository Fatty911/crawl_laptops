#!/usr/bin/env python3
"""Crawl MACHENIKE (机械师) official site for gaming notebooks.

MACHENIKE builds Clevo-barebone gaming laptops.  The official site has
structured product lists (lists/1.html = 电竞游戏本), series keyword pages
(keyword/曙光15Pro.html) and spec-rich product pages (product/NNN.html).

Raw record schema mirrors crawl_zol.py so merge_data.py can consume it:
source='Machinike', atomic_source_names=['Machinike'].
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from scripts.crawler_utils import (
    absolute_url,
    clean_text,
    gpu_fields,
    keyboard_flags,
    make_session,
    parse_cpu_fields,
    text_from_spec,
)

BASE_URL = "https://www.machenike.com"
LIST_URL = f"{BASE_URL}/lists/1.html"          # 电竞游戏本列表
KEYWORD_URL = f"{BASE_URL}/keyword/{{}}.html"   # 系列页
PRODUCT_URL = f"{BASE_URL}/product/{{}}.html"   # 详情页

# 准系统/游戏本品牌类目弱证据：蓝天模具游戏本标配数字小键盘
BARE_BONE_FORM = "游戏本"


def fetch(session: Any, url: str, *, retries: int = 3, delay: float = 1.0) -> str:
    """GET with retry/backoff; returns HTML text (get_html returns a soup)."""
    from scripts.crawler_utils import get_html

    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            soup, _final = get_html(session, url, encoding="utf-8", delay=delay)
            return str(soup)
        except Exception as exc:  # noqa: BLE001
            last = exc
            wait = 3 * (2 ** (attempt - 1))
            print(
                f"fetch {url} attempt {attempt}/{retries} failed: "
                f"{type(exc).__name__}; retry in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)
    raise RuntimeError(f"fetch failed after {retries} attempts: {url}: {last}")


def parse_list(html: str) -> list[str]:
    """Extract product detail URLs from the gaming-notebook list page.

    lists/1.html renders actual SKU cards: <a class="p-name"
    href="/product/NNN.html">title</a>.  Subcategory list pages
    (lists/N.html) are discovered from the nav; crawl them too.
    """
    soup = BeautifulSoup(html, "html.parser")
    links: set[str] = set()
    for a in soup.select("a.p-name, a[href*='product/']"):
        href = str(a.get("href", ""))
        if "/product/" in href and href not in links:
            links.add(absolute_url(BASE_URL, href))
    return sorted(links)


def parse_series(html: str, series_name: str) -> list[dict[str, Any]]:
    """Extract SKU cards from a MACHENIKE list page.

    Product cards: <a href="/product/NNN.html">title</a>; prices render in a
    separate .price list with matching order (product i <-> price i).
    """
    soup = BeautifulSoup(html, "html.parser")
    # 价格列表：页面内所有 .price 纯数字（按出现顺序与产品对应）
    prices: list[float | None] = []
    for el in soup.select(".price, .show-price, .goods-price, .ns-text-color"):
        raw = clean_text(el.get_text(" ", strip=True))
        m = re.search(r"([\d,]+\.?\d*)", raw)
        prices.append(float(m.group(1).replace(",", "")) if m else None)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in soup.select("a.p-name, a.item-title-name, a.goods-name, a[href*='/product/'], a[href*='/goods/']"):
        title = clean_text(link.get_text(" ", strip=True))
        if not title:
            title = clean_text(str(link.get("title", "")))
        if not title or title in seen:
            continue
        seen.add(title)
        href = str(link.get("href", ""))
        url = absolute_url(BASE_URL, href) if href else ""
        price = prices[len(items)] if len(items) < len(prices) else None
        items.append({"title": title, "url": url, "price": price})
    return items


def parse_product(html: str, item: dict[str, Any]) -> dict[str, Any]:
    """Enrich one SKU from its product detail page (spec table)."""
    soup = BeautifulSoup(html, "html.parser")
    specs: dict[str, str] = {}
    for row in soup.select("tr, .spec-item, .parameter-row, li.param"):
        cells = row.find_all(["td", "th", "dt", "dd", "span"])
        texts = [clean_text(c.get_text(" ", strip=True)) for c in cells if c.get_text(strip=True)]
        if len(texts) >= 2:
            specs[texts[0]] = texts[1]
    all_text = soup.get_text(" ", strip=True)

    title = item.get("title", "")
    cpu_raw = text_from_spec(specs, "处理器", "CPU", "CPU型号") or title
    cpu_brand, cpu_family = parse_cpu_fields(cpu_raw)
    memory = text_from_spec(specs, "内存容量", "内存", "内存大小")
    storage = text_from_spec(specs, "硬盘容量", "存储", "固态硬盘")
    gpu_raw = text_from_spec(specs, "显卡", "显卡类型", "GPU")
    gpu_type, dedicated_gpu = gpu_fields(gpu_raw, title)
    screen = text_from_spec(specs, "屏幕尺寸", "屏幕")
    keyboard = text_from_spec(specs, "键盘标准", "键盘") or all_text[:2000]
    numeric_keypad, keyboard_backlight = keyboard_flags(keyboard)
    # 准系统/游戏本弱证据：键盘标准"全尺寸"且为游戏本类目 → 数字键盘 True
    if numeric_keypad is None and "全尺寸" in keyboard and BARE_BONE_FORM in title:
        numeric_keypad = True
    refresh = text_from_spec(specs, "刷新率", "屏幕刷新率")
    resolution = text_from_spec(specs, "分辨率", "屏幕分辨率")

    def _num(value: str | None) -> float | None:
        if not value:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)", str(value))
        return float(m.group(1)) if m else None

    mem_match = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", str(memory or ""), re.I)
    sto_match = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", str(storage or ""), re.I)
    memory_gb = _num(mem_match.group(1)) if mem_match else None
    if mem_match and mem_match.group(2).upper() == "TB":
        memory_gb = (memory_gb or 0) * 1024
    storage_gb = _num(sto_match.group(1)) if sto_match else None
    if sto_match and sto_match.group(2).upper() == "TB":
        storage_gb = (storage_gb or 0) * 1024

    return {
        "cpu": cpu_raw,
        "cpu_brand": cpu_brand,
        "cpu_family": cpu_family,
        "numeric_keypad": numeric_keypad,
        "keyboard_backlight": keyboard_backlight,
        "gpu": gpu_raw,
        "gpu_type": gpu_type,
        "dedicated_gpu": dedicated_gpu,
        "screen_size": _num(screen),
        "refresh_rate": _num(refresh),
        "resolution": resolution or "",
        "memory_gb": memory_gb,
        "storage_gb": storage_gb,
        "keyboard": keyboard[:200],
        "evidence": {
            "numeric_keypad": keyboard[:200],
            "keyboard_backlight": keyboard[:200],
            "cpu": cpu_raw,
            "gpu": gpu_raw,
            "product_form": BARE_BONE_FORM,
        },
    }


def crawl(session: Any, output: str, max_items: int, delay: float) -> int:
    list_html = fetch(session, LIST_URL, delay=delay)
    cards = parse_series(list_html, "")
    print(f"list cards: {len(cards)}", file=sys.stderr)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in cards:
            if max_items and len(items) >= max_items:
                break
            title = card["title"]
            if title in seen:
                continue
            seen.add(title)
            record: dict[str, Any] = {
                "title": title,
                "brand": "机械师",
                "model": title,
                "source": "Machinike",
                "source_category": "官方",
                "atomic_source_names": ["Machinike"],
                "price": card["price"],
                "currency": "CNY",
                "source_url": card["url"],
                "source_product_id": title,
                "source_rank": len(items) + 1,
                "source_ranks": [len(items) + 1],
                "fetched_at": None,
            }
            # enrich detail page（规格 JS 渲染：降级为标题解析 + 键盘弱证据）
            try:
                detail_html = fetch(session, card["url"], delay=delay) if card["url"] else ""
                if detail_html:
                    record.update(parse_product(detail_html, record))
            except RuntimeError as exc:
                print(f"detail failed {card['url']}: {exc}", file=sys.stderr)
                record["crawl_warning"] = "detail_failed"
            # 标题级规格兜底：CPU/GPU 从标题提取（i7HX 4060 等）
            title = record.get("title", "")
            m_cpu = re.search(r"(i[3579][-A-Za-z0-9HXK]*|R[579][-A-Za-z0-9HXK]*|Ultra\s?\d[\w]*|锐龙[^/（）()]*|酷睿[^/（）()]*)", title)
            cpu_missing = not record.get("cpu") or str(record.get("cpu", "")).startswith(title[:10])
            if m_cpu and cpu_missing:
                record["cpu"] = m_cpu.group(1).strip()
                cb, cf = parse_cpu_fields(record["cpu"])
                record["cpu_brand"] = cb
                record["cpu_family"] = cf
            m_gpu = re.search(r"(RTX\s?\d{4,5}|GTX\s?\d{4}|RX\s?\d{4}|Arc\s?\d+)", title, re.I)
            if m_gpu:
                record["gpu"] = m_gpu.group(1).replace(" ", "")
                record["gpu_type"] = "dedicated"
                record["dedicated_gpu"] = True
            # 游戏本类目弱证据：蓝天模具游戏本标配数字键盘 + 背光
            if record.get("numeric_keypad") is None:
                record["numeric_keypad"] = True
                record.setdefault("evidence", {})["numeric_keypad"] = (
                    "准系统游戏本类目弱证据（蓝天模具标配数字键盘）"
                )
            items.append(record)

    if not items:
        print("Machinike crawl failed: no items", file=sys.stderr)
        return 2
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} Machinike records to {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/raw/machenike/latest.json")
    parser.add_argument("--max-items", type=int, default=200)
    parser.add_argument("--min-records", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    session = make_session()
    exit_code = crawl(session, args.output, args.max_items, args.delay)
    if exit_code == 0:
        import json as _json

        count = len(_json.loads(Path(args.output).read_text(encoding="utf-8")))
        if count < args.min_records:
            print(f"Machinike integrity failure: {count} < {args.min_records}", file=sys.stderr)
            return 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
