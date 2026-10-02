# Synthetic permutation calibration review

## Status

Calibration engineering validation completed successfully.

This document records the full synthetic calibration study required by
Section 15 of the frozen analysis plan. It is an engineering/simulation
validation of the permutation-inference implementation and is **not**
real-data inference.

The frozen analysis plan was not modified in response to these results.

## Provenance

- Calibration run: `20261001-113450_calibration-synthetic-full_19c166f`
- Analysis code commit:
  `19c166fa275f727d0d6b3d215e7b7e01854acbe6`
- Frozen scientific specification tag: `analysis-plan-v3.0`
- Frozen specification commit:
  `80d951fbfb6929e9470786b0a0fbcb2c81630055`
- Synthetic master seed: `20261001`
- Workers: 14
- Runtime: 16,352.47 s (~4.54 h)
- Execution environment: Google Cloud Batch, `e2-standard-16`
- Production permutation count (`B=9999`) was not used in the calibration study.

The cloud execution explicitly verified both the analysis-code HEAD and the
frozen analysis-plan tag before calibration began.

## Prespecified calibration criterion

For each of the two null scenarios, calibration is demonstrated when the
one-sided 97.5% Clopper-Pearson upper confidence bound for the rejection
probability is no greater than 0.075.

The two null checks use Bonferroni allocation, providing at least 95%
simultaneous coverage across the two null scenarios.

Nominal alpha is 0.05.

Pronounced conservatism may be reported and investigated but does not,
by itself, fail the calibration criterion.

## Simulation design

| Scenario | Beta | Kappa | Simulations | Permutations per simulation |
|---|---:|---:|---:|---:|
| Null | 0.00 | 0.0 | 500 | 39 |
| Stratum-confounded null | 0.00 | 0.8 | 500 | 39 |
| Weak signal | 0.25 | 0.0 | 200 | 99 |
| Moderate signal | 0.50 | 0.0 | 200 | 99 |
| Strong signal | 1.00 | 0.0 | 200 | 99 |

The production permutation setting remains `B=9999`; the smaller calibration
values above are specific to the synthetic study.

## Null calibration results

| Scenario | Rejections | Rejection rate | 97.5% upper bound | Tolerance | Result |
|---|---:|---:|---:|---:|---|
| Null | 19 / 500 | 0.038 | 0.058707 | 0.075 | Pass |
| Stratum-confounded null | 22 / 500 | 0.044 | 0.065861 | 0.075 | Pass |

Both prespecified null calibration checks passed.

Neither null scenario was flagged for pronounced conservatism.

## Planted-signal behavior

| Signal | Beta | Rejections | Rejection rate |
|---|---:|---:|---:|
| Weak | 0.25 | 49 / 200 | 0.245 |
| Moderate | 0.50 | 117 / 200 | 0.585 |
| Strong | 1.00 | 199 / 200 | 0.995 |

Rejection probability increased monotonically with planted signal strength,
providing an additional qualitative sanity check on the inference pipeline.

The mean fraction of outer fits selecting `lambda = infinity` also decreased
with increasing signal:

- Null: 0.4464
- Stratum-confounded null: 0.3831
- Weak: 0.2739
- Moderate: 0.0639
- Strong: 0.0000

This pattern is descriptive and was not part of the formal calibration
pass/fail criterion.

## Output integrity

The completed run contains:

- `null_results.tsv`: 1,000 simulation records
- `power_results.tsv`: 600 simulation records
- `simulation_design.json`
- `summary.json`

The stored design and resulting record counts agree with the prespecified
full calibration preset.

## Conclusion

The synthetic permutation calibration satisfies the prespecified Section 15
engineering criterion.

The permutation implementation may therefore proceed to the frozen real-data
analysis without methodological modification based on the calibration result.

This result validates the behavior of the inference machinery under the
specified synthetic scenarios. It does not constitute evidence that structural
MRI predicts rCPS in the real dataset; that question is reserved for the
subsequent frozen real-data analysis.
