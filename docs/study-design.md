# Study design

The accepted specification is [analysis_plan.md v3.0](analysis_plan.md), frozen
2026-09-28, paired with [configs/analysis.yaml](../configs/analysis.yaml).
This page explains the design; it does not amend that specification.

The question is whether prespecified structural MRI morphometrics improve prediction
of continuous, measured cortical ROI-mean rCPS beyond anatomical ROI identity in
held-out subjects. This is regression, not classification or a causal experiment.
The source is OpenNeuro ds004733 release 1.0.1, L-[1-11C]leucine PET and structural MRI.

There are 18 subjects, each with MRI and three PET conditions: Awake, SleepDeprived,
and Asleep. Regional measurements are nested within subjects; conditions are repeated
observations, not extra independent subjects. The primary outcome is the equal-weight
mean of the three condition-specific means in each of 68 bilateral DK cortical ROIs.
All conditions and ROIs are required. Thus 3,672 condition-level cells produce 1,224
subject–ROI targets, but the independent sample size remains 18.

Primary predictors are cortical thickness and ln(surface area / 1 mm²), with
unpenalised ROI effects. Volume and mean/Gaussian curvature belong only to the
prespecified five-feature sensitivity. The comparator is the training-subject mean
for each ROI. Primary validation is nested subject LOSO.

The single confirmatory test concerns MRI–outcome correspondence conditional on
recruitment wave × broad MRI acquisition family. It does not establish scanner-independent
prediction, external validity, causality, or positive population risk improvement.
The supplied rCPS maps are uncorrected for partial volume and include exact zeros;
geometry and mask effects may contribute to prediction. Sensitivities and exploratory
correlations/slopes are descriptive only. See [inference.md](inference.md),
[dataset.md](dataset.md), and [modeling.md](modeling.md).
