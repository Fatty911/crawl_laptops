#!/usr/bin/env python3
"""Deliver Codex Cloud commits directly to main and verify the result."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence, TextIO


STATE_FILENAME = "codex-delivery-gate.json"


class GateError(RuntimeError):
    """Raised when the direct-main delivery contract is not satisfied."""


def write_output(stream: TextIO, value: str) -> None:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    stream.write(value.encode(encoding, errors="replace").decode(encoding))


def run_command(
    root: Path,
    command: Sequence[str],
    *,
    check: bool = True,
    echo: bool = True,
) -> subprocess.CompletedProcess[str]:
    if echo:
        write_output(sys.stdout, "$ " + " ".join(command) + "\n")
    result = subprocess.run(
        list(command),
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.stdout:
        write_output(sys.stdout, result.stdout)
        if not result.stdout.endswith("\n"):
            write_output(sys.stdout, "\n")
    if result.stderr:
        write_output(sys.stderr, result.stderr)
        if not result.stderr.endswith("\n"):
            write_output(sys.stderr, "\n")
    if check and result.returncode != 0:
        raise GateError(
            f"command failed with exit code {result.returncode}: {' '.join(command)}"
        )
    return result


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def current_head(root: Path) -> str:
    result = run_command(root, ["git", "rev-parse", "HEAD"], echo=False)
    return result.stdout.strip()


def state_path(root: Path) -> Path:
    result = run_command(
        root, ["git", "rev-parse", "--git-dir"], echo=False
    )
    git_dir = Path(result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    return git_dir.resolve() / STATE_FILENAME


def write_state(root: Path, payload: dict[str, object]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def ensure_clean(root: Path) -> None:
    result = run_command(
        root,
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        echo=False,
    )
    if result.stdout.strip():
        raise GateError("working tree is not clean:\n" + result.stdout.rstrip())


def remote_head(root: Path, remote: str, branch: str) -> str:
    ref = f"refs/heads/{branch}"
    result = run_command(
        root,
        ["git", "ls-remote", "--exit-code", remote, ref],
        echo=False,
    )
    fields = result.stdout.strip().split()
    if len(fields) < 2 or fields[1] != ref:
        raise GateError(f"cannot resolve {remote}/{branch}")
    return fields[0]


def ensure_remote_is_ancestor(root: Path, remote_sha: str, head: str) -> None:
    result = run_command(
        root,
        ["git", "merge-base", "--is-ancestor", remote_sha, head],
        check=False,
        echo=False,
    )
    if result.returncode != 0:
        raise GateError(
            "origin/main is not an ancestor of HEAD; rebase onto the latest "
            "origin/main, resolve conflicts, and create a new commit"
        )


def validation_commands() -> list[list[str]]:
    return [
        ["git", "diff-tree", "--check", "--root", "HEAD"],
        [sys.executable, "scripts/validate_syntax.py", "--commit", "HEAD"],
        [sys.executable, "-m", "pytest", "tests"],
    ]


def deliver(
    root: Path,
    *,
    remote: str = "origin",
    branch: str = "main",
    run_checks: bool = True,
) -> str:
    root = root.resolve()
    head = current_head(root)
    started_at = int(time.time())
    try:
        ensure_clean(root)
        run_command(
            root,
            ["git", "fetch", "--quiet", "--no-tags", remote, f"refs/heads/{branch}"],
        )
        fetched_head = run_command(
            root, ["git", "rev-parse", "FETCH_HEAD"], echo=False
        ).stdout.strip()
        ensure_remote_is_ancestor(root, fetched_head, head)

        if run_checks:
            for command in validation_commands():
                run_command(root, command)

        run_command(root, ["git", "push", remote, f"HEAD:refs/heads/{branch}"])
        published_head = remote_head(root, remote, branch)
        if published_head != head:
            raise GateError(
                f"remote verification mismatch: local {head}, remote {published_head}"
            )

        write_state(
            root,
            {
                "status": "success",
                "head": head,
                "remote": remote,
                "branch": branch,
                "started_at": started_at,
                "finished_at": int(time.time()),
            },
        )
        print(f"DELIVERY_GATE_OK {head}")
        return head
    except Exception as exc:
        try:
            write_state(
                root,
                {
                    "status": "failed",
                    "head": head,
                    "remote": remote,
                    "branch": branch,
                    "started_at": started_at,
                    "finished_at": int(time.time()),
                    "error": str(exc),
                },
            )
        except Exception as state_error:
            print(
                f"DELIVERY_GATE_STATE_WRITE_FAILED {state_error}", file=sys.stderr
            )
        raise


def verify(
    root: Path,
    *,
    remote: str = "origin",
    branch: str = "main",
) -> str:
    root = root.resolve()
    ensure_clean(root)
    head = current_head(root)
    published_head = remote_head(root, remote, branch)
    if published_head != head:
        raise GateError(
            f"HEAD has not been delivered exactly: local {head}, remote {published_head}"
        )

    path = state_path(root)
    if not path.is_file():
        raise GateError(f"delivery state is missing: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"delivery state is unreadable: {exc}") from exc

    expected = {
        "status": "success",
        "head": head,
        "remote": remote,
        "branch": branch,
    }
    mismatches = [
        f"{key}={state.get(key)!r} (expected {value!r})"
        for key, value in expected.items()
        if state.get(key) != value
    ]
    if mismatches:
        raise GateError("delivery state mismatch: " + ", ".join(mismatches))

    print(f"DELIVERY_GATE_VERIFIED {head}")
    return head


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("deliver", "verify"))
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.action == "deliver":
            deliver(repository_root(), remote=args.remote, branch=args.branch)
        else:
            verify(repository_root(), remote=args.remote, branch=args.branch)
    except GateError as exc:
        print(f"DELIVERY_GATE_FAILED {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
