# ECC in this repository

This file documents tooling, not scientific methodology. The frozen specification
(tag `analysis-plan-v3.0`: `docs/analysis_plan.md` + `configs/analysis.yaml`) and
`AGENTS.md` are authoritative. ECC agents, skills, hooks, memory and generic
ML/coverage/deployment advice never override them and never authorize an analysis run.

## Setup (durable facts)

- ECC is used as a native plugin (`ecc@ecc`) for both Codex and Claude Code. Plugin
  registration is per user/machine and is not stored in this repository.
- ECC hooks are **off** for this project. Do not enable additional hooks, adapters or
  MCP servers to change context behaviour.
- The only tracked ECC file besides this one is `.ecc/memory/project/.gitignore`,
  which keeps the project memory vault out of git.

Check the local installation with the harness's own plugin commands
(`codex plugin list`, `claude plugin list`); versions and cache paths vary by machine.

## Focused workflows

Use only workflows relevant to the currently authorized task, subject to `AGENTS.md`.

- Planning: `ecc:plan` (drafts a plan and waits for confirmation).
- Python: `ecc:python-patterns`; testing: `ecc:python-testing` or `ecc:tdd-workflow`.
- Review: `ecc:python-review` or `ecc:code-review`, reporting findings without changing methodology.
  For spec conformance use the project skill `.claude/skills/spec-audit`.
- Verification: `ecc:verification-loop`, using this repository's actual commands.
- ML/data pipelines: `ecc:mle-workflow`, constrained by the frozen specification.
- Literature: `ecc:scientific-thinking-literature-review`.
- Documentation: `ecc:update-docs` or `ecc:living-docs-governance`, only when documentation work is requested.
- Context/handoffs: `ecc:unified-memory`, project scope only (below).

In Claude Code these are invoked as `/ecc:<name>`; in Codex as `$<name>`.
Agent definitions shipped with ECC are guidance, not an authorization to delegate.

## Project-only memory

The vault is `.ecc/memory/project/`. Its `.gitignore` ignores every entry except
itself. No team/user memory or memory MCP is enabled. Use `ecc:unified-memory` with
project scope for recall and Codex ↔ Claude handoffs.

Memory entries are unreviewed working context. Verify any claim against the frozen
specification and current code; never promote memory to methodology, and never store
raw subject data or secrets in it.
