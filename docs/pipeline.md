# Pipeline: implemented versus specified

Read [analysis_plan.md](analysis_plan.md) for accepted methodology. A plan statement
that code “asserts” something is a requirement until the implementation exists.
There is no Makefile, package installer, or raw-data-to-inference end-to-end runner.
The primary runner loads and validates the saved authoritative panel before passing it to `rcps.analysis`.
Use `PYTHONPATH=src` for module CLIs. Tests add `src` via `tests/conftest.py`.

| Stage | Actual module / function | Input → transformation → output | QC and downstream use |
|---|---|---|---|
| Canonical verification | `rcps.qc.verify_canonical` | Configured dataset + expected manifest → hashes/roster/git checks → `file_checks.tsv`, `summary.json`, run record | CLI exits nonzero on failure; required before reported analysis |
| Dataset inventory | `rcps.qc.run_qc`, `rcps.qc.dataset` | Metadata, derivatives, published release via `gh api` → inventory/hash/eligibility tables | `dataset/` supports cohort/provenance decisions |
| Spatial QC | `rcps.qc.spatial.audit_subject`, `rcps.labels.resample_labels_nn` | T1w, supplied rCPS, aparc+aseg → scanner-RAS nearest-neighbour labels, voxel counts, alignment diagnostics | `geometry/`, `labels/`, `alignment/`; supports spatial decisions, not target extraction |
| QC figures | `rcps.qc.overlays` called by `run_qc` | Anatomy, labels, rCPS → multiplanar/small-ROI/contact-sheet PNGs | Visual QC, not manuscript model figures |
| Historical registration comparison | `rcps.qc.spatial.historical_subject` via `run_qc` | Read-only historical LTAs → displacement/NMI comparisons and overlays | No new registration applied to analysis targets |
| Curator transform comparison | `rcps.qc.investigate_curator_reg` | Curator LTAs + images → `curator_transform_comparison.tsv` | Investigation only |
| Zero investigation | `rcps.qc.investigate_zeros` | Supplied maps/anatomy/mean PET → scan and cross-condition zero diagnostics | No ROI means or predictive analysis |
| Ridge primitives | `rcps.analysis.ridge` | Already transformed complete training panels → fitted ROI means/scales/slopes and predictions | Synthetic tests; no extraction or provenance gate |
| Nested LOSO | `rcps.analysis.cv` | Aligned IDs, X, Y → `OuterFold` objects and `LOSOSummary` | Synthetic tests; no persistence/CLI |
| Canonical primary panel | `rcps.panel` (`build` CLI; `spec`, `sources`, `mri`, `rcps_roi`, `assemble`) | Verified v1.0.1 aparc.stats, aparc+aseg, supplied rCPS maps → condition ROI means, long table, `CanonicalPanel` X `[18,68,2]` / y `[18,68]`, manifest | Data validity only; see [data-contracts.md](data-contracts.md). Saved artifact consumed by the primary runner |
| Synthetic calibration/power study | `rcps.analysis.calibration` (CLI `--preset quick|full`) | Own synthetic X/y (frozen strata) → Phase-4 engine per dataset → rejection rates, intervals | Synthetic only; outputs `outputs/<ts>_calibration-synthetic-<preset>_<sha>/`; `full` preset fixed (nulls 500 × B 39; power 200 × B 99), not yet run |
| Permutation engine | `rcps.analysis.permutation` | Frozen strata/seed/B → pre-generated donor assignments; permuted X → `nested_loso` → T_b, K, p, Monte Carlo uncertainty | Used by the primary runner; implementation does not imply completed real-data inference |
| Real-data P1 runner | `rcps.analysis.run_primary` | Saved canonical panel → manifest/array-hash/provenance gates → observed LOSO or frozen permutation inference | Separate `primary-observed` / `primary-permutation` run directories; clean committed tree required |
| Sensitivities, correlations, final figures/tables | **Not implemented here** | Frozen plan + validated panels → future run artifacts | Do not claim completed inference |

The primary CLI has two explicit modes: `python -m rcps.analysis.run_primary observed`, then
`python -m rcps.analysis.run_primary permutation --observed-run outputs/<observed-run>`.
Both use `outputs/20260930-175425_panel_62eb246/panel/`; no raw panel rebuilding or scientific overrides
are exposed. Permutation mode requires the same code commit and panel/spec identity as the completed
observed run and exact `T_obs` agreement before the null loop and with the permutation result.
Each run saves `summary.json`, `outer_folds.tsv`, `fold_diagnostics.json`, and `logs/run_metadata.json`;
permutation additionally saves `null_statistics.npy` and `assignments.npy`. Summary descriptives are the
currently supported equal-subject MSE means and D_s; additional planned descriptives remain unimplemented.
Canonical-verifier provenance is inherited explicitly from the saved panel build, not rerun on raw data.
Implementation and synthetic validation do not authorize execution; plan §15 remains a prerequisite.

## Historical chain (read-only migration evidence)

`FinalTry/Register_rCPS.py` invokes bbregister and cubic resampling;
`Extract_rCPS_statistics.py` invokes segstats and CSV conversion.
`Extract_MRI_statistics.py` produces FreeSurfer measure tables;
`legacy/5.Merge_MRI_txt.py` creates `{subject}_fs_combined.csv`.
`Combine_MRI_rCPS.py` inner-joins on `StructName`, writes condition-specific files,
`ALL_subjects_combined.csv`, and condition-averaged `ALL_subjects_combined_avg.csv`.
`Regression_model.py` consumes the latter; `Correlation_Analysis.py` computes per-ROI
correlations across subjects after aggregation. These files are **not runnable stages
of the reanalysis** and some current historical versions do not interoperate.

The manuscript-run and importance-run snapshots are distinct; exact filenames and
hashes are in frozen `PET-MRI-BrainSynthesis/provenance/manuscript_2025_2026/code/SOURCES.tsv`.
See [historical_discrepancies.md](historical_discrepancies.md) and
[results-map.md](results-map.md). No historical code was migrated by this audit.
