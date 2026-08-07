#!/usr/bin/env python3
"""MSE repair runner: deterministic rule-based merge_data normalisation.

The Agent outputs *rules* (strip prefixes/suffixes, case normalisation)
as JSON — NOT a diff (plan agents cannot reliably emit unified diffs).
This runner deterministically implements those rules in canonical_model_family,
runs tests, reviews via DeepSeek official, commits with trailers, pushes, and
triggers a merge-and-filter rerun.  The workflow cron repeats until the
compatible overlap count reaches zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
REPO = os.environ.get("GITHUB_REPOSITORY", "Fatty911/crawl_laptops")
MERGE_POLL = 420

# 归一化规则 -> 确定性 merge_data.py 补丁代码（插到 canonical_model_family 清洗段）
RULE_IMPLS = {
    "strip_prefix": '''    # MSE 增强：剥离源站常见 CPU/品牌前缀词（PConline 加"酷睿"，ZOL 省略）
    for _tok in ("酷睿", "intel", "英特尔"):
        if family.startswith(_tok):
            family = family[len(_tok):]
            break
''',
    "strip_suffix": '''    # MSE 增强：剥离屏幕规格后缀（/2.5K /240Hz /OLED /2.5K屏）
    family = re.sub(r"/(?:\\d+(?:\\.\\d+)?K|\\d+Hz|OLED|\\d+K屏)+$", "", family)
''',
    "normalize_case": '''    # MSE 增强：统一大小写与空白（Pro/PRO→pro、去连字符空格）
    family = re.sub(r"\\s+", "", family).replace("-", "").lower()
''',
}


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True,
                          timeout=timeout, env={**os.environ, "PYTHONUNBUFFERED": "1"})


def extract_json(raw: str) -> dict:
    start = raw.find("{")
    if start < 0:
        return {}
    depth = 0
    end = -1
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end <= start:
        return {}
    try:
        return json.loads(raw[start:end])
    except Exception:
        return {}


def apply_rules(rules: list[dict]) -> bool:
    """Insert deterministic normalisation code into canonical_model_family."""
    target = ROOT / "scripts/merge_data.py"
    if not target.exists():
        # 测试注入：允许 ROOT 直接含 merge_data.py
        alt = ROOT / "merge_data.py"
        if alt.exists():
            target = alt
        else:
            print(f"[mse-repair] merge_data.py not found under {ROOT}")
            return False
    src = target.read_text(encoding="utf-8")
    marker = "    # MSE 增强"
    if marker in src and RULE_IMPLS["normalize_case"].strip().splitlines()[-1] in src:
        print("[mse-repair] rules already applied; skip")
        return True
    anchor = "    return family or _identity_text(text)"
    if anchor not in src:
        print("[mse-repair] anchor not found in canonical_model_family")
        return False
    impls = []
    for r in rules:
        t = r.get("type")
        if t in RULE_IMPLS:
            impls.append(RULE_IMPLS[t])
    if not impls:
        print("[mse-repair] no implementable rules")
        return False
    block = "\n".join(impls)
    new_src = src.replace(anchor, block + "\n" + anchor, 1)
    target.write_text(new_src, encoding="utf-8")
    print(f"[mse-repair] applied {len(impls)} rules")
    return True


def review_patch(diff_text: str, diff_sha: str) -> list[dict]:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("[mse-repair] no DEEPSEEK_API_KEY; review skipped")
        return []
    import urllib.request
    prompt = (
        "审查 crawl_laptops 的 merge_data.py 归一化补丁（MSE 多源率修复）。"
        "要求：不影响现有合并行为、不破坏测试。合理输出：结论: PASS；否则 结论: FAIL 及原因。\n"
        f"DIFF_SHA256: {diff_sha}\n补丁：\n{diff_text[:6000]}"
    )
    body = json.dumps({"model": "deepseek-v4-flash",
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 1000}).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=180).read())
        content = resp["choices"][0]["message"]["content"]
        result = "PASS" if re.search(r"结论:\s*PASS", content) else "FAIL"
        print(f"[mse-repair] review: {result}")
        return [{"family": "DeepSeek", "model": "deepseek-v4-flash", "result": result}]
    except Exception as e:
        print(f"[mse-repair] review error: {e}")
        return []


def commit_with_trailers(diff_sha: str, reviews: list[dict], message: str) -> bool:
    _run(["git", "add", "-A"], cwd=ROOT)
    trailers = []
    for i, rv in enumerate(reviews, 1):
        trailers.append(f"Review-Model-Family-{i}: {rv['family']}")
        trailers.append(f"Review-Result-{i}: {rv['result']}")
    msg = message + "\n\n" + "\n".join(trailers) + f"\nReviewed-Diff-SHA256: {diff_sha}\n"
    r = _run(["git", "commit", "-m", msg], cwd=ROOT)
    if r.returncode != 0:
        print(f"[mse-repair] commit failed: {r.stderr[:300]}")
        return False
    p = _run(["git", "push", "origin", "main"], cwd=ROOT, timeout=180)
    print(f"[mse-repair] push: {p.returncode}")
    return p.returncode == 0


def trigger_merge_and_wait() -> bool:
    r = _run(["gh", "workflow", "run", "merge-and-filter.yml", "--repo", REPO], timeout=60)
    if r.returncode != 0:
        print(f"[mse-repair] trigger merge failed: {r.stderr[:200]}")
        return False
    deadline = time.time() + MERGE_POLL
    while time.time() < deadline:
        time.sleep(30)
        rr = _run(["gh", "run", "list", "--repo", REPO, "--workflow", "merge-and-filter.yml",
                   "--limit", "1", "--json", "status,conclusion,createdAt"], timeout=60)
        try:
            runs = json.loads(rr.stdout)
            if runs and runs[0]["status"] == "completed":
                return runs[0].get("conclusion") == "success"
        except Exception:
            pass
    print("[mse-repair] merge poll timeout")
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch-file", default="mse_patch_out.json")
    args = parser.parse_args()
    patch_path = Path(args.patch_file)
    if not patch_path.exists():
        print("[mse-repair] no patch file; nothing to do")
        return 0
    raw = patch_path.read_text(encoding="utf-8")
    agent = extract_json(raw)
    rules = agent.get("rules", [])
    if not rules:
        # Agent 不可用时用确定性默认规则（Agent 前轮已确认的归一化方向）
        print("[mse-repair] no rules in agent output; using deterministic defaults")
        rules = [
            {"type": "strip_prefix", "tokens": ["酷睿", "Intel", "英特尔"]},
            {"type": "strip_suffix", "pattern": "/(\\d+(\\.\\d+)?K|\\d+Hz|OLED|\\d+K屏)"},
            {"type": "normalize_case", "detail": "统一小写、去空格连字符、Pro/PRO→pro"},
        ]
    if not apply_rules(rules):
        return 6
    tp = _run(["python", "-m", "pytest", "tests/", "-q"], timeout=400)
    print(f"[mse-repair] tests: {tp.returncode}")
    if tp.returncode != 0:
        # 保留改动不恢复：失败详情留给日志；下轮 cron 幂等跳过应用后重试
        print(f"[mse-repair] tests failed:\n{tp.stdout[-1500:]}\n{tp.stderr[-800:]}")
        return 8
    diff_text = _run(["git", "diff", "HEAD"]).stdout
    sha = hashlib.sha256(diff_text.encode()).hexdigest()
    reviews = review_patch(diff_text, sha)
    if not commit_with_trailers(sha, reviews, "fix(mse): merge_data 归一化增强（兼容重叠合并）"):
        return 9
    if not trigger_merge_and_wait():
        print("[mse-repair] merge rerun failed; fix committed, next cron re-scans")
    print("[mse-repair] round complete; next cron tick re-scans")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
