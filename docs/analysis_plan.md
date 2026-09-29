# Analysis Plan: rCPS from Structural MRI (Reanalysis)

**Status: SCIENTIFIC SPECIFICATION FROZEN — 2026-09-28 (v3.0).** See §14 for the freeze and amendment rules.

- This document and [`configs/analysis.yaml`](../configs/analysis.yaml) together are the single authoritative
  specification. The config is the machine-readable copy of the choices below, and the two must agree.
- The dataset, cohort, spatial handling and zero handling rest on completed and reproduced QC
  ([`docs/qc_decisions.md`](qc_decisions.md)).
- Governing rules: [`AGENTS.md`](../AGENTS.md). Historical issues:
  [`historical_discrepancies.md`](historical_discrepancies.md).

**Revision history**

| Version | Date | Change |
|---|---|---|
| v1 | 2026-09-27 | Initial draft |
| v2 | 2026-09-27 | Independent methodological review: primary effect, comparator, model, features and inference replaced |
| v2.1 | 2026-09-27 | Primary cohort = ds004733 v1.0.1 roster (N = 18); S1 redefined |
| v2.2 | 2026-09-27 | QC decisions finalised; zero rule (primary includes zeros, S7 excludes) |
| **v3.0** | **2026-09-28** | **Frozen**, after the final independent audit. Normalised ridge objective and pooled scaling; λ grid with 0 and ∞; tolerance tie rule; E2-restricted permutation (4 acquisition strata); sampling, seed and reporting rules; S1–S7 frozen; subcortical and PVC/PVE deferred; implementation test requirements |

---

## 1. Two separate tracks

| Track | Purpose | Inputs | Status of results |
|---|---|---|---|
| **A. Historical reproduction** | Check whether the 2025 manuscript numbers (ROI+MRI mean R² 0.344, ROI-only 0.228, mean ΔR² 0.116) regenerate from the preserved code and CSVs | Frozen copies in `PET-MRI-BrainSynthesis/provenance/manuscript_2025_2026/` and the hashed manuscript-era CSVs | Provenance evidence only. **Never** used as, or mixed with, reanalysis results |
| **B. Corrected reanalysis** | Answer the scientific question | The canonical ds004733 v1.0.1 dataset **only**. All derived tables are regenerated in this repository | The results of this project |

Track B never reads manuscript-era derived files (`ALL_subjects_combined*.csv`, `fs_combined.csv`, `*_segstats.csv`,
`1.rCPS_alig/*`). Agreement with Track A is never an acceptance criterion.

## 2. Question, estimand and target

> In held-out subjects, does adding prespecified MRI morphometrics to ROI identity reduce the squared error of
> predicting **measured, uncorrected cortical ROI-mean rCPS**?

- **Target:** for each subject and each of the 68 cortical ROIs, the arithmetic mean of the three condition-specific
  ROI means: **mean rCPS across the three observed conditions** (Awake, SleepDeprived, Asleep). All three conditions
  are required. Units: nmol/g/min.
- **Measured, uncorrected:**
  - ROI means come from the supplied rCPS maps without partial-volume correction, so they are partly shaped by
    cortical geometry.
  - A predictive signal **must not** be interpreted as necessarily reflecting underlying biological protein
    synthesis.
- **Supplied-map zeros (limitation):**
  - The published maps contain exact-zero voxels, concentrated at brain/CSF boundaries (a median 5.8% of cortical
    voxels per scan; `qc_decisions.md` §3b).
  - The primary target includes them as supplied (§5), so it may contain mask/edge effects that are themselves
    related to cortical geometry.
  - Interpretation stays narrow: it concerns the supplied derivative's ROI means, not tissue protein synthesis.
  - S7 shows how much results depend on this.
- **What the primary test assesses:** whether the observed subject-level prediction-improvement statistic T is
  unusually large relative to the MRI–outcome reassignments allowed under the prespecified E2 exchangeability
  scheme (§11).
  - Rejection alone does not imply T_obs > 0; a positive observed improvement requires T_obs > 0.
  - Rejection does not establish positive population risk improvement, causality, mechanism or scanner-independent
    prediction (§11.6).

## 3. Cohort

**Canonical source: OpenNeuro ds004733 release 1.0.1** (DOI `10.18112/openneuro.ds004733.v1.0.1`; tag `1.0.1` =
commit `badd0108199e5b9f85451d317e472e5ee6105464`). The local verified copy is described in `qc_decisions.md` §6.

| | Definition | N |
|---|---|---|
| **Primary** | All subjects in the v1.0.1 `participants.tsv`: SP02, 03, 05, 06, 09, 10, 11, 12, 14, 15, 16, 18, 20, 21, 22, 23, 26, 28 | **18** |
| S1 (sensitivity) | The historical release-1.0.0 roster: the primary cohort without `sub-SP06`, taken from the same v1.0.1 data | 17 |

- Release 1.0.1 explicitly added `sub-SP06` to `participants.tsv`. Imaging and derivative content is identical
  between the releases.
- SP06 passes all automated and visual QC.
- The historical 1.0.0 roster issue is documented in `historical_discrepancies.md`. No reason for the omission is
  inferred.
- There are no QC exclusions (`qc_decisions.md` §4). Any future technical exclusion follows the prespecified QC
  rules, is independent of prediction results, and is logged.
- The cohort is read from `participants.tsv` at run time, checked against `configs/canonical_dataset.yaml`, and
  recorded in run provenance.

## 4. ROI scope

- The 68 bilateral Desikan–Killiany cortical ROIs (34 per hemisphere, as in `?h.aparc.stats`). `unknown` and
  `corpuscallosum` are excluded by definition, and left and right are separate ROIs.
- The code asserts that all 68 ROIs are present with valid target and features for every subject. Otherwise it fails
  with an explicit error; it never drops an ROI silently.
- **The study is cortical only.** Subcortical analysis is deferred (§13).

## 5. Target construction

1. **Inputs:** `derivatives/rCPS/sub-*/ses-{Awake,SleepDeprived,Asleep}/*_stat-rCPS_statmap.nii.gz` from the verified
   v1.0.1 copy.
2. **Spatial handling (final; `qc_decisions.md` §3):**
   - rCPS intensities stay on their supplied grid, with no additional PET registration.
   - `aparc+aseg` labels are resampled to that grid by nearest-neighbour interpolation through the verified
     scanner-RAS header mapping.
   - In QC, this preserved all 68 ROI labels and their voxel counts under that mapping.
3. **Condition-specific ROI value (primary):** the arithmetic mean of **all** voxel rCPS values within the label,
   **including exact-zero voxels as supplied**.
   - Numeric zero is not reinterpreted as missing without authoritative metadata.
   - For every subject × condition × ROI, the voxel count, zero count and zero fraction are recorded.
   - Non-finite or negative voxel values cause an explicit validation failure.
4. **Primary target:** the equally weighted mean of the three condition-specific ROI values.
   Condition-specific targets are used only in S2–S4.
5. **S7 target construction:** see §12.

## 6. Features

Features are read from each subject's `stats/?h.aparc.stats` (curator recon-all, FreeSurfer 7.3.2).

| Feature | Column | Transform (primary) |
|---|---|---|
| Cortical thickness | `ThickAvg` | none (mm) |
| Surface area | `SurfArea` (white surface) | **ln(area / 1 mm²)**; area must be > 0 |

- **Excluded from the primary analysis:** volume, curvatures, age, sex and eTIV. Only S5 uses additional
  morphometrics (§12).
- The historical log1p transform is **not** used anywhere.
- No feature is selected, added or removed on the basis of predictive performance.
- No PET-derived quantity enters any model; this is asserted in code.
- **Non-finite feature or outcome values:** explicit validation failure. No silent deletion and no imputation.

## 7. Primary model

**Notation.**

- T is a training set of m subjects; R = 68.
- x_{s,r,j} is feature j for subject s and ROI r; y_{s,r} is the target.

**Comparator (ROI-only baseline).** ŷ⁰_{s,r} = ȳ_{r,T}, the mean of y_{·,r} over the training subjects of the fold.
This is the ROI-identity predictor under squared loss. A global training mean may be reported descriptively only.

**Augmented model.** ROI fixed effects (unpenalised) plus shared ridge-penalised MRI slopes:
y_{s,r} = α_r + x_{s,r}ᵀβ + ε. It is implemented in the equivalent centred form (the equivalence must be verified by an implementation test before real modelling; §15):

1. **ROI centring (training only):**
   - μ_{r,j,T} = mean over s ∈ T of x_{s,r,j};
   - x̃_{s,r,j} = x_{s,r,j} − μ_{r,j,T}.
2. **Pooled scaling (training only; one scale per feature, ddof = 0, denominator mR):**
   - σ_{j,T} = sqrt( (1/(mR)) Σ_{s∈T} Σ_r x̃_{s,r,j}² );
   - z_{s,r,j} = x̃_{s,r,j} / σ_{j,T}.
   - Held-out subjects use the training μ and σ.
   - **If σ_{j,T} = 0**, predictor j is omitted for that fit, its contribution is forced to zero, and the event is
     recorded.
3. **Outcome residualisation:** u_{s,r} = y_{s,r} − ȳ_{r,T}.
4. **Objective (normalised):** minimise over β
   - (1/(mR)) Σ_{s∈T} Σ_r (u_{s,r} − z_{s,r}ᵀβ)² + λ‖β‖².
   - There is no additional intercept, and ROI effects are not penalised.
5. **Prediction:** ŷ_{s,r} = ȳ_{r,T} + z_{s,r}ᵀβ̂.

**λ grid (fixed; no adaptive refinement):** {0, 0.01, 0.1, 1, 10, 100, ∞}.

- **Finite λ > 0:** `sklearn.linear_model.Ridge(alpha = m·68·λ, fit_intercept=False, solver="svd")`. This alpha is
  exactly the normalised objective scaled by mR.
- **λ = 0:** the deterministic minimum-norm least-squares solution (`numpy.linalg.lstsq`, `rcond=None`, i.e. machine
  epsilon × max(rows, cols)). The numerical rank is recorded.
- **λ = ∞:** the solver is bypassed; slopes are zero, and predictions equal the training ROI means exactly (identical
  to the comparator).

**Tie rule (numerical tolerance only).**

- Let S_min be the minimum inner score over the grid and S_∞ the inner score of λ = ∞.
- A candidate is tied if S(λ) − S_min ≤ 1e-12 · S_∞. If S_∞ = 0, exact equality is required.
- Among tied candidates the **largest λ** is chosen, with ∞ the largest.

**Not part of the analysis:** random forest, model tournaments, mixed/hierarchical models, or covariate additions,
except by dated amendment (§14).

## 8. Cross-validation

| | Primary (N = 18) | S1 (N = 17) |
|---|---|---|
| Outer | subject LOSO, 18 folds; each fit trains on 17 subjects | 17 folds; 16 per fit |
| Inner (λ selection) | LOSO over the 17 outer-training subjects: 17 validation folds, each fit trains on 16 | 16 validation folds; 15 per fit |

- **Inner loss:** for an inner-held-out subject s, L_s(λ) = the mean over the 68 ROIs of the squared error.
- **Selection score:** S(λ) = the arithmetic mean of L_s(λ) over the inner-held-out subjects (equal-subject). Row-pooled
  scores and R² are never used.
- All preprocessing (ROI means of y and x, pooled σ, zero-variance handling) is recomputed inside every inner training
  set.
- After selection, preprocessing and the selected model are **refitted on all outer-training subjects** before the
  untouched outer subject is predicted.
- Inner-validation outcomes may influence only the candidate scores, and hence λ selection. They never enter fitted
  preprocessing or model parameters.

## 9. Primary effect and metrics

- **Per held-out subject:** D_s = MSE_s(ROI-only baseline) − MSE_s(ROI+MRI), each MSE over the 68 ROIs. Units:
  (nmol/g/min)².
- **Primary statistic:** **T = mean_s D_s** over the 18 outer subjects. Positive T means lower held-out MSE with MRI.
- **Descriptive only:**
  - R²_s and ΔR²_s (ΔR²_s = D_s / σ²_s, where σ²_s is the population variance of the subject's 68 targets);
  - MAE_s and RMSE_s for both models;
  - global-mean reference;
  - level/pattern decomposition (§10).
- **Zero target variance:** if a subject's target variance is 0, R²_s and ΔR²_s are **undefined** and are recorded as
  NA. No finite-value substitution (for example sklearn's) is used.
- **Reporting:** every subject-level value, plus mean, median, SD, IQR and range. ROI rows are never treated as
  independent observations for inference. Pooled row-level metrics are labelled descriptive.

## 10. Level / pattern decomposition (descriptive)

For subject s and model m, let e_{s,r} = y_{s,r} − ŷ^m_{s,r} and ē_s = (1/R) Σ_r e_{s,r}. Then exactly:

    MSE_s^m = ē_s² + (1/R) Σ_r (e_{s,r} − ē_s)²        (level error + centred regional-pattern error)

ē_s = observed subject mean − predicted subject mean, so this is algebraically identical to the independent review's
formulation in terms of subject means and centred patterns. D_s = D_s^level + D_s^pattern. This is descriptive and is
not a second test.

## 11. The single primary confirmatory test

### 11.1 Hypotheses and null

- **H1 (upper tail):** the observed T is unusually large relative to the E2-restricted permutation null.
- **Operational null (conditional on the fixed E2 strata):** conditional on recruitment-wave / broad MRI
  acquisition-family membership, whole-subject MRI assignments to outcome subjects are exchangeable within stratum.
- **Shorthand:** X_s ⫫ Y_s | Z_s, subject to within-stratum exchangeability.

### 11.2 Fixed permutation strata (E2 = recruitment wave × broad MRI acquisition family)

The strata are derived from acquisition metadata only. The factual provenance is recorded in
`qc_decisions.md` §8 ("Acquisition provenance relevant to exchangeability"). Using these groups as exchangeability
strata is a statistical decision of this plan.

| # | Stratum | Subjects |
|---|---|---|
| 1 | Wave 1: Siemens 3 T FLASH family | SP02, SP06, SP10 |
| 2 | Wave 1: Philips 1.5 T FFE | SP03, SP05, SP11, SP12, SP15 |
| 3 | Wave 1: Philips 3 T FFE | SP09, SP14 |
| 4 | Wave 2: Philips 3 T TFE | SP16, SP18, SP20, SP21, SP22, SP23, SP26, SP28 |

Valid permutation group: 3!·5!·2!·8! = **58,060,800** assignments.

### 11.3 One replicate

1. **Draw** one whole-subject MRI assignment **within strata**. Both MRI features move together as a block, and all
   68 ROI correspondences are preserved.
2. **Held fixed:** outcomes, outcome-subject identities, strata, outer and inner folds, and the λ grid.
3. **Scope:** one global assignment is used for the entire nested-CV replicate.
4. **Recomputed** in every replicate (every MRI-dependent step): feature centring, pooled scaling, zero-variance
   handling, inner tuning, outer refitting, and MRI-model predictions.
5. **May be cached:** outcome data, outcome ROI training means, ROI-only predictions and losses, the fixed folds, the
   λ grid, and results for exactly duplicated assignments.
6. **Never reused:** observed-data preprocessing, observed selected λs, or observed MRI fits.

### 11.4 Sampling, seed and ordering

- **Number of replicates:** B = **9999**.
- **Sampling:** independent, uniform and **with replacement** from the E2 group.
- **Identity and duplicates:** the identity assignment is allowed. Duplicates are allowed and keep their
  multiplicity; their computation may be cached.
- **Generator:** NumPy `PCG64`, seed **20260929**, used only for permutation sampling and independent of any model
  RNG.
- **Deterministic construction:**
  - Subjects are sorted lexicographically within each stratum, and strata are processed in the order of §11.2.
  - For each replicate and each stratum in turn, `rng.permutation(n_stratum)` gives π. Outcome subject `stratum[i]`
    receives the MRI block of `stratum[π[i]]`.
- **Pre-generation:** the full list of B assignments is generated **before** any (parallel) evaluation. It is saved,
  or recorded with a deterministic checksum, together with the NumPy / bit-generator version.

### 11.5 p-value and reporting

- Each replicate gives T_b, the same primary statistic.
- K = #{b : T_b ≥ T_obs}. Equality counts as exceedance.
- **p = (1 + K) / (B + 1) = (1 + K) / 10000.** The formal threshold is **p ≤ 0.05**.
- **Report:**
  - T_obs, K, B and p;
  - a 95% Clopper–Pearson interval for the full-group exceedance probability, from K successes in B draws;
  - optionally, the Monte Carlo SE sqrt(q̂(1 − q̂)/B) with q̂ = K/B;
  - the null distribution, saved.
- Monte Carlo uncertainty is **uncertainty from sampling permutations, not uncertainty in the prediction improvement**.
- No selective reruns, no seed changes, and no increase in B after results are seen.
- **No population confidence interval** is reported for T.

### 11.6 Interpretation

- **Rejection means:** T_obs is unusually large relative to MRI reassignment within the preserved strata. It supports
  a detectable individual MRI–rCPS correspondence beyond the preserved wave / acquisition-family structure.
- **Rejection alone does not establish:**
  - a positive observed improvement, unless T_obs > 0;
  - positive population risk improvement;
  - causality or biological mechanism;
  - scanner-independent prediction or external validity;
  - a population confidence interval.
- **Non-rejection** does not establish that MRI carries no information.
- There is **one** confirmatory test. No other analysis can declare the primary question answered.

## 12. Sensitivity analyses (descriptive only)

**Common rules for all sensitivities:**

- no p-values;
- reported whatever their direction;
- each has its own complete nested refitting and tuning, and never reuses primary selected λs or models;
- comparator = the training-only ROI mean;
- outcome = D_s and the §9 descriptives.

| ID | Specification |
|---|---|
| **S1** | The same v1.0.1 data with the historical N = 17 roster (SP06 excluded). Only membership changes; CV counts are in §8 |
| **S2** | Primary pipeline with the **Awake** target only |
| **S3** | Primary pipeline with the **SleepDeprived** target only |
| **S4** | Primary pipeline with the **Asleep** target only |
| **S5** | Five-feature ridge (see below) |
| **S6** | HGBR (see below) |
| **S7** | Zero-handling sensitivity (see below) |

**S5, five-feature ridge:**

- Features: thickness; ln(area / 1 mm²); ln(GrayVol / 1 mm³); MeanCurv untransformed; GausCurv untransformed.
- Area and volume must be > 0 and curvatures must be finite; otherwise explicit validation failure.
- The centring, pooled scaling, zero-variance, λ-grid, solver and tie machinery are identical to the primary model.

**S6, HGBR:**

- **Inputs:** categorical ROI identity with a fixed 68-level mapping (codes 0–67 in the order of
  `rcps.labels.dk_cortical_labels()`: lh 1001–1035 without 1004, then rh 2001–2035 without 2004), plus thickness and
  ln(area / 1 mm²). Continuous inputs are neither centred nor scaled.
- **Estimator:** `HistGradientBoostingRegressor(loss="squared_error", learning_rate=0.05, min_samples_leaf=20,
  l2_regularization=1.0, max_depth=None, max_bins=255, early_stopping=False, random_state=20260929)`.
  - No feature subsampling, and no monotonic or interaction constraints.
  - Histogram bins are fitted from training data only.
- **Grid (four candidates only):** max_leaf_nodes ∈ {3, 7} × max_iter ∈ {100, 300}.
- **Selection:** subject-grouped inner LOSO with equal-subject MSE. Numerical ties use the §7 tolerance first.
  Its reference scale S_∞ is the inner score of the training-only ROI-mean comparator, the same quantity as λ = ∞
  in the ridge rule. Remaining ties prefer (1) fewer leaves, then (2) fewer boosting iterations.
- There is no tuned HGBR ROI-only baseline.

**S7, zero-handling sensitivity:**

- Exact-zero rCPS voxels are excluded separately within each ROI × condition. Near-zero values are not removed.
- Labels, alignment and extraction are otherwise unchanged. Retained voxel counts and zero fractions are recorded.
- The three condition-specific ROI means are then averaged equally.
- If **any** ROI × condition has zero retained non-zero voxels, S7 (complete panel) is **not estimable**. In that
  case it is reported as such: no zero substitution, no ROI deletion, and no two-condition averaging.
  (QC found no such cell.)

**Also descriptive (not sensitivities):** D1 = R², ΔR², MAE, RMSE; D2 = the level/pattern decomposition (§10);
X1 = per-ROI morphometry–rCPS correlations across subjects; X2 = the distribution of fitted ridge slopes across
outer folds. X1 and X2 are exploratory and descriptive only.

## 13. Deferred work (not part of this study)

| Item | Disposition | Reason |
|---|---|---|
| Subcortical analysis | **Deferred** (future work) | Needs different features (thickness, area and curvature are undefined for aseg structures), new label harmonisation and a separate question. The study is cortical |
| PVC/PVE reprocessing | **Deferred** (future work) | rCPS is a derived kinetic map. A defensible PVC would need PSF/reconstruction modelling of the upstream PET and kinetic re-estimation, which is outside the supplied derivative. The study concerns measured, uncorrected ROI-mean rCPS, and the limitation is stated in §2 |

Neither item is an open pre-freeze choice, and neither may be run as part of this analysis without a dated amendment.

## 14. Freeze and amendment rules

- **The scientific specification was frozen on 2026-09-28** (this v3.0 plus `configs/analysis.yaml`).
- **After freeze:** any change needs a **dated amendment** here, with its justification, **before** any affected
  result is inspected. Amendments are appended to the revision history; earlier text is kept.
- **Fidelity:** the implementation must reproduce this document and `configs/analysis.yaml` exactly. Any discrepancy
  found in implementation is resolved by amendment, not by silent code choice.
- **Provenance:** every run records software versions, solver conventions (Ridge solver, lstsq `rcond`, numerical
  ranks), seeds, the categorical ROI mapping, the permutation-list checksum, the repository SHA and dirty flag, and
  the dataset tag and commit. Canonical-verifier results and config hashes are recorded in run provenance
  (`rcps.provenance`).

## 15. Implementation test requirements (before any real modelling run)

The following must be verified by automated tests on synthetic data before the primary analysis is run:

1. No outer-subject leakage: the outer held-out subject never enters any fitted quantity.
2. No inner-validation leakage into fitted preprocessing or model parameters. Inner-validation outcomes affect only
   candidate scores and λ selection. A perturbation test changes held-out data and asserts that all fitted
   quantities are unchanged.
3. λ = ∞ gives predictions exactly equal to the ROI-only baseline.
4. The sklearn `alpha = m·68·λ` conversion matches a direct solution of the normalised objective.
5. The centred formulation equals the one-hot, unpenalised-intercept formulation.
6. Zero-variance predictors are omitted, contribute zero, and the event is recorded.
7. The categorical ROI mapping is fixed and stable.
8. E2 permutations never cross strata. MRI blocks preserve ROI correspondence, and both features move together.
9. Identity and duplicate assignments are handled with the right multiplicity and caching. The permutation sequence
   is deterministic from the frozen seed and ordering.
10. R² is undefined (NA) for zero target variance.
11. S7 fails as "not estimable" when any ROI × condition has zero retained voxels.
12. The decomposition identity (§10) and ΔR²_s = D_s/σ²_s hold.
13. A synthetic null simulation shows a calibrated test, and a planted signal shows power.

## 16. Analysis register

| ID | Analysis | Role | Inference |
|---|---|---|---|
| **P1** | N = 18; 68 cortical ROIs; 3-condition mean target (zeros included); ROI-mean baseline vs ridge (thickness, ln area); nested LOSO; T = mean D_s; E2-restricted permutation test | **Primary confirmatory** | **The only formal test** |
| D1, D2 | R², ΔR², MAE, RMSE; level/pattern decomposition | Secondary | Descriptive |
| S1–S7 | §12 | Sensitivity | Descriptive |
| X1, X2 | Per-ROI correlations; fitted-slope distributions | Exploratory | Descriptive |
| R1 | Historical reproduction (Track A) | Provenance | — |
| — | Subcortical; PVC/PVE | **Deferred** (§13) | — |
