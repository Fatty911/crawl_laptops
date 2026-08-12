from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_plan_agent_boundary import _plan_key_matches


def test_ai_providers_metadata_only_is_exempt(tmp_path: Path) -> None:
    """ai_providers.py 只声明 key_env 元数据（无 os.getenv）时豁免；有读取则拦截。"""
    module_dir = tmp_path / "scripts"
    module_dir.mkdir(parents=True)
    target = module_dir / "ai_providers.py"

    # 纯元数据：豁免（validate_repository 逻辑）
    target.write_text(
        'PROVIDERS = [{"key_env": "VOLCENGINE_CODING_PLAN_API_KEY", "endpoint": "https://x"}]',
        encoding="utf-8",
    )
    matches = _plan_key_matches(target.read_text(encoding="utf-8"))
    assert len(matches) == 1

    # 有 os.getenv 读取 → 不能豁免
    target.write_text(
        'import os\nPROVIDERS = [{"key": os.getenv("VOLCENGINE_CODING_PLAN_API_KEY")}]',
        encoding="utf-8",
    )
    assert "os.getenv" in target.read_text(encoding="utf-8")
    assert _plan_key_matches(target.read_text(encoding="utf-8"))
