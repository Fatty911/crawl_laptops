#!/usr/bin/env python3
"""Crawl PConline's server-rendered notebook popularity ranking."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.crawler_utils import (
        absolute_url, clean_text, get_html, gpu_fields, infer_brand,
        keyboard_flags, make_session, parse_battery_wh, parse_capacity_gb,
        parse_cpu_fields, parse_number, parse_price, text_from_spec, utc_now,
    )
    from scripts.merge_data import classify_cpu_voltage, extract_cpu_model
except ModuleNotFoundError:
    from crawler_utils import (
        absolute_url, clean_text, get_html, gpu_fields, infer_brand,
        keyboard_flags, make_session, parse_battery_wh, parse_capacity_gb,
        parse_cpu_fields, parse_number, parse_price, text_from_spec, utc_now,
    )
    from merge_data import classify_cpu_voltage, extract_cpu_model

try:
    from scripts.crawl_runtime import Budget
except ModuleNotFoundError:
    from crawl_runtime import Budget


class NodeManager:
    """mihomo 节点管理器：切换 PROXY select 组到具体节点，维护风控黑名单。

    通过 mihomo external-controller API（默认 127.0.0.1:9090）把 PROXY
    组从 BALANCE（round-robin 轮询全部节点）切到单个具体节点，从而：
      - 每次请求都走同一个节点（可感知风控）
      - 发现风控（榜单页行数 < 2）后把该节点拉黑，本次工作流不再使用
      - 黑名单存到文件（/tmp/pconline_blacklist.json），同一工作流内
        多个页面/进程共享，避免反复撞风控节点
    """

    def __init__(
        self,
        controller: str = "127.0.0.1:9090",
        group: str = "PROXY",
        blacklist_path: str = "/tmp/pconline_blacklist.json",
    ) -> None:
        self.controller = controller
        self.group = group
        self.blacklist_path = Path(blacklist_path)
        self.blacklist: set[str] = self._load_blacklist()
        self.nodes: list[str] = []
        self.current: str | None = None
        self._refresh_nodes()

    def _api(self, method: str, path: str, body: dict | None = None):
        import json as _json
        import urllib.request

        url = f"http://{self.controller}{path}"
        data = _json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                return _json.loads(raw) if raw else {}
        except Exception:
            return {}

    def _load_blacklist(self) -> set[str]:
        try:
            return set(_json_load(self.blacklist_path))
        except Exception:
            return set()

    def _save_blacklist(self) -> None:
        try:
            self.blacklist_path.write_text(
                _json_dumps(sorted(self.blacklist)), encoding="utf-8"
            )
        except Exception:
            pass

    def _refresh_nodes(self) -> None:
        data = self._api("GET", f"/proxies/{self.group}")
        all_names = data.get("all") or []
        # 过滤掉 BALANCE 等组名，只留具体节点
        self.nodes = [
            name for name in all_names
            if name not in ("BALANCE", self.group)
        ]
        now = data.get("now")
        self.current = now if now and now != "BALANCE" else None

    def select_next(self) -> str | None:
        """切换到下一个未被拉黑的节点，返回节点名；全部拉黑返回 None。"""
        if not self.nodes:
            self._refresh_nodes()
        for name in self.nodes:
            if name not in self.blacklist and name != self.current:
                self._api("PUT", f"/proxies/{self.group}", {"name": name})
                self.current = name
                return name
        return None

    def mark_blocked(self, name: str | None) -> None:
        """把节点加入黑名单（风控），后续请求不再使用。"""
        if not name:
            return
        self.blacklist.add(name)
        self._save_blacklist()
        print(
            f"[node-manager] 节点 {name[:30]} 被风控，加入黑名单 "
            f"({len(self.blacklist)}/{len(self.nodes)})",
            file=sys.stderr,
        )

    def healthy_count(self) -> int:
        return len(self.nodes) - len(self.blacklist)


def _json_load(path: Path):
    import json as _json

    return _json.loads(path.read_text(encoding="utf-8"))


def _json_dumps(value):
    import json as _json

    return _json.dumps(value, ensure_ascii=False)

BASE_URL = "https://product.pconline.com.cn"
PAGE_SIZE = 25


def ranking_url(offset: int) -> str:
    return (
        f"{BASE_URL}/notebook/s10.shtml"
        if offset <= 0 else f"{BASE_URL}/notebook/{offset}s10.shtml"
    )


def parse_specs(html: Any) -> dict[str, str]:
    specs: dict[str, str] = {}
    for row in html.select("table tr, tr"):
        cells = row.select("th, td")
        if len(cells) >= 2:
            key = clean_text(cells[0].get_text(" ", strip=True)).replace("纠错", "")
            value = clean_text(cells[1].get_text(" ", strip=True)).replace("纠错", "")
            if key and value and len(key) <= 32:
                specs.setdefault(key.rstrip(":："), value)
    for row in html.select("li.param-item, .parameter-item, .product-parameter-item"):
        text = clean_text(row.get_text(" ", strip=True))
        match = re.match(r"^(.{1,32}?)[:：]\s*(.+)$", text)
        if match:
            specs.setdefault(clean_text(match.group(1)), clean_text(match.group(2)))
    return specs


def parse_ranking_page(html: Any, page: int) -> list[dict[str, Any]]:
    selectors = (
        "#productList li, ul#J_ProductList li, .product-list li, "
        ".product_list li, ul.plist li, ul.prolist li, .rank-list li, "
        ".item-title"
    )
    cards: list[Any] = []
    seen: set[int] = set()
    for card in html.select(selectors):
        if id(card) not in seen:
            seen.add(id(card))
            cards.append(card)
    rows: list[dict[str, Any]] = []
    for index, card in enumerate(cards, start=1):
        link = (
            card.select_one("a.item-title-name[href]")
            or card.select_one("h3 a[href]")
            or card.select_one(".p-name a[href]")
            or card.select_one("a.product-title[href]")
            or card.select_one("a[href*='/notebook/']")
            or card.select_one("a[href]")
        )
        if link is None:
            continue
        title = clean_text(link.get_text(" ", strip=True) or link.get("title"))
        if not title:
            continue
        href = clean_text(link.get("href", ""))
        match = re.search(r"/(\d{3,})(?:[._/]|$)", href)
        product_id = match.group(1) if match else ""
        if not product_id:
            data_id = re.search(r"data-id=[\"']?(\d+)", str(card), re.I)
            product_id = data_id.group(1) if data_id else re.sub(r"\W+", "-", href).strip("-")
        price_node = card.select_one(".price, .p-price, .price-type, [class*='price']")
        rows.append(
            {
                "title": title, "model": title, "brand": infer_brand(title),
                "price": parse_price(price_node.get_text(" ", strip=True) if price_node else ""),
                "currency": "CNY", "source": "PConline",
                "atomic_source_names": ["PConline"],
                "source_category": "PConline notebook",
                "source_rank": (max(1, page) - 1) * PAGE_SIZE + index,
                "source_product_id": product_id,
                "source_url": absolute_url(BASE_URL, href),
            }
        )
    return rows


def title_fields(title: str) -> dict[str, Any]:
    cpu = extract_cpu_model(title)
    cpu_brand, cpu_family = parse_cpu_fields(cpu)
    gpu_match = re.search(
        r"\b((?:RTX|GTX)\s*\d{3,4}(?:\s*Ti)?|Radeon\s+RX\s*\d{3,4}\w*)\b",
        title, re.I,
    )
    gpu = clean_text(gpu_match.group(1)) if gpu_match else ""
    gpu_type, dedicated_gpu = gpu_fields("", gpu or title)
    screen = re.search(r"(\d{2}(?:\.\d+)?)\s*(?:英寸|吋|寸)", title)
    memory = re.search(r"(\d{1,3})\s*GB(?=[/+\s)]|$)", title, re.I)
    storage = re.findall(r"(\d+(?:\.\d+)?)\s*(TB|GB)(?=[/+\s)]|$)", title, re.I)
    return {
        "cpu": cpu, "cpu_brand": cpu_brand, "cpu_family": cpu_family,
        "cpu_voltage_type": classify_cpu_voltage(cpu),
        "numeric_keypad": None, "keyboard_backlight": None,
        "gpu": gpu, "gpu_type": gpu_type, "dedicated_gpu": dedicated_gpu,
        "screen_size": float(screen.group(1)) if screen else None,
        "resolution": "", "refresh_rate": None,
        "memory_gb": int(memory.group(1)) if memory else None,
        "storage_gb": max(int(float(n) * (1024 if u.upper() == "TB" else 1)) for n, u in storage) if storage else None,
        "battery_wh": None, "weight_kg": None, "ports": [],
        "evidence": {"numeric_keypad": "", "keyboard_backlight": "",
                     "cpu": title, "gpu": gpu or title, "product_form": ""},
    }


def enrich_item(session: Any, item: dict[str, Any], delay: float) -> dict[str, Any]:
    item.update(title_fields(item["title"]))
    try:
        detail_url = item["source_url"]
        if detail_url.endswith(".html") and not detail_url.endswith("_detail.html"):
            detail_url = detail_url[:-5] + "_detail.html"
        detail, final_url = get_html(session, detail_url, encoding="gb18030", delay=delay)
    except Exception as exc:
        item["crawl_warning"] = f"detail_failed:{type(exc).__name__}"
        return item
    specs = parse_specs(detail)
    detail_text = "；".join(f"{k}：{v}" for k, v in specs.items())
    numeric, backlight = keyboard_flags(detail_text)
    cpu_raw = text_from_spec(specs, "CPU型号", "处理器型号", "CPU") or item["title"]
    cpu = extract_cpu_model(cpu_raw)
    cpu_brand, cpu_family = parse_cpu_fields(cpu_raw)
    gpu_type_raw = text_from_spec(specs, "显卡类型")
    gpu = text_from_spec(specs, "显卡芯片", "显卡型号") or item["gpu"]
    gpu_type, dedicated_gpu = gpu_fields(gpu_type_raw, gpu)
    ports_text = "；".join(v for k, v in specs.items() if "接口" in k)
    product_form = clean_text("；".join(v for k, v in specs.items() if k in {"产品类型", "产品定位", "产品特点", "包装清单"}))
    item.update(
        {
            "cpu": cpu, "cpu_brand": cpu_brand, "cpu_family": cpu_family,
            "cpu_voltage_type": classify_cpu_voltage(cpu),
            "numeric_keypad": numeric if numeric is not None else item["numeric_keypad"],
            "keyboard_backlight": backlight if backlight is not None else item["keyboard_backlight"],
            "gpu": gpu, "gpu_type": gpu_type, "dedicated_gpu": dedicated_gpu,
            "screen_size": parse_number(text_from_spec(specs, "屏幕尺寸")) or item["screen_size"],
            "resolution": text_from_spec(specs, "屏幕分辨率", "分辨率") or item["resolution"],
            "refresh_rate": parse_number(text_from_spec(specs, "屏幕刷新率", "刷新率")) or item["refresh_rate"],
            "memory_gb": parse_capacity_gb(text_from_spec(specs, "内存容量")) or item["memory_gb"],
            "storage_gb": parse_capacity_gb(text_from_spec(specs, "硬盘容量", "存储容量")) or item["storage_gb"],
            "battery_wh": parse_battery_wh(text_from_spec(specs, "电池容量", "电池类型")) or item["battery_wh"],
            "weight_kg": parse_number(text_from_spec(specs, "笔记本重量", "产品重量", "重量")) or item["weight_kg"],
            "ports": [clean_text(x) for x in re.split(r"[；;]", ports_text) if clean_text(x)],
            "product_form": product_form, "spec_url": final_url,
            "evidence": {
                "numeric_keypad": detail_text if numeric is not None else "",
                "keyboard_backlight": detail_text if backlight is not None else "",
                "cpu": cpu_raw, "gpu": clean_text(f"{gpu_type_raw} {gpu}"),
                "product_form": product_form,
            },
        }
    )
    return item


def _mihomo_controller_ready() -> bool:
    """探测 mihomo external-controller 是否可用。"""
    try:
        import socket

        with socket.create_connection(("127.0.0.1", 9090), timeout=2):
            return True
    except Exception:
        return False


def _fetch_ranking_with_node_retry(
    session,
    url: str,
    page: int,
    node_mgr: "NodeManager | None",
    delay: float,
) -> list[dict[str, Any]]:
    """带节点切换的榜单页抓取：风控（行数 < 2）时拉黑当前节点并换节点重试。

    最多尝试 nodes 数量次；全部拉黑或无法切换时返回空列表。
    """
    if node_mgr is None:
        html, final_url = get_html(
            session, url, encoding="gb18030", delay=delay
        )
        return parse_ranking_page(html, page), final_url

    attempts = max(len(node_mgr.nodes), 1)
    last_url = url
    for attempt in range(attempts):
        # 确保当前节点未被拉黑；被拉黑则切换
        if node_mgr.current in node_mgr.blacklist:
            node_mgr.select_next()
        if node_mgr.current is None:
            node_mgr.select_next()
        if node_mgr.current is None:
            print(
                "[node-manager] 所有节点均被风控，无法继续爬取",
                file=sys.stderr,
            )
            return []
        try:
            html, final_url = get_html(
                session, url, encoding="gb18030", delay=delay
            )
            last_url = final_url
        except Exception as exc:
            print(
                f"[node-manager] 节点 {node_mgr.current[:30]} 请求失败 "
                f"{type(exc).__name__}，换节点重试",
                file=sys.stderr,
            )
            node_mgr.mark_blocked(node_mgr.current)
            node_mgr.select_next()
            continue
        page_items = parse_ranking_page(html, page)
        if len(page_items) >= 2:
            return page_items, last_url
        # 风控特征：行数 < 2
        node_mgr.mark_blocked(node_mgr.current)
        node_mgr.select_next()
    return [], last_url


def crawl(
    pages: int,
    max_items: int,
    delay: float,
    time_limit: float = 0,
) -> list[dict[str, Any]]:
    session = make_session()
    session.headers["Referer"] = f"{BASE_URL}/notebook/"
    budget = Budget(time_limit)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    controller_ready = _mihomo_controller_ready()
    print(
        f"[pconline] mihomo controller ready: {controller_ready}",
        file=sys.stderr,
    )
    node_mgr = NodeManager() if controller_ready else None
    if node_mgr is not None:
        print(
            f"[pconline] NodeManager nodes={len(node_mgr.nodes)} "
            f"blacklist={sorted(node_mgr.blacklist)[:5]}",
            file=sys.stderr,
        )
    for page in range(1, pages + 1):
        if budget.expired():
            print("PConline time budget exhausted; keeping scanned prefix")
            break
        url = ranking_url((page - 1) * PAGE_SIZE)
        page_items, final_url = _fetch_ranking_with_node_retry(
            session, url, page, node_mgr, delay
        )
        if not page_items:
            raise RuntimeError(f"PConline ranking page {page} returned no product cards")
        session.headers["Referer"] = final_url
        for item in page_items:
            key = item["source_product_id"] or item["source_url"]
            if key not in seen:
                seen.add(key)
                items.append(item)
            if len(items) >= max_items:
                break
        if len(items) >= max_items:
            break
    for index, item in enumerate(items):
        if budget.expired():
            print("PConline time budget exhausted during enrichment; keeping enriched prefix")
            break
        items[index] = enrich_item(session, item, delay)
        items[index]["fetched_at"] = utc_now()
    return [item for item in items if item.get("fetched_at")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/raw/pconline/latest.json")
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--max-items", type=int, default=120)
    parser.add_argument("--min-records", type=int, default=50)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument(
        "--time-limit",
        type=float,
        default=0,
        help="wall-clock budget in seconds (0 = unlimited)",
    )
    args = parser.parse_args()
    if args.pages < 1 or args.max_items < 0 or args.min_records < 1:
        print("PConline CLI limits must be positive", file=sys.stderr)
        return 2
    try:
        items = crawl(args.pages, args.max_items, args.delay, args.time_limit)
    except Exception as exc:
        print(f"PConline crawl failed: {exc}", file=sys.stderr)
        return 2
    if len(items) < args.min_records:
        print(f"PConline integrity failure: {len(items)} rows < {args.min_records}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} PConline popularity-ranked records to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
