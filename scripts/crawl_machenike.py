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

try:
    from scripts.crawler_utils import (
        absolute_url,
        clean_text,
        gpu_fields,
        keyboard_flags,
        make_session,
        parse_cpu_fields,
        text_from_spec,
    )
except ModuleNotFoundError:
    from crawler_utils import (
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
    try:
        from scripts.crawler_utils import get_html
    except ModuleNotFoundError:
        from crawler_utils import get_html

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


def parse_attr_specs(detail_html: str) -> dict[str, str]:
    """解析机械师规格参数表（tab_attr 区 <li title="键：值">）。

    返回 {"CPU型号": "i9-13900HX", "屏幕规格": "16英寸 UHD 4K 电竞屏", ...}
    """
    specs: dict[str, str] = {}
    idx = detail_html.find('id="tab_attr"')
    if idx < 0:
        return specs
    seg = detail_html[idx:idx + 8000]
    for m in re.finditer(r'<li title="([^"]+)">', seg):
        item = m.group(1)
        if "：" in item:
            key, value = item.split("：", 1)
            specs[key.strip()] = value.strip()
    return specs


def parse_sku_configs(detail_html: str) -> list[dict[str, str]]:
    """从详情页 data-spec-value-name 提取 SKU 配置组合（笛卡尔积）。

    机械师详情页 SKU 选择器：<li data-id="组:值" data-spec-value-name="配置">。
    组标签如"选择显卡"（RTX4080 12G显存 2.5K屏）、内存组（32G+1TB）。
    返回 [{gpu, screen, memory, storage}]，SKU 组合 = 各组选项笛卡尔积。
    """
    # 组容器：<dt>选择显卡</dt> + <li data-id="6:434" data-spec-value-name="...">
    groups: list[tuple[str, list[str]]] = []
    # 用 data-spec-value-name 分组：先找组标签再收集选项
    for gm in re.finditer(r"<dt[^>]*>([^<]{1,20})</dt>", detail_html):
        label = gm.group(1).strip()
        if not label or label in ("配送至", "服务"):
            continue
        # 该 dt 后的 li 选项（到下一个 dt）
        seg = detail_html[gm.end():]
        next_dt = seg.find("<dt")
        if next_dt >= 0:
            seg = seg[:next_dt]
        opts = re.findall(r'data-spec-value-name="([^"]*)"', seg)
        if opts:
            groups.append((label, opts))

    if not groups:
        return []

    # 笛卡尔积
    from itertools import product
    combos = []
    for combo in product(*[opts for _, opts in groups]):
        record: dict[str, str] = {}
        for label, _opts in groups:
            pass
        # 按组标签归类
        for label, opts in groups:
            value = combo[groups.index((label, opts))]
            text = value.replace("\xa0", " ").strip()
            if "显卡" in label:
                record["gpu_raw"] = text
            elif re.search(r"内存|存储", label):
                record["mem_raw"] = text
            else:
                record.setdefault("extra", []).append(text)
        combos.append(record)
    return combos


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


# 外设/台式机/配件垃圾词（机械师官网列表混入大量非笔记本商品）
JUNK_TITLE = re.compile(
    r"鼠标|键盘|耳机|显示器|屏幕|音响|音箱|充电器|氮化镓|背包|箱包|贴膜|按摩|礼盒|"
    r"水冷箱|水冷|支架|扩展|hub|硬盘盒|散热|转接|U盘|移动硬盘|台式机|主机|迷你|mini|"
    r"电竞主机|游戏电脑|电脑主机|设计台式|未来战舰|游戏台式|TWS|蓝牙耳机|笔记本散热|"
    r"机械键盘|电竞屏|键鼠|工作站|仅供升级|升级选项|升级144|补差价|"
    r"电脑包|笔记本包|内胆包|双肩包|手提包|保护套|收纳包|电脑背包|电脑内胆|电脑双肩",
    re.I,
)
# 笔记本系列名（标题无"笔记本"字样但属这些系列的保留）
NOTEBOOK_SERIES = ("曙光", "星辰", "F117", "T90", "T58", "创物者", "飞行家", "Machcreator", "设计本")


def is_notebook(title: str) -> bool:
    """仅保留笔记本商品（剔除台式机/外设/配件/升级件/电脑包）。"""
    if JUNK_TITLE.search(title):
        return False
    if re.search(r"游戏本|笔记本|notebook", title, re.I):
        return True
    return any(series in title for series in NOTEBOOK_SERIES)


def is_plausible_price(price: float | None) -> bool:
    """价格合理性：游戏本 <500 元视为异常（配件/错误标价）。"""
    if price is None:
        return True
    return price >= 500


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
            # 标题清理：去营销描述词，只留型号（如 "机械师F117-X 重磅游戏本新品" → "机械师F117-X"）
            _clean = title
            _clean = re.sub(r"【[^】]*】", "", _clean)  # 【新】【NEW】【金属版】等
            _clean = re.sub(r"(重磅|新品|全新|金属版|电竞|游戏本|笔记本|轻薄|旗舰|高端|专业|升级|特价|高配|顶配|爆款|热销)", "", _clean)
            _clean = re.sub(r"\s{2,}", " ", _clean).strip()
            if _clean and len(_clean) >= 4:
                title = _clean
            if not is_notebook(title):
                continue  # 剔除台式机/外设/配件/电脑包（机械师列表混入大量非笔记本）
            if card.get("price") is not None and not is_plausible_price(card.get("price")):
                continue  # 异常低价（<500）视为配件/错误标价
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
            # SKU 配置解析：data-spec-value-name 含每 SKU 的显卡/屏幕/内存/存储
            try:
                if detail_html:
                    _skus = parse_sku_configs(detail_html)
                    if _skus:
                        # 用默认 SKU 的配置（首组组合）；SKU 级数据存 skus 字段供前端展开
                        _s0 = _skus[0]
                        if _s0.get("gpu_raw") and not record.get("gpu"):
                            _g = _s0["gpu_raw"]
                            _gm = re.match(r"(RTX\s?\d{4,5}|GTX\s?\d{4}|RX\s?\d{4}|Arc\s?\d+)", _g, re.I)
                            if _gm:
                                record["gpu"] = _gm.group(1).replace(" ", "")
                                record["gpu_type"] = "dedicated"
                                record["dedicated_gpu"] = True
                            _sm = re.search(r"(\d+(?:\.\d+)?)K屏", _g)
                            if _sm:
                                record["resolution"] = _sm.group(1) + "K"
                            _scm = re.search(r"(\d+(?:\.\d+)?)英寸|(\d+(?:\.\d+)?)吋", _g)
                            if _scm and not record.get("screen_size"):
                                record["screen_size"] = float(_scm.group(1) or _scm.group(2))
                        if _s0.get("mem_raw") and not record.get("memory_gb"):
                            _mm = re.match(r"(\d+)G\+(\d+)TB?", _s0["mem_raw"])
                            if _mm:
                                record["memory_gb"] = float(_mm.group(1))
                                record["storage_gb"] = float(_mm.group(2)) * 1024
                        # 全部 SKU 配置存起来（前端 SKU 展开）
                        record["sku_configs"] = [
                            {"gpu": s.get("gpu_raw", ""), "memory": s.get("mem_raw", "")}
                            for s in _skus
                        ]
            except Exception:
                pass
            # 规格参数表提取（tab_attr li title）：CPU型号/屏幕规格/内存/存储——硬性字段
            try:
                if detail_html:
                    _attrs = parse_attr_specs(detail_html)
                    if _attrs:
                        _acpu = _attrs.get("CPU型号", "")
                        _cur_cpu = str(record.get("cpu") or "")
                        _cpu_is_weak = (
                            not _cur_cpu
                            or _cur_cpu.startswith(str(record.get("title", ""))[:10])
                            or not re.search(r"\d{3,5}", _cur_cpu)
                        )
                        if _acpu and _cpu_is_weak:
                            record["cpu"] = _acpu
                            cb, cf = parse_cpu_fields(_acpu)
                            record["cpu_brand"] = cb
                            record["cpu_family"] = cf
                        _ascr = _attrs.get("屏幕规格", "")
                        if _ascr:
                            _scm = re.search(r"(\d+(?:\.\d+)?)\s*英寸", _ascr)
                            if _scm and not record.get("screen_size"):
                                record["screen_size"] = float(_scm.group(1))
                            _arm = re.search(r"(\d+(?:\.\d+)?)K|(UHD|FHD|2K|4K)", _ascr)
                            if _arm and not record.get("resolution"):
                                record["resolution"] = _arm.group(1) + "K" if _arm.group(1) else _arm.group(2)
                        _amem = _attrs.get("内存容量", "")
                        if _amem and not record.get("memory_gb"):
                            _mm = re.search(r"(\d+)\s*G", _amem, re.I)
                            if _mm:
                                record["memory_gb"] = float(_mm.group(1))
                        _asto = _attrs.get("固态硬盘", "")
                        if _asto and not record.get("storage_gb"):
                            _sm = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB)", _asto, re.I)
                            if _sm:
                                _v = float(_sm.group(1))
                                record["storage_gb"] = _v * 1024 if _sm.group(2).upper() == "TB" else _v
                            _proto = extract_storage_protocol(_asto)
                            if _proto:
                                record["storage_protocol"] = _proto
                        _agpu = _attrs.get("独立显卡", "")
                        if _agpu and not record.get("gpu"):
                            _gm2 = re.search(r"(GeForce[^\s]*|RTX\s?\d{4,5}|GTX\s?\d{4}|RX\s?\d{4}|Arc\s?\d+)", _agpu, re.I)
                            if _gm2:
                                record["gpu"] = _gm2.group(1).replace(" ", "")
                                record["gpu_type"] = "dedicated"
                                record["dedicated_gpu"] = True
                        # 老机型规格表无 CPU型号键：从 meta content 描述提取（如 "i7-8750H处理器"）
                        if not re.search(r"\d{3,5}", _cur_cpu):
                            _mdesc2 = re.search(r'<meta content="([^"]{100,})"', detail_html)
                            if _mdesc2:
                                _dcpu = re.search(r"(?:i[3579]|锐龙|R[579]|Ultra\s?[579])\s?-?\s*\d{4,5}[A-Za-z0-9]*", _mdesc2.group(1))
                                if _dcpu:
                                    record["cpu"] = _dcpu.group(0).replace(" ", "")
                                    cb, cf = parse_cpu_fields(record["cpu"])
                                    record["cpu_brand"] = cb
                                    record["cpu_family"] = cf
            except Exception:
                pass
            # 描述文本提取：散热（双液金/双风扇等）
            try:
                if detail_html:
                    _mdesc = re.search(r'<meta content="([^"]{100,})"', detail_html)
                    _desc = _mdesc.group(1) if _mdesc else ""
                    if _desc:
                        _cool = re.search(r"([^，,；;]{0,10}(?:液金|风扇|热管)[^，,；;]{0,10})", _desc)
                        if _cool and not record.get("cooling"):
                            record["cooling"] = _cool.group(1).strip()
            except Exception:
                pass
            # 描述文本提取：散热（双液金/双风扇等）/屏幕尺寸/分辨率
            try:
                if detail_html:
                    _mdesc = re.search(r'<meta name="description" content="([^"]*)"', detail_html)
                    _desc = _mdesc.group(1) if _mdesc else ""
                    if _desc:
                        _cm = re.search(r"(\d+(?:\.\d+)?)\s*英寸", _desc)
                        if _cm and not record.get("screen_size"):
                            record["screen_size"] = float(_cm.group(1))
                        _rm = re.search(r"(\d+(?:\.\d+)?)K", _desc)
                        if _rm and not record.get("resolution"):
                            record["resolution"] = _rm.group(1) + "K"
                        _cool = re.search(r"([^，,；;]{0,8}(?:液金|风扇|热管|散热)[^，,；;]{0,8})", _desc)
                        if _cool and not record.get("cooling"):
                            record["cooling"] = _cool.group(1).strip()
            except Exception:
                pass
            # 标题级规格兜底：CPU/GPU 从标题提取（i7HX 4060 等）
            title = record.get("title", "")
            m_cpu = re.search(r"(i[3579][-A-Za-z0-9HXK]*|R[579][-A-Za-z0-9HXK]*|Ultra\s?\d[\w]*|锐龙[^/（）()]*|酷睿[^/（）()]*)", title)
            cpu_missing = not record.get("cpu") or str(record.get("cpu", "")).startswith(title[:10])
            if m_cpu and cpu_missing:
                record["cpu"] = m_cpu.group(1).strip()
                cb, cf = parse_cpu_fields(record["cpu"])
                record["cpu_brand"] = cb
                record["cpu_family"] = cf
            elif cpu_missing and str(record.get("cpu", "")).startswith(title[:10]):
                # 标题无 CPU 家族词（如"曙光16Pro 4090"）：清空错误回退
                record["cpu"] = ""
                record["cpu_brand"] = ""
                record["cpu_family"] = ""
            m_gpu = re.search(r"(RTX\s?\d{4,5}|GTX\s?\d{4}|RX\s?\d{4}|Arc\s?\d+)", title, re.I)
            if not m_gpu:
                # 裸数字 GPU（"4090游戏本"/"5060"）：补 RTX 前缀
                # 排除 CPU 数字（5 位 i7-13900HX 等）和年份
                _m = re.search(r"(?<![0-9A-Za-z])(\d{4}0?(?:Ti)?)(?![0-9A-Za-z])", title)
                if _m:
                    _g = _m.group(1)
                    if _g in ("13900", "14900", "13620", "14650", "13700", "14700", "7945", "8945", "8845", "7840", "7940", "7735", "8840", "8940", "7940"):
                        _m = None
                if _m:
                    record["gpu"] = "RTX " + _m.group(1)
                    record["gpu_type"] = "dedicated"
                    record["dedicated_gpu"] = True
            if m_gpu:
                record["gpu"] = m_gpu.group(1).replace(" ", "")
                record["gpu_type"] = "dedicated"
                record["dedicated_gpu"] = True
            # 游戏本类目弱证据：蓝天模具游戏本标配数字键盘 + 背光键盘 + H 系 CPU
            if record.get("cpu_voltage_type") in (None, "unknown"):
                # 蓝天模具游戏本全系 H/HX 标压 CPU（产品形态决定，非型号推断）
                record["cpu_voltage_type"] = "standard_performance"
                record.setdefault("evidence", {})["cpu_voltage_type"] = (
                    "准系统游戏本类目弱证据（蓝天模具标配 H 系标压 CPU）"
                )
            if record.get("numeric_keypad") is None:
                record["numeric_keypad"] = True
                record.setdefault("evidence", {})["numeric_keypad"] = (
                    "准系统游戏本类目弱证据（蓝天模具标配数字键盘）"
                )
            if record.get("keyboard_backlight") is None:
                record["keyboard_backlight"] = True
                record.setdefault("evidence", {})["keyboard_backlight"] = (
                    "准系统游戏本类目弱证据（蓝天模具标配背光键盘）"
                )
            # 游戏本类目独显默认：机械师列表来自"电竞游戏本"分类（独显游戏本），
            # 除非标题明确"集显/核显"（如 曙光16S 集显版）
            if record.get("dedicated_gpu") is None:
                if re.search(r"集显|核显|集成显卡", title):
                    record["dedicated_gpu"] = False
                    record["gpu_type"] = "integrated"
                else:
                    record["dedicated_gpu"] = True
                    record["gpu_type"] = "dedicated"
            # CPU 家族前缀补全：CPU 字段纯数字（如 7945HX）时，从标题家族词补前缀
            # （R9-7945HX / i7-13620H / U7-275HX）——用户要求必须带家族
            _cpu_v = str(record.get("cpu") or "")
            if re.match(r"^\d{4,5}[A-Za-z]*$", _cpu_v.strip()):
                _fam = ""
                _fm = re.search(r"\b(R[579]|i[3579]|U[3579]|Ultra\s?[579])\b", title)
                if _fm:
                    _fam = _fm.group(1).replace(" ", "")
                if _fam:
                    record["cpu"] = f"{_fam}-{_cpu_v.strip()}"
                    cb, cf = parse_cpu_fields(record["cpu"])
                    record["cpu_brand"] = cb
                    record["cpu_family"] = cf
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
