# Project Instructions (canonical for Claude, Codex, and humans)

This repository is the **only** place for new analysis, validation, figures, tables, and resubmission work for the
PET-MRI study on predicting regional cerebral protein synthesis (rCPS) from structural MRI morphometrics.
Status: **reconstruction / reanalysis**. The goal is a correct, reproducible analysis. It is **not** to recover
the conclusion of the rejected 2025 manuscript.

The target is continuous measured cortical ROI-mean rCPS from OpenNeuro ds004733 1.0.1.
This is regression, not classification. Primary prediction asks whether thickness and
ln(surface area) improve over training ROI means in held-out subjects.

## 0. Authority

1. **Frozen scientific specification (sole authority):** tag `analysis-plan-v3.0` (`80d951f`), i.e.
   `docs/analysis_plan.md` v3.0 plus `configs/analysis.yaml`. Read them from the tag
   (`git show analysis-plan-v3.0:<path>`) when checking a change. They change only by a dated amendment
   (`analysis_plan.md §14`).
2. **This manual:** operating rules for agents and humans. It does not define methodology.
3. **Other `docs/` pages:** summaries, decision records, QC records and engineering documentation. Where they
   restate the plan, the plan wins. `configs/` other than `analysis.yaml` hold paired machine-readable facts.
4. **Source code:** implementation, which may be under review. It never defines methodology.
5. **ECC, Claude, Codex, plugins, skills, hooks and agent memory:** workflow aids only. They cannot override the
   frozen specification or this manual, and they never authorize an analysis run.

If any source disagrees with the frozen specification, or implementation appears to require a methodology
change, **stop and flag it** for a dated amendment. Never resolve it by a silent code or documentation choice.

## 1. Scientific rules (non-negotiable)

1. **The subject is the independent experimental unit.** ROI rows are not independent samples. With primary N = 18,
   every inferential statement is about subjects.
2. **Subject grouping applies everywhere it is relevant:** train/test splitting, hyperparameter tuning,
   feature selection, preprocessing fitted on data (scalers, encoders, imputers), uncertainty estimation
   (bootstrap and permutation), and statistical comparison between models. Anything fitted on data goes inside
   the grouped CV loop. A subject must never contribute to both the fitting and the evaluation of the same fold.
3. **Never optimize toward a desired conclusion.** Do not reproduce, strengthen, or rescue a result by choosing
   among analyses after seeing outcomes. Analysis choices are fixed in config **before** results are inspected.
   Any post-hoc change is labelled post-hoc.
4. **Reviewer criticisms are hypotheses to test, not facts to accept.** Test each one against the data and code.
   Report what the test finds, whichever way it goes.
5. **Report negative, unstable, or null findings as they are.** Report per-subject distributions and uncertainty,
   not only means.
6. **Separate exploratory from confirmatory.** Label every analysis as one or the other. Confirmatory tests are
   pre-specified in config; exploratory results are never presented as inferential.
7. **Never silently drop ROIs, subjects, or features.** Every exclusion is explicit in config or code, logged with
   counts before and after, and justified in the run record. An inner join, `dropna`, or label mismatch that
   removes data is an exclusion.
8. **Document any discrepancy between manuscript text and implementation**, in `docs/`.
9. **Do not infer missing provenance.** If something cannot be established from evidence, record it as `UNKNOWN`.
10. **Reproducibility beats agreement with the old manuscript.** Matching historical numbers is never an
    acceptance criterion for new code.

## 2. Data rules

- Raw and original data are **read-only**. Never modify, move, or write into the dataset directory.
- Do not commit data. The dataset location is set **outside the repo**, as `bids_root` in the untracked
  `configs/paths.local.yaml` (see README). There is no environment-variable override. `data/` is git-ignored.
- **No machine-specific absolute paths in Python.** Paths come from config or the CLI.

## 3. Outputs and run records

- Historical results are never overwritten. New outputs go only into run-specific directories:
  `outputs/<YYYYMMDD-HHMMSS>_<run-name>_<shortsha>/`. Code must refuse to write into an existing run directory.
- Every analysis run writes a machine-readable run record in its output directory containing:
  git SHA (and whether the tree was dirty), UTC timestamp, exact CLI and resolved config, random seed(s),
  Python and package versions (plus FreeSurfer/FSL versions where used), input paths, input file hashes where
  practical, and the output directory.
- Runs from a dirty git tree are flagged in the record and are not used for reported results.

## 4. Code rules

- Small, tested functions in `src/`; tests in `tests/` (pytest). Leakage-sensitive logic, such as grouping,
  fold construction, and exclusion accounting, must have tests.
- Configuration lives in `configs/` (YAML). No hidden defaults that change scientific behaviour.
- Seeds are explicit and recorded. Never rely on implicit global randomness.
- Match the existing code's style. Keep dependencies minimal and add them to `environment.yml` deliberately.

## 5. Historical sources (migration only, not authoritative)

- The historical repositories `FinalTry` and `PET-MRI-BrainSynthesis` are **read-only migration sources**. Their
  local locations are machine-specific; `FinalTry` is set as `historical_finaltry` in `configs/paths.local.yaml`.
  They are **always read-only**: never modify, clean, commit to, or run analyses inside them.
- **Do not read them unless the user explicitly asks** for a provenance comparison. Cite the frozen record and
  the existing `docs/` findings instead.
- The frozen provenance record is in `PET-MRI-BrainSynthesis/provenance/manuscript_2025_2026/` (checksums,
  code snapshots, environments). Cite it; do not regenerate it.
- Code migrated from historical sources is reviewed and changed deliberately, never copied as authoritative.
  Record its origin (file and hash) in the commit message or `docs/`.
- Known historical defects that must not be reproduced silently:
  - the subcortical ROI label bug that left a cortex-only model set;
  - undocumented features and transforms (Gaussian curvature, log1p on area and volume);
  - a permutation-importance output that does not match the manuscript text;
  - `sub-SP06` missing from the v1.0.0 `participants.tsv` (fixed in release 1.0.1, which is canonical here);
  - undocumented handling of zero-valued rCPS voxels, and a displacing `bbregister` re-registration.

## 6. Agent workflow

- Do not commit, push, or rewrite history unless the user asks.
- Do not run modelling, FreeSurfer, PET processing, or other scientific analysis unless the user asks for that
  specific step.
- When unsure whether a choice is scientific (it affects results) or mechanical, treat it as scientific: state
  it and ask.

## 7. Read the right source first

1. `docs/analysis_plan.md` v3.0 + `configs/analysis.yaml` (tag `analysis-plan-v3.0`): frozen specification.
2. `docs/study-design.md`: question, observational unit, target and scope (summary).
3. `docs/dataset.md`: canonical release, identifiers, availability and acquisition provenance.
4. `docs/pipeline.md`: implemented modules versus missing/planned stages.
5. `docs/data-contracts.md`: actual array/QC schemas and required future assembly checks.
6. `docs/modeling.md`, `docs/inference.md`: implementation status and boundaries (summaries of plan §§7–12).
7. `docs/results-map.md`: generators, existing artifacts and invalidation dependencies.
8. `docs/qc_plan.md` + `docs/qc_decisions.md`: criteria, findings and dated QC decisions.
9. `docs/decisions/README.md`: accepted decision index and amendment policy.
10. `docs/audit-2026-09-29.md`: dated record of known gaps and unresolved discrepancies, not policy.

## 8. Invariants most easily broken in code

The frozen plan is authoritative for every value; cite its sections instead of copying numbers.

- Outer and inner cross-validation are subject-level; inner folds lie entirely within outer training
  subjects (§8). Every fitted quantity is refitted inside each inner and outer training split (§§7–8).
- No global fitted preprocessing, imputation, feature selection or target-dependent filtering (§§6–8).
- The primary statistic is the equal-subject mean of per-subject MSE differences, not pooled R² (§9).
- Permutations move whole-subject MRI blocks within the strata of `configs/analysis.yaml:permutation.strata`,
  in their listed order; never shuffle ROI rows or feature columns (§11). Read strata from config; do not
  hard-code subject lists or create duplicate configs.
- Each permutation replicate regenerates all MRI-dependent fitting and tuning; seed, B, sampling and
  identity/duplicate handling are exactly as frozen (§11.3–11.4).
- P1 is the only confirmatory test; everything else is descriptive or exploratory (§16).

## 9. Current boundaries

See `docs/pipeline.md` for the module map. There is no real-data model/permutation CLI, MRI parser, ROI-mean
target assembler, correlation runner or final model-figure generator yet. Do not invent paths or claim that a
synthetic-tested primitive completes the scientific pipeline.

## 10. Practical coding and testing

- Environment specifies Python 3.12; use `pathlib` and the existing small-function style.
- Run `python -m pytest -q tests`; tests insert `src` on the import path.
- For module CLIs use `PYTHONPATH=src python -m ...`; there is no Makefile/package installer.
- Prefer synthetic fixtures for modeling tests; do not load real outcomes to choose code/design.
- Test no train/test subject overlap and held-out perturbation invariance of fitted state.
- Test duplicate IDs and future subject × condition × ROI keys before merges/pivots.
- Test deterministic behavior, semantic ROI alignment and expected output schemas.
- Permutation work needs block/stratum integrity, identity/duplicate/cache multiplicity tests.
- Config integrity tests are not a substitute for tests of operational permutations.
- Meet `analysis_plan.md §15` before any real modeling run, including calibration/power checks.
- Fail explicitly on missing subjects/ROIs and nonfinite features/targets; log exclusions.
- Inspect git status first; preserve unrelated and pre-existing untracked user work.

## 11. Documentation and completion

Methodological changes require a dated amendment under `analysis_plan.md §14`, the
matching config change, a decision record where useful, and affected contract/results
map updates. Do this before inspecting affected results. Never erase historical text
or silently promote an exploratory result to a scientific assumption. Summary docs
point to plan sections rather than copying frozen values.

Before finishing, check:

- Does this affect subject independence or introduce leakage?
- Does this change exchangeability or the inferential population?
- Are train-derived transformations isolated from held-out subjects?
- Are whole-subject blocks, strata, seeds and schemas preserved?
- Which existing outputs become stale, and are regeneration requirements recorded?
- Do methodology, implementation status, config and docs still agree?
- Were relevant tests run, and are remaining limitations stated?
- Did raw/historical data remain untouched, with no unauthorized analysis or commit?
