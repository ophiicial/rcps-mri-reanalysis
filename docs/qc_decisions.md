# QC Decisions: Canonical Dataset and PET–MRI Spatial Handling

**Status: FINAL for the primary analysis (2026-09-27).**

| Item | Status |
|---|---|
| Canonical dataset creation (DataLad clone of ds004733, tag `1.0.1`) | **COMPLETE** |
| Canonical verification (`rcps.qc.verify_canonical --require-git`) | **PASS**: 444/444 files, roster 18/18, HEAD = release commit, clean tree |
| Committed-tree QC rerun (repo `b4e9608`, clean) against the canonical copy | **PASS**: reproduces the pre-commit QC exactly (§7) |
| Spatial handling | **FINAL** for the primary analysis (§3) |
| Cohort | **FINAL**: v1.0.1 roster, N = 18; S1 = v1.0.0 roster, N = 17, descriptive (§2) |
| Zero handling | **FINAL**: primary includes exact zeros; S7 excludes them (§3b) |

No predictive modelling has been run, and no ROI-mean target has been computed.

**Runs** (git-ignored; regenerate from the listed modules):

| Run | Content | Module |
|---|---|---|
| **`outputs/20260927-131732_qc_b4e9608/`** | **Reference QC run**: committed tree `b4e9608` (clean, `usable_for_reported_results: true`) against the canonical v1.0.1 copy. Supplementary record: `logs/supplementary_provenance.json` | `rcps.qc.run_qc` |
| `outputs/20260927-131655_verify-canonical_b4e9608/` | Canonical verification: 444/444 PASS | `rcps.qc.verify_canonical --require-git` |
| `outputs/20260927-030610_qc_nocommit/` | Pre-commit QC (uncommitted tree, pre-canonical local copy); superseded by the reference run, reproduced exactly | `rcps.qc.run_qc` |
| `outputs/20260927-112615_zero-investigation_nocommit/` | Zero-valued rCPS voxels (§3b) | `rcps.qc.investigate_zeros` |
| `outputs/20260927-112818_curator-reg-investigation_nocommit/` | Curators' PETPrep PET→T1 transforms under the same criteria (§3) | `rcps.qc.investigate_curator_reg` |
| `outputs/20260927-025943_qc_nocommit/` | **Failed run** (table-writer crash; `logs/RUN_FAILED.txt`). Do not use | — |

Rules: `docs/qc_plan.md` §2b (written before cohort-wide results were inspected). The R9 rating criteria were fixed
before the formal rating pass.

---

## 1. Canonical dataset: verification evidence

| Item | Finding | Evidence (`dataset/` in the QC run) |
|---|---|---|
| Accession | OpenNeuro **ds004733**. Official GitHub mirror `OpenNeuroDatasets/ds004733`. Tags: `1.0.0` = `d8265dd32f0ee8a67953b87fc8f42b2f675870ec` (2023-12-08); **`1.0.1` = `badd0108199e5b9f85451d317e472e5ee6105464` (2026-05-20, latest)** | `published/`, OpenNeuro GraphQL |
| Local full copy vs 1.0.0 | **443 / 444** fingerprinted files identical. All **342 annexed** files match the published SHA-256 annex keys; 101 / 102 git-tracked files match their blob SHA | `published_verification.tsv` |
| Local modification | `README`: **one inserted line** in the Reference section, a Greek sentence about a "random forest regression model … predicting rCPS". Apparently an accidental local edit, unrelated to the dataset. Everything else matches the published README. Left untouched | `local_vs_authoritative_metadata_diff/README__published_1.0.0_vs_local.diff` |
| 1.0.0 → 1.0.1 | Only `CHANGES`, `dataset_description.json` (DOI → v1.0.1) and **`participants.tsv` (adds `sub-SP06`, 21, F)** changed. **No imaging or derivative file changed** (441 / 444 manifest paths share the identical blob across tags). The README is unchanged, so it still states 9 F + 8 M. 1.0.1 still has no `sub-SP06_sessions.tsv` (17 session files) | GitHub compare; `same_blob_in_1.0.1` |
| Derivatives-only copy (`Research/…`) | All 381 derivative manifest files are byte-identical to the full copy. It lacks the BIDS metadata and raw T1w | `identical_in_PET-MRI` |
| Source fingerprint | `source_manifest.tsv`: 444 files, manifest SHA-256 `844ac49f56f5d5cc289f1a8b16ab35ff97f07c60373dc5591f35f0b0ec1e0136` | `source_manifest.tsv` |

## 2. Cohort (decided)

- **Primary cohort = the ds004733 v1.0.1 `participants.tsv` roster: N = 18** (SP02, 03, 05, **06**, 09, 10, 11, 12,
  14, 15, 16, 18, 20, 21, 22, 23, 26, 28). See `docs/analysis_plan.md` §3.
- Every one of the 18 has all required inputs and passes every automated and visual QC rule (§4). No QC exclusions.
- The former conflict (D2) is resolved by the investigators' decision to use v1.0.1.
- The v1.0.0 omission of SP06 stays documented as historical. No reason for it is inferred.
- Table: `dataset/subject_eligibility.tsv`.

## 3. Spatial handling (decided)

**Coordinate provenance, all 18 subjects:**

- rCPS voxel → scanner RAS (NIfTI sform, qform identical) → aparc+aseg voxel (inverse MGH scanner vox2ras).
  tkregister RAS is not used.
- `rawavg.mgz` is **voxel-identical** to the published T1w for every subject. recon-all's input was the MiDeFace
  T1w.
- Every rCPS map has exactly the T1w grid and affine. The published README states that the T1w was co-registered to
  the rCPS images.
- Header identity was **not** taken as proof of anatomical correspondence. It was tested as follows.

**Evidence:**

- **Header / orientation:** 54/54 scans pass R2, R3 and R10.
- **Labels:** NN resampling is lossless (count ratio 1.000). All 68 DK ROIs are present in every scan; minimum 995
  voxels.
- **Left–right:** 34/34 pairs are correctly ordered in all scans. Header NMI exceeds mirrored-anatomy NMI for all 4
  metrics in 54/54 scans.
- **Quantitative alignment** (primary metric `nmi_t1_interior`): every single-axis profile peaks within ±1 mm / ±1°.
  The local 6-DOF optimum lies a median **0.68 mm** (max 2.08 mm) mean cortical displacement from the header
  alignment (peak displacement max 3.27 mm); NMI gains are ≤ 0.006.
- **Curators' own PET→T1 transforms** (`rcps-modified-petprep` `from-pet_to-T1w_reg.lta`; `mri_coreg` of the mean PET,
  which is on the same grid; used by the curators to sample the rCPS maps onto surfaces):
  - they differ from header alignment by a median 1.65 mm mean cortical displacement (0.72° rotation; max 3.1 mm
    mean, 6.7 mm peak);
  - on the primary metric they are neither better nor worse than header alignment (better in 26/54; median ΔNMI
    −0.0001);
  - on both tissue-class metrics they are lower in 54/54;
  - the inverse transform is worse than the transform itself in 54/54 (primary metric), which confirms the direction
    convention.
  - **Interpretation:** two independent alignment routes agree to about 1–2 mm, and neither improves on the header
    alignment by these criteria. This scale matches the estimated local-optimum offsets and the curators' assumed
    4 mm PET PSF (`mri_gtmpvc --psf 4`).
- **Historical `bbregister`** (evaluated after the baseline): the transforms displace cortical labels a mean **8.4 mm**
  (2.9–14.8; rotations up to 8.3°).
  - They score lower than header alignment on all 4 metrics in 54/54 scans (the inverse also scores lower in 54/54).
  - They place ~3.8× more cortical label voxels on zero-valued rCPS.
  - Registration cost correlates with displacement (r = 0.68).
  - This is judged on identical criteria, not on the mere fact that the transform differs.
- **Visual rating (R9):** 54/54 PASS (§4).

**Decision:**

- **no additional PET registration**;
- rCPS intensities stay on their supplied grid;
- `aparc+aseg` is resampled to that grid with **nearest-neighbour** interpolation via the scanner-RAS header
  mapping;
- neither the historical `bbregister` nor the curators' PETPrep transforms are applied.

## 3b. Zero-valued rCPS voxels (D3): evidence and decision

Run: `outputs/20260927-112615_zero-investigation_nocommit/` (all 18 subjects × 3 conditions).

**Documentation evidence:**

- The rCPS sidecars (identical across all 54 maps) state only: "Voxelwise Basis Function Method (BFM)", ArtIF, 0–60
  min, nmol/g/min. There is **no** mention of masking, thresholding, fill values or a validity mask.
- `derivatives/rCPS/dataset_description.json` says "Primary data analysis — see references". The published README
  says only "original statistical maps from the paper".
- No validity or mask image accompanies the rCPS maps.
- The curators' code (Zenodo 10.5281/zenodo.7768340 v1.0.0, MD5 verified; `kinsurf.m`, `kinvol.m`) samples the rCPS
  maps with `mri_vol2surf` / `mri_vol2vol` **without any zero handling**. Zeros therefore enter their surface and
  MNI products as ordinary values.
- The code that produced the rCPS maps is **not** in the dataset.

**Numerical and spatial evidence (54 scans):**

- **No negative and no non-finite values.** Positive values extend continuously down to ~0 (0.7% of in-brain positive
  voxels are < 0.02).
- Exact zeros form a **distinct point mass**. In cortex, a median of 5.8% of voxels (2.4–12.8%) are exactly 0, versus
  ~3,200 voxels per scan in the adjacent (0, 0.02) bin (pooled: 2.38 M zeros vs 0.17 M in (0, 0.02)).
- Zeros are **concentrated at the brain boundary**:
  - within 2 mm of the FreeSurfer brain-mask edge, a median 97% of voxels are zero;
  - at 2–5 mm, 59%; at 5–10 mm, 21%;
  - deeper than 10 mm, still 9% (range 5–15%).
  - By tissue class: CSF 73%, cortical GM 6.6%, WM 5.0%, subcortical/cerebellum 8.1%.
- **Deep zeros occur where PET activity is present:**
  - the curators' mean PET image is non-zero at every zero-rCPS voxel;
  - median mean-PET in zero vs non-zero cortical voxels: ratio 0.93;
  - zeros are about twice as frequent in the lowest-activity decile of cortex (13%) as in the middle 80% (5.8%).
- **Zeros are partly shared across conditions:**
  - within the brain mask, Jaccard overlap between conditions is a median 0.75–0.77, and 68% of voxels that are zero
    in any condition are zero in all three;
  - within cortex only, overlap was lower (0.11–0.62 in 4 spot-checked subjects).
- Cortical zeros occur as many small clusters: a median of 8,535 clusters per scan, 16% of zero voxels in clusters of
  at least 100 voxels.

**Interpretation:** the evidence points to **at least two mechanisms**.

1. A **shared, boundary- and CSF-concentrated support mask**, which is anatomy-like and largely common to the three
   sessions. Here zero almost certainly means **"outside the estimated support"**, not a measured rCPS of 0.
2. **Scattered interior zeros** that are more frequent at low activity and differ between sessions. These are
   consistent with either **non-negativity-constrained estimates clipped at 0** (a numerical estimate, biased) or
   **failed or rejected voxel fits set to 0** (invalid).

The available metadata and code **cannot distinguish** mechanism 2's alternatives. A true grey-matter rCPS of exactly
0 nmol/g/min is not physiologically plausible, but a clipped noisy estimate is not "invalid" in the same sense as a
masked voxel.

**Decision (investigators, 2026-09-27).** This supersedes the QC-stage recommendation, which is recorded below
for transparency.

- **Primary: ROI means include exact-zero voxels exactly as supplied** in the published rCPS derivative.
  - Numeric zero is **not** reinterpreted as missing or invalid without authoritative metadata.
  - For every subject × condition × ROI, record the voxel count, **zero count** and **zero fraction**.
- **Zero-handling sensitivity (analysis_plan S7):** recompute ROI means excluding exact-zero voxels. This is a
  sensitivity analysis, **not** an alternative primary definition.
- **Rationale:**
  - no authoritative validity mask or metadata marks zero as missing;
  - boundary zeros appear mask-related, but deeper zeros remain ambiguous;
  - excluding every zero based only on the target value would itself be an undocumented, outcome-dependent
    transformation;
  - the primary analysis therefore preserves the published derivative as supplied.
- **Limitation (carried into `analysis_plan.md` §2):** the primary target may contain mask/edge effects, possibly
  related to cortical geometry, so biological interpretation must remain narrow.
- **No ROI is dropped for its zero fraction.** The maximum observed is 30% (entorhinal); no ROI × scan exceeds 50%.
- **Optional action:** ask the dataset authors or curators how masked or invalid voxels are encoded. An
  authoritative answer before freeze would be documented, and the rule revisited as a dated amendment.

*Superseded QC-stage recommendation* (not adopted): primary = exclude zeros, sensitivity = include. The argument was
that including boundary zeros makes ROI means depend on ROI geometry. The investigators judged that excluding values
by the target value is itself an undocumented transformation. The geometry concern is instead handled by the
limitation above and by S7.

## 3c. R6 / R11 threshold review

- **R6 (minimum ROI voxel count): kept as a descriptive metric, not an exclusion rule.**
  - Known resolution: HRRT; the raw PET sidecar gives `PointSpreadFunctionEffectiveResolutionAxial: 1.231` (units not
    stated); the curators assumed a 4 mm FWHM PSF for GTM.
  - The rCPS maps are **not** piecewise-constant: adjacent in-brain positive voxels never share a value on any axis.
    *This corrects an earlier note in this file.*
  - Cortical partial-volume loss depends on ribbon thickness relative to the PSF, not on ROI voxel count. A voxel
    threshold would therefore not target the relevant problem.
  - All 68 ROIs have ≥ 995 voxels (≈ 1 cm³) in every scan, far above any count at which a mean would be numerically
    unstable.
  - No threshold is imposed. Partial-volume effects remain analysis-plan item T2.
- **R11 (quantitative alignment tolerance): kept as a descriptive metric, not an exclusion rule.**
  - The primary-metric optimum offsets (median 0.68 mm, max 2.08 mm mean cortical displacement) and the curators'
    independent transforms (median 1.65 mm) are all below the 4 mm assumed PSF FWHM.
  - The NMI surface is shallow (gains ≤ 0.006).
  - There is no principled basis for a tighter cut-off, and the data provide no candidate for exclusion.
  - The recurring +1.3–1.5 mm z component in several optima is recorded as descriptive; it is well within the
    registration-precision scale above.
- **R10 condition consistency:** the critical part (identical affines) passes 18/18. The optimum-displacement
  comparison across conditions is descriptive only (maximum within-subject range 1.05 mm, SP02).

## 4. Pass/fail and visual-rating table (subject × condition)

- **Automated critical rules** (R1, R2, R3, R4, R5, R7, R10): **54/54 PASS**.
- **Visual rating R9:** **54/54 PASS, 0 FAIL, 0 UNSURE.**
- R6, R8 and R11 are descriptive (§3c, §3b).
- **No exclusions.**

**Visual rater and method.**

- The rating was done by the AI assistant (Claude) on 2026-09-27, before any predictive result existed.
- It covered only the prespecified overlays: `*_multiplanar.png` and `*_small_rois.png` for each scan, plus each
  subject's `*_contact_sheet.png`. That is 7 images per subject and 126 in total, each opened once. No additional
  slices were generated.
- The criteria are in `qc_plan.md` §2b.
- **Sensitivity:** at the rendered resolution (70 dpi, 1 mm voxels) the review can detect gross misalignment (about a
  gyral width, several mm) or flips. It cannot resolve 1–2 mm offsets; those are covered quantitatively (R11).
- **Human spot-check:** recommended, but **not** a technical exclusion requirement. The 54/54 PASS results stand
  unless a human reviewer identifies a problem. Any such finding is recorded here with the scan, the reason and the
  consequence under R9.

| Subject | Cond | R1 | R2 | R3 | R4 | R5 | R7 | R10 | Automated | R6 min ROI vox | R8 ctx zero frac | R11 opt disp mean/max mm | R9 visual | Visual note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sub-SP02 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1000 | 0.076 | 0.79 / 0.94 | PASS |  |
| sub-SP02 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1000 | 0.079 | 1.61 / 2.80 | PASS |  |
| sub-SP02 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1000 | 0.058 | 1.84 / 3.27 | PASS |  |
| sub-SP03 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1435 | 0.084 | 0.71 / 0.76 | PASS | rh entorhinal abuts the rCPS support edge but lies within support |
| sub-SP03 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1435 | 0.084 | 0.72 / 0.75 | PASS | 〃 |
| sub-SP03 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1435 | 0.090 | 0.78 / 0.81 | PASS | 〃 |
| sub-SP05 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1403 | 0.091 | 0.70 / 0.72 | PASS | midline sagittal: sparse rCPS support (zero voxels near CSF); boundaries still follow the outline |
| sub-SP05 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1403 | 0.107 | 0.70 / 0.72 | PASS | 〃 |
| sub-SP05 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1403 | 0.100 | 0.73 / 0.74 | PASS | 〃 |
| sub-SP06 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1336 | 0.059 | 1.17 / 2.27 | PASS | lh entorhinal at the support edge in coronal panels; within support |
| sub-SP06 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1336 | 0.055 | 1.64 / 2.02 | PASS | 〃 |
| sub-SP06 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1336 | 0.056 | 2.08 / 2.18 | PASS | 〃 |
| sub-SP09 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1083 | 0.096 | 0.76 / 0.87 | PASS | lower T1w grey/white contrast; boundaries follow the rCPS outline |
| sub-SP09 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1083 | 0.106 | 0.70 / 0.75 | PASS | 〃 |
| sub-SP09 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1083 | 0.103 | 1.46 / 1.55 | PASS | 〃 |
| sub-SP10 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1269 | 0.044 | 0.59 / 0.62 | PASS |  |
| sub-SP10 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1269 | 0.054 | 0.69 / 0.74 | PASS |  |
| sub-SP10 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1269 | 0.052 | 0.67 / 0.80 | PASS |  |
| sub-SP11 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1523 | 0.111 | 0.74 / 0.80 | PASS | highest cortical zero fraction; rh entorhinal borders zero regions |
| sub-SP11 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1523 | 0.128 | 0.70 / 0.73 | PASS | 〃 |
| sub-SP11 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1523 | 0.115 | 0.70 / 0.77 | PASS | 〃 |
| sub-SP12 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1549 | 0.057 | 0.73 / 0.81 | PASS |  |
| sub-SP12 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1549 | 0.088 | 1.62 / 2.04 | PASS |  |
| sub-SP12 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1549 | 0.057 | 0.76 / 0.80 | PASS |  |
| sub-SP14 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1050 | 0.059 | 1.44 / 1.53 | PASS |  |
| sub-SP14 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1050 | 0.079 | 0.77 / 0.86 | PASS |  |
| sub-SP14 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1050 | 0.089 | 0.68 / 0.86 | PASS |  |
| sub-SP15 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1471 | 0.053 | 0.53 / 0.68 | PASS |  |
| sub-SP15 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1471 | 0.055 | 0.51 / 0.57 | PASS |  |
| sub-SP15 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1471 | 0.064 | 0.49 / 0.58 | PASS |  |
| sub-SP16 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1101 | 0.038 | 0.58 / 1.06 | PASS | pronounced head pitch, identical in T1w and rCPS |
| sub-SP16 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1101 | 0.042 | 0.51 / 0.54 | PASS | 〃 |
| sub-SP16 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1101 | 0.040 | 0.56 / 0.60 | PASS | 〃 |
| sub-SP18 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 995 | 0.037 | 0.67 / 0.72 | PASS |  |
| sub-SP18 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 995 | 0.034 | 0.68 / 0.72 | PASS |  |
| sub-SP18 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 995 | 0.027 | 0.64 / 0.68 | PASS |  |
| sub-SP20 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1250 | 0.047 | 0.63 / 0.70 | PASS | ventral orbitofrontal: sparse rCPS support in all conditions (zero-voxel context, not misalignment) |
| sub-SP20 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1250 | 0.076 | 1.34 / 2.15 | PASS | 〃 |
| sub-SP20 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1250 | 0.078 | 0.74 / 0.95 | PASS | 〃 |
| sub-SP21 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1094 | 0.038 | 0.63 / 0.66 | PASS |  |
| sub-SP21 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1094 | 0.033 | 0.58 / 0.70 | PASS |  |
| sub-SP21 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1094 | 0.047 | 0.55 / 0.59 | PASS |  |
| sub-SP22 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1034 | 0.045 | 0.47 / 0.59 | PASS |  |
| sub-SP22 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1034 | 0.040 | 0.47 / 0.54 | PASS |  |
| sub-SP22 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1034 | 0.036 | 0.45 / 0.56 | PASS |  |
| sub-SP23 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1272 | 0.024 | 0.45 / 0.74 | PASS |  |
| sub-SP23 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1272 | 0.044 | 0.48 / 0.54 | PASS |  |
| sub-SP23 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1272 | 0.024 | 0.46 / 0.53 | PASS |  |
| sub-SP26 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1237 | 0.058 | 0.35 / 0.50 | PASS |  |
| sub-SP26 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1237 | 0.082 | 0.36 / 0.46 | PASS |  |
| sub-SP26 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1237 | 0.067 | 0.35 / 0.37 | PASS |  |
| sub-SP28 | Awake | pass | pass | pass | pass | pass | pass | pass | PASS | 1128 | 0.069 | 0.38 / 0.48 | PASS |  |
| sub-SP28 | SleepDeprived | pass | pass | pass | pass | pass | pass | pass | PASS | 1128 | 0.088 | 0.33 / 0.41 | PASS |  |
| sub-SP28 | Asleep | pass | pass | pass | pass | pass | pass | pass | PASS | 1128 | 0.084 | 0.33 / 0.43 | PASS |  |

(〃 = the note on the subject's Awake row applies to all its conditions.)

## 5. Status of QC items

| ID | Item | Status |
|---|---|---|
| D1 | Clean, verified v1.0.1 copy at `~/Documents/Research/PET-MRI/openneuro/ds004733/` | **COMPLETE**, verifier PASS (§6) |
| D2 | Primary cohort | Resolved: v1.0.1, N = 18. S1 = v1.0.0 roster, N = 17, descriptive |
| D3 | Zero-voxel ROI-mean rule | Resolved: primary includes zeros; S7 excludes them (§3b) |
| D4 | R6 threshold | Resolved: descriptive only (§3c) |
| D5 | R10 / R11 tolerances | Resolved: descriptive only (§3c) |
| D6 | R9 visual rating | Resolved: 54/54 PASS (agent-assisted). Human spot-check recommended, not required |
| D7 | QC re-run from a committed tree on the clean copy | **PASS**: exact reproduction (§7) |

No open QC items remain.

## 6. Canonical dataset: creation and verification (executed 2026-09-27)

**Executed 2026-09-27.** The results are below; the procedure is kept for re-creation. The existing Desktop and
Research copies were not modified and remain as archaeology (comparison-only in `configs/paths.local.yaml`).

**Result:**

- **Tools:** DataLad 1.1.4 and git-annex 10.20240927 were already installed; nothing was installed.
- **Clone:** `https://github.com/OpenNeuroDatasets/ds004733.git` checked out at tag `1.0.1`, HEAD
  `badd0108199e5b9f85451d317e472e5ee6105464`, with a clean `git status`.
- **Retrieved content:** only the 444 manifest paths. 342 annexed files were fetched and 102 were git-tracked;
  1.88 GB of the 244 GB dataset. Another 36 files (`mri/orig/001.mgz`, `scripts/lastcall.build-stamp.txt`) became
  present automatically because they share annex keys with required files. There is no unused annex content.
- **`git annex fsck`** on the required files: 342/342 ok (full re-hash).
- **Metadata:** `dataset_description.json`, `participants.tsv`, `README` and `CHANGES` equal the published 1.0.1 git
  blobs. The README has no stray line, and `participants.tsv` lists the 18 expected IDs.
- **Verifier:** `verify_canonical --require-git` PASS, 444/444.
- **Write protection:** git-annex objects are read-only by default. All 516 git-tracked regular working-tree files
  were set `a-w`; `.git/` and directories were left untouched so git-annex keeps working. `git status` stayed
  clean, and a test write was refused.
- **Operational rule, in addition:** analysis code never writes into `bids_root`; all outputs go to this
  repository's `outputs/`; and `verify_canonical --require-git` is run before scientific runs.

**Target:** `~/Documents/Research/PET-MRI/openneuro/ds004733/`, a DataLad clone of the official OpenNeuro mirror,
checked out at release tag **`1.0.1`** (commit `badd0108199e5b9f85451d317e472e5ee6105464`).

**Prerequisites (one-time; installs software, so needs approval):** `datalad` and `git-annex`, e.g.
`conda install -n rcps-mri-reanalysis -c conda-forge datalad git-annex`. Record their versions in the verification
run.

**Steps:**

```bash
mkdir -p ~/Documents/Research/PET-MRI/openneuro
cd ~/Documents/Research/PET-MRI/openneuro
datalad clone https://github.com/OpenNeuroDatasets/ds004733.git ds004733
cd ds004733
git checkout 1.0.1                      # detached HEAD at the release commit
git rev-parse HEAD                      # must print badd0108199e5b9f85451d317e472e5ee6105464

# Retrieve only the files the analysis uses (the paths in the committed expected-hash table).
# git-annex verifies every retrieved file against its SHA256E key.
grep -v '^#' <repo>/configs/ds004733_v1.0.1_expected_sha256.tsv | tail -n +2 | cut -f1 > /tmp/ds004733_paths.txt
xargs datalad get < /tmp/ds004733_paths.txt
xargs git annex fsck < /tmp/ds004733_paths.txt   # full content check (re-hashes) of every retrieved annexed file
git status --porcelain                  # must print nothing

chmod -R a-w .                          # make the working tree read-only
```

Then set `bids_root: "~/Documents/Research/PET-MRI/openneuro/ds004733"` in `configs/paths.local.yaml` (git-ignored)
and run, from this repository:

```bash
PYTHONPATH=src python -m rcps.qc.verify_canonical --require-git
```

**Pass criteria** (all must hold; they are written to `outputs/<ts>_verify-canonical_<sha>/summary.json`):

1. HEAD = `badd0108199e5b9f85451d317e472e5ee6105464`, and `git status --porcelain` is empty.
2. All **444** files in `configs/ds004733_v1.0.1_expected_sha256.tsv` exist with the listed size and SHA-256.
   - 440 of them equal the hashes verified in §1 (published annex keys / git blobs, identical in 1.0.0 and 1.0.1).
   - `README`, `CHANGES`, `dataset_description.json` and `participants.tsv` must equal the **published 1.0.1** text.
   - In particular, `README` must be the published text, SHA-256 `dbbdf67a…`, without the stray local line.
3. `participants.tsv` lists exactly the 18 expected IDs.

Control check: the verifier was run on the current Desktop copy (2026-09-27). It correctly **FAILED**: 440 / 444
OK; `README`, `CHANGES`, `dataset_description.json` and `participants.tsv` mismatched (a 1.0.0 copy with an edited
README); the roster did not match; and the copy is not a git checkout.

**Avoiding local modifications:**

- The tree is read-only after retrieval.
- Never open dataset files in an editor. The stray README line looks like an editor paste.
- Analysis code will record the dataset HEAD SHA and the expected-hash table's hash in every run record.
- `verify_canonical --require-git` is run before each reported analysis.
- Any metadata correction needed later goes into this repository as a documented override, never into the dataset.

## 7. Reproducibility of the committed-tree QC rerun

Reference run `outputs/20260927-131732_qc_b4e9608/` compared with the pre-commit run
`outputs/20260927-030610_qc_nocommit/`:

**Identical cell for cell (all 9 imaging-derived tables):** `image_geometry`, `affine_checks`, `roi_voxel_counts`,
`label_integrity`, `left_right_check`, `zeros_by_tissue`, `quantitative_metrics`, `perturbation_profiles`,
`historical_bbregister_comparison`. This covers:

- 54/54 automated critical PASS;
- lossless 68-ROI NN label mapping;
- header alignment near the local optimum;
- historical `bbregister` worse on all prespecified metrics in 54/54;
- identical zero-voxel fractions;
- no exclusions.

**Byte-identical outputs:** all 126 standard overlays, all 54 historical-comparison overlays, and all 18 NN label
images. The 54/54 visual PASS rating (§4) therefore applies unchanged to the reference run's overlays.

**Expected dataset-table differences (by design):**

- The local copy is now v1.0.1, so `dataset_description.json`, `participants.tsv` and `CHANGES` differ from 1.0.0
  (and equal 1.0.1).
- The README now equals the published text.
- The local roster is 18.
- The new `source_manifest.tsv` matches `configs/ds004733_v1.0.1_expected_sha256.tsv` in 444/444 files.
- Its own file hash differs from the pre-commit manifest because the manifest also records modification times.

**Known cosmetic issue in committed code (no effect on results):**

- `subject_eligibility.tsv` still names a column `preliminary_eligible_primary_as_planned_N17`; it correctly reads
  True for all 18.
- `run_qc`'s `run_metadata.json` does not natively record the dataset tag/commit, the verifier result or the
  config hashes. Those are in `logs/supplementary_provenance.json` for this run.
- Both should be fixed in a follow-up commit.
