"""keyboard facts 集成测试：官网事实表在源证据缺失时补键盘证据。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import merge_data


def _facts() -> list[dict]:
    return [
        {
            "model": "惠普 (HP) 战66 八代 16英寸商务笔记本电脑",
            "series": "战66", "size_inch": "16英寸",
            "page_url": "https://www.hpstore.cn/hp-probook-4-g1ah-16-inch-notebook-pc-d89wqpc.html",
            "keyboard_text": "防泼溅背光数字键盘",
            "source": "hp-official",
            "numeric_keypad": True, "keyboard_backlight": True,
        },
        {
            "model": "惠普 (HP) 战66 八代 14英寸商务笔记本电脑",
            "series": "战66", "size_inch": "14英寸",
            "page_url": "https://www.hpstore.cn/hp-probook-4-g1a-14-inch-notebook-ai-pc-d89wlpc.html",
            "keyboard_text": "防泼溅背光键盘",
            "source": "hp-official",
            "numeric_keypad": None, "keyboard_backlight": True,
        },
        {
            "model": "惠普 (HP) HyperX 暗影精灵PRO 15.3英寸游戏笔记本电脑",
            "series": "暗影精灵PRO", "size_inch": "15.3英寸",
            "page_url": "https://www.hpstore.cn/hyperx-omen-15-inch-gaming-laptop-pc-15-ga0150tx-dc2k4p.html",
            "keyboard_text": "带数字小键盘的全尺寸暗影黑键盘，单区背光",
            "source": "hp-official",
            "numeric_keypad": True, "keyboard_backlight": True,
        },
        {
            "model": "苍龙 16 Ultra - 机械革命",
            "series": "苍龙", "size_inch": "16英寸",
            "page_url": "https://www.mechrevo.com/cn/products/canglong16ultra",
            "keyboard_text": "独立数字小键盘",
            "source": "mechrevo-official",
            "numeric_keypad": True, "keyboard_backlight": None,
        },
        {
            "model": "惠普 (HP) HyperX 暗影精灵 PRO 16英寸游戏笔记本电脑",
            "series": "暗影精灵", "size_inch": "16英寸",
            "page_url": "https://www.hpstore.cn/hyperx-16-16-ap1026ax-dn8j7pa.html",
            "keyboard_text": "带数字小键盘的全尺寸暗影黑键盘，4 个区域点亮 RGB 背光",
            "source": "hp-official",
            "numeric_keypad": True, "keyboard_backlight": True,
        },
    ]


def test_keyboard_fact_for_exact_series_size():
    facts = _facts()
    # 精确系列+尺寸命中
    f = merge_data.keyboard_fact_for("惠普(HP)战66 八代 16英寸商务笔记本 i7-14650HX", facts)
    assert f is not None and f["numeric_keypad"] is True and f["keyboard_backlight"] is True
    # 14 英寸命中不同事实（数字键盘 None）
    f14 = merge_data.keyboard_fact_for("惠普(HP)战66 八代 14英寸笔记本", facts)
    assert f14 is not None and f14["numeric_keypad"] is None and f14["keyboard_backlight"] is True
    # 暗影精灵 PRO
    f_omen = merge_data.keyboard_fact_for("惠普HyperX 暗影精灵PRO 15.3英寸游戏本", facts)
    assert f_omen is not None and f_omen["numeric_keypad"] is True


def test_keyboard_fact_for_suffix_size_form_and_normalized_series():
    facts = _facts()
    # 暗影精灵 Pro 16酷睿版（标题无"英寸"字样，系列带空格+后缀）→ 官网 16 英寸事实
    f = merge_data.keyboard_fact_for(
        "惠普HyperX 暗影精灵 Pro 16酷睿版 (Ultra7 270HX Plus/16GB/1TB/RTX5060)", facts
    )
    assert f is not None and f["numeric_keypad"] is True and f["keyboard_backlight"] is True
    # 机械革命苍龙 16 Ultra（"16 Ultra" 尺寸写法）
    f2 = merge_data.keyboard_fact_for("机械革命苍龙 16 Ultra", facts)
    assert f2 is not None and f2["numeric_keypad"] is True
    # CPU 型号数字不应被误判为尺寸（Ultra7 270HX 不是尺寸）
    f3 = merge_data.keyboard_fact_for("惠普(HP)战66 八代 17英寸笔记本", facts)
    assert f3 is None


def test_keyboard_fact_for_size_mismatch_returns_none():
    facts = _facts()
    # 同系列不同尺寸（17 英寸无事实）→ None
    f = merge_data.keyboard_fact_for("惠普(HP)战66 八代 17英寸笔记本", facts)
    assert f is None
    # 无系列命中
    f2 = merge_data.keyboard_fact_for("联想拯救者R9000P 2025", facts)
    assert f2 is None


def test_apply_keyboard_facts_fills_missing_evidence():
    record = {
        "title": "惠普(HP)战66 八代 16英寸商务笔记本 i7-14650HX",
        "numeric_keypad": None,
        "keyboard_backlight": None,
        "evidence": {"cpu": "i7-14650HX"},
    }
    out = merge_data.apply_keyboard_facts(record, facts=_facts())
    assert out["numeric_keypad"] is True
    assert out["keyboard_backlight"] is True
    assert "numeric_keypad_fact" in out["evidence"]
    assert "numeric_keypad_fact_url" in out["evidence"]
    assert out["keyboard_fact_sources"] == ["hp-official"]


def test_apply_keyboard_facts_does_not_override_source_evidence():
    record = {
        "title": "惠普(HP)战66 八代 16英寸商务笔记本",
        "numeric_keypad": False,  # 源站证据明确无
        "keyboard_backlight": True,
        "evidence": {"numeric_keypad": "列表页规格无数字键盘"},
    }
    out = merge_data.apply_keyboard_facts(record, facts=_facts())
    assert out["numeric_keypad"] is False  # 不被官网 True 覆盖
    assert "numeric_keypad_fact" not in out["evidence"]


def test_apply_keyboard_facts_no_facts_file():
    record = {"title": "任意型号", "numeric_keypad": None, "keyboard_backlight": None}
    # 事实文件不存在时返回空列表，不阻断
    out = merge_data.apply_keyboard_facts(record, facts=[])
    assert out["numeric_keypad"] is None
