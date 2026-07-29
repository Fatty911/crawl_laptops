# Repository Rules

These rules apply to the entire repository.

## Non-negotiable publication gate

Every record written to the Pages payload must have positive evidence for:

1. a numeric keypad;
2. keyboard backlighting; and
3. a standard/high-performance CPU whose model suffix is `H`, `HX`, `HS`, or `HK`.

Unknown values fail closed. Low-power suffixes (`U`, `Y`, `UL`, `UP`, `G1`,
`G4`, `G7`) must never be published. Do not weaken this policy in crawler,
merge, audit, test, or UI code.

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

