# Analysis Plan: rCPS from Structural MRI (Reanalysis)

**Status: DRAFT — NOT FROZEN.**

- **Resolved:** the canonical dataset and cohort (ds004733 v1.0.1, N = 18) and the spatial handling / zero-voxel rule
  (`docs/qc_decisions.md`).
- **Freeze requires** the remaining statistical items in §13 to be fixed and independently checked.
- **Before any analysis run:** the clean v1.0.1 copy must be created and must pass
  `rcps.qc.verify_canonical --require-git`, and QC must be re-run from a committed tree.
- After freeze, any change to the primary analysis is a dated, justified amendment.

Governing rules: [`AGENTS.md`](../AGENTS.md). Historical issues: [`historical_discrepancies.md`](historical_discrepancies.md).
Revision history: v1 (initial draft); v2 (incorporates an independent methodological review; primary effect,
comparator, model, features and inference replaced); v2.1 (2026-09-27: primary cohort redefined as the
ds004733 v1.0.1 roster, N = 18; fold counts updated accordingly; S1 redefined. No other statistical or model
change); v2.2 (2026-09-27: QC decisions finalised. Spatial handling fixed; zero-voxel rule adopted with primary =
zeros included and a zero-handling sensitivity (S7); target limitation added; resolved items removed from §13).

---

## 1. Two separate tracks

| Track | Purpose | Inputs | Status of results |
|---|---|---|---|
| **A. Historical reproduction** | Check whether the 2025 manuscript numbers (ROI+MRI mean R² 0.344, ROI-only 0.228, mean ΔR² 0.116) regenerate from the preserved code and CSVs | Frozen copies in `PET-MRI-BrainSynthesis/provenance/manuscript_2025_2026/` and the hashed manuscript-era CSVs | Provenance evidence only. **Never** used as, or mixed with, reanalysis results |
| **B. Corrected reanalysis** | Answer the scientific question | The canonical ds004733 dataset **only**. All derived tables are regenerated in this repository | The results of this project |

Track B must not read manuscript-era derived files (`ALL_subjects_combined*.csv`, `fs_combined.csv`,
`*_segstats.csv`, `1.rCPS_alig/*`). Agreement with Track A is never an acceptance criterion.

## 2. Question, estimand and target

> In held-out subjects, does adding prespecified MRI morphometrics to ROI identity reduce the squared error of
> predicting **measured, uncorrected cortical ROI-mean rCPS**?

- **Target:** for each subject and each of the 68 cortical ROIs, the arithmetic **mean rCPS across the three
  observed conditions** (Awake, SleepDeprived, Asleep). All three conditions are required. Units: nmol/g/min.
- **Measured, uncorrected:** ROI means are taken from the supplied rCPS maps without partial-volume correction.
  ROI-mean rCPS is therefore partly shaped by cortical geometry through partial-volume effects. A predictive signal
  **must not** be interpreted as necessarily reflecting underlying biological protein synthesis (§12, T2).
- **Supplied-map zeros (limitation):** the published rCPS maps contain exact-zero voxels. They are concentrated at
  brain/CSF boundaries, and a median 5.8% of cortical voxels per scan are zero (`docs/qc_decisions.md` §3b). Their
  meaning is not documented. The primary target includes them as supplied (§5).
  - It may therefore contain mask/edge effects that are themselves related to cortical geometry.
  - Biological interpretation of any result must stay narrow: a statement about the supplied derivative's ROI means,
    not about tissue protein synthesis.
  - The zero-handling sensitivity (S7) shows how strongly results depend on this.
- **What the primary test assesses:** whether the pipeline detects a subject-specific MRI–rCPS association that
  improves out-of-subject squared-error prediction in this sample. It does **not** assess a causal effect of
  morphology, and it does not guarantee improved risk in the population.

## 3. Cohort

**Canonical cohort definition: OpenNeuro ds004733 release 1.0.1** (2026-05-20; DOI
`10.18112/openneuro.ds004733.v1.0.1`; GitHub-mirror tag `1.0.1` = commit `badd0108199e5b9f85451d317e472e5ee6105464`).

| | Definition | Expected N |
|---|---|---|
| **Primary** | All subjects listed in the **v1.0.1** `participants.tsv` | **18**: SP02, 03, 05, **06**, 09, 10, 11, 12, 14, 15, 16, 18, 20, 21, 22, 23, 26, 28 |
| Sensitivity S1 | Primary minus `sub-SP06`, i.e. the release-1.0.0 roster. Descriptive only | 17 |

- Release 1.0.0 (2023-12-08) listed 17 subjects. Release **1.0.1 explicitly adds `sub-SP06`** to `participants.tsv`.
  Its CHANGES entry reads "Added a row for sub-SP06 in participants.tsv".
- Imaging and derivative content is **identical** between the releases. Only `CHANGES`, `dataset_description.json`
  (DOI) and `participants.tsv` differ (`docs/qc_decisions.md` §1).
- `sub-SP06` passes every automated QC rule and the visual rating (`docs/qc_decisions.md` §4). Therefore **N = 18
  is the primary cohort** of the new analysis.
- The historical N = 17 metadata issue stays documented in `docs/historical_discrepancies.md`. It no longer defines
  the cohort. No reason for SP06's absence from v1.0.0 is inferred.
- The published 1.0.1 `README` is unchanged from 1.0.0 and still states 9 F + 8 M (17). The 1.0.1
  `participants.tsv` lists SP06 as F, age 21 (10 F + 8 M). This inconsistency is recorded, not interpreted.
- Technical or QC exclusions, if any, follow the prespecified rules in `docs/qc_plan.md`. Those rules are fixed
  before any predictive modelling and are independent of prediction results. Every exclusion is logged.
- Cohort membership is derived from the v1.0.1 `participants.tsv` at run time and written to the run record.

## 4. ROI scope

- **Primary:** the 68 bilateral Desikan–Killiany cortical ROIs (34 per hemisphere, as listed in `?h.aparc.stats`).
  `unknown` and `corpuscallosum` are excluded by definition. Left and right are separate ROIs.
- For every subject the code asserts that all 68 ROIs are present with valid target and features, and it fails
  otherwise. It never drops ROIs silently.
- **Subcortical:** optional, exploratory, and **separate** (E3). Subcortical structures are never combined with
  cortical ROIs in a shared morphology model, because thickness, area and curvature are not defined equivalently
  for them.

## 5. Target construction (regenerated from source)

1. rCPS maps: `derivatives/rCPS/sub-*/ses-{Awake,SleepDeprived,Asleep}/*_stat-rCPS_statmap.nii.gz`.
2. Spatial handling (**decided**; `docs/qc_decisions.md` §3; to be confirmed by the committed QC re-run on the clean
   copy):
   - No additional PET registration.
   - rCPS intensities stay on their supplied grid.
   - `aparc+aseg` labels are resampled to that grid by nearest-neighbour interpolation through the scanner-RAS header
     mapping (lossless: ROI voxel counts equal the native counts).
   - The historical `bbregister` transforms are not used.
   - Basis: FreeSurfer ran on the exact published T1w (`rawavg` voxel-identical); rCPS and T1w share their affines;
     header alignment sits within ~0.7 mm (median) of the local NMI optimum in the brain interior; and the historical
     transforms scored lower on every metric in every scan.
3. ROI value (**primary**): the arithmetic mean of **all** voxel rCPS values within each cortical label, per subject
   and condition, **including exact-zero voxels exactly as supplied** in the published derivative.
   - Numeric zero is not reinterpreted as missing or invalid, because no authoritative metadata or validity mask says
     so (`docs/qc_decisions.md` §3b).
   - For every subject × condition × ROI the pipeline records the voxel count, **zero count** and **zero fraction**
     (and asserts that there are no non-finite or negative values).
   - **Zero-handling sensitivity (S7):** ROI means recomputed over voxels with rCPS ≠ 0. This is a sensitivity
     analysis, not an alternative primary definition.
4. Primary target: the mean of the three condition ROI values. Condition-specific targets are used only in S2–S4.

## 6. Features

**Primary MRI features** (read from each subject's `stats/?h.aparc.stats`, curator recon-all, FreeSurfer 7.3.2):

| Feature | Column | Units | Transform |
|---|---|---|---|
| Cortical thickness | `ThickAvg` | mm | none |
| Surface area | `SurfArea` (white surface) | mm² | **natural log**, ln(mm²). The code asserts area > 0 |

**Excluded from the primary analysis:** cortical volume, mean curvature, Gaussian curvature, age, sex and eTIV.
**Sensitivity S5:** all five historical morphometrics (thickness, ln area, cortical GM volume `GrayVol`, `MeanCurv`,
`GausCurv`). The volume transform (ln) must be fixed before freeze. The historical log1p is **not** inherited.

No feature is selected, added or removed based on observed predictive performance. No PET-derived quantity may
enter any model, and this is asserted in code.

## 7. Models

Notation: y_{s,r} is the target for subject s and ROI r; x_{s,r} is its MRI feature vector; R = 68.

**Primary comparator: ROI-mean baseline.** For held-out subject s, ŷ⁰_{s,r} = ȳ_r, the mean of y_{·,r} over the
**training subjects** of that outer fold. This is the optimal ROI-identity-only predictor under squared loss. The
global training mean is kept as a descriptive reference only.

**Primary augmented model: ROI fixed effects + shared ridge-penalised MRI slopes.**

    y_{s,r} = α_r + x_{s,r}ᵀβ + ε_{s,r},   minimise  Σ (y − α_r − xᵀβ)² + λ‖β‖²   (α_r unpenalised)

- **Equivalent implementation (must be documented and tested):** because α is unpenalised and every training
  subject has all 68 ROIs, minimising over α gives α_r = ȳ_r − x̄_rᵀβ (Frisch–Waugh–Lovell).
  - Fitting reduces to ridge without intercept on within-ROI-centred data: ỹ = y − ȳ_r and x̃ = x − x̄_r, with ROI
    means taken over training subjects.
  - Prediction: ŷ_{s,r} = ȳ_r + (x_{s,r} − x̄_r)ᵀβ̂.
  - A test must show numerically that this matches the one-hot, unpenalised-intercept formulation.
  - As λ → ∞, the model reduces exactly to the ROI-mean baseline, so the two models are nested.
- **Scaling:** after within-ROI centring, each feature is divided by its SD over the training rows of the fold, so the
  penalty is scale-invariant. The exact scaling rule is to be checked independently (§13).
- **λ tuning:** a prespecified log-spaced grid, fixed before any run and to be checked independently (§13). The grid
  and the tie-breaking rule (choose the larger λ on ties) are stored in config.

**Nonlinear sensitivity S6: historical-style HGBR.**

- `HistGradientBoostingRegressor` with ROI identity and the primary MRI features, compared against the same ROI-mean
  baseline.
- A small prespecified hyperparameter grid, tuned by the same subject-grouped inner CV with equal-subject loss.
- `early_stopping=False` set explicitly, no feature subsampling, fixed `random_state`.
- Exact encoding of ROI identity and grid: to be fixed before freeze.

**Not part of the core analysis:** random forest, any model tournament. A mixed or hierarchical model is added only if
a specific scientific reason emerges, and it is documented as an amendment.

## 8. Cross-validation

- **Outer:** leave-one-subject-out (18 folds for the primary analysis).
- **Inner:** within the training subjects of each outer fold, grouped strictly by subject. Proposed: inner LOSO over
  the 17 training subjects, which is cheap for closed-form ridge.
- **Inner selection criterion:** equal-subject prediction loss, i.e. the mean over inner-held-out subjects of each
  subject's MSE. The default row-pooled R² scorer is not used.
- Every fitted operation happens inside the relevant training split: ROI means, feature centring and scaling, λ
  selection, and HGBR tuning.
- Estimator behaviour that performs internal row-random validation or early stopping is explicitly disabled or
  controlled.
- **Required tests** (§11): no subject leakage in outer folds, inner folds, preprocessing or tuning.

## 9. Metrics and summaries

Per held-out subject s, over its 68 ROIs:

- **Primary effect:** D_s = MSE_s(ROI-mean baseline) − MSE_s(ROI+MRI). Positive means MRI improves prediction.
  Units: (nmol/g/min)².
- **Secondary, descriptive:**
  - R²_s for both models (sklearn definition, subject's own mean in the denominator) and ΔR²_s. Note the identity
    ΔR²_s = D_s / σ²_s, where σ²_s is the population variance of y across subject s's 68 ROIs. ΔR² is therefore D_s
    reweighted by each subject's regional variance, which is why D_s is primary;
  - MAE_s and RMSE_s for both models, and their differences;
  - level / pattern decomposition (§10).

Each quantity is reported as all subject-level values (table and paired/strip plot) plus mean, median, SD, IQR and
range. ROI rows are **never** treated as independent observations for inference. Pooled row-level metrics may be
shown only as labelled descriptive values.

## 10. Level / pattern decomposition (secondary, descriptive)

For subject s and model m, let e_{s,r} = y_{s,r} − ŷ^m_{s,r} and ē_s = (1/R) Σ_r e_{s,r}. Then, exactly:

    MSE_s^m = ē_s²                          (level error: squared error of the predicted subject mean)
            + (1/R) Σ_r (e_{s,r} − ē_s)²      (centred regional-pattern error)

So D_s = D_s^level + D_s^pattern, with each term differenced between the two models. This is descriptive and is
not a second primary test. The identity is verified by unit test.

*Reconciled with the independent review:* the review's formulation, in terms of observed and predicted subject
means and centred patterns, is algebraically identical to the residual form above.
MSE = mean(e)² + mean((e − mean(e))²), with mean(e) = observed subject mean − predicted subject mean.

## 11. Inference: the single primary confirmatory test

**Global whole-subject MRI permutation test** of H1: MRI provides positive incremental predictive information
(upper tail).

- **Statistic:** T = mean_s(D_s) over the primary cohort.
- **One replicate:**
  1. Draw one permutation π of the cohort's subjects, uniformly over all permutations; **not** restricted to
     derangements, so the identity is allowed.
  2. Outcome subject s receives subject π(s)'s complete MRI feature block, with ROI correspondence preserved
     (π(s)'s ROI r is paired with s's ROI r).
  3. This one global permutation is used for the entire nested-CV replicate: the training rows and test rows of
     every fold.
  4. Rerun all MRI-dependent steps (centring, scaling, inner λ tuning, ROI+MRI fitting) and recompute T.
- **Held fixed across replicates:** outer and inner fold definitions, the candidate hyperparameter grid, and the seed
  policy. ROI-only predictions are cached, because they do not depend on MRI.
- **Exchangeability:** subjects are treated as exchangeable under H0. If a valid restriction is discovered before
  freeze (for example a design stratum), permutations are restricted to preserve it and the restriction is
  documented.
- **p-value:** p = (1 + #{T*_b ≥ T_obs}) / (B + 1), with target **B = 9999**. This is feasible for closed-form ridge.
  Report the Monte Carlo uncertainty of the estimated p: its binomial SE √(p̂(1−p̂)/B) and a Clopper–Pearson 95%
  interval for the exceedance probability. The null distribution and permutation seed are saved.
- There is **one** primary confirmatory test. No other analysis can be used to declare the primary question
  answered positively.
- **Removed from formal inference:** the sign-flip test (it was never exact under LOSO dependence), the
  sign-flip-inversion CI, the fixed-score BCa CI, and the order-statistic median CI.
- **No population 95% CI** is reported for T. Reporting is: point estimate of T, all D_s, descriptive summaries, the
  permutation null and p, and the Monte Carlo uncertainty of p. Any future full-pipeline bootstrap CI would need
  separate justification and would be labelled exploratory.

**Required tests before any real run:**

- outer, inner, preprocessing and tuning leakage tests. These include perturbing the held-out subject's data and
  asserting that every training-derived quantity (ROI means, centring and scaling constants, the chosen λ) is
  unchanged;
- the FWL equivalence test (§7);
- a permutation block-integrity test (ROI correspondence preserved; ROI-only cache unchanged);
- the decomposition identity (§10) and the ΔR²_s = D_s/σ²_s identity (§9);
- a synthetic-data check that the test is calibrated under a null simulation and has power under a planted signal.

## 12. Analysis register

| ID | Analysis | Role | Inference |
|---|---|---|---|
| **P1** | N = 18 (v1.0.1 roster), 68 cortical ROIs, 3-condition mean target; ROI-mean baseline vs ridge (thickness, ln area); LOSO; T = mean D_s; global permutation test | **Primary confirmatory** | **The only formal test** |
| D1 | R²_s, ΔR²_s, MAE_s, RMSE_s for P1 | Secondary | Descriptive |
| D2 | Level / pattern decomposition of P1 (§10) | Secondary | Descriptive |
| S1 | P1 without SP06, i.e. the v1.0.0 roster (N = 17) | Sensitivity | Descriptive |
| S2–S4 | P1 with Awake / SleepDeprived / Asleep targets | Sensitivity | Descriptive |
| S5 | P1 with all five morphometrics | Sensitivity | Descriptive |
| S6 | HGBR (§7) vs the ROI-mean baseline | Sensitivity | Descriptive |
| S7 | Zero-handling sensitivity: P1 with ROI means computed excluding exact-zero voxels (§5.3) | Sensitivity | Descriptive |
| E1 | Per-ROI morphometry–rCPS correlations across subjects | Exploratory | Descriptive only |
| E2 | Interpretation of fitted ridge slopes across folds (per-fold β distribution) | Exploratory | Descriptive only |
| E3 | Separate subcortical analysis, if approved | Exploratory | Descriptive only |
| T1 | PET–MRI spatial handling: **decided** (`qc_decisions.md` §3) | Technical decision | — |
| T2 | PVC / PVE sensitivity feasibility (optional; §13.5) | Technical item | — |
| R1 | Historical reproduction (Track A) | Provenance | — |

Sensitivity and exploratory analyses report the same descriptive summaries as P1. They do not carry confirmatory
p-values, and they cannot rescue or overturn the primary conclusion. Disagreement between them and P1 is reported
as a finding. Seed sensitivity is not required for the deterministic ridge pipeline; S6 uses a fixed seed with
deterministic settings.

## 13. Decisions still open before freeze

Only statistical and implementation items remain. Dataset, cohort, spatial handling and zero handling are resolved
(`docs/qc_decisions.md`).

1. **Ridge details:** feature scaling rule, λ grid, tie-breaking, and the inner scheme (inner LOSO over the 17
   training subjects proposed). To be independently checked.
2. **Permutation implementation:** exchangeability (any restrictions), B, Monte Carlo reporting, and whether every
   MRI-dependent step is rerun per replicate. To be independently checked.
3. **S5 exact specification:** volume transform (ln) and exact column choices.
4. **S6 exact specification:** HGBR ROI encoding and hyperparameter grid.
5. **Optional exploratory work:** whether to run E3 (subcortical: structures, features, label map) and whether a
   defensible PVC/PVE sensitivity is feasible (T2). Neither is part of the primary analysis.
