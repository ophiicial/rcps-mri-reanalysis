# Project Instructions (canonical for Claude, Codex, and humans)

This repository is the **only** place for new analysis, validation, figures, tables, and resubmission work for the
PET-MRI study on predicting regional cerebral protein synthesis (rCPS) from structural MRI morphometrics.
Status: **reconstruction / reanalysis**. The goal is a correct, reproducible analysis. It is **not** to recover
the conclusion of the rejected 2025 manuscript.

The target is continuous measured cortical ROI-mean rCPS from OpenNeuro ds004733 1.0.1.
This is regression, not classification. Primary prediction asks whether thickness and
ln(surface area) improve over training ROI means in held-out subjects.

Authority: this manual + accepted methodology in `docs/`; paired machine-readable
choices/facts in `configs/`; ECC memory is temporary session knowledge; source code is
implementation, which may be under review. If docs/config disagree, flag the conflict
and follow the frozen amendment procedure rather than choosing silently.

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
- Do not commit data. The dataset location is set **outside the repo** (environment variable or an untracked
  local config; see README). `data/` is git-ignored.
- **No machine-specific absolute paths in Python.** Paths come from config, the CLI, or the environment.

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
  Never modify, clean, commit to, or run analyses inside them.
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

- `docs/study-design.md`: question, observational unit, target and scope.
- `docs/dataset.md`: canonical release, identifiers, availability and acquisition provenance.
- `docs/pipeline.md`: actual modules versus missing/planned stages.
- `docs/data-contracts.md`: actual array/QC schemas and required future assembly checks.
- `docs/modeling.md`: training-only preprocessing, nested LOSO and implementation status.
- `docs/inference.md`: accepted null, exchangeability, permutation object and interpretation.
- `docs/results-map.md`: generators, existing artifacts and invalidation dependencies.
- `docs/analysis_plan.md` v3.0 + `configs/analysis.yaml`: frozen scientific specification.
- `docs/qc_plan.md` + `docs/qc_decisions.md`: criteria, findings and dated QC decisions.
- `docs/decisions/README.md`: accepted decision index and amendment policy.
- `docs/audit-2026-09-29.md`: known gaps and unresolved discrepancies, not new policy.

## 8. Accepted modeling and inference invariants

- P1 has 18 subjects, 68 bilateral DK cortical ROIs, two MRI features.
- Target averages Awake, SleepDeprived and Asleep equally; all three are required.
- Include exact-zero voxels in primary ROI means; S7 is the specified sensitivity.
- Keep supplied rCPS intensities on their grid; nearest-neighbour resample labels only.
- Outer subject LOSO; inner subject LOSO entirely within outer training subjects.
- Fit ROI means, feature scales and models separately in every inner/outer training split.
- No global fitted preprocessing, imputation, feature selection or target-dependent filtering.
- ROI baseline uses training subjects only; selection averages subject MSE equally.
- Primary statistic is mean subject baseline MSE minus augmented MSE, not pooled R².
- Whole-subject MRI blocks move together for the accepted permutation test.
- Never independently shuffle ROI rows or feature columns for confirmatory inference.
- Preserve ROI correspondence and fixed outcomes/folds in each global assignment.
- Restrict assignments to `configs/analysis.yaml:permutation.strata` in its listed order.
- Do not hard-code those subject lists in production code or create duplicate configs.
- Regenerate all MRI-dependent fitted quantities and tuning for each assignment.
- Preserve identity/duplicate multiplicity, seed and B exactly as frozen in config.
- Inference is conditional on recruitment/acquisition structure, not scanner-independent biology.
- P1 is the only confirmatory test; sensitivities and X1/X2 are descriptive.
- See inference docs for donor IDs versus outcome IDs under the accepted global shuffle.

## 9. Pipeline map and current boundaries

| Module | Purpose |
|---|---|
| `rcps.qc.verify_canonical` | Hash/roster/git verification; writes a run record |
| `rcps.qc.run_qc` | Dataset inventory, spatial checks, label counts, overlays |
| `rcps.qc.investigate_zeros` | Zero-valued voxel diagnostics, not ROI-mean targets |
| `rcps.qc.investigate_curator_reg` | Curator-transform comparison, not new registration |
| `rcps.labels`, `rcps.fsgeom` | DK identities and coordinate/label utilities |
| `rcps.analysis.ridge` | Fit/predict/score primitives on complete transformed panels |
| `rcps.analysis.cv` | Nested LOSO; untracked at 2026-09-29 audit start, since committed (`18471e9`) |
| `rcps.provenance`, `rcps.runrecord` | Provenance and non-reused output directories |

There is no real-data model/permutation CLI, MRI parser, ROI-mean target assembler,
correlation runner or final model-figure generator here yet. Do not invent paths or
claim that a synthetic-tested primitive completes the scientific pipeline.

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
- Keep dependency additions deliberate; environment versions are not fully pinned.
- Fail explicitly on missing subjects/ROIs and nonfinite features/targets; log exclusions.
- Inspect git status first; preserve unrelated and pre-existing untracked user work.

## 11. Documentation and completion

Methodological changes require a dated amendment under `analysis_plan.md §14`, the
matching config change, a decision record where useful, and affected contract/results
map updates. Do this before inspecting affected results. Never erase historical text
or silently promote an exploratory result to a scientific assumption.

Before finishing, check:

- Does this affect subject independence or introduce leakage?
- Does this change exchangeability or the inferential population?
- Are train-derived transformations isolated from held-out subjects?
- Are whole-subject blocks, strata, seeds and schemas preserved?
- Which existing outputs become stale, and are regeneration requirements recorded?
- Do methodology, implementation status, config and docs still agree?
- Were relevant tests run, and are remaining limitations stated?
- Did raw/historical data remain untouched, with no unauthorized analysis or commit?
