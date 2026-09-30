# Statistical inference

This is the inference entry point. The accepted design is the frozen
[analysis_plan.md §11](analysis_plan.md) (tag `analysis-plan-v3.0`) and its machine-readable
counterpart [configs/analysis.yaml:permutation](../configs/analysis.yaml). This page introduces
no design choices; any conflict requires a dated amendment, not a silent preference.

## Where the accepted design is specified

| Topic | Frozen source |
|---|---|
| Hypotheses, operational null, conditioning on strata | plan §11.1 |
| E2 strata, membership, order, group size | plan §11.2; `permutation.strata`, `permutation.group_size` |
| One replicate: what moves, what is fixed, recomputed, cacheable, never reused | plan §11.3; `permutation.fixed`, `recompute`, `cacheable`, `never_reuse` |
| B, sampling, identity/duplicates, RNG, seed, construction, pre-generation | plan §11.4; `permutation.B`, `sampling`, `rng`, `construction` |
| Exceedance, p-value, threshold, reporting, no reruns/seed changes | plan §11.5 |
| Interpretation and what rejection does not establish | plan §11.6, §2 |

Strata provenance is in [qc_decisions.md §8](qc_decisions.md); acquisition uncertainty
(including SP06's inferred wave placement) is summarized in [dataset.md](dataset.md).
Strata are read from config; a separate strata file would duplicate them.

## Current implementation

`rcps.analysis.permutation` implements the sampler, the whole-subject block evaluator
around `nested_loso`, exceedance counting, the p-value and Monte Carlo uncertainty. Its
contract is in [data-contracts.md](data-contracts.md). It is tested on synthetic panels
only. **No real-data T_obs, null distribution or p-value has been computed**, and no
permutation runner or CLI connects it to the canonical panel.

Two kinds of synthetic check exist:
- Sanity tests in `tests/test_permutation.py`. These are single datasets and make no statistical claim.
- A repeated-simulation study, `rcps.analysis.calibration`. Its null and planted-signal scenarios each use many
  independent synthetic datasets, and every dataset goes through the unchanged nested permutation stack.

The study uses the frozen strata but a study-specific B and seed, and it cannot consume real data. Its
null criterion is an engineering false-positive-control check, not frozen methodology: a one-sided 97.5%
upper bound on the rejection rate must be ≤ 0.075.

In the confounded null, shared stratum effects make X and y dependent across datasets, given only the
stratum label. What holds is that, given the realized stratum effects, the subject-specific components are
independent and subjects are exchangeable within strata. The joint distribution is therefore invariant to
within-stratum block permutation.

Only the `quick` preset has been run, as a benchmark. The sizes and B of the `full` preset are provisional
and must be fixed before execution. **Plan §15 item 13 is not yet satisfied.**
Historical `sklearn.inspection.permutation_importance` shuffles feature columns over
held-out ROI rows to describe fitted-model importance. It is not the accepted
whole-subject test and produces no corresponding confirmatory p-value.

## Engineering and test guidance (not frozen methodology)

The checks below are implementation guidance for a future permutation runner. They
follow from plan §11.3 but are **not** additions to the accepted design or to the plan §15
test list; promoting any of them to a requirement of the specification needs an amendment.

- Keep outcome-subject IDs distinct from the subject whose MRI block each outcome
  subject receives in a replicate. Under the plan's single global assignment, a held-out
  outcome subject's original MRI block may be assigned to a training outcome subject; that
  is part of the specified reassignment, not leakage.
- Useful consistency checks: each MRI block is used exactly once per assignment; within
  each split, the blocks assigned to training and evaluation outcome subjects are disjoint;
  held-out outcomes and the block assigned to the held-out subject cannot affect fitted state.
- Never replace the global assignment with fold-local shuffles. Resolve any proposed
  scientific departure by amendment first.
