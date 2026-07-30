from scripts.merge_data import (
    atomic_sources,
    build_identity_key,
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
