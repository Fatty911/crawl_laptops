import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_prepare_pages_writes_manifest_with_release_provenance(tmp_path):
    payload = {
        "schema_version": 1,
        "generated_at": "2026-07-30T01:02:03+00:00",
        "count": 1,
        "sources": ["ZOL"],
        "items": [
            {
                "identity_key": "fixture",
                "title": "测试游戏本",
                "cpu": "Intel Core i7-13700H",
                "cpu_voltage_type": "standard_performance",
                "numeric_keypad": True,
                "keyboard_backlight": True,
                "source": "ZOL",
                "atomic_source_names": ["ZOL"],
                "source_count": 1,
            }
        ],
    }
    input_path = tmp_path / "laptops-latest.json"
    config_path = tmp_path / "filter.json"
    docs_dir = tmp_path / "docs"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    config_path.write_text("{}", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "prepare_pages_payload.py"),
            "--input",
            str(input_path),
            "--config",
            str(config_path),
            "--docs-dir",
            str(docs_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((docs_dir / "data" / "manifest.json").read_text())
    assert manifest == {
        "schemaVersion": 1,
        "updatedAt": "2026-07-30T01:02:03+00:00",
        "rowCount": 1,
        "sourceCounts": {"ZOL": 1},
        "files": {
            "latestJson": "data/latest.json",
            "filterConditions": "data/filter_conditions.json",
        },
    }


def test_pages_policy_and_labels_describe_narrow_desktop_cpu_exception():
    config = json.loads(
        (ROOT / "config" / "filter_conditions.json").read_text(encoding="utf-8")
    )
    allowed = config["forced"]["cpu_voltage_type"]["allowed_values"]
    app = (ROOT / "docs" / "app.js").read_text(encoding="utf-8")

    assert allowed == [
        "standard_performance",
        "high_performance",
        "desktop_performance",
    ]
    assert "桌面级 CPU · 形态已核验" in app
    assert "桌面级 CPU 仅限形态证据例外" in app


def test_pages_workflow_reads_back_deployed_manifest():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["deploy"]["steps"]
    names = [step["name"] for step in steps]

    deploy_index = names.index("Deploy Pages")
    verify_index = names.index("Verify deployed manifest")
    verify = steps[verify_index]

    assert deploy_index < verify_index
    assert "${{ steps.deployment.outputs.page_url }}data/manifest.json" in verify["env"][
        "MANIFEST_URL"
    ]
    assert "docs/data/manifest.json" in verify["run"]
