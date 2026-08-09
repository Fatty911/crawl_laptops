"""crawl_machenike 测试：列表解析 / 系列解析 / 价格配对。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.crawl_machenike import (
    BASE_URL,
    LIST_URL,
    parse_list,
    parse_product,
    parse_series,
)


def _page(cards):
    body = ""
    for i, (title, price) in enumerate(cards):
        body += (
            f'<div class="card"><a href="{BASE_URL}/product/{100+i}.html">'
            f"{title}</a><span class=\"price\">{price}</span></div>"
        )
    return f"<html><body>{body}</body></html>"


def test_parse_list_extracts_product_links():
    html = _page([("机械师曙光16Pro 4090游戏本", "16999")])
    links = parse_list(html)
    assert len(links) == 1
    assert "/product/100.html" in links[0]


def test_parse_series_pairs_prices():
    html = _page(
        [
            ("机械师曙光16Pro 4090游戏本", "16999"),
            ("机械师曙光16Pro 4060游戏本", "9999"),
        ]
    )
    cards = parse_series(html, "")
    assert len(cards) == 2
    assert cards[0]["price"] == 16999.0
    assert cards[1]["price"] == 9999.0
    assert cards[0]["title"] == "机械师曙光16Pro 4090游戏本"


def test_parse_series_dedup():
    html = _page([("机械师曙光15游戏本", "6999"), ("机械师曙光15游戏本", "6999")])
    cards = parse_series(html, "")
    assert len(cards) == 1


def test_list_url():
    assert LIST_URL == "https://www.machenike.com/lists/1.html"


def test_is_notebook_filter():
    from scripts.crawl_machenike import is_notebook

    # 笔记本保留
    assert is_notebook("机械师曙光16Pro 4090游戏本")
    assert is_notebook("机械师星辰S15 3050")
    assert is_notebook("机械师F117-FPAR27P")
    assert is_notebook("机械师T58-V 11代i7游戏本")
    # 外设/台式机/配件剔除
    assert not is_notebook("机械师23.8英寸 电竞屏游戏显示器")
    assert not is_notebook("K31 87按键机械键盘")
    assert not is_notebook("机械师TWS真无线蓝牙耳机")
    assert not is_notebook("机械师未来战舰III代 游戏台式机")
    assert not is_notebook("机械师Mini GTR 迷你主机")
    assert not is_notebook("机械师曙光16Pro 水冷箱")
    assert not is_notebook("i7-10870H 8核处理器,仅供升级选项使用")
    assert not is_notebook("升级144Hz电竞屏")
    assert not is_notebook("机械师氮化镓充电器")
