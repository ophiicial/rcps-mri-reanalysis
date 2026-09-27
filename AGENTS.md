# Project Instructions (canonical for Claude, Codex, and humans)

This repository is the **only** place for new analysis, validation, figures, tables, and resubmission work for the
PET-MRI study on predicting regional cerebral protein synthesis (rCPS) from structural MRI morphometrics.
Status: **reconstruction / reanalysis**. The goal is a correct, reproducible analysis. It is **not** to recover
the conclusion of the rejected 2025 manuscript.

## 1. Scientific rules (non-negotiable)

1. **The subject is the independent experimental unit.** ROI rows are not independent samples. With N ≈ 18,
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
