"""NodeManager 风控黑名单测试：模拟 mihomo API 验证节点切换逻辑。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import crawl_pconline as pcl


class FakeController:
    """模拟 mihomo external-controller：select 组切换 + 黑名单文件。"""

    def __init__(self, nodes: list[str], tmp_path: Path):
        self.nodes = nodes
        self.current = nodes[0] if nodes else None
        self.tmp = tmp_path
        self.switch_history: list[str] = []

    def handle(self, method: str, path: str, body: dict | None):
        if path == f"/proxies/PROXY" and method == "GET":
            return {"all": self.nodes, "now": self.current}
        if path == f"/proxies/PROXY" and method == "PUT":
            self.current = body["name"]
            self.switch_history.append(body["name"])
            return {}
        return {}


@pytest.fixture
def node_mgr(tmp_path):
    pcl._api_impl = None  # placeholder to avoid unused warning

    class FakeNodeManager(pcl.NodeManager):
        def __init__(self):
            self.controller = "fake"
            self.group = "PROXY"
            self.blacklist_path = tmp_path / "blacklist.json"
            self.blacklist = set()
            self.nodes = ["node-a", "node-b", "node-c"]
            self.current = "node-a"

        def _api(self, method, path, body=None):
            return self.fake.handle(method, path, body)

    mgr = FakeNodeManager()
    mgr.fake = FakeController(["node-a", "node-b", "node-c"], tmp_path)
    return mgr


def test_select_next_skips_blacklisted(node_mgr):
    node_mgr.mark_blocked("node-a")
    nxt = node_mgr.select_next()
    assert nxt == "node-b"
    node_mgr.mark_blocked("node-b")
    nxt2 = node_mgr.select_next()
    assert nxt2 == "node-c"


def test_select_next_all_blocked_returns_none(node_mgr):
    node_mgr.mark_blocked("node-a")
    node_mgr.mark_blocked("node-b")
    node_mgr.mark_blocked("node-c")
    node_mgr.current = "node-a"
    assert node_mgr.select_next() is None
    assert node_mgr.healthy_count() == 0


def test_blacklist_persists_across_instances(tmp_path):
    bl = tmp_path / "blacklist.json"
    bl.write_text(json.dumps(["node-a"]), encoding="utf-8")

    class Mgr(pcl.NodeManager):
        def __init__(self):
            self.controller = "fake"
            self.group = "PROXY"
            self.blacklist_path = bl
            self.blacklist = self._load_blacklist()
            self.nodes = ["node-a", "node-b"]
            self.current = None

    m = Mgr()
    assert "node-a" in m.blacklist


def test_fetch_retry_switches_node_on_blocked_page(tmp_path, monkeypatch):
    """模拟：node-a 返回风控页（1 行），node-b 正常（25 行）→ 自动切换成功。"""
    from bs4 import BeautifulSoup

    def make_soup(rows: int):
        cards = "".join(
            f'<li class="item-title"><a href="//product.pconline.com.cn/notebook/hp/{1000+i}.html">'
            f"惠普测试笔记本 {i} 型号（酷睿 i7）</a></li>"
            for i in range(rows)
        )
        return BeautifulSoup(f'<html><body><ul id="J_ProductList">{cards}</ul></body></html>', "html.parser")

    fetch_calls = []

    class Mgr(pcl.NodeManager):
        def __init__(self):
            self.controller = "fake"
            self.group = "PROXY"
            self.blacklist_path = tmp_path / "bl.json"
            self.blacklist = set()
            self.nodes = ["node-a", "node-b"]
            self.current = "node-a"
            self.state = {"node-a": 1, "node-b": 25}  # a 风控，b 正常

        def _api(self, method, path, body=None):
            if method == "PUT":
                self.current = body["name"]
            return {}

    mgr = Mgr()

    def fake_get_html(session, url, encoding=None, delay=0.0, timeout=25):
        fetch_calls.append(mgr.current)
        rows = mgr.state.get(mgr.current, 0)
        return make_soup(rows), url

    monkeypatch.setattr(pcl, "get_html", fake_get_html)
    monkeypatch.setattr(pcl, "parse_ranking_page", pcl.parse_ranking_page)

    items = pcl._fetch_ranking_with_node_retry(None, "http://x/s10.shtml", 1, mgr, 0.0)
    assert len(items) == 25  # 最终拿到 node-b 的 25 行
    assert "node-a" in mgr.blacklist  # node-a 被拉黑
    assert fetch_calls == ["node-a", "node-b"]  # 先 a 后 b


def test_fetch_retry_all_blocked_returns_empty(tmp_path, monkeypatch):
    from bs4 import BeautifulSoup

    soup1 = BeautifulSoup('<html><body><ul><li class="item-title"><a href="//x/1.html">a</a></li></ul></body></html>', "html.parser")

    class Mgr(pcl.NodeManager):
        def __init__(self):
            self.controller = "fake"
            self.group = "PROXY"
            self.blacklist_path = tmp_path / "bl.json"
            self.blacklist = set()
            self.nodes = ["node-a", "node-b"]
            self.current = "node-a"

        def _api(self, method, path, body=None):
            if method == "PUT":
                self.current = body["name"]
            return {}

    mgr = Mgr()
    monkeypatch.setattr(pcl, "get_html", lambda *a, **k: (soup1, "x"))

    items = pcl._fetch_ranking_with_node_retry(None, "http://x/s10.shtml", 1, mgr, 0.0)
    assert items == []  # 两个节点都只有 1 行 → 全拉黑 → 空
    assert mgr.healthy_count() == 0
