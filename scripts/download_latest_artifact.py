#!/usr/bin/env python3
"""Download and safely extract the newest cross-workflow GitHub Actions artifact."""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from pathlib import Path

try:
    from scripts.download_latest_crawler_artifact import api_get, newest_artifact
except ModuleNotFoundError:
    from download_latest_crawler_artifact import api_get, newest_artifact


def extract_archive(content: bytes, destination: Path) -> int:
    """Extract an artifact ZIP while rejecting path traversal."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for member in archive.infolist():
            relative = Path(member.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"unsafe artifact path: {member.filename!r}")
            target = (destination / relative).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise RuntimeError(f"unsafe artifact path: {member.filename!r}") from exc
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/repository")
    parser.add_argument("--workflow", required=True, help="workflow file name")
    parser.add_argument("--artifact-prefix", required=True)
    parser.add_argument("--extract-dir", required=True)
    parser.add_argument("--min-files", type=int, default=1)
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    import requests

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "crawl-laptops-pipeline",
        }
    )
    try:
        artifact = newest_artifact(session, args.repo, args.workflow, args.artifact_prefix)
        response = api_get(session, artifact["archive_download_url"])
        count = extract_archive(response.content, Path(args.extract_dir))
        if count < args.min_files:
            raise RuntimeError(
                f"artifact {artifact['name']} extracted {count} files; minimum is {args.min_files}"
            )
    except Exception as exc:
        print(f"artifact extraction failed: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "artifact": artifact["name"],
                "artifact_id": artifact["id"],
                "files": count,
                "extract_dir": str(Path(args.extract_dir)),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
