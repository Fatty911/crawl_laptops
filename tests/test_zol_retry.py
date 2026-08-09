"""crawl_zol 页面抓取重试测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.crawl_zol import MAX_PAGE_FETCH_RETRIES, PAGE_RETRY_BACKOFF


def test_retry_constants():
    assert MAX_PAGE_FETCH_RETRIES == 3
    assert PAGE_RETRY_BACKOFF >= 3


def test_retry_backoff_sequence():
    # 退避序列：5s, 10s, 20s（指数）
    waits = [PAGE_RETRY_BACKOFF * (2 ** (i - 1)) for i in range(1, MAX_PAGE_FETCH_RETRIES + 1)]
    assert waits == [5, 10, 20]
