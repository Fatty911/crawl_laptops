"""Long-run crawl runtime: cursor, budget, pacing, incremental merge."""

import time

from scripts.crawl_runtime import (
    Budget,
    Progress,
    human_delay,
    item_key,
    merge_new_items,
    read_jsonl,
    rewrite_jsonl,
)


def test_progress_round_trip(tmp_path):
    progress = Progress(current_page=7, scan_complete=True, processed_ids=["1", "2"], total_items=42)
    progress.save(tmp_path)
    loaded = Progress.load(tmp_path)
    assert loaded.current_page == 7
    assert loaded.scan_complete is True
    assert loaded.processed_ids == ["1", "2"]
    assert loaded.total_items == 42


def test_progress_load_is_forgiving(tmp_path):
    (tmp_path / "progress.json").write_text("{broken json", encoding="utf-8")
    loaded = Progress.load(tmp_path)
    assert loaded.current_page == 1
    assert loaded.scan_complete is False
    assert Progress.load(tmp_path / "missing-dir").processed_ids == []


def test_budget_expiry_and_disabled():
    disabled = Budget(0)
    assert not disabled.expired()
    assert disabled.remaining() == float("inf")
    expired = Budget(0.001)
    time.sleep(0.01)
    assert expired.expired()
    assert expired.remaining() == 0.0


def test_human_delay_env_override(monkeypatch):
    monkeypatch.setenv("CRAWL_MIN_DELAY_SECONDS", "8")
    monkeypatch.setenv("CRAWL_MAX_DELAY_SECONDS", "20")
    for _ in range(20):
        assert 8 <= human_delay(0.25) <= 20
    monkeypatch.setenv("CRAWL_MIN_DELAY_SECONDS", "")
    monkeypatch.setenv("CRAWL_MAX_DELAY_SECONDS", "")
    assert human_delay(0.25) == 0.25


def test_merge_new_items_deduplicates():
    existing = [{"source_product_id": "a"}]
    merged, added = merge_new_items(
        existing,
        [
            {"source_product_id": "a"},
            {"source_product_id": "b"},
            {"source_product_id": "b"},
        ],
        item_key,
    )
    assert added == 1
    assert [item["source_product_id"] for item in merged] == ["a", "b"]


def test_read_jsonl_skips_corrupt_lines(tmp_path):
    path = tmp_path / "items.jsonl"
    path.write_text('{"a": 1}\nnot json\n\n{"b": 2}\n', encoding="utf-8")
    assert read_jsonl(path) == [{"a": 1}, {"b": 2}]
    rewrite_jsonl(path, [{"c": 3}])
    assert read_jsonl(path) == [{"c": 3}]
