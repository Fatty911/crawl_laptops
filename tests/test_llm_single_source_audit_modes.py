from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "llm_single_source_audit.py"


def _module():
    spec = importlib.util.spec_from_file_location("laptops_audit_modes", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inputs(directory: Path) -> tuple[Path, Path]:
    data = directory / "data.json"
    report = directory / "report.json"
    data.write_text(json.dumps([{"brand": "A", "model": "M", "source": "JD"}]), encoding="utf-8")
    report.write_text(
        json.dumps(
            {
                "total": 1,
                "multi_count": 0,
                "multi_rate": 0,
                "single_count": 1,
                "single_rate": 100,
                "causes": {"series_only_single": 1, "trim_merge_gap": 0},
                "source_distribution": {"JD": 1},
                "detail": {"top_single_products": [{"product": "M", "source": "JD", "rows": 1}]},
            }
        ),
        encoding="utf-8",
    )
    return data, report


def test_prompt_and_agent_response_modes_are_local(tmp_path: Path):
    module = _module()
    data, report = _inputs(tmp_path)
    prompt = tmp_path / "prompt.md"
    output = tmp_path / "analysis.md"
    loaded_report, _rows, built = module._load_inputs(type("Args", (), {"data": str(data), "report": str(report)})())
    prompt.write_text(built, encoding="utf-8")
    response = tmp_path / "agent.md"
    response.write_text("# Agent result", encoding="utf-8")
    module.consume_agent_response(response, output)
    assert output.read_text(encoding="utf-8") == "# Agent result"
    assert all("KIMI_CODINGPLAN_API_KEY" not in model.get("env_keys", []) for model in module.AA_MODELS)
    assert loaded_report["single_count"] == 1


def test_deterministic_fallback_mode_is_available(tmp_path: Path):
    module = _module()
    _data, report_path = _inputs(tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    output = tmp_path / "fallback.md"
    module.write_deterministic_fallback(report, output)
    assert "确定性降级报告" in output.read_text(encoding="utf-8")


def test_agent_response_must_match_request_manifest(tmp_path: Path):
    module = _module()
    manifest_path = tmp_path / "manifest.json"
    manifest = module.write_request_manifest("stable prompt", manifest_path)
    response = tmp_path / "agent.md"
    response.write_text(
        f"REQUEST_ID: {manifest['request_id']}\n"
        f"PROMPT_SHA256: {manifest['prompt_sha256']}\n"
        "# bound result\n",
        encoding="utf-8",
    )
    output = tmp_path / "analysis.md"
    module.consume_agent_response(response, output, manifest_path)
    assert output.read_text(encoding="utf-8") == "# bound result\n"

    response.write_text(
        f"REQUEST_ID: {manifest['request_id']}\nPROMPT_SHA256: {'0' * 64}\n# bad\n",
        encoding="utf-8",
    )
    with __import__("pytest").raises(ValueError, match="not bound"):
        module.consume_agent_response(response, output, manifest_path)
