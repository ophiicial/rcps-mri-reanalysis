# Dataset and provenance

Canonical identity and roster: [configs/canonical_dataset.yaml](../configs/canonical_dataset.yaml).
The dataset is ds004733 **1.0.1**, commit `badd0108199e5b9f85451d317e472e5ee6105464`.
The expected SHA-256 manifest contains 444 paths. Local locations come from the ignored
`configs/paths.local.yaml` through `rcps.config.load_paths`; there is currently no
implemented environment-variable override for `bids_root`.

The 18-subject roster and ordered permutation groups are already centralized in
[configs/analysis.yaml](../configs/analysis.yaml). Do not introduce a second
`config/acquisition_strata.yaml` or copy subject lists into production Python.
Acquisition provenance is [qc_decisions.md §8](qc_decisions.md); this was cross-checked
against local release T1w JSON sidecars and session TSV metadata on 2026-09-29.

## Availability and identifiers

Use full IDs such as `sub-SP02`, never an inferred integer sequence. Conditions are
exactly `Awake`, `SleepDeprived`, `Asleep`; MRI uses `ses-MRI`.
The reference QC run `outputs/20260927-131732_qc_b4e9608/dataset/subject_eligibility.tsv`
records T1w, all three rCPS maps, both aparc stats, aparc+aseg, and recon-all completion
for all 18 subjects. No QC exclusions were accepted. These are recorded findings,
not a fresh imaging verification performed by the documentation audit.

| Input | Dataset-relative path |
|---|---|
| T1w and acquisition sidecar | `sub-*/ses-MRI/anat/*_T1w.nii.gz`, corresponding `.json` |
| PET-derived continuous rCPS | `derivatives/rCPS/sub-*/ses-{condition}/*_stat-rCPS_statmap.nii.gz` |
| Curator FreeSurfer 7.3.2 | `derivatives/freesurfer/sub-*/stats/{lh,rh}.aparc.stats` |
| Labels and anatomical QC | `derivatives/freesurfer/sub-*/mri/{aparc+aseg,orig,rawavg,brainmask}.mgz` |
| Curator transform investigation only | `derivatives/rcps-modified-petprep/sub-*/ses-*/pet/*_from-pet_to-T1w_reg.lta` |
| Recruitment-date evidence | `sub-*/sub-*_sessions.tsv`, column `acq_time` |

## Acquisition structure and uncertainty

The four accepted groups are wave 1 Siemens 3 T FLASH (3), wave 1 Philips 1.5 T FFE (5),
wave 1 Philips 3 T FFE (2), and wave 2 Philips 3 T TFE (8). Exact membership and order
are in `analysis.yaml:permutation.strata`. Wave 1 PET dates span 2010-05–2011-04;
wave 2 spans 2014-07–2015-04. Dates are month-resolution evidence, not exact scan dates.

**SP06 has no sessions TSV. Its PET dates are UNKNOWN.** Its accepted wave-1 placement
is an inference recorded in `qc_decisions.md §8`, based on shared Siemens scanner
serial 40288 and FLASH family with SP02/SP10. Its protocol, excitation and TR/TE differ.
This is a provenance limitation, not a newly reconstructed date.

Broad acquisition families are not physical-scanner strata: SP15 uses a different
1.5 T unit; the two Philips 3 T units appear in both waves with different sequences.
Wave-2 protocol names include both `3D T1 TFE SAG 1 SENSE` and the `WIP` variant.
Reasons for protocol changes and MRI timing relative to PET are UNKNOWN.
The exchangeability assumption within these broad groups is not proven by metadata.

## Known anomalies

- Release 1.0.0 omitted SP06 from participants.tsv despite available imaging; 1.0.1
  adds it. The omission reason is UNKNOWN. The published README still describes 17.
- Primary supplied-map zeros are included; S7 excludes exact zeros. Their generating
  mechanism is unresolved. Do not silently recode zeros as missing.
- Historical re-registration and cortical/subcortical label mismatches are documented
  in [historical_discrepancies.md](historical_discrepancies.md).
- Visual QC was AI-assisted; human spot-confirmation remains recommended in the
  original decision record. See [audit-2026-09-29.md](audit-2026-09-29.md) for provenance gaps.
