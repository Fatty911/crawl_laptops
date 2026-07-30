import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_report_counts_verified_desktop_cpu_exception_as_allowed(tmp_path):
    raw = tmp_path / "raw.json"
    merged = tmp_path / "merged.json"
    rejected = tmp_path / "rejected.json"
    output = tmp_path / "report.json"
    item = {
        "identity_key": "clevo-x170",
        "title": "CLEVO X170KM-G 游戏本准系统",
        "cpu_voltage_type": "desktop_performance",
        "numeric_keypad": True,
        "keyboard_backlight": True,
        "source": "ZOL",
        "atomic_source_names": ["ZOL"],
    }
    raw.write_text(json.dumps([item]), encoding="utf-8")
    merged.write_text(json.dumps({"items": [item]}), encoding="utf-8")
    rejected.write_text("[]", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "analysis" / "merge_evidence_report.py"),
            "--raw",
            str(raw),
            "--merged",
            str(merged),
            "--rejected",
            str(rejected),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["raw"][0]["source"] == "ZOL"
    assert report["raw"][0]["positive_evidence"]["allowed_cpu"] == 1
    assert report["raw"][0]["positive_evidence"]["desktop_cpu_exception"] == 1
