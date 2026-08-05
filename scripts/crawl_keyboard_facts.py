#!/usr/bin/env python3
"""crawl_keyboard_facts.py — 从品牌官网采集型号级键盘事实（数字键盘/背光）。

免登录、只读、单次运行产出 keyboard_facts.json。
来源：
  1. HP 中国官网 hpstore.cn —— dd data-th="键盘" 结构化规格表
  2. 机械革命官网 mechrevo.com —— 产品详情页文本（键盘特性描述）

每条 fact 含 series/size_inch 匹配键，merge_data.py 用它们在爬虫证据
缺失时按 "系列+尺寸" 精确匹配补键盘事实（型号级事实，非猜测）。

用法: python scripts/crawl_keyboard_facts.py --output config/keyboard_facts.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

HP_LIST_URLS = [
    "https://www.hpstore.cn/notebooks.html",
    "https://www.hpstore.cn/laptops.html",
    "https://www.hpstore.cn/personal-laptops.html",
    "https://www.hpstore.cn/business-laptops.html",
    "https://www.hpstore.cn/laptop-gaming.html",
    "https://www.hpstore.cn/omen-laptops.html",
    "https://www.hpstore.cn/hp-zhan66.html",
    "https://www.hpstore.cn/hp-zhanx.html",
]

MECHREVO_HOME = "https://www.mechrevo.com/cn/"

NUMERIC_KEYPAD_PATTERNS = [
    r"数字键盘", r"数字小键盘", r"小键盘", r"numpad", r"numeric\s+keypad",
    r"带数字", r"含数字", r"数字区", r"数字键区",
]
NO_KEYPAD_PATTERNS = [
    r"无数字键盘", r"无小键盘", r"without\s+(?:numeric\s+)?keypad", r"no\s+(?:numeric\s+)?keypad",
]
BACKLIGHT_PATTERNS = [
    r"背光键盘", r"背光", r"backlit", r"backlight", r"RGB键盘", r"rgb\s*backlit",
    r"防泼溅背光", r"白色背光", r"单色背光",
]
NO_BACKLIGHT_PATTERNS = [
    r"无背光", r"non[-\s]?backlit", r"no\s+backlight",
]

BRAND_PREFIXES = [
    "惠普 (HP)", "惠普(HP)", "惠普", "HP", "机械革命", "MECHREVO",
    "联想", "Lenovo", "戴尔", "Dell", "华硕", "ASUS", "宏碁", "Acer", "神舟", "HASEE",
]
SUB_BRAND_PREFIXES = ["HyperX", "OMEN", "VICTUS", "ROG", "TUF", "Legion", "ThinkPad", "IdeaPad"]

SUFFIXES = ("游戏笔记本电脑", "商务笔记本电脑", "笔记本电脑", "游戏笔记本",
            "商务笔记本", "笔记本", "游戏本", "商务本", "电脑", "notebook pc",
            "notebook", "laptop pc", "laptop")

SIZE_PATTERNS = [
    r"(\d+(?:\.\d+)?)\s*(?:英?寸|英寸|inch|吋)",          # 16英寸 / 16 英寸 / 16inch
    r"(\d+(?:\.\d+)?)(?=\s*(?:Ultra|Pro|Plus|Max|AI)\b)",  # 16 Ultra / 16 Pro
]


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_keyboard(text: str) -> dict:
    """从键盘规格文本解析数字键盘/背光。返回 (numeric_keypad, keyboard_backlight)。"""
    lowered = text.lower()
    numeric = None
    backlight = None
    if re.search(r"|".join(NO_KEYPAD_PATTERNS), lowered, re.I):
        numeric = False
    if re.search(r"|".join(NUMERIC_KEYPAD_PATTERNS), lowered, re.I):
        numeric = True
    if re.search(r"|".join(NO_BACKLIGHT_PATTERNS), lowered, re.I):
        backlight = False
    if re.search(r"|".join(BACKLIGHT_PATTERNS), lowered, re.I):
        backlight = True
    return {"numeric_keypad": numeric, "keyboard_backlight": backlight}


def extract_series(model: str) -> str:
    """从型号名提取系列核心词：先剥品牌前缀，再剥子品牌前缀。"""
    text = model
    for prefix in BRAND_PREFIXES + SUB_BRAND_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            # 剥完一个前缀后继续尝试剥下一个（子品牌跟随品牌）
            for prefix2 in BRAND_PREFIXES + SUB_BRAND_PREFIXES:
                if text.startswith(prefix2):
                    text = text[len(prefix2):].strip()
                    break
            break
    text = text.strip(" -:：|")
    for suffix in SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    token = re.split(r"[\s(（]", text)[0].strip()
    return token


def extract_size_inch(model: str) -> str:
    """从型号名提取尺寸（如 16英寸/15.3英寸），未提及返回空。"""
    for pattern in SIZE_PATTERNS:
        m = re.search(pattern, model, re.I)
        if m:
            return f"{m.group(1)}英寸"
    return ""


def crawl_hp() -> list[dict]:
    facts: list[dict] = []
    seen: set[str] = set()
    product_links: list[str] = []
    for list_url in HP_LIST_URLS:
        try:
            html = fetch(list_url)
        except Exception as exc:
            print(f"[hp] list {list_url} failed: {type(exc).__name__} {exc}", file=sys.stderr)
            continue
        # 产品页：slug 含型号编码（数字），排除分类页（以 -laptops.html 等结尾）
        links = re.findall(r'href="(https://www\.hpstore\.cn/[^"]*\.html)"', html)
        for link in dict.fromkeys(links):
            slug = link.split("/")[-1]
            if slug.endswith(("-laptops.html", "-desktops.html", "-monitors.html",
                              "-printers.html", "-tablets.html", "-accessories.html",
                              "-promotions.html", "-scanners.html", "-keyboards.html",
                              "-mice.html", "-docks.html", "-webcams.html",
                              "-speakers.html", "-cases-sleeves.html", "-batteries-chargers-adapters.html")):
                continue
            if not any(c.isdigit() for c in slug):
                continue
            if link not in seen:
                seen.add(link)
                product_links.append(link)
    print(f"[hp] found {len(product_links)} product pages", file=sys.stderr)
    for url in product_links:
        try:
            html = fetch(url)
        except Exception as exc:
            print(f"[hp] {url} failed: {type(exc).__name__} {exc}", file=sys.stderr)
            continue
        title_m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = clean(title_m.group(1)) if title_m else ""
        kb_rows = re.findall(
            r'<dd[^>]*data-th=["\']键盘["\'][^>]*>(.*?)</dd>', html, re.S | re.I
        )
        kb_texts = [clean(re.sub(r"<[^>]+>", "", row)) for row in kb_rows]
        if not kb_texts:
            for m in re.finditer(r"键盘[^<]{0,10}<[^>]*>([^<]{2,80})<", html):
                val = clean(m.group(1))
                if val and val not in kb_texts:
                    kb_texts.append(val)
        kb_text = "；".join(kb_texts)
        parsed = parse_keyboard(kb_text)
        if parsed["numeric_keypad"] is None and parsed["keyboard_backlight"] is None:
            continue
        model = clean(title.split("|")[0].split("-")[0])[:80]
        fact = {
            "model": model,
            "series": extract_series(model),
            "size_inch": extract_size_inch(model),
            "page_url": url,
            "keyboard_text": kb_text[:200],
            "source": "hp-official",
            **parsed,
        }
        facts.append(fact)
        print(f"[hp] {model[:38]!r} series={fact['series']!r} size={fact['size_inch']!r} "
              f"kb={kb_text[:36]!r} -> {parsed}", file=sys.stderr)
        time.sleep(1)
    return facts


def crawl_mechrevo() -> list[dict]:
    facts: list[dict] = []
    try:
        html = fetch(MECHREVO_HOME)
    except Exception as exc:
        print(f"[mechrevo] home failed: {type(exc).__name__} {exc}", file=sys.stderr)
        return facts
    links = re.findall(r'href="(/cn/products/[^"]+)"', html)
    product_links = list(dict.fromkeys(links))
    print(f"[mechrevo] found {len(product_links)} product pages", file=sys.stderr)
    for path in product_links:
        url = f"https://www.mechrevo.com{path}"
        try:
            page = fetch(url)
        except Exception as exc:
            print(f"[mechrevo] {url} failed: {type(exc).__name__} {exc}", file=sys.stderr)
            continue
        title_m = re.search(r"<title>(.*?)</title>", page, re.S)
        title = clean(title_m.group(1)) if title_m else ""
        kb_chunks: list[str] = []
        for m in re.finditer(r"[^<>]{0,30}(?:键盘|键盘特性|keycap)[^<>]{0,50}", page):
            chunk = clean(m.group(0))
            if chunk and chunk not in kb_chunks:
                kb_chunks.append(chunk)
            if len(kb_chunks) >= 6:
                break
        kb_text = "；".join(kb_chunks)[:300]
        parsed = parse_keyboard(kb_text)
        if parsed["numeric_keypad"] is None and parsed["keyboard_backlight"] is None:
            continue
        model = clean(title.split("|")[0])[:80]
        fact = {
            "model": model,
            "series": extract_series(model),
            "size_inch": extract_size_inch(model),
            "page_url": url,
            "keyboard_text": kb_text,
            "source": "mechrevo-official",
            **parsed,
        }
        facts.append(fact)
        print(f"[mechrevo] {model[:38]!r} series={fact['series']!r} size={fact['size_inch']!r} "
              f"-> {parsed}", file=sys.stderr)
        time.sleep(1)
    return facts


def merge_duplicate_facts(facts: list[dict]) -> list[dict]:
    """按 series+size_inch 合并重复条目：键盘文本拼接，布尔值取更确定者。"""
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for fact in facts:
        key = (fact["series"], fact["size_inch"], fact["source"])
        if key not in merged:
            merged[key] = dict(fact)
            order.append(key)
            continue
        prev = merged[key]
        prev["keyboard_text"] = "；".join(
            t for t in (prev.get("keyboard_text", ""), fact.get("keyboard_text", ""))
            if t and t not in prev.get("keyboard_text", "")
        )
        for field in ("numeric_keypad", "keyboard_backlight"):
            if prev.get(field) is None and fact.get(field) is not None:
                prev[field] = fact[field]
        urls = prev.get("page_urls") or [prev.get("page_url")]
        if fact.get("page_url") not in urls:
            urls.append(fact["page_url"])
        prev["page_urls"] = urls
    return [merged[key] for key in order]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="config/keyboard_facts.json")
    parser.add_argument("--sources", default="hp,mechrevo", help="逗号分隔: hp,mechrevo")
    args = parser.parse_args()

    facts: list[dict] = []
    for source in args.sources.split(","):
        source = source.strip()
        if source == "hp":
            facts.extend(crawl_hp())
        elif source == "mechrevo":
            facts.extend(crawl_mechrevo())
        else:
            print(f"unknown source: {source}", file=sys.stderr)

    facts = merge_duplicate_facts(facts)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(facts)} keyboard facts to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
