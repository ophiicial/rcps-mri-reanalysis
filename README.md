# rCPS from Structural MRI: Reanalysis

This project tests whether structural MRI morphometrics (FreeSurfer) predict regional cerebral protein synthesis
(rCPS) measured with L-[1-¹¹C]leucine PET, beyond what regional identity alone predicts. Data: OpenNeuro
ds004733 derivatives.

**Status:** reconstruction and reanalysis. No results in this repository are final. An earlier manuscript
(2025) was rejected, and this repository re-derives the analysis from scratch under the rules in
[`AGENTS.md`](AGENTS.md).

## Data location

The dataset is **not** stored in or committed to this repository, and its location is not hard-coded.

- **Canonical source:** OpenNeuro **ds004733 release 1.0.1** (primary cohort N = 18).
- **Location:** copy `configs/paths.example.yaml` to `configs/paths.local.yaml` (git-ignored) and set `bids_root`.
- **Verification:** a copy must match `configs/ds004733_v1.0.1_expected_sha256.tsv`. Check it with
  `PYTHONPATH=src python -m rcps.qc.verify_canonical --require-git`. Instructions for creating a clean DataLad copy are in
  `docs/qc_decisions.md` §6.
- Original data are treated as read-only.

## Pipeline stages (implemented status: [pipeline map](docs/pipeline.md))

1. Canonical dataset verification and source fingerprinting
2. PET–MRI spatial correspondence QC (method decided by QC evidence)
3. ROI extraction of rCPS per condition (68 Desikan–Killiany cortical ROIs)
4. MRI morphometric extraction (FreeSurfer `aparc.stats`)
5. MRI–PET ROI harmonization with explicit, logged ROI accounting
6. Dataset assembly
7. Subject-grouped predictive modelling (LOSO) and the prespecified permutation test
8. Descriptive, sensitivity and exploratory analyses
9. Figures and tables for resubmission

See also `docs/historical_discrepancies.md`.

The frozen methodology is [analysis_plan.md](docs/analysis_plan.md) plus
[configs/analysis.yaml](configs/analysis.yaml). Start with the [study design](docs/study-design.md),
[dataset](docs/dataset.md), [data contracts](docs/data-contracts.md), [modeling](docs/modeling.md),
[inference](docs/inference.md), and [results map](docs/results-map.md).
The [2026-09-29 audit](docs/audit-2026-09-29.md) separates implementation gaps from accepted decisions.

## Reproducibility principles

- The subject is the unit of analysis. All splitting, tuning, preprocessing, and inference respect subject grouping.
- Every run writes to its own `outputs/<timestamp>_<name>_<sha>/` directory with a full run record (git SHA,
  config, seed, package versions, input hashes).
- No silent exclusions of subjects, ROIs, or features.
- Environment: `conda env create -f environment.yml`.

## Running (QC tools and synthetic-tested modeling primitives)

Ridge primitives and nested LOSO operate on supplied arrays; no real-data model or
permutation CLI exists. The LOSO module/tests were untracked at the documentation audit start
and have since been committed (`18471e9`).
QC commands below require explicit authorization for a new scientific run.

```bash
conda activate rcps-mri-reanalysis
python -m pytest -q tests                                  # unit tests (one data test skips without a local dataset)
PYTHONPATH=src python -m rcps.qc.verify_canonical          # verify the configured dataset copy
PYTHONPATH=src python -m rcps.qc.run_qc                    # dataset + imaging QC -> outputs/<ts>_qc_<sha>/
PYTHONPATH=src python -m rcps.qc.investigate_zeros         # zero-valued rCPS investigation
PYTHONPATH=src python -m rcps.qc.investigate_curator_reg   # curators' PET->T1 transforms, same QC criteria
```

`run_qc` also calls the GitHub API (via an authenticated `gh` CLI) to verify files against the published release.
Its optional historical comparison reads the read-only historical `FinalTry` repository set in
`configs/paths.local.yaml`.

## External tools (not managed by conda)

- **FreeSurfer:** not required by the current code. The dataset's recon-all derivatives (7.3.2) are read directly
  (`aparc.stats`, `aparc+aseg.mgz`) with nibabel. The historical pipeline used 8.0.0-beta tools. If FreeSurfer
  tools are ever needed, their version is recorded.
- **FSL:** not required. The historical pipeline used it (6.0.7.16) for `bbregister --init-fsl`; the re-registration
  is not used (`docs/qc_decisions.md` §3).
- **DataLad / git-annex:** needed only to create the canonical dataset copy (`docs/qc_decisions.md` §6).
- **gh CLI:** used by `run_qc` for published-release verification.

## Historical repositories

`FinalTry` and `PET-MRI-BrainSynthesis` are **temporary migration sources**, not authoritative going forward.
Their frozen provenance record is in `PET-MRI-BrainSynthesis/provenance/manuscript_2025_2026/`.
