import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "codex_delivery_gate.py"
SPEC = importlib.util.spec_from_file_location("codex_delivery_gate", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def configure_repository(root: Path) -> None:
    empty_hooks = root / ".test-empty-hooks"
    empty_hooks.mkdir()
    git(root, "config", "user.name", "Delivery Gate Test")
    git(root, "config", "user.email", "delivery-gate@example.invalid")
    git(root, "config", "core.hooksPath", str(empty_hooks))


def create_repository(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    remote.mkdir()
    work.mkdir()
    git(remote, "init", "--bare", "--initial-branch=main")
    git(work, "init", "--initial-branch=main")
    configure_repository(work)
    (work / "data.txt").write_text("initial\n", encoding="utf-8")
    git(work, "add", "data.txt")
    git(work, "commit", "-m", "initial")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-u", "origin", "main")
    return work, remote


def commit_change(root: Path, content: str, message: str) -> str:
    (root / "data.txt").write_text(content, encoding="utf-8")
    git(root, "add", "data.txt")
    git(root, "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def test_deliver_pushes_main_and_verify_accepts_exact_head(tmp_path: Path) -> None:
    work, remote = create_repository(tmp_path)
    head = commit_change(work, "delivered\n", "deliver")

    assert GATE.deliver(work, run_checks=False) == head
    assert git(remote, "rev-parse", "refs/heads/main") == head
    assert GATE.verify(work) == head


def test_run_command_replaces_invalid_utf8_output(tmp_path: Path) -> None:
    result = GATE.run_command(
        tmp_path,
        [sys.executable, "-c", "import os; os.write(1, b'\\xad')"],
    )

    assert result.returncode == 0
    assert result.stdout == "\ufffd"


def test_write_output_replaces_characters_the_stream_cannot_encode() -> None:
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="ascii", errors="strict")

    GATE.write_output(stream, "\U0001f50d")
    stream.flush()

    assert buffer.getvalue() == b"?"


def test_verify_rejects_an_unpushed_commit(tmp_path: Path) -> None:
    work, _remote = create_repository(tmp_path)
    commit_change(work, "not delivered\n", "local only")

    with pytest.raises(GATE.GateError, match="has not been delivered exactly"):
        GATE.verify(work)


def test_deliver_rejects_diverged_main_without_overwriting_it(
    tmp_path: Path,
) -> None:
    work, remote = create_repository(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", str(remote), str(other))
    configure_repository(other)
    remote_head = commit_change(other, "remote update\n", "remote update")
    git(other, "push", "origin", "main")
    commit_change(work, "local update\n", "local update")

    with pytest.raises(GATE.GateError, match="is not an ancestor"):
        GATE.deliver(work, run_checks=False)

    assert git(remote, "rev-parse", "refs/heads/main") == remote_head
    state = json.loads(
        (work / ".git" / GATE.STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert state["status"] == "failed"
    assert "is not an ancestor" in state["error"]
