from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from scripts.download_latest_artifact import extract_archive


def test_extract_archive_preserves_nested_raw_files(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("raw_html/123.html", "<html>raw</html>")
        archive.writestr("raw/zol/latest.json", '{"items": []}')

    count = extract_archive(payload.getvalue(), tmp_path / "out")

    assert count == 2
    assert (tmp_path / "out/raw_html/123.html").read_text() == "<html>raw</html>"
    assert (tmp_path / "out/raw/zol/latest.json").read_text() == '{"items": []}'


def test_extract_archive_rejects_path_traversal(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../escape.txt", "no")

    with pytest.raises(RuntimeError, match="unsafe artifact path"):
        extract_archive(payload.getvalue(), tmp_path / "out")
