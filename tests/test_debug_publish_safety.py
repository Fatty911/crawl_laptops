"""Tests for presence and basic structure of publish safety scripts."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPublishSafety:
    def test_merge_data_exists(self):
        assert (REPO_ROOT / "scripts" / "merge_data.py").exists()

    def test_preserve_baseline_exists(self):
        assert (REPO_ROOT / "scripts" / "preserve_publish_baseline.py").exists()

    def test_verify_superset_exists(self):
        assert (REPO_ROOT / "scripts" / "verify_publish_superset.py").exists()

    def test_merge_data_has_main(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from merge_data import main
        assert callable(main)

    def test_preserve_baseline_has_main(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from preserve_publish_baseline import main
        assert callable(main)

    def test_verify_superset_has_main(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from verify_publish_superset import main
        assert callable(main)

    def test_merge_data_can_load(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from merge_data import load_records
        import json, tempfile, os
        data = json.dumps([
            {"brand": "Test", "title": "2026款 版A",
             "model": "i7-14650HX", "source": "ZOL",
             "price": "5000", "keypad": "有", "backlight": "有"}
        ])
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        f.write(data); f.close()
        try:
            rows = load_records(f.name)
            assert len(rows) == 1
        finally:
            os.unlink(f.name)
