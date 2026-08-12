#!/usr/bin/env python3
"""评审验证证据收集器：评审前自动收集真实证据（测试输出/数据抽查/一致性检查）。

用法：python3 scripts/collect_review_evidence.py
输出：/tmp/review_evidence.txt（注入评审 prompt）
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as exc:
        return "RUN FAIL: %s %s" % (type(exc).__name__, exc)


def staged_files():
    r = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, cwd=ROOT)
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def check_pytest():
    out = run(["python3", "-m", "pytest", "tests/", "-q"], timeout=400)
    lines = [l for l in out.splitlines() if "passed" in l or "failed" in l or "error" in l]
    return "\n".join(lines[-5:]) or out[-500:]


def check_artifacts():
    lines = []
    for prefix, wf in [("machenike-data-", "crawl-machenike.yml"),
                        ("pconline-search-data-", "crawl-pconline-search.yml")]:
        tmp = "/tmp/ev_" + prefix.strip("-") + ".json"
        cmd = ("cd %s && GITHUB_TOKEN=$(gh auth token) python3 scripts/download_latest_crawler_artifact.py "
               "--repo Fatty911/crawl_laptops --workflow %s --artifact-prefix %s --output %s --min-records 1 2>&1 | tail -1"
               % (ROOT, wf, prefix, tmp))
        r = run(["bash", "-c", cmd], timeout=120)
        if not Path(tmp).exists():
            lines.append("[%s] 下载失败: %s" % (prefix, r.strip()[:80]))
            continue
        try:
            data = json.loads(Path(tmp).read_text(encoding="utf-8"))
            items = data.get("items", data) if isinstance(data, dict) else data
            if not items:
                lines.append("[%s] 空数据" % prefix)
                continue
            junk_words = ["鼠标", "键盘", "显示器", "耳机", "背包", "包", "水冷", "台式", "充电器", "支架", "散热", "膜", "礼盒", "补差价"]
            junk = [r for r in items if any(w in str(r.get("title", "")) for w in junk_words)]
            cheap = [r for r in items if r.get("price") and float(r.get("price")) < 500]
            gpu_bad = [r for r in items
                       if r.get("dedicated_gpu") is False
                       and re.search(r"RTX|GTX|RX\s?\d", str(r.get("gpu", "")), re.I)]
            lines.append("[%s] 共%d条 | 垃圾词命中%d | 低价<500: %d | GPU矛盾: %d"
                         % (prefix, len(items), len(junk), len(cheap), len(gpu_bad)))
            if junk:
                lines.append("  垃圾样例: " + str([str(r.get("title", ""))[:30] for r in junk[:3]]))
            if cheap:
                cheap_s = [str(r.get("title", ""))[:25] + "¥" + str(r.get("price")) for r in cheap[:3]]
                lines.append("  低价样例: " + str(cheap_s))
            if gpu_bad:
                lines.append("  GPU矛盾样例: " + str([str(r.get("title", ""))[:30] for r in gpu_bad[:3]]))
        except Exception as exc:
            lines.append("[%s] 解析失败: %s" % (prefix, exc))
    return "\n".join(lines)


def check_regex_escapes():
    files = staged_files()
    if not files:
        r = subprocess.run(["git", "diff", "--name-only", "HEAD"], capture_output=True, text=True, cwd=ROOT)
        files = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    issues = []
    for f in files:
        if not f.endswith(".py"):
            continue
        try:
            src = Path(ROOT, f).read_text(encoding="utf-8")
        except Exception:
            continue
        # 用 tokenize 识别真正的 raw 字符串字面量（正则扫行会把普通三引号模板里
        # 的 r"..." 文本误判为 raw——mse_repair_runner 的 RULE_IMPLS 模板即此类）。
        import io
        import tokenize
        try:
            tokens = tokenize.generate_tokens(io.StringIO(src).readline)
            for tok in tokens:
                if tok.type != tokenize.STRING:
                    continue
                raw_text = tok.string
                is_raw = raw_text.startswith(("r\"", "R\"", "r'", "R'"))
                if is_raw and re.search(r"[\\][sd]", raw_text[2:-1]) and "chr(92)" not in raw_text:
                    issues.append("  %s:%d: raw 字符串含双反斜杠 %s" % (f, tok.start[0], raw_text.strip()[:60]))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            # 解析失败时回退行级扫描（仅限真实 raw 字面量行）
            for i, line in enumerate(src.splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith(("r\"", "R\"")) and re.search(r"[\\][sd]", line) and "chr(92)" not in line:
                    issues.append("  %s:%d: raw 字符串含双反斜杠 %s" % (f, i, line.strip()[:60]))
    return "\n".join(issues) if issues else "未发现 raw 字符串双反斜杠问题"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()

    files = staged_files() if args.staged else []
    evidence = []
    evidence.append("=== 1. 变更文件 ===")
    evidence.append("\n".join(files) if files else "(未 staged，使用工作区全部)")
    evidence.append("\n=== 2. pytest 真实输出 ===")
    evidence.append(check_pytest())
    evidence.append("\n=== 3. artifact 数据质量抽查（垃圾/低价/GPU矛盾）===")
    evidence.append(check_artifacts())
    evidence.append("\n=== 4. 正则转义检查 ===")
    evidence.append(check_regex_escapes())

    out = Path("/tmp/review_evidence.txt")
    out.write_text("\n".join(evidence), encoding="utf-8")
    print("\n".join(evidence))
    print("\n[evidence saved to %s]" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
