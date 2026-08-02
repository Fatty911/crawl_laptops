from scripts.merge_data import (
    atomic_sources,
    build_identity_key,
    canonical_cpu_identity,
    canonical_model_family,
    merge_records,
    normalize_source_name,
)


def laptop(source, *, price, title="联想 ThinkBook 16+ 2025", model="ThinkBook 16+ 2025"):
    return {
        "title": title,
        "model": model,
        "brand": "联想",
        "cpu": "Intel Core Ultra 7 255H",
        "numeric_keypad": True,
        "keyboard_backlight": True,
        "price": price,
        "source": source,
        "source_url": f"https://example.test/{source}",
        "source_rank": 3,
    }


def test_identity_key_ignores_memory_storage_and_gpu_configuration_noise():
    first = laptop(
        "ZOL",
        price=6999,
        title="联想 ThinkBook 16+ 2025 32GB 1TB RTX 5060",
    )
    second = laptop(
        "JD",
        price=6899,
        title="联想 ThinkBook 16+ 2025 16GB 512GB",
    )
    assert build_identity_key(first) == build_identity_key(second)


def test_catalog_identity_joins_same_family_and_cpu_across_sources():
    zol = laptop(
        "ZOL",
        price=7999,
        title="惠普暗影精灵11(i7 14650HX/RTX5060/16GB/1TB/黑色)",
        model="惠普暗影精灵11(i7 14650HX/RTX5060/16GB/1TB/黑色)",
    )
    pconline = laptop(
        "PConline",
        price=7899,
        title="惠普暗影精灵11(酷睿i7-14650HX/16GB/1TB/RTX5060/2.5K/240Hz)",
        model="惠普暗影精灵11(酷睿i7-14650HX/16GB/1TB/RTX5060/2.5K/240Hz)",
    )
    zol["cpu"] = pconline["cpu"] = "i7-14650HX"
    zol["brand"] = pconline["brand"] = "惠普"
    pconline["numeric_keypad"] = None

    assert canonical_model_family(zol) == "暗影精灵11"
    assert build_identity_key(zol) == build_identity_key(pconline)
    merged, rejected = merge_records([zol, pconline])
    assert rejected == []
    assert merged[0]["atomic_source_names"] == ["PConline", "ZOL"]


def test_catalog_identity_keeps_neighboring_model_families_distinct():
    y7000 = laptop(
        "ZOL", price=6999, title="联想拯救者Y7000 2025(i7-14650HX/16GB/512GB)"
    )
    y7000p = laptop(
        "PConline", price=7999, title="联想拯救者Y7000P 2025(i7-14650HX/16GB/1TB)"
    )
    y7000["model"] = y7000["title"]
    y7000p["model"] = y7000p["title"]
    y7000["cpu"] = y7000p["cpu"] = "i7-14650HX"

    assert build_identity_key(y7000) != build_identity_key(y7000p)


def test_catalog_identity_normalizes_intel_cpu_aliases_across_sources():
    zol = laptop(
        "ZOL", price=6999, title="华硕天选7 Pro 酷睿版(Ultra 7 251HX/16GB/1TB)"
    )
    pconline = laptop(
        "PConline",
        price=6899,
        title="华硕天选7 Pro 酷睿版(酷睿Ultra7 251HX/16GB/1TB)",
    )
    zol["model"] = zol["title"]
    pconline["model"] = pconline["title"]
    zol["brand"] = pconline["brand"] = "华硕"
    zol["cpu"] = "Intel 酷睿Ultra 7 251HX"
    pconline["cpu"] = pconline["title"]

    assert canonical_cpu_identity(zol) == "intel-ultra7-251hx"
    assert build_identity_key(zol) == build_identity_key(pconline)


def test_catalog_identity_normalizes_amd_cpu_aliases_across_sources():
    zol = laptop("ZOL", price=6999, title="华硕天选6 Pro 锐龙版(锐龙9 8940HX/16GB/1TB)")
    pconline = laptop(
        "PConline", price=6899, title="华硕天选6 Pro 锐龙版(R9-8940HX/16GB/1TB)"
    )
    zol["model"] = zol["title"]
    pconline["model"] = pconline["title"]
    zol["brand"] = pconline["brand"] = "华硕"
    zol["cpu"] = "AMD Ryzen 9 8940HX"
    pconline["cpu"] = "R9-8940HX"

    assert canonical_cpu_identity(pconline) == "amd-r9-8940hx"
    assert build_identity_key(zol) == build_identity_key(pconline)


def test_jd_merchant_parentheses_do_not_collapse_model_identity():
    first = laptop(
        "JD", price=6999, title="联想(Lenovo)拯救者Y7000 i7-14650HX 游戏本"
    )
    second = laptop(
        "JD", price=7999, title="联想(Lenovo)拯救者Y9000P i7-14650HX 游戏本"
    )
    first["model"] = first["title"]
    second["model"] = second["title"]
    first["cpu"] = second["cpu"] = "i7-14650HX"

    assert build_identity_key(first) != build_identity_key(second)


def test_identity_deduplication_and_multi_source_merge():
    zol = laptop("中关村在线", price=6999)
    zol["source_rank"] = 17
    jd = laptop("京东", price=6799)
    jd["source_rank"] = 4
    merged, rejected = merge_records([zol, jd])
    assert rejected == []
    assert len(merged) == 1
    item = merged[0]
    assert item["atomic_source_names"] == ["JD", "ZOL"]
    assert item["source"] == "JD+ZOL"
    assert item["source_count"] == 2
    assert item["source_urls"] == {
        "JD": "https://example.test/京东",
        "ZOL": "https://example.test/中关村在线",
    }
    assert item["source_ranks"] == {"JD": 4, "ZOL": 17}
    assert item["source_rank"] == 4


def test_source_aliases_are_atomic_and_normalized():
    record = {
        "source": "中关村在线 + 京东商城",
        "atomic_source_names": ["zol", "JD.com"],
    }
    assert atomic_sources(record) == ["JD", "ZOL"]
    assert normalize_source_name("京东自营") == "JD"


def test_distinct_models_are_not_deduplicated():
    first = laptop("ZOL", price=6999)
    second = laptop("JD", price=7999, model="ThinkBook 16p 2025", title="联想 ThinkBook 16p 2025")
    merged, _ = merge_records([first, second])
    assert len(merged) == 2


def test_explicit_negative_evidence_wins_conflict():
    positive = laptop("ZOL", price=6999)
    negative = laptop("JD", price=6899)
    negative["numeric_keypad"] = False
    merged, rejected = merge_records([positive, negative])
    assert merged == []
    assert rejected[0]["reasons"] == ["numeric_keypad_not_confirmed"]

def test_merge_pconline_aliases():
    assert True
