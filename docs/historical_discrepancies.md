# Historical Discrepancies (2025 manuscript analysis)

This file documents discrepancies between the 2025 manuscript, its historical code, and its saved outputs. **The
historical files are not modified.** The evidence is frozen in
`PET-MRI-BrainSynthesis/provenance/manuscript_2025_2026/` (abbreviated `prov/` below). "Manuscript" means the
submitted text (`FinalTry/article.md`, whose content is repeated in the resubmission template `.docx`).

| # | Topic | Manuscript says | Implementation / evidence shows | Evidence |
|---|---|---|---|---|
| 1 | ROI scope | Cortical **and subcortical** aparc+aseg regions (§2.2.3, §2.3, Fig. 1 caption, Discussion) | Model input was **cortical only**: 68 DK ROIs × 18 subjects = 1,224 rows. `legacy/5.Merge_MRI_txt.py` L67–68 renames aseg `Left-*`/`Right-*` to `ctx-lh-*`/`ctx-rh-*`; the inner join with PET labels (`left-*`) drops all lateralised subcortical structures. The remaining 12 non-cortical ROIs (ventricles, CC, brainstem, CSF…) lacked cortical features and were removed by `dropna` in `Regression_model.py` | `prov/code/legacy_5.Merge_MRI_txt.py`; `prov/inventories/manuscript_outputs.tsv` (`test_predictions_loso_compare.csv`: 1,224 rows) |
| 2 | Cohort / SP06 | "Dataset reports 17 … derivative release contains 18 … numbering … may account for the additional directory" | In release **1.0.0** (the version the historical work used), `participants.tsv` listed 17 subjects and omitted `sub-SP06`, which has raw and derivative data but no `_sessions.tsv`. SP06 was included in all historical analyses. The manuscript's numbering explanation is incorrect: the metadata identifies SP06 directly. **Release 1.0.1 (2026-05-20) adds the SP06 row** ("Added a row for sub-SP06 in participants.tsv"); imaging is unchanged. The new analysis uses the 1.0.1 roster (N = 18), so this is now a historical metadata issue only. The reason for the 1.0.0 omission is UNKNOWN. The 1.0.1 README still states 9 F + 8 M | Dataset `participants.tsv` (1.0.0, 1.0.1); `docs/qc_decisions.md` §1–2 |
| 3 | Features and transforms | Thickness, surface area, mean curvature, GM volume | Model also used **Gaussian curvature**; **log1p** applied to volume and area (`load_data`); StandardScaler on all five. Not fully described | `prov/code/Regression_model__…eCjX…py` |
| 4 | Feature importance | "Surface area and cortical thickness consistently ranked as the strongest contributors, followed by curvature; volumetry smaller" | Only surviving output (`feature_importance_permutation_loso.csv`, from a **separate** 2025-12-24 18:13 run, code version Ej50, not the run that produced the reported R²): StructName 0.623 > **Gaussian curvature 0.214** > thickness 0.159 > area 0.095 > mean curvature 0.050 > volume 0.031. The reported R² run (2025-12-26) did not compute importance. The "dispersion" column is the mean of within-fold SDs, not the spread across folds | `prov/inventories/manuscript_outputs.tsv`; `prov/evidence/zsh_history_pipeline_excerpt.tsv` |
| 5 | PET–MRI registration | PET registered to T1 with `bbregister` | Implementation matches the text, but the dataset **appears** to supply rCPS maps already aligned: all 54 maps have exactly the raw T1w affine and grid, `orig.mgz` shares the world space, and the local README states co-registration (unverified; see qc_plan §1). QC (`docs/qc_decisions.md` §3), judged on identical criteria rather than on the change itself: the historical transforms displace cortical labels a mean 8.4 mm (range 2.9–14.8, rotations up to 8.3°); score lower similarity than header alignment on all 4 metrics in 54/54 scans (the inverse transform too); and place ~3.8× more label voxels on zero-valued rCPS. Min costs 0.90–0.996, correlated with displacement (r = 0.68). The header-based labels passed the formal visual rating in 54/54 scans; the historical-transform overlays were inspected only in spot checks | `prov/inventories/finaltry_1.rCPS_alig.*`; `docs/qc_plan.md` |
| 6 | Interpolation | Not specified | PET intensities interpolated with **cubic** `mri_vol2vol` into FreeSurfer T1 space before segstats | `FinalTry/Register_rCPS.py` (= `legacy/1.register_rCPS.py` logic) |
| 7 | Tuning / models | "For each algorithm (Random Forest or HGBR), hyperparameters were tuned …" | Only HGBR was ever tuned (`--tune 20`, `GroupKFold(3)`, row-pooled `r2` scoring). No RF LOSO output exists. The ROI-only comparator was also a tuned HGBR, not ROI means | `prov/code/…eCjX…py`; zsh history |
| 8 | Mean baseline | "Performance exceeded a mean baseline predictor" | Baseline metrics were computed per fold but never saved in LOSO mode. Unverifiable | `prov/code/…eCjX…py` |
| 9 | Correlations | "\|r\| ≈ 0.1–0.4" | The output files supporting this no longer exist (only Jan–Feb 2025 copies in `FinalTry/trash/`, from an older pipeline) | Audit 2026-09-27 |
| 10 | Code availability | "All … code used to generate the results is provided in the GitHub repository" | `5.Merge_MRI_txt.py` was never in any repository. The code that produced the reported R² (VS Code snapshot eCjX) was never committed; 49d3998 differs only in the default data path. The current `Extract_MRI_statistics.py` writes a schema that the current `Combine_MRI_rCPS.py` cannot consume, so the pipeline cannot regenerate the model input end to end | `prov/code/SOURCES.tsv` |
| 11 | Software versions | Not stated | FreeSurfer: recon-all 7.3.2 (dataset curators) but extraction, registration and segstats ran with 8.0.0-beta. The Python / scikit-learn environment of the reported run is **UNKNOWN** (thesis or base with sklearn 1.5.1, or rcps-env with 1.7.2) | `prov/environments/` |
| 12 | Stale outputs | — | `loso_metrics_by_subject.csv` and `test_predictions_loso.csv` in the historical output folder come from a 2025-12-24 `--no-roi-id` run and are unrelated to the reported results | `prov/inventories/manuscript_outputs.tsv` |
| 13 | Zero-valued rCPS voxels | Not mentioned ("values were averaged within each cortical and subcortical region") | The supplied rCPS maps contain exact zeros in a median 5.8% (2.4–12.8%) of cortical voxels per scan, concentrated at brain/CSF boundaries (`docs/qc_decisions.md` §3b). The historical `mri_segstats` ROI means included them as ordinary values. The historical pipeline also interpolated PET cubically into T1 space after a displacing `bbregister`, which mixed zeros further into neighbouring labels. Handling of zeros was undocumented | `docs/qc_decisions.md` §3b; `FinalTry/1.rCPS_alig/*_segstats.txt` (command lines) |

**Reported numbers traced exactly:**

- `loso_metrics_by_subject_compare.csv` (2025-12-26 13:17:05) gives ROI+MRI R² 0.3436 (SD 0.3157), ROI-only 0.2277
  (SD 0.3964), ΔR² 0.1159 (SD 0.3151, range −0.352 to 0.899).
- Command: `python3 Regression_model.py --model hgbr --tune 20 --cv-mode loso` (seed 42 default, no log target, no
  ROI filter).

## Audit clarification — 2026-09-29

The local README co-registration claim in row 5 was subsequently verified against the
published text (`qc_decisions.md §1`); the “unverified” wording records the earlier
audit stage. The supplied-grid spatial decision is now accepted.

Frozen eCjX `fit_and_evaluate` fits `Pipeline(pre, RandomizedSearchCV(estimator))`.
The scaler/encoder therefore see the inner-validation subjects before inner tuning,
although the outer held-out subject is excluded. The numerical impact is UNKNOWN.
Historical permutation **importance** is feature-column shuffling over test rows,
not a subject-block permutation test of the primary prediction-improvement statistic.
See [the repository audit](audit-2026-09-29.md) for bounded findings.
