"""PConline 全量库（catalog s1）测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.crawl_pconline import page_size, ranking_url


def test_ranking_url_default_hotlist():
    assert ranking_url(0) == "https://product.pconline.com.cn/notebook/s10.shtml"
    assert ranking_url(25) == "https://product.pconline.com.cn/notebook/25s10.shtml"


def test_ranking_url_catalog():
    assert ranking_url(0, catalog=True) == "https://product.pconline.com.cn/notebook/s1.shtml"
    assert ranking_url(113, catalog=True) == "https://product.pconline.com.cn/notebook/113s1.shtml"
    assert ranking_url(226, catalog=True) == "https://product.pconline.com.cn/notebook/226s1.shtml"


def test_page_size():
    assert page_size(False) == 25  # 热门榜
    assert page_size(True) == 25  # 全量库（offset 步长 25，每页 25 个 series）
