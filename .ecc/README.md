# Local ECC setup and handoffs

Setup checked 2026-09-30. This file documents tooling, not scientific methodology.
`AGENTS.md`, accepted `docs/`, and paired `configs/` remain authoritative.
Memory entries are unreviewed working context and cannot authorize analysis.

## Installed

- Official ECC 2.2.2 native Codex plugin (`ecc@ecc`), source commit
  `bd9402f774511f682f6a6d9a8c5dcc38a4c5536c`.
- Installation used the official guided native installer from a reviewed checkout.
  No legacy sync, manual skill overlay, Graft runtime, or global ECC npm installation.
- Native plugins expose the full skills catalog. No selective install profile was
  applied; `minimal/core/research` are not native catalog filters. Use relevant
  skills on demand. Do not enable additional hooks or adapters to reduce context.
- Codex hooks remain untrusted. Chrome DevTools MCP is explicitly disabled using
  the server override supported by Codex CLI 0.159.0.
- Codex registration is user-level and affects sessions using this Codex home.
- Claude Code 2.1.285 was repaired in place using the official npm reinstall
  procedure with optional dependencies and install scripts enabled. Doctor and
  authentication checks passed. ECC 2.2.2 is enabled at local scope for this repo.
  Its hooks are off; its bundled browser MCP is opted out for this project in
  `~/.claude.json`. An authenticated startup smoke test confirmed ECC loaded.

Restart Codex to discover the plugin. Verify registration with:

```sh
codex plugin list --json
node "$HOME/.codex/plugins/cache/ecc/ecc/2.2.2/scripts/codex/check-plugin-cache.js"
```

## Focused workflows

Use only workflows relevant to the current authorized task. ECC's generic ML,
coverage, deployment, and automation advice never overrides project methodology.

- Planning: ask Codex to read the cached `agents/planner.md` for implementation
  planning, subject to `AGENTS.md`; `$plan-orchestrate` can draft a workflow from
  an existing plan without executing it.
- Python: `$python-patterns`; testing: `$python-testing` or `$tdd-workflow`.
- Review: ask Codex to use the cached `agents/python-reviewer.md` or
  `agents/code-reviewer.md`, reporting findings without changing methodology.
- Verification: `$verification-loop`, using this repository's actual commands.
- ML/data pipelines: `$mle-workflow`, constrained by the frozen specification.
- Literature: `$literature-review`; documentation: `$living-docs-governance` only
  when documentation work is requested. Existing search tools remain available;
  no extra research MCP services were installed.
- Context/handoffs: `$unified-memory`, with project-only scope below.

Agent files are under `$HOME/.codex/plugins/cache/ecc/ecc/2.2.2/agents/`.
They are guidance, not registered Codex subagents or an authorization to delegate.

## Project-only memory

The vault is `.ecc/memory/project/`. Its generated `.gitignore` ignores all
entries except itself. No team/user memory or memory MCP was enabled. Both
harnesses can use the same CLI from this repository, without installing another
copy of ECC. Define this shell function (not persisted in shell startup files):

```sh
ecc_memory() {
  node "$HOME/.codex/plugins/cache/ecc/ecc/2.2.2/scripts/ecc.js" memory "$@"
}
ecc_memory search "handoff" --scope project --target-harness codex
ecc_memory doctor --scope project
ecc_memory read MEMORY_ID --scope project
```

Create a handoff from a reviewed, regular text file outside tracked source:

```sh
ecc_memory handoff --scope project --from codex --target claude \
  --title "Current implementation handoff" --body-file /tmp/rcps-handoff.md
```

For the reverse direction, use `--from claude --target codex`. Recall with the
matching `--target-harness`. Verify claims against authoritative files and current
code; do not promote memory to methodology or store raw subject data or secrets.
The cache path is version-specific: check the installed version after an update.

## Claude workflow in this repository

Start `claude` from the repository root, or run `/reload-plugins` in an existing
session. Use these commands only for the work currently authorized:

- `/ecc:plan <implementation task>`
- `/ecc:python-patterns` and `/ecc:python-testing`
- `/ecc:python-review` or `/ecc:code-review`
- `/ecc:verification-loop`
- `/ecc:mle-workflow`
- `/ecc:literature-review`
- `/ecc:update-docs` only when documentation changes are requested
- `/ecc:unified-memory` with project scope for recall and handoffs

Check configuration with `claude plugin list --json` and
`claude plugin configure ecc@ecc --json`. The hook flag must remain false;
`hook_profile=standard` is an inactive fallback while that flag is false.

Claude can use its own bundled memory runtime against the same vault:

```sh
node "$HOME/.claude/plugins/cache/ecc/ecc/2.2.2/scripts/ecc.js" memory search \
  "handoff" --scope project --target-harness claude
node "$HOME/.claude/plugins/cache/ecc/ecc/2.2.2/scripts/ecc.js" memory doctor --scope project
```

Claude setup changed `.claude/settings.local.json` (ignored), native plugin
marketplace/cache/registration under `~/.claude/plugins/`, ECC hook options in
`~/.claude/settings.json`, and this project's disabled-MCP list in `~/.claude.json`.
The installer's unrelated attribution change was reverted. No project or global
instruction file, scientific documentation, or Codex configuration was changed.
