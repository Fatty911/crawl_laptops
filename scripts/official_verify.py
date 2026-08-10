#!/usr/bin/env python3
"""品牌官网数字键盘验证器：≤15.5寸+数字键盘的可疑条目，抓官网 specs 验证。

支持品牌：
- Redmi/小米：mi.com 产品 specs 页（如 https://www.mi.com/redmi-books/14-2024/specs）
- 机械革命：mechrevo.com 产品页
- 机械师：machenike.com 产品详情页（tab_attr 规格表）

验证结果写入记录：official_verified=True/False + official_evidence（官网原文）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.crawler_utils import get_html, make_session, clean_text
except ModuleNotFoundError:
    from crawler_utils import get_html, make_session, clean_text


def verify_redmi(session: Any, title: str, source_url: str) -> tuple[bool, str]:
    """Redmi/小米：mi.com specs 页（键盘数据在 specs JS 里，需解析 JS）。

    实测：specs JS 含键盘描述文本（"全尺寸键盘，3档键盘背光，1.3mm 键程"），
    数字键盘必须出现"数字键盘/数字小键盘/独立数字"字样才算有。
    """
    m = re.search(r"Redmi\s*Book\s*(\d+)\s*(\d{4})", title, re.I)
    if not m:
        return False, "无法从标题提取 Redmi Book 型号"
    slug = f"redmi-books/{m.group(1)}-{m.group(2)}"
    url = f"https://www.mi.com/{slug}/specs"
    try:
        soup, _ = get_html(session, url, delay=0.5, timeout=25)
        html = str(soup)
        # 找 specs JS（产品数据在 JS 里）
        js_url = ""
        js_match = re.search(r'src="([^"]*specs[^"]*\.js)"', html)
        if js_match:
            js_url = "https:" + js_match.group(1) if js_match.group(1).startswith("//") else js_match.group(1)
            js_soup, _ = get_html(session, js_url, delay=0.3, timeout=25)
            html = str(js_soup)
        # 键盘描述
        kb = re.search(r"[\u4e00-\u9fff]{0,10}键盘[\u4e00-\u9fff0-9a-zA-Z，,。.、\s]{0,50}", html)
        has_numpad = bool(re.search(r"数字键盘|数字小键盘|独立数字", html))
        kb_text = kb.group(0)[:70] if kb else "无键盘描述"
        return has_numpad, f"官网JS({url}{'#specs.js' if js_url else ''}): {kb_text}"
    except Exception as exc:
        return False, f"官网访问失败({url}): {type(exc).__name__}"


def verify_mechrevo(session: Any, title: str, source_url: str) -> tuple[bool, str]:
    """机械革命：mechrevo.com。"""
    m = re.search(r"机械革命([\u4e00-\u9fffA-Za-z0-9\s]+?)\s*(?:\(|$)", title)
    model = m.group(1).strip() if m else title[:20]
    url = f"https://www.mechrevo.com/search?keyword={model}"
    try:
        soup, _ = get_html(session, url, delay=0.5, timeout=25)
        html = str(soup)
        has_numpad = bool(re.search(r"数字键盘|数字小键盘|独立数字", html))
        kb = re.search(r"键盘[^<]{0,60}", html)
        return has_numpad, f"官网搜索({url}): {kb.group(0)[:60] if kb else '无键盘描述'}"
    except Exception as exc:
        return False, f"官网访问失败({url}): {type(exc).__name__}"


def verify_machenike(session: Any, title: str, source_url: str) -> tuple[bool, str]:
    """机械师：详情页 tab_attr 规格表（键盘相关）。"""
    if not source_url or "machenike.com" not in source_url:
        return False, "无机械师官网 URL"
    try:
        soup, _ = get_html(session, source_url, delay=0.5, timeout=25)
        html = str(soup)
        # 规格表 li title
        specs = {}
        for m in re.finditer(r'<li title="([^"]+)">', html):
            item = m.group(1)
            if "：" in item:
                k, v = item.split("：", 1)
                specs[k.strip()] = v.strip()
        kb_text = " ".join(f"{k}：{v}" for k, v in specs.items() if "键盘" in k)
        has_numpad = bool(re.search(r"数字键盘|数字小键盘|独立数字", kb_text or html))
        return has_numpad, f"机械师官网({source_url}): {kb_text[:60] if kb_text else specs}"
    except Exception as exc:
        return False, f"机械师官网访问失败: {type(exc).__name__}"


def verify_record(session: Any, record: dict[str, Any]) -> dict[str, Any]:
    """按品牌分发验证。"""
    title = str(record.get("title", ""))
    source_url = str(record.get("source_url", ""))
    source = str(record.get("source", ""))
    if "Redmi" in title or "小米" in title:
        ok, ev = verify_redmi(session, title, source_url)
    elif "机械革命" in title:
        ok, ev = verify_mechrevo(session, title, source_url)
    elif "机械师" in title or "Machinike" in source:
        ok, ev = verify_machenike(session, title, source_url)
    else:
        return {**record, "official_verified": False,
                "official_evidence": f"品牌 {record.get('brand','')} 无验证器"}

    out = dict(record)
    out["official_verified"] = ok
    out["official_evidence"] = ev
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="待验证记录 JSON")
    parser.add_argument("--output", required=True, help="验证结果 JSON")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data

    session = make_session()
    results = []
    for i, record in enumerate(items):
        if i % 5 == 0:
            print(f"验证进度 {i}/{len(items)}", file=sys.stderr)
        results.append(verify_record(session, record))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    verified = sum(1 for r in results if r.get("official_verified"))
    print(f"验证完成: {len(results)} 条, 官网确认数字键盘 {verified} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
