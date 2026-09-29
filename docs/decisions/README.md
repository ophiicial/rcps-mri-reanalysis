# Accepted decision records

The repository already has dated scientific decision records. Keep their history and
amendment mechanism; do not fabricate numbered ADRs or rewrite acceptance dates.

| Accepted decision | Canonical record | Rationale / alternatives / consequences |
|---|---|---|
| Continuous regression; cortical scope; ROI baseline + ridge; nested subject LOSO | [analysis plan §§2,4,7–8,13–14](../analysis_plan.md) | Predict held-out continuous ROI means; historical model tournament and subcortical/PVC extensions are outside frozen scope |
| Supplied rCPS grid, NN anatomical labels, no new registration | [QC decisions §3](../qc_decisions.md) | Header alignment judged by QC; historical/curator extra transforms evaluated, not selected |
| N=18 canonical release; zero inclusion primary/S7 exclusion | [QC decisions §§1–3](../qc_decisions.md), [analysis plan §§3,5,12](../analysis_plan.md) | Release provenance and measured-derivative target; explicit sensitivity |
| E2 restricted whole-subject permutation and acquisition grouping | [analysis plan §11](../analysis_plan.md), [QC provenance §8](../qc_decisions.md) | Preserves major wave/acquisition structure; conditional inference, not scanner independence |

For a genuinely new accepted methodological decision, add a short dated record with
Title, Status, Context, Decision, Rationale, Consequences, Alternatives considered;
also append the required amendment to `analysis_plan.md §14` and synchronize config
before inspecting affected results. Proposed decisions must remain labelled proposed.
