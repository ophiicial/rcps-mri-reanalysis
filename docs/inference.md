# Statistical inference

This is the inference entry point. The accepted decision remains the frozen
[analysis_plan.md §11](analysis_plan.md) and its exact machine-readable counterpart
[configs/analysis.yaml:permutation](../configs/analysis.yaml). This summary introduces
no new design choices; any conflict requires a dated amendment, not a silent preference.

## Accepted / intended design

The operational null is exchangeability of whole-subject MRI assignments to outcome
subjects **within recruitment wave × broad MRI acquisition family**. The independent
unit is the subject. ROI rows and individual feature columns are not exchangeable
units for this test. Strata membership, order and rationale already exist in config
and [qc_decisions.md §8](qc_decisions.md); a separate strata file would duplicate them.

A replicate moves each complete 68×2 MRI block to an outcome subject in its stratum,
preserving both features and ROI correspondence. Outcomes, outcome-subject IDs, folds,
strata and lambda grid remain fixed. Primary Y already averages the three conditions;
conditions are neither independently shuffled nor pooled as extra subjects.
One global assignment is used throughout the replicate, including every inner fold.

Each MRI-dependent centring, scale, zero-scale decision, tuning, outer refit and
prediction is recomputed. Only outcome-only quantities, folds, grid and exact duplicate
assignment results may be cached. Do not reuse observed lambdas or MRI fitted state.

There are 3!×5!×2!×8! = **58,060,800** allowed assignments including identity.
The accepted strategy is Monte Carlo, not enumeration: B=9,999 independent uniform
draws **with replacement**, NumPy PCG64 seed 20260929. Identity and duplicates are
allowed; cached duplicates retain their sampling multiplicity. Sort IDs within each
stratum and use config stratum order. Pre-generate the full assignment list before
evaluation; save it or its deterministic checksum and NumPy/bit-generator version.

T is the equal-subject mean of baseline MSE minus ROI+MRI MSE. Count
K = number of sampled T_b ≥ T_obs, including equality. Report
**p=(1+K)/(B+1)**, threshold p≤.05, T_obs, K, B, saved null distribution, and a
95% Clopper–Pearson interval for the exceedance probability from K of B. The added
one accounts for the observed statistic; it does not require removing identity draws.
Monte Carlo uncertainty is not a population confidence interval for improvement.
Do not change seed/B or rerun selectively after seeing results.

## Assumptions and scope

Within-stratum exchangeability is a scientific assumption. Broad families retain
protocol/unit heterogeneity; SP06's accepted wave placement is inferred, with dates
UNKNOWN. Restriction preserves major acquisition/recruitment structure but does not
remove every possible nuisance effect. Rejection concerns conditional individual
MRI–rCPS correspondence; it does **not** demonstrate scanner-independent biological
prediction, causality, external validity, or positive population risk improvement.
Positive observed improvement additionally requires T_obs>0.

## Current implementation

There is **no reanalysis permutation sampler, evaluator, p-value routine, or null
output**. Config tests verify the frozen constants and strata partition; they do not
test operational shuffling, caching or calibration. Those tests remain required.
Historical `sklearn.inspection.permutation_importance` shuffles feature columns over
held-out ROI rows to describe fitted-model importance. It is not the accepted
whole-subject null test and produces no corresponding confirmatory p-value.

## Implementation review boundary

Maintain distinct outcome-subject IDs and MRI donor IDs in each permuted panel.
Under the accepted global reassignment, a held-out outcome subject's original MRI
may be assigned to a training outcome subject. This is part of the specified null
transformation, not permission for overlap of assigned train/test feature blocks.
Test that each donor block occurs once, that training and evaluation assigned blocks
are disjoint per split, and that held-out outcomes and assigned held-out predictors
cannot affect fitted state. Never silently replace the global permutation with
fold-local shuffles. Resolve any proposed scientific departure by amendment first.
