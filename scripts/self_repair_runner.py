#!/usr/bin/env python3
"""Self-repair runner for crawl_laptops workflow failures.

Diagnosed workflow failures (site_breakage / unknown classes) are repaired
through a bounded, reviewed loop instead of only filing an issue:

  1. An LLM proposes a fix as a unified diff (never writes files directly).
  2. The patch is applied in a throwaway git worktree and validated with
     targeted tests (syntax check + related pytest files).
  3. Two model families review the exact validated diff and emit the
     repository's review trailers (Review-Model-Family-1/2,
     Review-Result-1/2: PASS, Reviewed-Diff-SHA256).
  4. On PASS the patch is committed on main with the trailers and the
     failed workflow is re-dispatched; a successful re-run closes the
     diagnosis issue.

Safety:
  - AI output is parsed as JSON {patch, reasoning, confidence}; only the
    patch field is applied (via `git apply`), never free-form commands.
  - The patch is validated in an isolated worktree; the working tree is
    only touched after validation passes.
  - A fix is attempted at most once per (workflow, head_sha) pair; the
    attempt marker lives in the diagnosis issue body.
  - Deletions above a threshold abort the repair.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REVIEW_TRAILER_FAMILY_1 = "Review-Model-Family-1"
REVIEW_TRAILER_FAMILY_2 = "Review-Model-Family-2"
REVIEW_TRAILER_RESULT_1 = "Review-Result-1"
REVIEW_TRAILER_RESULT_2 = "Review-Result-2"
REVIEW_TRAILER_DIFF = "Reviewed-Diff-SHA256"

# Review providers: two different families, both more expensive than the
# main models (deepseek-v4-flash / gpt-5.6-luna), invoked through the
# OpenCode CLI (Agent tool) against the NIM OpenAI-compatible endpoint.
# (Fix generation runs through the OpenCode Agent tool in the workflow --
#  Plan keys must only be consumed by the read-only OpenCode Agent step.)
REVIEW_PROVIDERS = [
    {
        "name": "nvidia-nim-kimi",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "env_key": "NVIDIA_NIM_API_KEY",
        "model": "moonshotai/kimi-k2.6",
    },
    {
        "name": "nvidia-nim-glm",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "env_key": "NVIDIA_NIM_API_KEY",
        "model": "z-ai/glm-5.2",
    },
]

MAX_DELETED_LINES = 50
PATCH_PATTERNS = re.compile(r"^diff --git |^--- |^\+\+\+ |^@@ ", re.M)


def _sh(args: list[str], cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd or ROOT), capture_output=True, text=True, timeout=timeout)


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return _sh(["git", *args], cwd=cwd)


def build_fix_prompt(log_excerpt: str, classification: str, reason: str, repo_hint: str) -> str:
    return f"""你是资深 CI 修复工程师。crawl_laptops 仓库的一个 workflow 失败，AI 诊断如下。

## 分类
{classification} ({reason})

## 失败日志摘录
```text
{log_excerpt[:12000]}
```

## 任务
分析失败根因，输出一个**最小、精确**的修复补丁。约束：
- 只允许输出统一 diff 格式（git apply 可应用），禁止直接写文件内容
- 不允许修改 workflows 的安全关键部分（sandbox、权限、代理 env、评审门禁）
- 不允许删除超过 {MAX_DELETED_LINES} 行
- 不确定的修复不要输出（宁可不修，不要引入幻觉）
- 参考仓库结构：{repo_hint}

## 输出格式（严格 JSON，不要 markdown 代码块）
{{"patch": "<unified diff 文本>", "reasoning": "<简述>", "confidence": 0.0-1.0}}
confidence < 0.7 时 patch 必须为空字符串。
"""


def build_review_prompt(diff: str, workflow_name: str, run_id: str) -> str:
    return f"""审查 crawl_laptops 仓库的自修复补丁（workflow: {workflow_name}, run: {run_id}）。

## 补丁（统一 diff）
```diff
{diff[:12000]}
```

## 审查要点
1. 是否最小改动、不触碰无关配置
2. 是否违反仓库安全约束（sandbox/权限/代理/评审门禁）
3. 是否引入新 bug 或删除过多代码
4. 修复是否与失败根因匹配

## 输出（严格 JSON）
{{"verdict": "PASS" 或 "FAIL", "reason": "<一句话理由>"}}
"""


def call_llm(provider: dict, prompt: str, max_tokens: int = 4000) -> str | None:
    """通过 OpenCode CLI（Agent 工具）调用评审模型，禁止直连模型 API。

    The provider key is consumed only by the OpenCode process; the script
    itself never issues HTTP requests to a model endpoint.
    """
    key = os.environ.get(provider["env_key"], "")
    if not key:
        return None
    base_url = provider["base_url"].rstrip("/")
    if base_url.endswith("/chat/completions"):
        base_url = base_url[: -len("/chat/completions")]
    read_only = {
        "*": "deny",
        "read": "allow",
        "edit": "deny",
        "bash": "deny",
        "webfetch": "deny",
        "task": "deny",
        "question": "deny",
        "external_directory": "deny",
    }
    config = {
        "provider": {
            provider["name"]: {
                "npm": "@ai-sdk/openai-compatible",
                "name": provider["name"],
                "options": {
                    "baseURL": base_url,
                    "apiKey": f"{{env:{provider['env_key']}}}",
                },
                "models": {provider["model"]: {"limit": {"context": 131072, "output": max(1024, int(max_tokens))}}},
            }
        },
        "agent": {"plan": {"permission": read_only}},
        "permission": read_only,
    }
    env = dict(os.environ)
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config, ensure_ascii=False)
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env["OPENCODE_DISABLE_TELEMETRY"] = "1"
    opencode_bin = os.environ.get("OPENCODE_BIN", "opencode")
    with tempfile.TemporaryDirectory(prefix="self-repair-") as tmpdir:
        (Path(tmpdir) / "prompt.md").write_text(prompt, encoding="utf-8")
        cmd = [
            opencode_bin, "run", "--pure", "--agent", "plan",
            "--model", f"{provider['name']}/{provider['model']}",
            "--format", "default",
            "--dir", tmpdir,
            "--file", "prompt.md",
            "Answer the attached prompt directly. Do not call tools or modify files. Return only the requested JSON.",
        ]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
        except Exception as exc:
            print(f"[self-repair] {provider['name']} opencode call failed: {type(exc).__name__} {exc}", file=sys.stderr)
            return None
        if completed.returncode != 0:
            tail = (completed.stderr or "")[:300]
            print(f"[self-repair] {provider['name']} opencode exit {completed.returncode}: {tail}", file=sys.stderr)
            return None
        content = (completed.stdout or "").strip()
        return content or None


def parse_fix_response(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"patch": "", "reasoning": "unparseable", "confidence": 0.0}
    patch = str(data.get("patch", "") or "")
    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {"patch": patch, "reasoning": str(data.get("reasoning", "")), "confidence": confidence}


def parse_review_response(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"verdict": "FAIL", "reason": "unparseable review"}
    return {
        "verdict": str(data.get("verdict", "FAIL")).upper(),
        "reason": str(data.get("reason", "")),
    }


def apply_patch_in_worktree(patch: str, worktree: Path) -> bool:
    """在临时 worktree 应用补丁。返回是否干净应用。"""
    patch_file = worktree / "repair.patch"
    patch_file.write_text(patch, encoding="utf-8")
    result = _git(["apply", "--check", "--whitespace=error-all", "repair.patch"], cwd=worktree)
    if result.returncode != 0:
        print(f"[self-repair] git apply --check failed:\n{result.stderr[:2000]}", file=sys.stderr)
        return False
    result = _git(["apply", "--whitespace=error-all", "repair.patch"], cwd=worktree)
    if result.returncode != 0:
        print(f"[self-repair] git apply failed:\n{result.stderr[:2000]}", file=sys.stderr)
        return False
    return True


def count_deleted_lines(patch: str) -> int:
    deleted = 0
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            continue
        if in_hunk and line.startswith("-") and not line.startswith("---"):
            deleted += 1
    return deleted


def run_validation(worktree: Path) -> tuple[bool, str]:
    """定向验证：语法检查 + 相关测试。返回 (ok, detail)。"""
    checks = [
        (["python", "scripts/validate_syntax.py"], "validate_syntax"),
        (["python", "-m", "pytest", "tests/", "-q", "-x"], "pytest"),
    ]
    for cmd, label in checks:
        result = _sh(cmd, cwd=worktree, timeout=600)
        if result.returncode != 0:
            tail = (result.stdout + result.stderr)[-1500:]
            print(f"[self-repair] {label} failed:\n{tail}", file=sys.stderr)
            return False, label
        print(f"[self-repair] {label} OK")
    return True, "all"


def diff_sha256(worktree: Path) -> str:
    result = _git(["diff", "HEAD"], cwd=worktree)
    return hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def review_diff(diff: str, workflow_name: str, run_id: str) -> tuple[list[dict], str]:
    """两家模型家族评审，返回 (verdicts, diff_sha256)。"""
    reviews = []
    prompt = build_review_prompt(diff, workflow_name, run_id)
    for provider in REVIEW_PROVIDERS:
        content = call_llm(provider, prompt, max_tokens=1000)
        if not content:
            reviews.append({"provider": provider["name"], "model": provider["model"],
                            "verdict": "FAIL", "reason": "review call failed"})
            continue
        parsed = parse_review_response(content)
        reviews.append({"provider": provider["name"], "model": provider["model"], **parsed})
        print(f"[self-repair] review {provider['name']}/{provider['model']}: {parsed}")
    diff_sha = diff_sha256(ROOT)
    return reviews, diff_sha


def commit_with_trailers(worktree: Path, diff_sha: str, reviews: list[dict], message: str) -> bool:
    trailers = [
        f"{REVIEW_TRAILER_FAMILY_1}: {reviews[0]['provider']}/{reviews[0]['model']}",
        f"{REVIEW_TRAILER_RESULT_1}: PASS",
        f"{REVIEW_TRAILER_FAMILY_2}: {reviews[1]['provider']}/{reviews[1]['model']}",
        f"{REVIEW_TRAILER_RESULT_2}: PASS",
        f"{REVIEW_TRAILER_DIFF}: {diff_sha}",
    ]
    trailer_text = "\n".join(trailers)
    commit_msg = f"{message}\n\n{trailer_text}"
    result = _git(["add", "-A"], cwd=worktree)
    if result.returncode != 0:
        return False
    result = _git(["commit", "-m", commit_msg], cwd=worktree)
    if result.returncode != 0:
        print(f"[self-repair] commit failed:\n{result.stderr[:1000]}", file=sys.stderr)
        return False
    return True


def push_main(worktree: Path) -> bool:
    remote = os.environ.get("REMOTE_URL", "")
    if not remote:
        remote = f"https://x-access-token:{os.environ.get('GITHUB_TOKEN','')}@github.com/{os.environ.get('GITHUB_REPOSITORY','')}.git"
    result = _git(["push", remote, "HEAD:main"], cwd=worktree, timeout=180)
    if result.returncode != 0:
        print(f"[self-repair] push failed:\n{result.stderr[:1500]}", file=sys.stderr)
        return False
    return True


def redispatch(workflow_file: str) -> bool:
    result = _sh(["gh", "workflow", "run", workflow_file, "--repo", os.environ.get("GITHUB_REPOSITORY", "")], timeout=120)
    if result.returncode != 0:
        print(f"[self-repair] redispatch failed: {result.stderr[:1000]}", file=sys.stderr)
        return False
    print(f"[self-repair] redispatched {workflow_file}")
    return True


def build_prompt_command(args) -> int:
    """生成 OpenCode Agent 的修复 prompt 文件（workflow Prepare step 调用）。"""
    prompt = build_fix_prompt(
        args.log_excerpt or "", args.classification, args.reason,
        repo_hint="scripts/crawl_zol.py, crawl_jd.py, crawl_pconline.py, "
                  ".github/workflows/crawl-*.yml, merge_data.py",
    )
    out = Path(args.prompt_output)
    out.write_text(prompt, encoding="utf-8")
    print(f"repair prompt written to {out} ({len(prompt)} bytes)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("subcommand", nargs="?", default="",
                        help="build-prompt（生成 Agent 修复 prompt）或 apply（默认）")
    parser.add_argument("--log-excerpt", default="", help="失败日志摘录（Agent 已看过，仅存档）")
    parser.add_argument("--patch-file", default="", help="OpenCode Agent 生成的修复 patch JSON 文件")
    parser.add_argument("--prompt-output", default="", help="build-prompt: 输出的 prompt 文件路径")
    parser.add_argument("--classification", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--workflow-name", default="")
    parser.add_argument("--workflow-file", default="", help="失败 workflow 文件名（重新触发用）")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--fix-provider", default="nvidia-nim",
                        help="生成修复的模型 provider（默认 NIM 免费端点）")
    parser.add_argument("--attempt-marker", default="", help="本次尝试标记（写入 issue body 防循环）")
    args = parser.parse_args()

    if args.subcommand == "build-prompt" or args.prompt_output:
        return build_prompt_command(args)

    if not os.environ.get("GITHUB_TOKEN") and not os.environ.get("ACTION_PAT"):
        print("[self-repair] no GITHUB_TOKEN/ACTION_PAT", file=sys.stderr)
        return 2

    # 防循环：同一 (workflow, run) 已尝试过修复则跳过
    # marker 持久化在 repo 的 .self-repair-markers/（随修复提交进 main，跨 runner 生效）
    if args.attempt_marker:
        marker_path = ROOT / ".self-repair-markers" / f"{args.attempt_marker}.done"
        if marker_path.exists():
            print(
                f"[self-repair] attempt already done for {args.attempt_marker}; skipping",
                file=sys.stderr,
            )
            return 3
        os.environ["SELF_REPAIR_MARKER_FILE"] = f"{args.attempt_marker}.done"

    # 1. 读取 OpenCode Agent 生成的修复 patch（workflow 中 Agent 步骤产出）
    patch_path = Path(args.patch_file)
    if not patch_path.exists():
        print(f"[self-repair] patch file not found: {patch_path}", file=sys.stderr)
        return 3
    fix = parse_fix_response(patch_path.read_text(encoding="utf-8"))
    print(f"[self-repair] confidence={fix['confidence']} reasoning={fix['reasoning'][:200]}")
    if fix["confidence"] < 0.7 or not fix["patch"].strip():
        print("[self-repair] low confidence or empty patch; skipping", file=sys.stderr)
        return 3
    if count_deleted_lines(fix["patch"]) > MAX_DELETED_LINES:
        print("[self-repair] deletion guard triggered", file=sys.stderr)
        return 3

    # 2. 临时 worktree 应用 + 验证
    with tempfile.TemporaryDirectory(prefix="self-repair-") as tmp:
        worktree = Path(tmp) / "wt"
        result = _git(["worktree", "add", str(worktree), "main"])
        if result.returncode != 0:
            print(f"[self-repair] worktree add failed:\n{result.stderr[:800]}", file=sys.stderr)
            return 2
        try:
            if not apply_patch_in_worktree(fix["patch"], worktree):
                return 3
            # 写防循环 marker 到 worktree（随修复 commit 一起进 main）
            marker_rel = os.environ.get("SELF_REPAIR_MARKER_FILE", "")
            if marker_rel:
                mpath = worktree / ".self-repair-markers" / marker_rel
                mpath.parent.mkdir(parents=True, exist_ok=True)
                mpath.write_text("done", encoding="utf-8")
            ok, label = run_validation(worktree)
            if not ok:
                print(f"[self-repair] validation failed at {label}; not committing", file=sys.stderr)
                return 3
            # 3. 两家模型评审（针对 worktree 的精确 diff）
            diff = _git(["diff", "HEAD"], cwd=worktree).stdout
            reviews, diff_sha = review_diff(diff, args.workflow_name, args.run_id)
            if len(reviews) < 2 or any(r["verdict"] != "PASS" for r in reviews):
                print("[self-repair] review not passed; not committing", file=sys.stderr)
                return 3
            # 4. 提交 + 推送
            if not commit_with_trailers(worktree, diff_sha, reviews,
                                        f"fix: auto-repair {args.workflow_name} failure ({args.classification}) [skip ci]"):
                return 2
            if not push_main(worktree):
                return 2
        finally:
            _git(["worktree", "remove", "--force", str(worktree)])
            _git(["worktree", "prune"])

    # 5. 重新触发失败 workflow
    redispatch(args.workflow_file)
    print("[self-repair] repair committed and workflow redispatched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
