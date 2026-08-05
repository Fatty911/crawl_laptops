"""Tests for scripts/restore_pconline_cache.py (laptops adapter)."""

import importlib.util
import io
import json
import zipfile
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "restore_pconline_cache.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pconline_cache_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artifact(artifact_id, created_at, *, expired=False, branch="main", run_id=1):
    return {
        "id": artifact_id,
        "name": f"pconline-data-{run_id}-1",
        "created_at": created_at,
        "expired": expired,
        "workflow_run": {"id": run_id, "head_branch": branch},
    }


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, value in files.items():
            if not isinstance(value, bytes):
                value = json.dumps(value, ensure_ascii=False).encode("utf-8")
            bundle.writestr(name, value)
    return buffer.getvalue()


def valid_laptop(laptop_id):
    return {
        "phone_id": str(laptop_id),
        "id": str(laptop_id),
        "型号": "2026款 小新Pro 14",
        "name": "2026款 小新Pro 14",
        "品牌": "联想",
        "source": "太平洋电脑网",
        "url": "https://product.pconline.com.cn/notebook/lenovo/12345.html",
        "产品链接": "https://product.pconline.com.cn/notebook/lenovo/12345.html",
        "上市时间": "2026-03",
        "CPU型号": "Intel Core i7-14650HX",
        "内存容量": "16GB",
        "存储容量": "512GB SSD",
        "屏幕尺寸": "14英寸",
        "电池容量": "65Wh",
        "显卡型号": "NVIDIA GeForce RTX 4060",
    }


class TestRestorePconlineCache:
    def test_artifact_prefix_is_laptop(self):
        module = load_module()
        assert module.ARTIFACT_PREFIX == "pconline-data-"

    def test_valid_candidates_filters_expired_and_prefix(self):
        module = load_module()
        arts = [
            artifact(1, "2026-08-01T00:00:00Z", expired=True),
            artifact(2, "2026-08-01T01:00:00Z"),
            {"id": 3, "name": "pconline-phone-data-1-1", "created_at": "2026-08-01T02:00:00Z",
             "expired": False, "workflow_run": {"id": 1, "head_branch": "main"}},
        ]
        candidates = module._valid_candidates(arts, "main")
        assert len(candidates) == 1
        assert candidates[0]["id"] == 2

    def test_valid_candidates_sorts_by_created_at_desc(self):
        module = load_module()
        arts = [
            artifact(1, "2026-08-01T01:00:00Z"),
            artifact(2, "2026-07-31T00:00:00Z"),
            artifact(3, "2026-08-01T02:00:00Z"),
        ]
        candidates = module._valid_candidates(arts, "main")
        assert [c["id"] for c in candidates] == [3, 1, 2]

    def test_is_semantically_valid_record_accepts_good_record(self):
        module = load_module()
        laptop = valid_laptop("12345")
        assert module.is_semantically_valid_record(laptop, "12345") is True

    def test_is_semantically_valid_record_rejects_no_source(self):
        module = load_module()
        laptop = valid_laptop("12345")
        laptop["source"] = "ZOL"
        assert module.is_semantically_valid_record(laptop, "12345") is False

    def test_is_semantically_valid_record_rejects_wrong_id(self):
        module = load_module()
        laptop = valid_laptop("12345")
        assert module.is_semantically_valid_record(laptop, "99999") is False

    def test_is_semantically_valid_record_rejects_empty_brand(self):
        module = load_module()
        laptop = valid_laptop("12345")
        laptop["品牌"] = ""
        assert module.is_semantically_valid_record(laptop, "12345") is False

    def test_read_raw_files_accepts_valid_archive(self):
        module = load_module()
        laptop = valid_laptop("12345")
        raw = archive({"json/12345.json": laptop})
        result = module._read_raw_files(raw)
        assert "12345.json" in result

    def test_read_raw_files_rejects_unsafe_path(self):
        module = load_module()
        raw = archive({"json/../../../etc/passwd": "data"})
        with pytest.raises(module.InvalidCacheArtifact, match="unsafe"):
            module._read_raw_files(raw)

    def test_read_raw_files_rejects_non_json_suffix(self):
        module = load_module()
        laptop = valid_laptop("12345")
        raw = archive({"json/12345.txt": laptop})
        with pytest.raises(module.InvalidCacheArtifact, match="invalid"):
            module._read_raw_files(raw)

    def test_restore_latest_cache_returns_none_when_no_valid_artifact(self):
        module = load_module()
        arts = [artifact(1, "2026-08-01T00:00:00Z", expired=True)]
        result = module.restore_latest_cache(arts, lambda c: b"garbage", "/tmp/test",
                                             branch="main")
        assert result is None

    def test_replace_destination_creates_directory(self, tmp_path):
        module = load_module()
        dest = tmp_path / "pconline" / "json"
        raw_files = {"12345.json": json.dumps(valid_laptop("12345")).encode("utf-8")}
        module._replace_destination(raw_files, dest)
        assert (dest / "12345.json").exists()
