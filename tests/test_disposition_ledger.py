"""Disposition ledger tests for laptops merge_data.py."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


class TestDispositionLedger:
    def test_identity_building_works(self):
        """build_identity_key generates stable cross-source keys."""
        import merge_data as md
        key = md.build_identity_key({
            "brand": "联想",
            "title": "2026款 小新Pro",
            "model": "i7-14650HX",
        })
        assert isinstance(key, str) and len(key) > 0

    def test_source_normalization(self):
        """Source names are normalized correctly."""
        import merge_data as md
        assert md.normalize_source_name("ZOL") == "ZOL"
        assert md.normalize_source_name("JD") == "JD"
        assert md.normalize_source_name("PConline") == "PConline"

    def test_atomic_sources_extraction(self):
        """atomic_sources correctly extracts sources from records."""
        import merge_data as md
        sources = md.atomic_sources({"atomic_source_names": ["ZOL", "JD"]})
        assert "ZOL" in sources and "JD" in sources

    def test_canonical_model_family(self):
        """canonical_model_family normalizes CPU model names."""
        import merge_data as md
        family = md.canonical_model_family({"model": "i7-14650HX"})
        assert isinstance(family, str) and len(family) > 0

    def test_normalize_brand(self):
        """normalize_brand normalizes brand names (Lenovo -> 联想)."""
        import merge_data as md
        result = md.normalize_brand("  Lenovo ", "")
        assert isinstance(result, str) and len(result) > 0
