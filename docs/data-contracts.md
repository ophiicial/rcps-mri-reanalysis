# Data contracts

Names below distinguish existing artifacts from future requirements. The canonical
primary panel (below) is implemented; no serialized prediction schema exists yet. Never
assume the legacy capitalized columns are the schema of a new analysis table.

## Existing model API

| Name | Type / shape | Meaning / role / units |
|---|---|---|
| `subject_ids` | unique nonempty strings, length N | Identifier; caller order preserved; primary wrapper checks N=18, not canonical membership |
| `x` | finite real array `[N,68,F]` | Aligned subject × ROI × MRI feature predictors; F=2 for primary wrapper |
| `y` | finite real array `[N,68]` | Subject × ROI target, nmol/g/min; condition aggregation must occur upstream |
| feature 0 | `thickness`, `ThickAvg` source | Primary predictor, mm, no transform |
| feature 1 | `ln_area`, `SurfArea` source | Primary predictor, ln(area / 1 mm²); positive area required upstream |
| ROI axis | 68 positions | `dk_cortical_labels()` order; ctx-lh then ctx-rh, codes 1001–1035 / 2001–2035 excluding 1004/2004 |

The array API checks dimensions/finiteness, not semantic ROI order, units, condition
completeness, feature provenance, or whether PET data entered X. Upstream construction
must verify all of those. `primary_loso` intentionally accepts synthetic IDs.
`nested_loso` rejects duplicate IDs and masked panels; primitives do not accept IDs.

`OuterFold` (`rcps.analysis.cv`, frozen dataclass; arrays are read-only). Shapes use
N subjects, n_λ candidates (7 for the frozen grid) and F features; primary shapes in brackets.

| Field | Type / shape | Meaning |
|---|---|---|
| `held_out_index`, `subject_id` | int, str | Outer held-out subject (caller order) |
| `training_indices`, `inner_validation_indices` | int tuples, length N-1 | Outer-training subjects; each is an inner validation subject once |
| `lambdas` | float tuple, n_λ | Candidates in caller order; must be the complete frozen grid |
| `inner_losses` | float `[N-1, n_λ]` [17, 7] | Inner validation subject × candidate MSE |
| `inner_scores` | float `[n_λ]` [7] | Equal-subject mean of `inner_losses`, paired with `lambdas` |
| `inner_omitted` | bool `[N-1, n_λ, F]` [17, 7, 2] | Zero-variance predictor omission event per inner validation subject × candidate × feature |
| `inner_rank` | int64 `[N-1]` [17] | Numerical rank of each inner λ=0 fit |
| `selected_lambda` | float | Tie-rule selection from `inner_scores` |
| `fit` | `RidgeFit` | Fresh outer-training fit; carries its own `preprocessing.omitted` mask and `numerical_rank` (λ=0 only, else `None`) |
| `baseline_prediction`, `ridge_prediction` | float `[68]` | Held-out subject predictions, nmol/g/min |
| `baseline_mse`, `ridge_mse`, `d_s` | float | Held-out MSEs and their difference |

`inner_omitted` and `inner_rank` are provenance/diagnostic arrays required by the plan's
recording rules. They are **not reusable fitted state**: no inner preprocessing, means or
coefficients are retained, and any later evaluation (including a permutation replicate)
must refit every inner and outer model normally. `InnerFitDiagnostic` and the
`on_inner_fit` callback are test/diagnostic hooks only and are not part of the production
data contract.

`LOSOSummary` holds IDs, `d_s`, `t`, mean baseline/ridge MSE. MSE, D and T have units
(nmol/g/min)². These are in-memory dataclasses, not a committed CSV schema.

## Permutation engine (`rcps.analysis.permutation`)

In-memory API only; nothing is persisted yet. The scheme comes from `analysis.yaml`
(`load_scheme()`). Config validation fails if the strata do not partition
`cohort.primary.subjects`, if the group size differs, or if a frozen contract field
(type, sampling, exceedance, p-value, PCG64) departs from the implemented rule.
`load_scheme(config)` also accepts synthetic test schemes. Any real-data entry point must use
`frozen_scheme()` / `require_frozen_scheme()`, which requires equality with the scheme built from
the tagged `analysis-plan-v3.0` config (commit `80d951f`) and checks B, seed, group size and strata
count against fixed anchors.

| Object | Content |
|---|---|
| `PermutationScheme` | `canonical_subjects` (cohort order), `strata_names`, `strata` (listed order, subjects sorted within each), `stratum_index`, `group_size`, `b`, `seed` |
| `PermutationAssignments` | Read-only `donors` int64 `[B, N]`, `numpy_version`, `sha256` |
| `PermutationResult` | `t_obs`, read-only `null` `[B]` in replicate order, `k`, `b`, `p_value`, `monte_carlo`, `assignments_sha256`, `numpy_version`, `n_evaluations`, `n_cache_hits` |
| `MonteCarloUncertainty` | `q_hat = K/B`, `mc_se`, `clopper_pearson_95`; permutation-sampling uncertainty only |

**Assignment representation.** `donors[b, i] = j` means that, in replicate b, outcome subject
`canonical_subjects[i]` receives the complete `[68, F]` MRI block of `canonical_subjects[j]`.
- Donor arrays must already have an integer dtype. Floats (even `2.0`), bools, objects and masked arrays are rejected before any coercion.
- Each row must be a bijection on 0..N-1 that never crosses a stratum. Rows are validated at construction.
- The checksum is SHA-256 of the scheme provenance JSON (subjects, strata, group size, B, seed, bit generator), followed by the little-endian int64 donor bytes.
- `panel_donor_positions` maps a row onto any panel subject order by ID, so a panel does not need canonical order.
- The frozen sequence is regression-pinned in `tests/test_permutation.py`.

**Evaluation.**
- Masked X or y are rejected at the permutation boundary.
- `permute_mri` returns `x[donors]` and verifies that every block is intact.
- y, subject IDs, the ROI axis, folds and the λ grid are never changed.
- `permuted_folds` runs `nested_loso` on the permuted X, which recomputes every MRI-dependent quantity. No observed-data fit, scale, omission or λ is passed in.
- T_obs uses the identity row through the same path.
- `run_permutation_test` refuses an assignment list whose length differs from the scheme's B.

**Cache semantics.** `evaluate_null` evaluates replicates in index order.
- With `cache=True`, an exact duplicate row reuses the stored T_b, but still occupies its own position in `null`. K and the null therefore keep the full multiplicity; identity draws are kept.
- `n_evaluations + n_cache_hits = B`.
- No outcome-only intermediate is cached yet.

## Existing QC tables

All are tab-separated; QC identifiers use lowercase names. Source is
`rcps.qc.spatial` unless stated. Rows are diagnostic observations, not independent samples.

| Artifact (inside QC run) | Row / key | Important fields |
|---|---|---|
| `dataset/subject_eligibility.tsv` | `subject_id` | Boolean input/roster availability, per-condition map counts; `rcps.qc.dataset.eligibility` |
| `geometry/image_geometry.tsv` | `subject,image,condition` | shape, zooms, affine, orientation, qform/sform; condition empty for anatomy |
| `geometry/affine_checks.tsv` | `subject,check` | mixed-type `value`, Boolean `pass`, text `note` |
| `labels/roi_voxel_counts.tsv` | `subject,condition,code` | ROI diagnostic columns detailed below |
| `labels/label_integrity.tsv` | `subject,condition` | expected/present ROI counts, missing labels, support counts |
| `labels/left_right_check.tsv` | `subject,condition` | homologous-pair count and failing pairs |
| `labels/zeros_by_tissue.tsv` | `subject,condition,tissue` | voxel count and zero fraction |
| `alignment/quantitative_metrics.tsv` | `subject,condition,metric` | header/mirrored NMI, profile maxima, optional local-optimum displacement |
| `alignment/perturbation_profiles.tsv` | `subject,condition,metric,axis,offset` | NMI and difference from header; offset mm for t axes, degrees for r axes |

`roi_voxel_counts.tsv` has 3,672 rows in reference QC (18×3×68):

| Column | Type / units | Meaning |
|---|---|---|
| `subject`, `condition`, `roi` | string | Full subject ID, exact condition, `ctx-{lh,rh}-{name}` label |
| `code` | integer | FreeSurfer aparc+aseg label code; identifier, not numeric predictor |
| `n_voxels_rcps_grid`, `n_voxels_native_aparc` | integer voxels | Resampled and native ROI sizes |
| `ratio_rcps_to_native` | float, dimensionless | Resampled/native count ratio |
| `n_nonfinite`, `n_zero`, `n_negative` | integer voxels | QC counts, not predictors |
| `frac_zero_or_nonfinite` | float fraction | Union of zero/nonfinite voxels / ROI voxels; not strictly zero fraction if nonfinite exists |
| `centroid_x`, `centroid_y`, `centroid_z` | float mm | Scanner-RAS ROI centroid |

No rCPS mean is present in that QC table. Manifest tables use `relpath`, `bytes`,
`sha256`; the run source manifest adds `mtime_epoch`, and expected manifest adds
`verified_against`. Verification adds `status` (OK/MISSING/MISMATCH).

## Canonical primary panel (`rcps.panel`)

Built by `PYTHONPATH=src python -m rcps.panel.build` from the verified v1.0.1 copy only.
The CLI refuses to run unless `verify_canonical --require-git` passes. Every input must be
listed in `configs/ds004733_v1.0.1_expected_sha256.tsv` and is hash-checked when read
(`rcps.panel.sources.CanonicalSources`). Unlisted files, absolute or `..` manifest paths,
files whose resolved path (symlinks followed) leaves `bids_root`, and ambiguous rCPS maps
fail. git-annex symlinks into the dataset's own `.git/annex` stay inside and are accepted. The builder implements only the v3.0 primary choices:
`rcps.panel.spec.require_frozen_primary_contract` fails if `analysis.yaml` differs from them.
The panel layer never imports `rcps.analysis`.

| Input (dataset-relative) | Used for |
|---|---|
| `derivatives/freesurfer/<sub>/stats/{lh,rh}.aparc.stats` | `ThickAvg`, `SurfArea`; header must match subject, hemisphere, `?h.aparc.annot`, white surface, units mm / mm^2 |
| `derivatives/freesurfer/<sub>/mri/aparc+aseg.mgz` | Labels, NN-resampled onto each rCPS grid (`rcps.labels.resample_labels_nn`) |
| `derivatives/rCPS/<sub>/ses-<condition>/*_stat-rCPS_statmap.{nii.gz,json}` | Supplied rCPS values; sidecar units must be `nmol/g/min` |

Order: subjects follow `analysis.yaml:cohort.primary.subjects`, checked for equality with
`canonical_dataset.yaml:expected_participants` and, as a set, with `participants.tsv`.
Order is never discovered from files. ROIs follow `dk_cortical_labels()`; conditions follow
`analysis.yaml:target.conditions`. All tables are rebuilt in this key order, so input row
order has no effect. Duplicate, missing or extra keys fail; nothing is joined, dropped, filled or imputed.

**`panel/condition_roi_values.tsv`**: 3,672 rows, key `subject_id, condition, roi`.

| Column | Type / units | Meaning |
|---|---|---|
| `rcps_roi_mean` | float, nmol/g/min | Mean of all label voxels on the supplied grid, exact zeros included |
| `n_voxels`, `n_zero` | int voxels | Voxels averaged and exact-zero voxels among them |
| `zero_fraction` | float | `n_zero / n_voxels` |
| `source_relpath` | string | rCPS map used |

Before extraction the whole supplied 3-D map must be finite and nonnegative (any voxel, labelled or not);
exact zeros are valid. A label with no voxel fails. Counts must be integers with
0 ≤ `n_zero` ≤ `n_voxels`, `n_voxels` > 0, and `zero_fraction` exactly `n_zero / n_voxels`.

**`panel/long_table.tsv`**: 1,224 rows, key `subject_id, roi`. Rows are observations
nested in 18 subjects, not independent samples.

| Column | Type / units | Meaning |
|---|---|---|
| `subject_id`, `roi` | string | Canonical IDs (`sub-SPxx`, `ctx-{lh,rh}-<name>`) |
| `roi_index`, `roi_code`, `hemisphere` | int, int, `lh`/`rh` | Position on the ROI axis (0–67), aparc+aseg code |
| `thickness_mm` | float, mm | `ThickAvg`, untransformed; must be finite (no sign threshold) |
| `area_mm2` | float, mm² | `SurfArea`, raw (must be > 0) |
| `ln_area` | float | Natural log of `area_mm2 / 1 mm²` (not log1p) |
| `rcps_awake`, `rcps_sleep_deprived`, `rcps_asleep` | float, nmol/g/min | Condition ROI means |
| `rcps_mean` | float, nmol/g/min | Primary target: the three condition means summed in config order, divided by 3 |

Validation recomputes `ln_area` and `rcps_mean` and requires exact equality. Read these
TSVs with `rcps.panel.assemble.read_table_tsv`, which parses floats round-trip.
pandas' default parser can change the last bit.

**`CanonicalPanel`** (`panel_from_long_table`): frozen dataclass with read-only arrays.

| Field | Value |
|---|---|
| `subject_ids`, `roi_names`, `roi_codes` | Axis labels in canonical order |
| `feature_names` | `("thickness", "ln_area")`, the config feature names |
| `conditions`, `target_definition` | Condition order and a text statement of the target rule |
| `x` | float `[18, 68, 2]`: thickness, ln_area |
| `y` | float `[18, 68]`: `rcps_mean` |

The panel is not standardized; `rcps.analysis.ridge` fits all centring and scaling per split.

**`panel/panel_manifest.json`** is deterministic: no timestamps, machine paths or repository
state. It records the spec version, the frozen tag `analysis-plan-v3.0`, its commit and the tagged
`analysis_plan.md`/`analysis.yaml` hashes (the build fails if the working copies differ), the dataset identity and
expected-manifest hash, subject and ROI rosters with their hashes, conditions, feature and
target definitions, spatial handling, dimensions, every source relpath with its SHA-256,
and content hashes of `x`, `y` (float64 little-endian) and both TSVs.
`panel/validity_summary.json` holds data-validity counts and ranges only. The run record
(`logs/run_metadata.json`) adds repository state, the verifier result and config hashes.

## Historical CSVs (not new inputs)

`ALL_subjects_combined.csv`: logical key `Subject,Condition,StructName`.
`ALL_subjects_combined_avg.csv`: logical key `Subject,StructName` (Condition removed).
The historical combiner does not enforce those keys or all-three-condition coverage.
Predictors are `thickness_mm` (mm), `area_mm2` (mm²), `volume_mm3` (mm³),
`meancurv`, `gauscurv`, and categorical `StructName`. Curvature units in the historical
CSV are not explicitly established here. `PET_Mean` is the continuous target;
`PET_StdDev`, `PET_Volume_mm3` and other prefixed segstats fields are summaries, not
approved MRI predictors. Historical regression uses log1p(area/volume), unlike v3.0.
