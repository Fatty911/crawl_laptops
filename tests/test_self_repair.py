"""self_repair_runner 测试：patch 解析、安全守卫、评审 trailer。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import self_repair_runner as sr


def test_parse_fix_response_valid_json():
    text = '{"patch": "--- a/x\\n+++ b/x\\n@@ -1 +1 @@\\n-old\\n+new", "reasoning": "ok", "confidence": 0.9}'
    fix = sr.parse_fix_response(text)
    assert fix["confidence"] == 0.9
    assert "old" in fix["patch"]


def test_parse_fix_response_codeblock_stripped():
    text = '```json\n{"patch": "p", "reasoning": "r", "confidence": 0.8}\n```'
    fix = sr.parse_fix_response(text)
    assert fix["confidence"] == 0.8


def test_parse_fix_response_garbage():
    fix = sr.parse_fix_response("not json at all")
    assert fix["confidence"] == 0.0
    assert fix["patch"] == ""


def test_count_deleted_lines():
    patch = """--- a/x
+++ b/x
@@ -1,3 +1,2 @@
 line1
-line2
-line3
+line2
"""
    assert sr.count_deleted_lines(patch) == 2


def test_count_deleted_lines_no_hunk():
    patch = "some random text\n- not a real deletion\n--- only file marker"
    assert sr.count_deleted_lines(patch) == 0


def test_review_trailers_commit_message():
    reviews = [
        {"provider": "kimi-coding-plan", "model": "k3", "verdict": "PASS"},
        {"provider": "volcengine-coding", "model": "glm-5.2", "verdict": "PASS"},
    ]
    diff_sha = "abc123"
    # 直接测 trailer 拼接逻辑（通过 commit_with_trailers 的静态部分）
    trailers = [
        f"{sr.REVIEW_TRAILER_FAMILY_1}: {reviews[0]['provider']}/{reviews[0]['model']}",
        f"{sr.REVIEW_TRAILER_RESULT_1}: PASS",
        f"{sr.REVIEW_TRAILER_FAMILY_2}: {reviews[1]['provider']}/{reviews[1]['model']}",
        f"{sr.REVIEW_TRAILER_RESULT_2}: PASS",
        f"{sr.REVIEW_TRAILER_DIFF}: {diff_sha}",
    ]
    msg = f"fix: test\n\n{chr(10).join(trailers)}"
    assert "Review-Model-Family-1: kimi-coding-plan/k3" in msg
    assert "Review-Result-1: PASS" in msg
    assert "Reviewed-Diff-SHA256: abc123" in msg


def test_parse_review_response():
    r = sr.parse_review_response('{"verdict": "PASS", "reason": "ok"}')
    assert r["verdict"] == "PASS"
    r2 = sr.parse_review_response('{"verdict": "FAIL", "reason": "x"}')
    assert r2["verdict"] == "FAIL"
    r3 = sr.parse_review_response("garbage")
    assert r3["verdict"] == "FAIL"


def test_apply_patch_in_worktree(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "core.hooksPath", "/dev/null"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "a.txt").write_text("line1\nline2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)

    patch = """--- a/a.txt
+++ b/a.txt
@@ -1,2 +1,2 @@
 line1
-line2
+line2-new
"""
    assert sr.apply_patch_in_worktree(patch, tmp_path) is True
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "line1\nline2-new\n"


def test_apply_patch_in_worktree_rejects_bad_patch(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "core.hooksPath", "/dev/null"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)

    bad = """--- a/nonexistent.txt
+++ b/nonexistent.txt
@@ -1 +1 @@
-old
+new
"""
    assert sr.apply_patch_in_worktree(bad, tmp_path) is False


def test_build_fix_prompt_contains_constraints():
    prompt = sr.build_fix_prompt("some log", "site_breakage", "selector failed", "hint")
    assert "git apply" in prompt
    assert "JSON" in prompt
    assert "confidence" in prompt
    assert str(sr.MAX_DELETED_LINES) in prompt
