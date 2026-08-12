#!/usr/bin/env python3
"""PConline 搜索补充爬虫：用 ZOL 系列名搜索 PConline 未覆盖机型。

背景：PConline 热门榜/全量库仅 ~125 系列，ZOL 1812 条里 1708 条无
PConline 对应。PConline 站内搜索（ks.pconline.com.cn/product.shtml?q=）
可按"品牌 型号"（空格分隔）找到对应产品，大幅扩展覆盖。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    from scripts.crawler_utils import (
        clean_text,
        get_html,
        keyboard_flags,
        make_session,
        parse_cpu_fields,
        text_from_spec,
        utc_now,
    )
    from scripts.crawl_pconline import parse_specs, parse_ranking_page
except ModuleNotFoundError:
    from crawler_utils import (
        clean_text,
        get_html,
        keyboard_flags,
        make_session,
        parse_cpu_fields,
        text_from_spec,
        utc_now,
    )
    from crawl_pconline import parse_specs, parse_ranking_page

SEARCH_URL = "http://ks.pconline.com.cn/product.shtml"
BASE = "https://product.pconline.com.cn"


def search_products(session: Any, query: str, max_results: int = 20) -> list[dict[str, str]]:
    """搜索并返回 [{url, title}]（过滤非 notebook + 去重）。"""
    import urllib.parse

    q = urllib.parse.quote(query)
    url = f"{SEARCH_URL}?q={q}&scope=0"
    try:
        soup, _final = get_html(
            session, url, encoding="gb18030", delay=0.5,
            timeout=25,
        )
    except Exception as exc:
        print(f"search failed {query}: {type(exc).__name__}", file=sys.stderr)
        return []
    html = str(soup)
    results: dict[str, str] = {}
    # 产品链接 + 标题
    for m in re.finditer(
        r'href="(//product\.pconline\.com\.cn/notebook/[^"]+\.html)"[^>]*>',
        html,
    ):
        link = m.group(1)
        if "_" in link.split("/")[-1]:
            continue
        url_full = "https:" + link
        if url_full not in results:
            results[url_full] = ""
    for m in re.finditer(r'title="([^"]{5,60})"', html):
        title = m.group(1)
        if not re.search(r"笔记本|notebook|游戏本", title, re.I):
            continue
        # 关联到最近的产品链接（简化：标题列表顺序与链接顺序近似）
        pass
    items = [{"url": u, "title": ""} for u in results]
    # 用 title 属性补充（页面 title 含产品名）
    for m in re.finditer(r'<a[^>]*href="(//product\.pconline\.com\.cn/notebook/[^"]+\.html)"[^>]*title="([^"]+)"', html):
        link, title = "https:" + m.group(1), m.group(2)
        if link in results and "_" not in link.split("/")[-1]:
            results[link] = title
    items = [{"url": u, "title": t} for u, t in results.items() if u.startswith("https://product.pconline.com.cn/notebook/")]
    return items[:max_results]


def enrich_product(session: Any, url: str, delay: float) -> dict[str, Any] | None:
    """抓产品页并提取规格（复用 crawl_pconline 的详情 enrich）。"""
    detail_url = url[:-5] + "_detail.html" if url.endswith(".html") else url
    try:
        detail, _final = get_html(session, detail_url, encoding="gb18030", delay=delay)
    except Exception as exc:
        print(f"detail failed {url}: {type(exc).__name__}", file=sys.stderr)
        return None
    specs = parse_specs(detail)
    detail_text = "；".join(f"{k}：{v}" for k, v in specs.items())
    numeric, backlight = keyboard_flags(detail_text)
    cpu_raw = text_from_spec(specs, "CPU型号", "处理器型号", "CPU", "处理器") or ""
    cpu_brand, cpu_family = parse_cpu_fields(cpu_raw)
    title_el = detail.title
    raw_title = clean_text(str(title_el.string) if title_el and title_el.string else "") or url
    # 清理标题：去掉 "_参数_..." 后缀（如 联想拯救者R9000P 2025(...)参数_联想拯救者R9000P 2025(...)参数配置）
    title = re.split(r"_参数_|_报价_|_太平洋", raw_title)[0].strip()
    # 产品名（型号别称/产品名称），无则用清理后标题
    model_name = text_from_spec(specs, "型号别称", "产品名称", "型号") or title
    # 品牌提取（中文品牌 + 英文品牌开头）
    brand = ""
    for _b in ("联想", "华为", "苹果", "荣耀", "惠普", "华硕", "戴尔", "宏碁", "机械革命", "神舟", "雷神", "七彩虹", "小米", "微星"):
        if _b in title:
            brand = _b
            break
    if not brand:
        for _b in ("ThinkPad", "ThinkBook", "HUAWEI", "ROG", "Redmi", "Acer", "Alienware", "LG", "Xiaomi", "VAIO", "MacBook", "HP", "ASUS", "DELL"):
            if title.startswith(_b) or f" {_b} " in f" {title} ":
                brand = _b
                break
    # 型号别称兜底：spec 里的品牌
    if not brand:
        _alias = text_from_spec(specs, "型号别称", "产品名称")
        if _alias:
            for _b in ("ThinkPad", "ThinkBook", "HUAWEI", "ROG", "Redmi", "Acer", "Alienware", "LG", "VAIO", "MacBook"):
                if _b in str(_alias):
                    brand = _b
                    break
    # 关键规格
    mem_raw = text_from_spec(specs, "内存容量")
    sto_raw = text_from_spec(specs, "硬盘容量")
    scr_raw = text_from_spec(specs, "屏幕尺寸")
    gpu_raw = text_from_spec(specs, "显卡芯片", "显卡型号")
    def _num(v):
        if not v:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", str(v), re.I)
        if not m:
            return None
        n = float(m.group(1))
        return n * 1024 if m.group(2).upper() == "TB" else n
    return {
        "title": title,
        "model": model_name,
        "brand": brand,
        "cpu": cpu_raw,
        "cpu_brand": cpu_brand,
        "cpu_family": cpu_family,
        "numeric_keypad": numeric,
        "keyboard_backlight": backlight,
        "memory_gb": _num(mem_raw),
        "storage_gb": _num(sto_raw),
        "screen_size": _num(scr_raw) if scr_raw else None,
        "gpu": gpu_raw or "",
        "specs": specs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zol-input", required=True, help="ZOL raw JSON")
    parser.add_argument("--output", default="data/raw/pconline/search.json")
    parser.add_argument("--max-searches", type=int, default=600)
    parser.add_argument(
        "--published-first",
        default="",
        help="Pages 发布集 ZOL 单源 JSON：其搜索词优先（提升多源率的关键路径）",
    )
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    zol = json.loads(Path(args.zol_input).read_text(encoding="utf-8"))
    zol_items = zol.get("items", zol) if isinstance(zol, dict) else zol

    # 提取系列名（品牌 + 型号，空格分隔）——支持：
    # 1) 中文品牌 + 中文/混合型号（华硕 天选6 Pro / 联想 拯救者Y7000P / 神舟 战神S8）
    # 2) 英文品牌 + 英文型号（ThinkPad T14p / HUAWEI MateBook）
    # 3) 英文品牌 + 中文系列（Acer 暗影骑士·擎 / ROG 枪神9 / msi微星魔影15）
    queries: list[str] = []
    seen: set[str] = set()
    en_brands = ("ThinkPad", "ThinkBook", "HUAWEI", "ROG", "Redmi", "Acer", "Alienware", "LG", "Xiaomi", "VAIO", "MacBook", "HP", "ASUS", "DELL", "MSI", "Lenovo")
    cn_brands = ("联想", "华硕", "惠普", "戴尔", "宏碁", "神舟", "机械革命", "七彩虹", "微星", "雷神", "荣耀", "华为", "小米", "微软", "三星", "机械师", "火影", "吾空", "Acer宏碁")
    # 英文品牌后接中文系列（ROG 枪神9 / Acer 暗影骑士 / msi微星魔影15 / HP(惠普)）
    en_cn = (("ROG", "枪神", "魔霸", "幻"), ("Acer", "暗影骑士", "掠夺者", "战斧"), ("msi", "微星魔影"), ("MSI", "微星"), ("HP", "暗影精灵", "光影精灵", "星"), ("Lenovo", "拯救者", "小新", "ThinkBook", "扬天", "昭阳"), ("DELL", "游匣", "灵越"), ("ASUS", "天选", "无畏", "灵耀", "华硕"))
    # 括号双品牌格式：lenovo(联想)G5000 / HP(惠普)暗影精灵
    bracket_brands = (("lenovo", "联想"), ("hp", "惠普"), ("acer", "宏碁"), ("msi", "微星"), ("dell", "戴尔"), ("asus", "华硕"))

    def _extract_query(title: str) -> str | None:
        # 英文品牌 + 英文型号
        for b in en_brands:
            if title.startswith(b) and len(title) > len(b):
                rest = title[len(b):].strip()
                m = re.match(r"([A-Za-z0-9]+(?:\s*\+)?(?:\s*[- ]?[A-Za-z0-9]+)*)", rest)
                if m and m.group(1):
                    q = f"{b} {m.group(1)}".strip()
                    if len(q) >= 4:
                        return q
        # 英文品牌 + 中文系列
        for b, *cns in en_cn:
            prefix = title[:len(b)]
            if prefix.lower() == b.lower() or title.startswith(b):
                rest = title[len(b):].strip()
                # 跳过括号品牌（HP(惠普)）
                rest = re.sub(r"^[（(][^）)]*[）)]", "", rest).strip()
                m = re.match(r"([\u4e00-\u9fffA-Za-z0-9·]+(?:\s*[\u4e00-\u9fffA-Za-z0-9·]+)*)", rest)
                if m:
                    q = f"{b} {m.group(1)}".strip()
                    if len(q) >= 4:
                        return q
        # 括号双品牌：lenovo(联想)G5000
        low = title.lower()
        for b, cn in bracket_brands:
            if low.startswith(b + "(") and cn in title[:12]:
                rest = title[title.find(")") + 1:].strip()
                m = re.match(r"([\u4e00-\u9fffA-Za-z0-9·]+(?:\s*[\u4e00-\u9fffA-Za-z0-9·]+)*)", rest)
                if m:
                    q = f"{cn} {m.group(1)}".strip()
                    if len(q) >= 4:
                        return q
        # 中文品牌 + 系列
        for b in cn_brands:
            if title.startswith(b) and len(title) > len(b):
                rest = title[len(b):].strip()
                m = re.match(r"([\u4e00-\u9fffA-Za-z0-9·]+(?:\s*[\u4e00-\u9fffA-Za-z0-9·]+)*)", rest)
                if m:
                    q = f"{b} {m.group(1)}".strip()
                    if len(q) >= 4:
                        return q
        return None

    published_queries: list[str] = []
    if args.published_first:
        try:
            pub = json.loads(Path(args.published_first).read_text(encoding="utf-8"))
            pub_items = pub.get("items", pub) if isinstance(pub, dict) else pub
            for r in pub_items:
                q = _extract_query(str(r.get("title", "")))
                if q and q not in seen:
                    seen.add(q)
                    published_queries.append(q)
        except Exception as exc:
            print(f"published-first 加载失败，忽略: {exc}", file=sys.stderr)

    for r in zol_items:
        title = str(r.get("title", ""))
        q = _extract_query(title)
        if q and q not in seen:
            seen.add(q)
            queries.append(q)
        if len(queries) + len(published_queries) >= args.max_searches:
            break

    # 发布集优先：先搜 Pages 单源机型（直接提升多源率），再补 raw 其余
    queries = published_queries + queries[: max(0, args.max_searches - len(published_queries))]
    print(f"搜索词: {len(queries)}（发布集优先 {len(published_queries)}）", file=sys.stderr)
    session = make_session()
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for i, q in enumerate(queries):
        if i % 20 == 0:
            print(f"搜索进度 {i}/{len(queries)}", file=sys.stderr)
        for prod in search_products(session, q):
            if prod["url"] in seen_urls:
                continue
            seen_urls.add(prod["url"])
            enriched = enrich_product(session, prod["url"], args.delay)
            if enriched:
                results.append({
                    "title": enriched["title"],
                    "model": enriched["model"],
                    "brand": enriched.get("brand", ""),
                    "cpu": enriched["cpu"],
                    "cpu_brand": enriched["cpu_brand"],
                    "cpu_family": enriched["cpu_family"],
                    "numeric_keypad": enriched["numeric_keypad"],
                    "keyboard_backlight": enriched["keyboard_backlight"],
                    "memory_gb": enriched.get("memory_gb"),
                    "storage_gb": enriched.get("storage_gb"),
                    "screen_size": enriched.get("screen_size"),
                    "gpu": enriched.get("gpu", ""),
                    "source": "PConline",
                    "source_category": "搜索补充",
                    "atomic_source_names": ["PConline"],
                    "source_url": prod["url"],
                    "search_query": q,
                })

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(results)} PConline search records to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
