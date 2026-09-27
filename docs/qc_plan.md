# QC Plan: Canonical Dataset and PET–MRI Spatial Correspondence

**Status: FINAL for the current phase (2026-09-27).** The rules in §2b were written before the cohort-wide results were inspected. Outcomes and decisions are in `docs/qc_decisions.md`. Pass/fail criteria must be fixed **before** QC is run and before any predictive modelling.
QC decisions must be independent of model performance: no predictive results exist while QC is carried out.

Outputs: a run-specific directory `outputs/<timestamp>_qc_<shortsha>/`, containing the machine-readable metrics, the
overlay images, and a QC log. Final decisions (pass/fail per subject × condition, with reasons) go into
`docs/qc_decisions.md`, which is committed.

---

## 1. Dataset provenance

Known facts (read-only audit, 2026-09-27):

- Two local copies exist.
  - The research copy holds only `derivatives/` (freesurfer, rCPS, rcps-modified-petprep).
  - The full BIDS copy also holds raw `sub-*`, `participants.tsv`, `dataset_description.json`, `README`, `CHANGES`,
    `sessions.json` and a `.datalad/config` (dataset id `314b257d-97a2-434a-ad71-9e8544d29a04`). It has no `.git`.
- The derivative file lists match between the copies, and every sampled file compared was byte-identical.
- `dataset_description.json` gives `DatasetDOI doi:10.18112/openneuro.ds004733.v1.0.0`; `CHANGES` says
  `1.0.0 2023-12-08`.
- The full copy's `README` has a local mtime of **2025-03-09**, while every other file dates from 2023-12. It may have
  been edited locally, so its statements, including the T1w ↔ rCPS co-registration claim, **must not be relied on
  until verified**.
  - *Verified 2026-09-27* (`qc_decisions.md` §1): the local README differs from the published one by one inserted
    line only. The co-registration statement is in the published text. The canonical release is now **1.0.1**, and
    the acquisition and verification procedure for a clean copy is in `qc_decisions.md` §6.

Required steps:

1. **Choose one authoritative full BIDS copy** and record its location in `configs/paths.local.yaml` (never
   committed).
2. **Verify the version.** Compare the local copy with OpenNeuro ds004733 v1.0.0 (or its DataLad/GitHub mirror):
   `dataset_description.json`, `CHANGES`, `participants.tsv`, `README`, and file checksums for a defined set
   (all top-level files, all rCPS maps, all T1w images, each subject's `aparc+aseg.mgz`, `orig.mgz` and
   `?h.aparc.stats`).
3. **Verify metadata.** `participants.tsv` contains exactly the 17 expected IDs, and `dataset_description.json`
   fields are recorded.
4. **Fingerprint the source.** Write a SHA-256 manifest of every file used by the pipeline. Every run record cites
   that manifest's hash.
5. **Verify derivative correspondence.** Every subject in the derivatives maps to raw data, with sessions as expected.
   Report anything present in one place and absent in the other (known: `sub-SP06`).
6. If the local README differs from the published README, document the difference. Only the published text may be
   cited.

## 2. Spatial QC

**Scope:** every subject of the v1.0.1 roster (18, including SP06) × every PET condition (3).

| # | Check | Method | Initial proposal (**superseded**: binding rules are §2b; see the note below the table) |
|---|---|---|---|
| 1 | Dimensions and voxel size | Read headers of rCPS, raw T1w, FreeSurfer `orig.mgz` / `aparc+aseg.mgz` | rCPS grid equal to T1w grid; voxel sizes recorded |
| 2 | qform/sform consistency | Compare the qform and sform matrices and codes | Both codes > 0; matrices equal within 1e-4 |
| 3 | Orientation | Orientation codes (e.g. `aff2axcodes`) | Recorded; consistent across conditions within a subject |
| 4 | Left–right check | World-space centroids of lh (ctx-lh-*) and rh (ctx-rh-*) labels after resampling to the rCPS grid; check against T1w anatomy | Every lh cortical label centroid on the left side of RAS x and every rh label on the right; no hemisphere flip |
| 5 | T1w ↔ rCPS correspondence | Header comparison, plus a quantitative sharpness test: similarity (e.g. NMI) between rCPS and a FreeSurfer GM/cortical-ribbon mask at the header alignment vs small rigid perturbations (±1–3 mm, ±1–3°) | Header alignment within one voxel / 1° of the local similarity optimum. Otherwise flagged for review |
| 6 | FreeSurfer ↔ T1w correspondence | `orig.mgz` vs raw T1w in world space: bounding boxes, and intensity correlation after header resampling | High correspondence (threshold to be set); visual confirmation |
| 7 | Ribbon / aparc overlays | Overlay PNGs (axial, coronal, sagittal) of aparc cortical labels and the ribbon on the rCPS map and on the T1w | Visual pass by the rater, logged with reasons |
| 8 | Label coverage | Fraction of each of the 68 labels' voxels inside the rCPS field of view / support | Implemented as per-ROI zero counts (R8); no tolerance |
| 9 | Missing, zero or non-finite PET | Count of NaN/Inf, exact zeros and negatives per ROI and in the brain mask | Non-finite = 0 (R7, critical). Zeros: descriptive (R8); the early "≤ 1%" idea was dropped because it was not justified |
| 10 | Per-ROI voxel counts | Voxels per ROI on the rCPS grid | Recorded; ROIs below the threshold flagged (not dropped) |
| 11 | Small-ROI inspection | Visual review of the smallest ROIs (e.g. frontalpole, temporalpole, entorhinal, transversetemporal, pericalcarine, bankssts) | Visual pass logged |
| 12 | Condition consistency | Within a subject: identical affines across the 3 conditions; similar alignment metric (check 5); rCPS–rCPS spatial correlation between conditions within the brain | Affines identical; no condition that is an outlier on check 5 |

*Note:* check 6 was implemented more strictly than proposed, as voxel identity of `rawavg.mgz` and the T1w. The
between-condition rCPS–rCPS correlation in check 12 was not computed; condition consistency relied on identical
affines and the per-condition alignment metrics.

**Spatial method (decided; `docs/qc_decisions.md` §3):**

- keep rCPS intensities on their supplied grid;
- resample the discrete `aparc+aseg` labels to that grid with nearest-neighbour interpolation via header
  (world-space) alignment;
- no additional registration.

The historical `bbregister` transforms, and the curators' PETPrep transforms, were evaluated with the same criteria
and are not used. The judgement rested on those criteria, not on the mere fact that a transform differs.

## 2b. Formal pass/fail rules (Phase D)

Written 2026-09-27, **before** cohort-wide QC results were inspected. Only a single-subject smoke test (sub-SP02)
had been seen. Rules apply per subject × condition. Where no numeric threshold can yet be justified from first
principles, the rule says **REVIEW REQUIRED** and no number is invented. The 2026-09-27 review resolved every such rule as descriptive (below).

| ID | Rule | Criterion | Class |
|---|---|---|---|
| R1 | Missing required input | T1w, FreeSurfer `rawavg/orig/aparc+aseg/brainmask.mgz`, `?h.aparc.stats`, and exactly one rCPS map per condition must exist | **Critical FAIL** |
| R2 | qform/sform consistency | rCPS and T1w: qform_code > 0, sform_code > 0, max\|qform − sform\| ≤ 1e-4 mm (floating-point tolerance) | **Critical FAIL** |
| R3 | Header/transform correspondence | rCPS shape and affine equal to the T1w (max abs diff ≤ 1e-4); `rawavg.mgz` voxel-identical to the T1w (FreeSurfer ran on this exact image); aparc+aseg and brainmask share the `orig.mgz` geometry | Any failure = **REVIEW (transform ambiguity; blocks freeze)** |
| R4 | Left–right | All 34 homologous DK pairs have the lh centroid at smaller RAS x than the rh centroid on the rCPS grid, **and** primary-metric NMI(header) > NMI(L–R-mirrored anatomy) | **Critical FAIL** |
| R5 | Missing / zero-voxel cortical ROI | All 68 DK ROIs present on the rCPS grid with ≥ 1 voxel | **Critical FAIL** |
| R6 | Minimum ROI voxel count | Reported per ROI. **No threshold** (review 2026-09-27, `qc_decisions.md` §3c): PVE depends on ribbon thickness vs PSF, not voxel count, and all ROIs have ≥ 995 voxels | **Descriptive only** |
| R7 | Non-finite rCPS | Any NaN/Inf voxel inside the 68 cortical ROIs or the brain mask (no imputation policy exists) | **Critical FAIL** |
| R8 | Zero-valued rCPS inside cortical ROIs | Reported per ROI and per tissue class. No tolerance (no ROI dropped for its zero fraction). ROI-mean handling (`qc_decisions.md` §3b, `analysis_plan.md` §5.3): primary **includes** zeros as supplied; the zero-handling sensitivity S7 excludes them. Zero count and fraction are recorded per subject × condition × ROI | **Descriptive** |
| R9 | Visual misalignment | Rating of the standard overlays (multiplanar, small-ROI, contact sheet) as PASS / FAIL / UNSURE with a written reason. Rater recorded: the 2026-09-27 pass was AI-assisted, with human spot-confirmation recommended. Until rated: **PENDING-VISUAL** | Categorical; FAIL = critical |
| R10 | Condition consistency | Affines identical across the 3 conditions (exact) = critical. Alignment-optimum displacement across conditions: descriptive only (review 2026-09-27) | Critical / descriptive |
| R11 | Quantitative alignment | The primary metric (`nmi_t1_interior`) is evaluated at the header alignment vs its local 6-DOF optimum; mean/max cortical displacement reported. **No tolerance** (review 2026-09-27, `qc_decisions.md` §3c): all offsets are below the assumed 4 mm PSF FWHM, and two independent alignment routes agree to ~1–2 mm | **Descriptive only** |
| R12 | Unresolved transform ambiguity | Any open R3, or evidence that a registration step is needed | **Blocks freeze** |

**R9 visual-rating criteria** (fixed 2026-09-27, before the formal rating pass):

- **Material:** only the prespecified overlays: per subject × condition `*_multiplanar.png` and `*_small_rois.png`,
  plus the per-subject `*_contact_sheet.png`. No extra slices are generated for the rating.
- **PASS:** DK boundaries follow the rCPS brain outline, the interhemispheric fissure and the ventricles/deep
  structure in all three planes, with no visible systematic shift or rotation. All small-ROI panels place the
  target ROI over rCPS-supported cortex. Conditions look mutually consistent on the contact sheet.
- **FAIL:** visible systematic misalignment (boundaries consistently offset from the rCPS brain edge or
  ventricles in one direction, on the order of a gyral width or more); a left–right inconsistency; a small ROI
  lying clearly outside rCPS support; or a condition visibly inconsistent with the others.
- **UNSURE:** judgement is not possible or is ambiguous, e.g. extensive zero-valued rCPS regions obscuring the
  ROI/edge relationship, or an image artefact.
- Each FAIL / UNSURE carries a one-line reason.
- The rater is recorded. No prediction results exist or are consulted.

**Outcome per subject × condition:** `FAIL` if any critical rule fails; otherwise `PASS-automated` with the
outstanding `REVIEW` / `PENDING-VISUAL` items listed. No subject is excluded on a REVIEW item until the review is
resolved and recorded in `docs/qc_decisions.md`.

## 3. Exclusion rules

- A subject × condition failing any **critical** check (1, 2, 4, 9-nonfinite, or a failed visual review under 7)
  is excluded from targets that need that condition. Because the primary target needs all three conditions, this
  excludes the subject from P1.
- Non-critical flags (small ROI, borderline coverage) are reported but do not exclude, unless the finalised rules
  say otherwise.
- The rules are finalised and committed before QC runs. Exclusions are applied by code from the QC decision file,
  never by hand-editing data.

## 4. Deliverables before resolving T1 (alignment)

- A dataset verification report and source manifest hash (§1).
- A QC metrics table (subject × condition × check), overlays, and a QC log.
- `docs/qc_decisions.md`: per-subject decisions, the chosen spatial method, and its justification.
