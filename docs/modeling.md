# Modeling: specification and implementation status

## Methodology

[analysis_plan.md §§6–10,12,15](analysis_plan.md) and
[configs/analysis.yaml](../configs/analysis.yaml) retain the frozen scientific details.
The primary target is continuous three-condition mean rCPS. Inputs are thickness and
ln(area / 1 mm²); ROI identity enters as unpenalised ROI effects, not a fitted encoder.
The baseline is each ROI's training-subject mean.

Ridge uses training-only within-ROI feature centring, pooled per-feature scaling
(ddof=0, denominator m×68), and training ROI outcome means. Zero-scale features make
zero contribution and are recorded in fitted state. There is no imputation or
performance-based feature selection. The frozen lambda grid is 0, .01, .1, 1, 10,
100, infinity; positive lambda maps to sklearn alpha=m×68×lambda with SVD.
Zero uses minimum-norm least squares; infinity returns the baseline exactly.
Ties use the frozen tolerance and prefer larger lambda.

Outer LOSO separates 18 subjects; tuning is LOSO within the 17 training subjects,
with 16 used per inner fit. Every fit recomputes preprocessing; a fresh fit on all
outer-training subjects follows selection. Candidate scores average per-subject MSE
across 68 ROIs. The primary effect is baseline MSE minus augmented MSE per subject;
T averages these differences equally across subjects.

D1/D2 metrics and S1–S7 are descriptive; X1 correlations and X2 slope distributions
are exploratory descriptive. The five-feature ridge and categorical-ROI HGBR are
specified sensitivities, not implemented runners. Fixed ROI codes for HGBR are
0–67 in `dk_cortical_labels()` order. Its model seed and the independent permutation
seed are 20260929. Primary ridge itself is deterministic.

## Current implementation

`rcps.analysis.ridge` implements fit/transform/predict/loss/selection primitives.
`rcps.analysis.cv` implements nested LOSO and equal-subject summaries; it and its tests
were untracked at audit start on 2026-09-29 and were then committed (`18471e9`). A later
change adds an explicit failure when a λ=0 fit has no numerical rank, with a test; valid
inputs behave as before.
Inspection found no globally fitted preprocessing in this new CV path. Outer and
inner perturbation tests explicitly check isolation. This conclusion applies to the
array API, not an absent real-data loader or permutation runner.

Data loading, target extraction, log transforms, metadata gates, semantic axis checks,
HGBR sensitivities, R²/MAE/RMSE reporting, correlations, feature-importance reports,
and model artifact writing remain unimplemented. See [data-contracts.md](data-contracts.md).
Historical feature permutation importance is not part of the new primary analysis.

## Current observed results

No real-data predictive metrics or permutation results were found in this repository.
Synthetic test output is validation evidence, not an empirical result. Historical
HGBR numbers belong to provenance track A only; see [results-map.md](results-map.md).
