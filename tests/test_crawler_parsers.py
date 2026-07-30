from bs4 import BeautifulSoup

from scripts.crawler_utils import make_session, parse_battery_wh
from scripts.crawl_jd import parse_search_page, sales_url, title_spec_fields
from scripts.crawl_zol import parse_ranking_page


def soup(fragment):
    return BeautifulSoup(fragment, "html.parser")


def test_zol_real_pic_mode_dom_is_parsed():
    html = soup(
        """
        <ul id="J_PicMode">
          <li data-follow-id="p2165921">
            <a class="pic" href="/notebook/index2165921.shtml"></a>
            <h3><span class="title-black">
              <a href="/notebook/index2165921.shtml"
                 title="惠普星Book Pro Air 14(Ultra 5 225H/16GB/512GB)">
                惠普星Book Pro Air 14
              </a>
            </span></h3>
            <b class="price-type">6998</b>
            <div class="rank-row"><a>热门排行第<span>1</span>名</a></div>
          </li>
        </ul>
        """
    )

    rows = parse_ranking_page(html, 1)

    assert len(rows) == 1
    assert rows[0]["source_product_id"] == "2165921"
    assert rows[0]["source_rank"] == 1
    assert rows[0]["price"] == 6998
    assert rows[0]["source_url"].endswith("/notebook/index2165921.shtml")
    assert parse_ranking_page(html, 2)[0]["source_rank"] == 49


def test_jd_real_hotitem_dom_is_parsed():
    html = soup(
        """
        <ul class="details-ul">
          <li class="sku-detail cps-wrap no-slave-ware">
            <div class="pad-sku">
              <div class="price p-price" data-skuid="100329464752">
                <strong>8999.00</strong>
              </div>
              <div class="p-name">
                <a href="https://item.jd.com/100329464752.html"
                   title="机械革命极光X 16英寸 i7-13700HX 16G 1T RTX5060 背光键盘 数字小键盘">
                  机械革命极光X
                </a>
              </div>
              <div class="p-merchant">京东自营</div>
            </div>
          </li>
        </ul>
        """
    )

    rows = parse_search_page(html, 2)

    assert len(rows) == 1
    assert rows[0]["source_product_id"] == "100329464752"
    assert rows[0]["source_rank"] == 61
    assert rows[0]["price"] == 8999
    assert rows[0]["merchant"] == "京东自营"


def test_jd_sales_url_and_title_fallback_fields():
    assert "sort_type=sort_totalsales15_desc" in sales_url(2)
    assert "page=2" in sales_url(2)

    fields = title_spec_fields(
        "机械革命极光X 16英寸 i7-13700HX 16G 1T RTX5060 背光键盘 数字小键盘"
    )

    assert fields["cpu"] == "i7-13700HX"
    assert fields["cpu_voltage_type"] == "high_performance"
    assert fields["gpu"] == "RTX5060"
    assert fields["screen_size"] == 16
    assert fields["memory_gb"] == 16
    assert fields["storage_gb"] == 1024
    assert fields["numeric_keypad"] is True
    assert fields["keyboard_backlight"] is True

    actual_title_fields = title_spec_fields(
        "机械革命极光X i7-12800HX/RTX4070 16G运行内存+1TB固态硬盘"
    )
    assert actual_title_fields["storage_gb"] == 1024


def test_battery_capacity_ignores_cell_count():
    assert parse_battery_wh("3芯锂电池，59Wh") == 59


def test_crawler_session_has_bounded_status_retry_and_backoff():
    retry = make_session().get_adapter("https://").max_retries

    assert retry.total == 3
    assert retry.backoff_factor == 0.5
    assert set(retry.status_forcelist) == {429, 500, 502, 503, 504}
    assert retry.allowed_methods == frozenset({"GET", "HEAD"})
