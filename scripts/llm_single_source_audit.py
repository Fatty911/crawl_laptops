#!/usr/bin/env python3
"""Call a configured free model to analyze single-source root causes.

Reads the audit report + raw data sample, sends to a high-quality LLM
(AA Intelligence Index >= 50) and produces a markdown analysis.

The normal route is free-only. The historical AA 50+ list is available only
with the explicit --allow-paid switch and is never used by the Actions route.

Free-first models include NVIDIA NIM, OpenRouter, OpenCode Zen, Cloudflare,
Modal, ModelScope, and AtomGit compatible endpoints.

Paid opt-in models in descending AA Index:
  1. Claude Opus 5 (max) - AA 61
  2. GPT-5.6 Sol (max) - AA 59
  3. Kimi K3 - AA 57
  4. GPT-5.6 Sol (high) - AA 56
  5. Grok 4.5 (high) - AA 54

Usage:
    python3 scripts/llm_single_source_audit.py --data ./data/latest.json --report ./audit_report.json --output ./llm_analysis.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path


MAX_AGENT_RESPONSE_BYTES = 512 * 1024


# Free-compatible models used by the normal route.
FREE_MODELS = [
    {
        "name": "NVIDIA NIM DeepSeek V4 Flash (free route)",
        "aa_index": 50,
        "provider": "nvidia-nim",
        "model": "deepseek-ai/deepseek-v4-flash",
        "max_tokens": 8000,
        "env_keys": ["NVIDIA_NIM_API_KEY"],
        "endpoint": "https://integrate.api.nvidia.com/v1/chat/completions",
    },
    {
        "name": "OpenRouter Nemotron free",
        "aa_index": 0,
        "provider": "openrouter-free",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "max_tokens": 8000,
        "env_keys": ["OPENROUTER_API_KEY"],
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "headers": {"HTTP-Referer": "https://github.com/Fatty911", "X-Title": "Free-first audit"},
    },
    {
        "name": "OpenCode Zen Nemotron free",
        "aa_index": 0,
        "provider": "opencode-zen-free",
        "model": "nemotron-3-ultra-free",
        "max_tokens": 8000,
        "env_keys": ["ZEN_API_KEY"],
        "endpoint": "https://opencode.ai/zen/v1/chat/completions",
    },
    {
        "name": "Cloudflare Workers AI free",
        "aa_index": 0,
        "provider": "cloudflare-free",
        "model": "@cf/zai-org/glm-5.2",
        "max_tokens": 8000,
        "env_keys": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY"],
        "endpoint": "https://api.cloudflare.com/client/v4/accounts/b3becce2da2399953658ed2a053e7c08/ai/v1/chat/completions",
    },
    {
        "name": "Modal GLM free",
        "aa_index": 0,
        "provider": "modal-free",
        "model": "zai-org/GLM-5.1-FP8",
        "max_tokens": 8000,
        "env_keys": ["MODAL_API_KEY"],
        "endpoint": "https://api.us-west-2.modal.direct/v1/chat/completions",
    },
    {
        "name": "ModelScope MiniMax free",
        "aa_index": 0,
        "provider": "modelscope-free",
        "model": "MiniMax/MiniMax-M3",
        "max_tokens": 8000,
        "env_keys": ["MODELSCOPE_API_KEY"],
        "endpoint": "https://api-inference.modelscope.cn/v1/chat/completions",
    },
    {
        "name": "AtomGit GLM free",
        "aa_index": 0,
        "provider": "atomgit-free",
        "model": "zai-org/GLM-5.1",
        "max_tokens": 8000,
        "env_keys": ["ATOMGIT_API_KEY"],
        "endpoint": "https://api-ai.gitcode.com/v1/chat/completions",
    },
]


# Historical paid ordinary-API models, opt-in only.
PAID_AA_MODELS = [
    {
        "name": "DeepSeek V4 Flash 0731 (max)",
        "aa_index": 50,
        "provider": "nvidia-nim",
        "model": "deepseek-ai/deepseek-v4-flash",
        "max_tokens": 4000,
        "env_keys": ["NVIDIA_NIM_API_KEY"],
        "endpoint": "https://integrate.api.nvidia.com/v1/chat/completions",
    },
]


AA_MODELS = FREE_MODELS + PAID_AA_MODELS


def build_prompt(report: dict, data_sample: list[dict]) -> str:
    """Build analysis prompt from audit report + data sample."""
    src_dist = report.get("source_distribution", {})
    causes = report.get("causes", {})
    detail = report.get("detail", {})

    # Build top single-source series/products summary
    top_single = detail.get("top_single_series", detail.get("top_single_products", []))[:15]
    top_text = "\n".join(
        f"  - {item.get('series', item.get('product', '?'))}: {item.get('source', '?')} ({item.get('rows', 0)} rows)"
        for item in top_single
    )

    return f"""# 单源数据根因分析任务

你是一个数据质量分析专家。请分析以下爬虫数据的单源（single-source）问题，找出为什么很多条目只来自一个数据源。

## 数据概览
- 总行数: {report['total']}
- 多源行数: {report['multi_count']} ({report['multi_rate']}%)
- 单源行数: {report['single_count']} ({report['single_rate']}%)

## 数据源分布
{json.dumps(src_dist, ensure_ascii=False, indent=2)}

## 根因概要
{json.dumps(causes, ensure_ascii=False, indent=2)}

## 单源条目 Top 15
{top_text}

## 数据样本（前5行）
{json.dumps(data_sample[:5], ensure_ascii=False, indent=2, default=str)}

## 分析要求

请用中文输出以下内容：

### 1. 单源根因分类
对每个根因类别，说明：
- 具体原因
- 影响行数
- 修复建议（如果是代码可修的，指出具体修改方向）

### 2. 数据源覆盖分析
- 哪些数据源覆盖了哪些品牌/系列
- 哪些品牌/系列在多个源中都有但没被合并
- 哪些品牌/系列只有一个源有

### 3. 合并匹配改进建议
- 当前合并逻辑可能有什么问题
- 如何改进 trim/车型级匹配
- 是否需要增加新的爬取源

### 4. 优先级行动清单
按影响大小排序列出需要修复的问题，格式：
- [P0/P1/P2] 问题描述 → 修复方向 → 预期影响

### 5. 多源率提升路径
- 当前多源率: {report['multi_rate']}%
- 可达到的多源率: X% （说明依据）
- 达到80-90%多源率需要什么条件
"""


def _first_key(model: dict) -> str | None:
    """Return first available API key from candidate env var names."""
    for name in model.get("env_keys", []):
        val = os.environ.get(name)
        if val:
            return val
    return None


def _call_via_opencode(model: dict, prompt: str) -> str | None:
    """通过 OpenCode CLI（Agent 工具）调用模型，禁止直连模型 API。

    The provider key is consumed only by the OpenCode process; this function
    never issues HTTP requests to a model endpoint.
    """
    key = _first_key(model)
    if not key:
        return None
    endpoint = str(model.get("endpoint") or "").rstrip("/")
    if endpoint.endswith("/chat/completions"):
        endpoint = endpoint[: -len("/chat/completions")]
    if endpoint.endswith("/v1/messages"):
        endpoint = endpoint[: -len("/v1/messages")]
    provider_label = re.sub(r"[^A-Za-z0-9_-]", "-", str(model.get("name") or "provider").lower())[:60]
    is_anthropic = str(model.get("provider") or "").lower() == "anthropic"
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
            provider_label: {
                "npm": "@ai-sdk/anthropic" if is_anthropic else "@ai-sdk/openai-compatible",
                "name": provider_label,
                "options": {"baseURL": endpoint, "apiKey": f"{{env:{model['env_keys'][0]}}}"},
                "models": {model["model"]: {"limit": {"context": 131072, "output": int(model.get("max_tokens") or 8000)}}},
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
    import tempfile
    try:
        with tempfile.TemporaryDirectory(prefix="audit-llm-") as tmpdir:
            prompt_path = os.path.join(tmpdir, "prompt.md")
            with open(prompt_path, "w", encoding="utf-8") as handle:
                handle.write(prompt)
            cmd = [
                opencode_bin, "run", "--pure", "--agent", "plan",
                "--model", f"{provider_label}/{model['model']}",
                "--format", "default",
                "--dir", tmpdir,
                "--file", "prompt.md",
                "Answer the attached prompt directly. Do not call tools or modify files. Return only the requested analysis.",
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    except Exception as exc:
        print(f"  {model['name']} opencode call failed: {type(exc).__name__}", file=sys.stderr)
        return None
    if completed.returncode != 0:
        print(f"  {model['name']} opencode exit {completed.returncode}: {(completed.stderr or '')[:200]}", file=sys.stderr)
        return None
    content = (completed.stdout or "").strip()
    return content or None


def call_openai_compatible(model: dict, prompt: str) -> str | None:
    """通过 OpenCode CLI（Agent 工具）调用 OpenAI-compatible 端点。"""
    return _call_via_opencode(model, prompt)


def call_anthropic(model: dict, prompt: str) -> str | None:
    """通过 OpenCode CLI（Agent 工具）调用 Anthropic 端点。"""
    return _call_via_opencode(model, prompt)


def write_deterministic_fallback(report: dict, output: Path) -> None:
    fallback = f"""# 单源数据根因分析（确定性降级报告）

> 未配额AA 50+大模型API，以下为确定性分析。

## 数据概览
- 总行数: {report['total']}
- 多源: {report['multi_count']} ({report['multi_rate']}%)
- 单源: {report['single_count']} ({report['single_rate']}%)

## 根因分类
1. **车系仅单源**: {report['causes'].get('series_only_single', 0)} 行（对端未爬到该系列）
2. **trim级合并gap**: {report['causes'].get('trim_merge_gap', 0)} 行（系列有双源但具体车型未匹配）

## 数据源分布
{json.dumps(report.get('source_distribution', {}), ensure_ascii=False, indent=2)}

## Top 单源系列
{json.dumps(report.get('detail', {}).get('top_single_series', report.get('detail', {}).get('top_single_products', []))[:20], ensure_ascii=False, indent=2)}
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(fallback, encoding="utf-8")


def write_request_manifest(prompt: str, output: Path) -> dict[str, str]:
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    manifest = {
        "version": "single-source-audit-v1",
        "request_id": prompt_sha256[:16],
        "prompt_sha256": prompt_sha256,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def consume_agent_response(
    input_path: Path,
    output: Path,
    request_manifest: Path | None = None,
) -> None:
    raw = input_path.read_bytes()
    if not raw or len(raw) > MAX_AGENT_RESPONSE_BYTES:
        raise ValueError("Agent response is empty or exceeds the size limit")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Agent response is not UTF-8") from exc
    if not content.strip():
        raise ValueError("Agent response is empty")
    if request_manifest is not None:
        manifest = json.loads(request_manifest.read_text(encoding="utf-8"))
        request_id = str(manifest.get("request_id") or "").strip()
        prompt_sha256 = str(manifest.get("prompt_sha256") or "").strip()
        if not request_id or len(prompt_sha256) != 64:
            raise ValueError("request manifest is incomplete")
        required_lines = {
            f"REQUEST_ID: {request_id}",
            f"PROMPT_SHA256: {prompt_sha256}",
        }
        actual_lines = [line.strip() for line in content.splitlines()]
        if any(actual_lines.count(line) != 1 for line in required_lines):
            raise ValueError("Agent response is not bound to the request manifest")
        content = "\n".join(line for line in content.splitlines() if line.strip() not in required_lines).strip() + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def _load_inputs(args: argparse.Namespace) -> tuple[dict, list[dict], str]:
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        rows = data["items"]
    elif isinstance(data, dict) and "data" in data:
        rows = data["data"]
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    return report, rows, build_prompt(report, rows[:50])


def main():
    parser = argparse.ArgumentParser(description="LLM single-source audit")
    parser.add_argument("--data", required=True, help="Path to latest.json")
    parser.add_argument("--report", required=True, help="Path to audit report JSON")
    parser.add_argument("--output", required=True, help="Output markdown path")
    parser.add_argument("--prompt-output", help="Write a prompt for the external read-only Agent and exit")
    parser.add_argument("--manifest-output", help="Write the immutable prompt hash manifest")
    parser.add_argument("--agent-response-input", help="Validate and consume a response from the external Agent")
    parser.add_argument("--request-manifest", help="Require Agent response binding to this manifest")
    parser.add_argument("--fallback-only", action="store_true", help="Write only the deterministic report and never call a model")
    parser.add_argument("--allow-paid", action="store_true", help="Explicitly opt into the historical paid ordinary-API list")
    args = parser.parse_args()

    modes = sum(bool(value) for value in (args.prompt_output, args.agent_response_input)) + int(args.fallback_only)
    if modes > 1:
        parser.error("--prompt-output, --agent-response-input and --fallback-only are mutually exclusive")
    report, rows, prompt = _load_inputs(args)
    if args.prompt_output:
        prompt_path = Path(args.prompt_output)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        if args.manifest_output:
            write_request_manifest(prompt, Path(args.manifest_output))
        print(f"Agent prompt written to {prompt_path}")
        return
    if args.agent_response_input:
        consume_agent_response(
            Path(args.agent_response_input),
            Path(args.output),
            Path(args.request_manifest) if args.request_manifest else None,
        )
        print(f"Agent analysis written to {args.output}")
        return
    if args.fallback_only:
        write_deterministic_fallback(report, Path(args.output))
        print(f"Deterministic fallback written to {args.output}")
        return

    models = AA_MODELS if args.allow_paid else FREE_MODELS
    route_label = "paid opt-in AA 50+" if args.allow_paid else "free-only"
    print(f"Trying {route_label} models...")
    for model in models:
        print(f"  Trying {model['name']} (AA {model['aa_index']})...")
        if model["provider"] == "anthropic":
            result = call_anthropic(model, prompt)
        else:
            result = call_openai_compatible(model, prompt)
        if result:
            Path(args.output).write_text(result, encoding="utf-8")
            print(f"Analysis from {model['name']} written to {args.output}")
            return
        print(f"  {model['name']} unavailable, trying next...")

    write_deterministic_fallback(report, Path(args.output))
    print(f"No {route_label} model available - deterministic fallback written to {args.output}")


if __name__ == "__main__":
    main()
