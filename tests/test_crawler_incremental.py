"""Long-run incremental crawl mode for ZOL, JD and PConline (cursor + resume)."""

from bs4 import BeautifulSoup

import scripts.crawl_jd as jd
import scripts.crawl_pconline as pconline
import scripts.crawl_zol as zol
from scripts.crawl_runtime import Progress


def make_ranking_html(titles):
    cards = "".join(
        f'''<li data-follow-id="p{index}">
          <a class="pic" href="/notebook/index{index}.shtml"></a>
          <h3><span class="title-black">
            <a href="/notebook/index{index}.shtml" title="{title}">{title}</a>
          </span></h3>
          <b class="price-type">6999</b>
        </li>'''
        for index, title in enumerate(titles, start=1)
    )
    return BeautifulSoup(
        f'<html><body><ul id="J_PicMode">{cards}</ul></body></html>', "html.parser"
    )


def test_zol_incremental_scan_and_resume(tmp_path, monkeypatch):
    pages = {
        1: make_ranking_html(["机械革命极光X i7-13700HX 游戏本", "联想拯救者Y7000 2025 游戏本"]),
        2: make_ranking_html([]),
    }
    fetched = []

    def fake_get_html(session, url, encoding=None, delay=0.0, timeout=25):
        page = int(url.rstrip(".html").rsplit("_", 1)[-1])
        fetched.append(page)
        return pages[page], url

    monkeypatch.setattr(zol, "get_html", fake_get_html)
    monkeypatch.setattr(zol, "enrich_item", lambda session, item, delay: dict(item))

    output = tmp_path / "latest.json"
    progress_dir = tmp_path / "state"

    exit_code = zol.crawl_incremental(
        str(output), str(progress_dir), 0.0, min_records=1, time_limit=0, max_pages=0
    )

    assert exit_code == 0
    assert output.exists()
    progress = Progress.load(progress_dir)
    assert progress.scan_complete is True
    assert progress.total_items == 2

    # A resumed run after completion must restart the scan: the ranking
    # changes daily, so a completed cursor is stale and must not be reused.
    exit_code = zol.crawl_incremental(
        str(output), str(progress_dir), 0.0, min_records=1, time_limit=0, max_pages=0
    )
    assert exit_code == 0
    assert fetched == [1, 2, 1, 2]
    progress = Progress.load(progress_dir)
    assert progress.scan_complete is True


def test_zol_incremental_respects_time_budget(tmp_path, monkeypatch):
    pages = {page: make_ranking_html([f"型号{page}-{i} 游戏本" for i in range(3)]) for page in range(1, 40)}

    def fake_get_html(session, url, encoding=None, delay=0.0, timeout=25):
        page = int(url.rstrip(".html").rsplit("_", 1)[-1])
        return pages[page], url

    monkeypatch.setattr(zol, "get_html", fake_get_html)
    monkeypatch.setattr(zol, "enrich_item", lambda session, item, delay: dict(item))

    output = tmp_path / "latest.json"
    progress_dir = tmp_path / "state"
    exit_code = zol.crawl_incremental(
        str(output), str(progress_dir), 0.0, min_records=50, time_limit=0.001, max_pages=0
    )

    assert exit_code == 10
    progress = Progress.load(progress_dir)
    assert progress.scan_complete is False
    assert progress.current_page >= 1


def test_zol_incremental_fake_pagination_guard(tmp_path, monkeypatch):
    same_page = make_ranking_html(["机械革命极光X i7-13700HX 游戏本"])
    monkeypatch.setattr(zol, "get_html", lambda session, url, encoding=None, delay=0.0, timeout=25: (same_page, url))
    monkeypatch.setattr(zol, "enrich_item", lambda session, item, delay: dict(item))

    output = tmp_path / "latest.json"
    progress_dir = tmp_path / "state"
    exit_code = zol.crawl_incremental(
        str(output), str(progress_dir), 0.0, min_records=1, time_limit=0, max_pages=50
    )

    assert exit_code == 0
    progress = Progress.load(progress_dir)
    assert progress.scan_complete is True
    assert progress.total_items == 1


def test_jd_incremental_risk_page_preserves_progress(tmp_path, monkeypatch):
    ranking = BeautifulSoup(
        '''<html><body><ul>
        <li class="sku-detail">
          <div class="p-price" data-skuid="20001"><strong>8999</strong></div>
          <div class="p-name"><a href="https://item.jd.com/20001.html"
            title="机械革命极光X i7-13700HX 背光键盘 数字小键盘">极光X</a></div>
        </li>
        </ul></body></html>''',
        "html.parser",
    )
    risk = BeautifulSoup("<html><head><title>京东安全</title></head></html>", "html.parser")
    calls = {"n": 0}

    def fake_get_html(session, url, encoding=None, delay=0.0, timeout=25):
        calls["n"] += 1
        if calls["n"] == 1:
            return ranking, "https://www.jd.com/hotitem/p1"
        return risk, "https://www.jd.com/hotitem/p2"

    monkeypatch.setattr(jd, "get_html", fake_get_html)
    monkeypatch.setattr(jd, "enrich_item", lambda session, item, delay, detail_delay=None: dict(item))

    output = tmp_path / "latest.json"
    progress_dir = tmp_path / "state"
    exit_code = jd.crawl_incremental(
        str(output), str(progress_dir), 0.0, min_records=1, time_limit=0, max_pages=5
    )

    assert exit_code == 10
    progress = Progress.load(progress_dir)
    assert progress.total_items == 1
    assert progress.scan_complete is False


def test_jd_incremental_detail_risk_breaks_enrichment_loop(tmp_path, monkeypatch):
    ranking = BeautifulSoup(
        '''<html><body><ul>
        <li class="sku-detail">
          <div class="p-price" data-skuid="30001"><strong>8999</strong></div>
          <div class="p-name"><a href="https://item.jd.com/30001.html"
            title="机械革命极光X i7-13700HX">极光X</a></div>
        </li>
        <li class="sku-detail">
          <div class="p-price" data-skuid="30002"><strong>7999</strong></div>
          <div class="p-name"><a href="https://item.jd.com/30002.html"
            title="联想拯救者Y7000 i7-14650HX">Y7000</a></div>
        </li>
        </ul></body></html>''',
        "html.parser",
    )

    def fake_get_html(session, url, encoding=None, delay=0.0, timeout=25):
        return ranking, "https://www.jd.com/hotitem/p1"

    def fake_enrich(session, item, delay, detail_delay=None):
        record = dict(item)
        record["crawl_warning"] = "detail_risk_verification"
        return record

    monkeypatch.setattr(jd, "get_html", fake_get_html)
    monkeypatch.setattr(jd, "enrich_item", fake_enrich)

    output = tmp_path / "latest.json"
    progress_dir = tmp_path / "state"
    exit_code = jd.crawl_incremental(
        str(output), str(progress_dir), 0.0, min_records=1, time_limit=0, max_pages=1
    )

    assert exit_code == 10
    progress = Progress.load(progress_dir)
    # Only the first item was attempted before the risk breaker fired, and
    # risk-verified items stay retryable: they never enter processed_ids.
    assert len(progress.processed_ids) == 0
    assert progress.total_items == 2


def _pconline_ranking(titles):
    cards = "".join(
        f'<li data-id="{1000 + index}">'
        f'<a class="item-title-name" href="/notebook/{1000 + index}.shtml" title="{title}">{title}</a>'
        f'<span class="price">6999</span></li>'
        for index, title in enumerate(titles, start=1)
    )
    return BeautifulSoup(f'<html><body><ul id="productList">{cards}</ul></body></html>', "html.parser")


def test_pconline_incremental_scan_and_resume(tmp_path, monkeypatch):
    # PConline pagination: page N -> ranking_url((N-1)*PAGE_SIZE) -> offset.
    pages = {
        0: _pconline_ranking(["机械革命极光X i7-13700HX 游戏本", "联想拯救者Y7000 2025 游戏本"]),
        25: _pconline_ranking([]),
    }
    fetched = []

    def fake_fetch(session, url, page, node_mgr, delay):
        if url.endswith("/notebook/s10.shtml"):
            offset = 0
        else:
            offset = int(url.rstrip("s10.shtml").rsplit("/", 1)[-1])
        fetched.append(offset)
        return pconline.parse_ranking_page(pages[offset], page), url

    monkeypatch.setattr(pconline, "_fetch_ranking_with_node_retry", fake_fetch)
    monkeypatch.setattr(pconline, "_mihomo_controller_ready", lambda: False)
    monkeypatch.setattr(pconline, "enrich_item", lambda session, item, delay: dict(item))

    output = tmp_path / "latest.json"
    progress_dir = tmp_path / "state"

    exit_code = pconline.crawl_incremental(
        str(output), str(progress_dir), 0.0, min_records=1, time_limit=0, max_pages=0
    )

    assert exit_code == 0
    assert output.exists()
    progress = Progress.load(progress_dir)
    assert progress.scan_complete is True
    assert progress.total_items == 2

    # A resumed run after completion must not fetch anything again.
    exit_code = pconline.crawl_incremental(
        str(output), str(progress_dir), 0.0, min_records=1, time_limit=0, max_pages=0
    )
    assert exit_code == 0
    assert fetched == [0, 25]


def test_pconline_incremental_fake_pagination_guard(tmp_path, monkeypatch):
    same_page = _pconline_ranking(["机械革命极光X i7-13700HX 游戏本"])
    monkeypatch.setattr(
        pconline, "_fetch_ranking_with_node_retry",
        lambda session, url, page, node_mgr, delay: (
            pconline.parse_ranking_page(same_page, page), url
        ),
    )
    monkeypatch.setattr(pconline, "_mihomo_controller_ready", lambda: False)
    monkeypatch.setattr(pconline, "enrich_item", lambda session, item, delay: dict(item))

    output = tmp_path / "latest.json"
    progress_dir = tmp_path / "state"
    exit_code = pconline.crawl_incremental(
        str(output), str(progress_dir), 0.0, min_records=1, time_limit=0, max_pages=50
    )

    assert exit_code == 0
    progress = Progress.load(progress_dir)
    assert progress.scan_complete is True
    assert progress.total_items == 1
