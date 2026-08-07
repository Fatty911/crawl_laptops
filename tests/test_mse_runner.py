"""mse_repair_runner 测试：JSON 提取 / 规则应用。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.mse_repair_runner import RULE_IMPLS, apply_rules, extract_json


def test_extract_json_plain():
    raw = '{"rules": [{"type": "strip_prefix", "tokens": ["酷睿"]}], "reasoning": "x"}'
    d = extract_json(raw)
    assert d["rules"][0]["type"] == "strip_prefix"


def test_extract_json_with_markdown_prefix():
    raw = '```json\n{"rules": [{"type": "normalize_case"}], "confidence": 0.8}\n```'
    d = extract_json(raw)
    assert d["rules"][0]["type"] == "normalize_case"


def test_extract_json_no_brace():
    assert extract_json("nothing here") == {}


def test_apply_rules_inserts_code(tmp_path, monkeypatch):
    from scripts import mse_repair_runner as m
    src = '''def canonical_model_family(record):
    text = "something"
    family = _identity_text(text)
    return family or _identity_text(text)
'''
    target = tmp_path / "merge_data.py"
    target.write_text(src, encoding="utf-8")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    ok = apply_rules([{"type": "strip_prefix"}, {"type": "strip_suffix"}])
    assert ok
    out = target.read_text(encoding="utf-8")
    assert "MSE 增强" in out
    assert "酷睿" in out
    assert "re.sub" in out
    assert out.count("return family or _identity_text(text)") == 1


def test_apply_rules_idempotent(tmp_path, monkeypatch):
    from scripts import mse_repair_runner as m
    src = "def canonical_model_family(record):\n    family = _identity_text(text)\n    return family or _identity_text(text)\n"
    target = tmp_path / "merge_data.py"
    target.write_text(src, encoding="utf-8")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    assert apply_rules([{"type": "normalize_case"}]) is True
    # 第二次调用应跳过（marker 已存在）
    assert apply_rules([{"type": "normalize_case"}]) is True
    assert target.read_text(encoding="utf-8").count("MSE 增强") == 1


def test_apply_rules_no_anchor(tmp_path, monkeypatch):
    from scripts import mse_repair_runner as m
    target = tmp_path / "merge_data.py"
    target.write_text("def x(): pass\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    assert apply_rules([{"type": "normalize_case"}]) is False


def test_rule_impls_cover_all_types():
    assert "strip_prefix" in RULE_IMPLS
    assert "strip_suffix" in RULE_IMPLS
    assert "normalize_case" in RULE_IMPLS
