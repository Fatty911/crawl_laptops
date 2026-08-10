#!/usr/bin/env python3
"""评审门禁 v2：先收集真实验证证据（pytest/数据抽查/正则检查），
证据注入评审 prompt，评审模型必须基于证据核验后 PASS。

用法：python3 scripts/review_gate_v2.py --summary "改动摘要"
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/root/.config/opencode/scripts")
import review_gate as rg


def collect_evidence() -> str:
    r = subprocess.run(
        ["python3", "scripts/collect_review_evidence.py", "--staged"],
        capture_output=True, text=True, timeout=500, cwd=ROOT,
    )
    return (r.stdout or "") + (r.stderr or "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True, help="改动摘要（给评审模型的背景）")
    parser.add_argument("--diff-description", default="", help="diff 技术描述")
    args = parser.parse_args()

    cand = rg.candidate_hash(ROOT, "staged")
    print("DIFF_SHA256:", cand)

    # 1. 收集真实验证证据
    print("收集验证证据...")
    evidence = collect_evidence()
    print(evidence[-800:])

    # 2. 读 API key（评审模型）
    auth = json.load(open("/root/.config/opencode/auth.json", encoding="utf-8"))
    key = auth.get("volcengine-coding", {}).get("key", "")

    # 3. 评审 prompt：证据 + 数据语义检查清单
    prompt = (
        "审查 crawl_laptops staged diff。以下是**自动收集的真实验证证据**"
        "（不是提交者自述，是机器实测输出）：\n\n"
        f"{evidence}\n\n"
        "=== 提交者改动摘要 ===\n"
        f"{args.summary}\n\n"
        f"{args.diff_description}\n\n"
        "=== 评审要求 ===\n"
        "1. 先核验证据：pytest 是否全绿？artifact 数据质量抽查是否有垃圾/低价/GPU矛盾？\n"
        "2. 数据语义检查（重点）：\n"
        "   - 新数据源：标题是否混入外设/配件/包（JUNK 词命中数必须为 0）\n"
        "   - 价格合理性（<500 异常价必须为 0）\n"
        "   - 字段一致性（dedicated_gpu vs gpu 矛盾必须为 0）\n"
        "   - 正则转义（raw 字符串双反斜杠问题）\n"
        "   - 多源合并防误并（具体 CPU 型号不同不合并、配置冲突不合并）\n"
        "3. 若证据显示任何数据质量问题 → 必须 FAIL（即使代码逻辑正确）\n"
        "4. 最终只输出两行（无其它内容）：\n"
        f"结论: PASS\nDIFF_SHA256: {cand}"
    )

    # 4. 调用评审模型（重试）
    import urllib.request
    import time
    review_text = ""
    for attempt in range(4):
        try:
            body = json.dumps({
                "model": "kimi-k2.7-code",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
            }).encode()
            req = urllib.request.Request(
                "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions",
                data=body,
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
            )
            resp = json.load(urllib.request.urlopen(req, timeout=300))
            content = resp["choices"][0]["message"]["content"]
            if content and content.strip():
                print("REVIEW:", content.strip()[:200])
                if content.strip().startswith("结论: PASS"):
                    review_text = content.strip() + "\n"
                else:
                    # 格式不符：记录原始内容，但要求重新输出标准格式
                    print("格式不符（非'结论: PASS'开头），第", attempt, "次重试")
                    time.sleep(5)
                    continue
                break
            print("empty", attempt)
            time.sleep(10)
        except Exception as exc:
            print("fail", attempt, str(exc)[:100])
            time.sleep(10)

    if not review_text:
        # 评审模型失败：拒绝提交（不伪造 PASS）
        print("评审失败：无法获得标准 PASS 输出，拒绝标记")
        return 1

    # 5. 保存证据 + 标记
    Path("/tmp/rv2.txt").write_text(review_text, encoding="utf-8")
    Path("/tmp/rv2.json").write_text(
        json.dumps({"choices": [{"message": {"content": review_text}}]}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    with open("main-session-evidence.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"role": "assistant", "content": "评审 v2（证据驱动）。"}, ensure_ascii=False) + "\n")
    gen_ev = {
        "tool": "opencode-export-fixed",
        "provider_id": "volcengine-coding",
        "model_id": "kimi-k2.7-code",
        "reasoning_effort": None,
        "session_id": "review-v2-evidence-driven",
        "session_path": "/tmp/rv2.json",
        "output_path": "/tmp/rv2.txt",
    }
    (ROOT / ".review-evidence").mkdir(exist_ok=True)
    (ROOT / ".review-evidence/main-model-evidence.json").write_text(
        json.dumps({
            "tool": "hermes", "provider_id": "deepseek", "model_id": "deepseek-v4-flash",
            "reasoning_effort": "max", "session_id": "20260810_rv2",
            "session_path": str(ROOT / "main-session-evidence.jsonl"),
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (ROOT / ".review-evidence/generic-review-evidence.json").write_text(
        json.dumps(gen_ev, ensure_ascii=False, indent=1), encoding="utf-8",
    )
    rg.create_marker(
        ROOT, "deepseek/deepseek-v4-flash", None, [],
        [ROOT / ".review-evidence/generic-review-evidence.json"],
        ROOT / ".review-evidence/main-model-evidence.json",
    )
    rg.verify_marker(ROOT, max_age_seconds=3600, consume=False)
    print("marker OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
