"""JD source parity: marketing-title cleaning and cross-source identity merge."""

from scripts.crawl_jd import clean_jd_title_identity, parse_search_page
from scripts.crawler_utils import infer_brand
from scripts.merge_data import build_identity_key, canonical_model_family, merge_records


def jd_record(title, *, cpu="i7-14650HX", keypad=None, backlight=None):
    return {
        "title": title,
        "model": title,
        "model_identity": clean_jd_title_identity(title),
        "brand": infer_brand(title),
        "cpu": cpu,
        "numeric_keypad": keypad,
        "keyboard_backlight": backlight,
        "price": 6999.0,
        "source": "JD",
        "atomic_source_names": ["JD"],
        "source_url": "https://item.jd.com/100000000001.html",
        "source_rank": 3,
    }


def zol_record(title, *, cpu="i7-14650HX", keypad=True, backlight=True):
    return {
        "title": title,
        "model": title,
        "brand": infer_brand(title),
        "cpu": cpu,
        "numeric_keypad": keypad,
        "keyboard_backlight": backlight,
        "price": 7299.0,
        "source": "ZOL",
        "atomic_source_names": ["ZOL"],
        "source_url": "https://detail.zol.com.cn/notebook/index1.html",
        "source_rank": 11,
    }


def test_jd_title_identity_strips_brand_paren_config_and_category():
    cleaned = clean_jd_title_identity(
        "联想(Lenovo)拯救者Y7000 2025 电竞游戏笔记本 i7-14650HX RTX5060 16G 512G 2.5K 240Hz 黑色"
    )
    assert cleaned == "拯救者Y7000 2025"


def test_jd_title_identity_handles_generation_prefix_and_colorful_brand():
    cleaned = clean_jd_title_identity(
        "七彩虹(Colorful)iGame M16 Origo 13代酷睿i7-13650HX RTX4060 16G 512G"
    )
    assert cleaned == "iGame M16 Origo"


def test_jd_title_identity_promo_brackets_and_storage_units():
    cleaned = clean_jd_title_identity(
        "【国家补贴20%】惠普(HP)暗影精灵11 游戏本 i7-14650HX 16G 1TB RTX5060 白色"
    )
    assert cleaned == "暗影精灵11"


def test_jd_title_identity_falls_back_to_title_when_empty():
    title = "特殊商品"
    assert clean_jd_title_identity(title) == title


def test_jd_identity_merges_with_zol_catalog_identity():
    jd = jd_record("联想(Lenovo)拯救者Y7000 2025 i7-14650HX RTX5060 16G 512G 黑色")
    zol = zol_record("联想拯救者Y7000 2025(i7-14650HX/16GB/512GB)")
    assert canonical_model_family(jd) == canonical_model_family(zol)
    assert build_identity_key(jd) == build_identity_key(zol)
    merged, rejected = merge_records([jd, zol])
    assert rejected == []
    assert len(merged) == 1
    assert merged[0]["atomic_source_names"] == ["JD", "ZOL"]
    assert merged[0]["source_count"] == 2
    # ZOL keyboard evidence complements the JD row, making it publishable.
    assert merged[0]["publish_eligible"] is True


def test_jd_single_source_without_keyboard_evidence_is_rejected_honestly():
    jd = jd_record("联想(Lenovo)拯救者Y9000P 2025 i7-14650HX RTX5060 16G 1TB")
    merged, rejected = merge_records([jd])
    assert merged == []
    assert rejected[0]["reasons"] == [
        "numeric_keypad_not_confirmed",
        "keyboard_backlight_not_confirmed",
    ]


def test_jd_neighboring_model_families_stay_distinct_after_cleaning():
    first = jd_record("联想(Lenovo)拯救者Y7000 i7-14650HX 游戏本")
    second = jd_record("联想(Lenovo)拯救者Y9000P i7-14650HX 游戏本")
    assert build_identity_key(first) != build_identity_key(second)


def test_merge_jd_brand_paren_fallback_without_model_identity():
    record = {
        "title": "惠普(HP)暗影精灵11 i7-14650HX 游戏本",
        "model": "惠普(HP)暗影精灵11 i7-14650HX 游戏本",
        "brand": "惠普",
        "cpu": "i7-14650HX",
        "source": "JD",
        "atomic_source_names": ["JD"],
    }
    assert canonical_model_family(record) == "暗影精灵11"


def test_parse_search_page_writes_model_identity():
    html_doc = """
    <html><body><ul>
    <li class="sku-detail">
      <div class="pad-sku">
        <div class="p-name"><a href="//item.jd.com/100086.html"
          title="联想(Lenovo)拯救者Y7000 2025 i7-14650HX RTX5060 16G 512G">联想(Lenovo)拯救者Y7000 2025 i7-14650HX RTX5060 16G 512G</a></div>
        <div class="p-price" data-skuid="100086"><strong>￥6999.00</strong></div>
      </div>
    </li>
    </ul></body></html>
    """
    from bs4 import BeautifulSoup

    items = parse_search_page(BeautifulSoup(html_doc, "html.parser"), 1)
    assert len(items) == 1
    assert items[0]["model_identity"] == "拯救者Y7000 2025"
    assert items[0]["title"].startswith("联想(Lenovo)")
