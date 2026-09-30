# Results and regeneration map

No reanalysis model metrics, predictions, correlations, permutation nulls, feature
importance tables or manuscript model figures exist yet. Model APIs return objects
in memory. Future filenames/manuscript section assignments are UNKNOWN until a runner
and manuscript are implemented. Historical artifacts cannot substitute for these.

## Existing reanalysis/QC artifacts

Paths below are inside a new `outputs/<timestamp>_<run-name>_<sha>/` directory.
No existing run is overwritten. Reference QC is `20260927-131732_qc_b4e9608`.

| Generator | Output | Consumer / invalidation trigger |
|---|---|---|
| `rcps.qc.verify_canonical` | `summary.json`, `file_checks.tsv`, `logs/run_metadata.json` | Dataset gate; reverify on dataset/manifest changes |
| `rcps.qc.run_qc` | `dataset/{source_manifest,published_verification,subject_eligibility,local_vs_published_metadata}.tsv`, inventory/published metadata | Dataset and QC decision docs; changed inputs/config/verification logic |
| `run_qc` / `spatial` | `geometry/{image_geometry,affine_checks}.tsv`, `coordinate_provenance.json` | Spatial decisions; geometry/QC code/input changes |
| `run_qc` / `spatial` | `labels/{roi_voxel_counts,label_integrity,left_right_check,zeros_by_tissue}.tsv`, `nn_label_images/*.nii.gz` | Spatial/zero decisions; labels, maps, spatial method or counting changes |
| `run_qc` / `spatial` | `alignment/{quantitative_metrics,perturbation_profiles,historical_bbregister_comparison}.tsv` | Registration comparison; metric/config/transform/input changes |
| `run_qc` / `overlays` | `overlays/<subject>/*_{multiplanar,small_rois,contact_sheet}.png`, `alignment/historical_overlays/*.png` | Visual QC; rendering/geometry/input changes |
| `rcps.qc.investigate_zeros` | `zero_voxels_by_scan.tsv`, `zero_voxels_cross_condition.tsv` | `qc_decisions.md §3b`; zero logic/maps/labels changes |
| `rcps.qc.investigate_curator_reg` | `curator_transform_comparison.tsv` | `qc_decisions.md §3`; comparison logic/inputs changes |

The two investigation runs have `nocommit`/dirty provenance and no clean rerun was
found. Their findings must not be used as reported results under AGENTS.md without
clean-tree regeneration. The clean reference QC reproduces the nine core imaging
tables, not automatically every separate investigation. Formal QC rating artifacts
and supplementary provenance were inspected as existing evidence, not recreated.
`20260927-025943_qc_nocommit` failed; later dirty verifier runs do not replace clean
reference provenance. Full provenance is described in [qc_decisions.md](qc_decisions.md).

## Historical manuscript artifacts (read-only)

Frozen inventory: `PET-MRI-BrainSynthesis/provenance/manuscript_2025_2026/inventories/manuscript_outputs.tsv`.
Frozen generator identity: sibling `code/SOURCES.tsv`.

| Artifact | Generator / status | Downstream consequence |
|---|---|---|
| `ALL_subjects_combined*.csv`, `{subject}_fs_combined.csv` | Historical combine/merge scripts, provenance snapshots | Historical models/correlations only; new targets/features must be regenerated |
| `loso_metrics_by_subject_compare.csv`, `test_predictions_loso_compare.csv` | eCjX manuscript-run regression snapshot, 2025-12-26 | Reported ROI+MRI/ROI-only R²; invalid as corrected-analysis estimates |
| `feature_importance_permutation_loso.csv` | Ej50 snapshot, separate 2025-12-24 run | Historical feature ranking; not same run as reported R², not subject-level inference |
| `loso_metrics_by_subject.csv`, `test_predictions_loso.csv` | JUEp no-ROI-ID run | Stale relative to reported comparison; do not mix |
| Correlation outputs cited by manuscript | Supporting run files not recovered | Manuscript magnitude claim remains unverifiable |

**Engineering/provenance policy (not frozen methodology):**
model/target/features/CV changes require regenerating all affected predictions,
metrics, fitted-slope summaries, nulls and dependent figures/tables in a future run.
Permutation-only changes require regenerating the null, p-value/Monte Carlo uncertainty
and inferential text; observed predictions may be retained only if model/data provenance
is unchanged and verified. Neither kind of change alone invalidates geometry QC.
Never manually edit result tables to imitate regeneration.
