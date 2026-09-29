"""Integrity of the frozen statistical config (configs/analysis.yaml). No modelling."""
import math

import yaml

from rcps.config import REPO_ROOT
from rcps.qc.verify_canonical import load_canonical

CFG = yaml.safe_load((REPO_ROOT / "configs" / "analysis.yaml").read_text())


def test_cohort_matches_canonical_roster():
    assert CFG["cohort"]["primary"]["n"] == 18
    assert sorted(CFG["cohort"]["primary"]["subjects"]) == sorted(load_canonical()["expected_participants"])


def test_strata_partition_cohort_and_group_size():
    strata = [s["subjects"] for s in CFG["permutation"]["strata"]]
    flat = [x for s in strata for x in s]
    assert len(flat) == len(set(flat)) == 18 and set(flat) == set(CFG["cohort"]["primary"]["subjects"])
    assert [len(s) for s in strata] == [3, 5, 2, 8]
    assert all(s == sorted(s) for s in strata)            # lexicographic within stratum
    assert math.prod(math.factorial(len(s)) for s in strata) == CFG["permutation"]["group_size"] == 58060800


def test_lambda_grid_explicit_zero_and_inf():
    grid = CFG["ridge"]["lambda_grid"]
    assert grid[0] == 0 and grid[-1] == "inf" and grid[1:-1] == [0.01, 0.1, 1, 10, 100]
    parsed = [math.inf if g == "inf" else float(g) for g in grid]
    assert parsed == sorted(parsed)


def test_frozen_inference_constants():
    p = CFG["permutation"]
    assert p["B"] == 9999 and p["rng"]["seed"] == 20260929 and p["alpha"] == 0.05
    assert p["sampling"]["with_replacement"] and p["identity_allowed"] and p["duplicates"]["allowed"]
    assert p["alternative"] == "upper_tail"


def test_s1_and_s6_grid():
    assert CFG["sensitivities"]["S1"]["exclude"] == ["sub-SP06"] and CFG["sensitivities"]["S1"]["n"] == 17
    g = CFG["sensitivities"]["S6"]["grid"]
    assert g == {"max_leaf_nodes": [3, 7], "max_iter": [100, 300]}


def test_no_machine_specific_paths_in_config():
    text = (REPO_ROOT / "configs" / "analysis.yaml").read_text()
    assert "/Users/" not in text and "/home/" not in text


# ---- static freeze assertions (config sanity only; no model fitting, no outcomes) ----
E2_STRATA = [
    ("wave1_siemens_3T_flash", ["sub-SP02", "sub-SP06", "sub-SP10"]),
    ("wave1_philips_1p5T_ffe", ["sub-SP03", "sub-SP05", "sub-SP11", "sub-SP12", "sub-SP15"]),
    ("wave1_philips_3T_ffe", ["sub-SP09", "sub-SP14"]),
    ("wave2_philips_3T_tfe", ["sub-SP16", "sub-SP18", "sub-SP20", "sub-SP21", "sub-SP22", "sub-SP23", "sub-SP26", "sub-SP28"]),
]


def test_e2_strata_exact_membership_and_order():
    assert [(s["name"], s["subjects"]) for s in CFG["permutation"]["strata"]] == E2_STRATA


def test_ridge_solver_conventions():
    sol = CFG["ridge"]["solver"]
    assert sol["finite_positive"] == {"library": "sklearn.linear_model.Ridge", "alpha": "m*68*lambda",
                                      "fit_intercept": False, "solver": "svd"}
    assert sol["zero"]["method"] == "numpy.linalg.lstsq" and sol["zero"]["rcond"] is None
    assert sol["zero"]["solution"] == "minimum_norm" and sol["zero"]["record"] == "numerical_rank"
    assert sol["inf"] == {"method": "bypass", "slopes": "zero", "predictions": "training_roi_means"}
    sc = CFG["ridge"]["scaling"]
    assert sc == {"type": "pooled_per_feature", "ddof": 0, "denominator": "mR"} and CFG["ridge"]["intercept"] is False


def test_tie_rules_primary_and_hgbr():
    t = CFG["ridge"]["tie_rule"]
    assert t["relative_tolerance"] == 1e-12 and t["if_S_inf_zero"] == "exact_equality" and t["prefer"] == "largest_lambda"
    h = CFG["sensitivities"]["S6"]["tie_rule"]
    assert h["inherits"] == "ridge.tie_rule" and h["relative_tolerance"] == 1e-12 and h["if_S_inf_zero"] == "exact_equality"
    assert h["then_prefer"] == ["fewer_leaves", "fewer_iterations"]


def test_inner_validation_scope():
    iv = CFG["cv"]["inner_validation_outcomes"]
    assert iv["may_affect"] == ["candidate_scores", "hyperparameter_selection"]
    assert iv["may_not_affect"] == ["fitted_preprocessing", "candidate_model_fits_within_split"]


def test_s5_feature_transforms():
    f = {x["name"]: x for x in CFG["sensitivities"]["S5"]["features"]}
    assert [x["name"] for x in CFG["sensitivities"]["S5"]["features"]] == [
        "thickness", "ln_area", "ln_volume", "mean_curvature", "gaussian_curvature"]
    assert f["thickness"]["transform"] == "none"
    assert f["ln_area"]["transform"] == "ln_over_1mm2" and f["ln_area"]["require_positive"]
    assert f["ln_volume"]["source"] == "GrayVol" and f["ln_volume"]["transform"] == "ln_over_1mm3" and f["ln_volume"]["require_positive"]
    assert f["mean_curvature"]["transform"] == "none" and f["mean_curvature"]["require_finite"]
    assert f["gaussian_curvature"]["transform"] == "none" and f["gaussian_curvature"]["require_finite"]
    assert "log1p" not in (REPO_ROOT / "configs" / "analysis.yaml").read_text()


def test_s7_all_zero_cell_policy_and_primary_zero_handling():
    s7 = CFG["sensitivities"]["S7"]
    assert s7["any_cell_with_zero_retained_voxels"] == "not_estimable" and s7["near_zero_removed"] is False
    assert CFG["target"]["zero_handling"] == "include_exact_zeros"


def test_sensitivities_descriptive_only():
    common = CFG["sensitivities"]["common"]
    assert common["p_values"] is False and common["own_nested_refit_and_tuning"] is True
    assert common["reuse_primary_models_or_lambdas"] is False
    assert set(k for k in CFG["sensitivities"] if k != "common") == {"S1", "S2", "S3", "S4", "S5", "S6", "S7"}
    assert set(CFG["descriptive_and_exploratory"]) == {"D1", "D2", "X1", "X2"}


def test_permutation_frozen_inference_fields():
    p = CFG["permutation"]
    assert p["B"] == 9999 and p["rng"] == {"generator": "numpy.random.PCG64", "seed": 20260929, "independent_of_model_rng": True}
    assert p["sampling"] == {"independent": True, "uniform_over_group": True, "with_replacement": True}
    assert p["identity_allowed"] is True and p["duplicates"]["allowed"] is True and p["duplicates"]["keep_multiplicity"] is True
    assert p["alternative"] == "upper_tail" and p["exceedance"] == "T_b >= T_obs"
    assert p["p_value"] == "(1 + K) / (B + 1)" and p["alpha"] == 0.05 and p["decision_rule"] == "p <= 0.05"
    assert p["pregenerate_full_list"] is True and p["population_confidence_interval"] == "none"
