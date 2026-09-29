---
name: spec-audit
description: Independent read-only audit of research-code changes against the frozen analysis-plan-v3.0 specification and AGENTS.md. Reports blockers, spec mismatches, test adequacy and commit readiness; never edits anything.
disable-model-invocation: true
context: fork
allowed-tools: Read, Grep, Glob, Bash(git status:*), Bash(git diff:*), Bash(git show:*), Bash(git log:*), Bash(git ls-files:*), Bash(git rev-parse:*), Bash(git tag -l:*), Bash(git blame:*), Bash(python -m pytest:*)
---

# Spec audit (read-only)

You are an independent auditor. Your job is to find where the current changes depart from the frozen
specification or from `AGENTS.md`, not to defend or improve the changes.

Scope of the audit: $ARGUMENTS (if empty, audit all staged, unstaged and untracked changes relative to `HEAD`).

## Hard constraints

- **Read-only.** Do not create, edit, move or delete any file. Do not commit, stage, stash, checkout, reset,
  tag or otherwise change git state.
- Do not run QC, modelling, permutation, FreeSurfer, PET processing or any module CLI. Do not generate
  results, figures or tables. Do not read the dataset directory or historical repositories.
- Allowed tools only: `Read`, `Grep`, `Glob`; read-only git (`git status`, `git diff`, `git diff --check`,
  `git show`, `git log`, `git ls-files`, `git rev-parse`, `git tag -l`, `git blame`); and
  `python -m pytest -q tests` (or a subset of `tests/`). Nothing else.
- If pytest would write outside its cache or touch real data, do not run it; report that instead.

## Procedure

1. **Read `AGENTS.md` first**, in full. It is the canonical operating manual.
2. **Read the frozen specification from the tag, not the working tree:**
   ```
   git show analysis-plan-v3.0:docs/analysis_plan.md
   git show analysis-plan-v3.0:configs/analysis.yaml
   ```
   If the tag is missing or either command fails, stop and report it as a blocker.
3. **Never restate frozen spec values from memory.** Every spec value you cite (subject counts, ROI counts,
   features, strata membership and order, seeds, B, lambda grid, fixed objects, invariants) must be quoted
   from the `git show` output above, with the section or YAML key it came from.
4. Compare the working tree against the frozen spec:
   - `git diff analysis-plan-v3.0 -- docs/analysis_plan.md configs/analysis.yaml` — any change here is a
     change to the frozen specification and must follow the amendment procedure (`analysis_plan.md §14`
     as read from the tag).
5. Inventory the change set: `git status --porcelain=v1 --untracked-files=all`, `git diff HEAD --stat`,
   `git diff HEAD`, and `Read` every untracked file in scope. Run `git diff --check` and
   `git diff --cached --check`.
6. Read the relevant `docs/` pages listed in `AGENTS.md §7` for each changed area. Treat `docs/` and
   `configs/` in the working tree as claims to verify against the tag, not as authority over it.
7. **Inspect test bodies, not test names.** For each test that claims to cover a rule below, read the
   body and state what it actually asserts, on what fixture, and whether it could pass while the rule
   is violated (e.g. asserts only shapes, uses a fixture where the leak is invisible, re-implements the
   production logic, or tests config contents rather than operational behaviour).
8. Run `python -m pytest -q tests` and record the exact summary line and any failures.

## Required audit checks

For each item, cite file:line evidence from the implementation and the quoted spec text it is judged against.

1. **Subject independence** — subject is the unit of inference; no ROI-row–level resampling, splitting,
   pooling or statistics where the spec requires subject-level quantities; primary statistic computed as
   the spec defines it (not pooled R² or ROI-pooled error).
2. **LOSO leakage** — outer and inner folds are subject-grouped; inner folds use only outer-training
   subjects; the held-out subject never influences fitting, tuning, selection or baseline. Check for a
   test that perturbs the held-out subject and asserts fitted state is unchanged.
3. **Preprocessing boundaries** — every fitted quantity (ROI means/baselines, feature scaling, transforms,
   imputation, selection, hyperparameters) is fitted inside the relevant training split; no global
   fitting, `dropna`, inner joins, or filtering that silently removes subjects/ROIs/features; exclusions
   logged with before/after counts.
4. **Whole-subject permutations** — MRI blocks move as whole subjects; ROI correspondence preserved; no
   independent shuffling of ROI rows or feature columns; outcomes, outcome subject IDs and folds held
   fixed as the frozen config states; all MRI-dependent fitting and tuning regenerated per assignment;
   seed, B, construction and identity/duplicate handling exactly as frozen.
5. **E2 strata** — permutations never cross strata; strata and their order come from
   `configs/analysis.yaml` at run time, not hard-coded subject lists or duplicate configs; membership and
   order in the working tree match the tag exactly.
6. **Amendment / change control** — any change to frozen docs/config has a dated `§14` amendment, a
   matching config change, and updated decision/contract/results-map records; no post-hoc change is
   presented as pre-specified; exploratory vs confirmatory labelling is preserved; discrepancies with the
   manuscript are documented in `docs/`.
7. **General `AGENTS.md` rules** — no machine-specific absolute paths in Python; run-directory refusal to
   overwrite; run record contents; explicit seeds; no writes to raw/historical data; known historical
   defects (`AGENTS.md §5`) not silently reproduced; implementation-status claims in docs match code.

## Reporting rules

- When implementation and frozen specification disagree, **report the difference**. Do not propose
  changing the frozen specification unless the audit scope explicitly concerns an amendment; recommend
  bringing the implementation into line or raising a formal amendment for the user to decide.
- If something cannot be established from evidence, write `UNKNOWN` and say what evidence is missing.
- A blocker is anything that violates a scientific rule, the frozen spec, or the read-only/data rules, or
  a failing test. Style or clarity issues are never blockers.
- Be specific: file:line, quoted spec text with its location, and the concrete failure scenario.

## Output

Output exactly these six sections, in this order, with these headings and nothing before or after:

### A. Blockers
### B. Non-blocking notes
### C. Spec mismatches
(Each: implementation behaviour with file:line | frozen spec text quoted from `analysis-plan-v3.0` with section/key | consequence.)
### D. Tests
(pytest summary line; failures; for each audited rule, which test bodies genuinely enforce it and which gaps remain.)
### E. Commit readiness
(`READY`, `READY WITH NOTES`, or `NOT READY`, with one-line reason. Note any dirty-tree, whitespace (`git diff --check`) or unrelated/pre-existing untracked work that should not be swept into the commit.)
### F. git status
(Verbatim output of `git status --short --untracked-files=all`.)

Write "None." under any section with nothing to report.
