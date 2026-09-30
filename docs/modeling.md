# Modeling: specification pointers and implementation status

## Methodology

The frozen specification is [analysis_plan.md](analysis_plan.md) v3.0 (tag `analysis-plan-v3.0`)
with [configs/analysis.yaml](../configs/analysis.yaml). This page does not restate or amend it.

| Topic | Frozen source |
|---|---|
| Features and transforms | plan §6; `analysis.yaml:features` |
| ROI-mean baseline, centred ridge, scaling, zero-scale rule, λ grid, solvers, tie rule | plan §7; `analysis.yaml:ridge` |
| Outer/inner subject LOSO, selection score, refit | plan §8; `analysis.yaml:cv` |
| Per-subject D_s and primary statistic T | plan §9; `analysis.yaml:primary_effect` |
| Level/pattern decomposition (descriptive) | plan §10 |
| Sensitivities S1–S7, D1/D2, X1/X2 | plan §12, §16; `analysis.yaml:sensitivities`, `descriptive_and_exploratory` |
| Implementation tests required before real modeling | plan §15; `analysis.yaml:implementation_tests_required` |

## Current implementation

`rcps.analysis.ridge` implements fit/transform/predict/loss/selection primitives.
`rcps.analysis.cv` implements nested LOSO and equal-subject summaries; its returned
contract is in [data-contracts.md](data-contracts.md).
Inspection found no globally fitted preprocessing in this CV path. Outer and
inner perturbation tests explicitly check isolation. This conclusion applies to the
array API, not an absent real-data loader or permutation runner.

Data loading, target extraction, log transforms, metadata gates, semantic axis checks,
the five-feature ridge and HGBR sensitivities, R²/MAE/RMSE reporting, correlations,
slope summaries and model artifact writing remain unimplemented.
Historical feature permutation importance is not part of the new primary analysis.

## Current observed results

No real-data predictive metrics or permutation results were found in this repository.
Synthetic test output is validation evidence, not an empirical result. Historical
HGBR numbers belong to provenance track A only; see [results-map.md](results-map.md).
