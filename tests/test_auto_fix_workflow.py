"""Tests for scripts/auto_fix_workflow.py (multi-provider auto-fix)."""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import auto_fix_workflow as afw


class TestProviderDiscovery:
    def test_free_only_discovery(self):
        """With free-only mode, only free providers with API_KEY env vars are discovered."""
        os.environ["NVIDIA_NIM_API_KEY"] = "test-key-12345"
        os.environ["ZEN_API_KEY"] = "test-zen-key-67890"
        os.environ["OPENROUTER_API_KEY"] = "test-or-key-11111"
        try:
            fixer = afw.WorkflowErrorFixer(mode="free-only")
            assert len(fixer.providers) == 3, f"expected 3 free providers, got {len(fixer.providers)}"
            prefixes = [p["prefix"] for p in fixer.providers]
            assert "NVIDIA_NIM" in prefixes
            assert "ZEN" in prefixes
            assert "OPENROUTER" in prefixes
        finally:
            del os.environ["NVIDIA_NIM_API_KEY"]
            del os.environ["ZEN_API_KEY"]
            del os.environ["OPENROUTER_API_KEY"]

    def test_paid_only_rejected_without_proof(self):
        """paid-only requires a preceding all_free_429 proof."""
        with pytest.raises(ValueError, match="paid-only requires"):
            afw.WorkflowErrorFixer(mode="paid-only", free_status="")

    def test_paid_only_accepted_with_proof(self):
        """paid-only is accepted when free_status=all_free_429."""
        fixer = afw.WorkflowErrorFixer(mode="paid-only", free_status="all_free_429")
        assert fixer.mode == "paid-only"

    def test_no_credentials_returns_no_providers(self):
        """Without any API_KEY env vars, no providers are discovered."""
        fixer = afw.WorkflowErrorFixer(mode="free-only")
        assert len(fixer.providers) == 0

    def test_is_plan_prefix_detection(self):
        assert afw.is_plan_prefix("KIMI_CODINGPLAN") is True
        assert afw.is_plan_prefix("VOLCENGINE_CODING_PLAN") is True
        assert afw.is_plan_prefix("NVIDIA_NIM") is False
        assert afw.is_plan_prefix("ZEN") is False


class TestFixError:
    def test_no_providers_returns_false(self):
        """fix_error returns False when no providers are available."""
        fixer = afw.WorkflowErrorFixer(mode="free-only")
        result = fixer.fix_error("some error output")
        assert result is False
        assert fixer.route_status == "no_credentials"

    def test_parse_json_strips_code_block(self):
        fixer = afw.WorkflowErrorFixer(mode="free-only")
        result = fixer._parse_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_direct(self):
        fixer = afw.WorkflowErrorFixer(mode="free-only")
        result = fixer._parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_invalid_returns_none(self):
        fixer = afw.WorkflowErrorFixer(mode="free-only")
        result = fixer._parse_json("not json at all")
        assert result is None


class TestProviderBaseUrls:
    def test_known_providers_have_base_urls(self):
        """All free providers must have a base URL."""
        for prefix in afw.FREE_PREFIXES:
            assert prefix in afw.PROVIDER_BASE_URLS, f"{prefix} missing base URL"

    def test_free_providers_have_default_models(self):
        """All free providers must have at least one default model."""
        for prefix in afw.FREE_PREFIXES:
            assert prefix in afw.PROVIDER_DEFAULT_MODELS, f"{prefix} missing default models"
            assert len(afw.PROVIDER_DEFAULT_MODELS[prefix]) > 0, f"{prefix} has empty model list"
