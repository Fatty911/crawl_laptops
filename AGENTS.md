# Repository Rules

These rules apply to the entire repository.

## Non-negotiable publication gate

Every record written to the Pages payload must have positive evidence for:

1. a numeric keypad;
2. keyboard backlighting; and
3. either:
   - a standard/high-performance CPU whose model suffix is `H`, `HX`, `HS`, or
     `HK`; or
   - an explicitly identified desktop-performance CPU in a proven portable
     notebook/barebone product.

Unknown values fail closed. Low-power suffixes (`U`, `Y`, `UL`, `UP`, `G1`,
`G4`, `G7`) must never be published. A desktop CPU exception requires both a
source notebook/barebone category and positive product-form evidence such as
`laptop`, `notebook`, `笔记本`, `游戏本`, `准系统`, or a named ODM chassis.
Desktop PCs, mini PCs, NUCs, all-in-ones, and records with only a powerful CPU
remain ineligible. `蓝天`/Clevo and `仁宝`/Compal are ODM evidence, not
unconditional allowlists. Numeric-keypad and keyboard-backlight evidence
remain mandatory for every published record. Do not weaken this policy in
crawler, merge, audit, test, or UI code.

## Data and source integrity

- Keep source-local product IDs as evidence, never as cross-source identity.
- Deduplicate by a normalized product identity.
- Store canonical atomic sources in `atomic_source_names`; aliases normalize to
  `ZOL` or `JD`.
- Preserve the last published eligible baseline and reject publication shrink.
- A crawler artifact with fewer than 50 records is incomplete and must fail.
- The UI may hide more records, but it must never turn a rejected raw record
  into a published record.

## Engineering workflow

- Run `python -m pytest tests/ -v` before committing.
- Keep crawler network parsing separate from deterministic merge and audit logic.
- Add fixtures/tests when changing source parsing or publication semantics.
- Use `actions/checkout@main` and `actions/setup-python@main`; do not pin action
  commit SHAs in this repository.
- Git commits must use `Fatty911 <xuerui911@gmail.com>`, never a bot identity.


## Git 提交作者身份规则（Fatty911 全局要求，2026-08-04）

本仓库所有 Git 提交必须遵守以下作者命名规则：

1. **全局兜底身份**：`Fatty911 <xuerui911@gmail.com>`。禁止使用 `bot@users.noreply.github.com` 邮箱（该邮箱关联 GitHub 用户名 `bot`，网页端会显示纯 `bot`）。
2. **Agent 工具显式提交**：使用动态格式 `<实际工具名>-<实际模型>`。工具名 = 实际执行提交的 Agent 工具（如 hermes-agent / codex / opencode / openclaw / mimocode / qoder）。模型名 = 本次实际处理会话的模型 ID 的小写紧凑写法（如 GLM-5.2 → `glm5.2`、GPT-5.6-Sol → `gpt5.6sol`、Kimi-K3 → `kimi-k3`、DeepSeek-V4-Flash → `deepseek-v4-flash`）。示例：`opencode-kimi-k3`、`hermes-agent-glm5.2`、`codex-gpt5.5`。
3. 禁止纯 `bot` 名称或系统 bot 身份冒充源码/文档提交；`github-actions[bot]` 仅限数据/进度自动提交。
4. 邮箱一律使用 `xuerui911@gmail.com`。
