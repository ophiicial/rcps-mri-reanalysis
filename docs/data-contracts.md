# Data contracts

Names below distinguish existing artifacts from future requirements. No reanalysis
merged dataframe or serialized prediction schema exists yet. Never assume the legacy
capitalized columns are the schema of a new analysis table.

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

`OuterFold` holds held-out subject/index, training/inner-validation indices, candidate
lambdas, inner losses `[N-1,7]`, scores `[7]`, selected lambda, fresh fit,
ROI baseline/ridge predictions `[68]`, two MSEs and `d_s`.
`LOSOSummary` holds IDs, `d_s`, `t`, mean baseline/ridge MSE. MSE, D and T have units
(nmol/g/min)². These are in-memory dataclasses, not a committed CSV schema.

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

## Required future assembly contract

Before a real-data runner is accepted: one condition-level observation per subject ×
condition × cortical ROI; one primary target per subject × ROI after exactly three
condition means are averaged equally. Validate duplicate keys before pivoting or
joining, exact roster/ROI/condition coverage, positive areas, finite/nonnegative
voxel targets, and one-to-one MRI correspondence. Log before/after counts and every
exclusion; never use an inner join or `dropna` as an undocumented filter.
Final serialized column names and filenames are **NOT YET IMPLEMENTED**.

## Historical CSVs (not new inputs)

`ALL_subjects_combined.csv`: logical key `Subject,Condition,StructName`.
`ALL_subjects_combined_avg.csv`: logical key `Subject,StructName` (Condition removed).
The historical combiner does not enforce those keys or all-three-condition coverage.
Predictors are `thickness_mm` (mm), `area_mm2` (mm²), `volume_mm3` (mm³),
`meancurv`, `gauscurv`, and categorical `StructName`. Curvature units in the historical
CSV are not explicitly established here. `PET_Mean` is the continuous target;
`PET_StdDev`, `PET_Volume_mm3` and other prefixed segstats fields are summaries, not
approved MRI predictors. Historical regression uses log1p(area/volume), unlike v3.0.
