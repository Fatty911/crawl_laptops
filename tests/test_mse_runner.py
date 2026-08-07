"""mse_repair_runner 测试：JSON 提取 / 评审解析。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.mse_repair_runner import extract_json


def test_extract_json_plain():
    raw = '{"patch": "diff", "reasoning": "x", "confidence": 0.9}'
    assert extract_json(raw) == {"patch": "diff", "reasoning": "x", "confidence": 0.9}


def test_extract_json_with_markdown_prefix():
    raw = 'opencode output:\n```json\n{"patch": "p1", "reasoning": "r", "confidence": 0.8}\n```\n'
    d = extract_json(raw)
    assert d.get("patch") == "p1"
    assert d.get("confidence") == 0.8


def test_extract_json_nested():
    raw = 'before {"patch": {"file": "a.py", "body": "x"}, "reasoning": "r"} after'
    d = extract_json(raw)
    assert d["patch"]["file"] == "a.py"


def test_extract_json_no_brace():
    assert extract_json("no json here") == {}
