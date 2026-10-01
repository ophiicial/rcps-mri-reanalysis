"""Phase 4.5: synthetic calibration/power study mechanics. Tiny sizes only; no statistical assertions."""
import dataclasses
import inspect
import json
import math
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

import rcps.analysis.calibration as cal
from rcps.analysis.calibration import (SYNTHETIC_LABEL, Scenario, SimulationDesign, SimulationRecord,
                                       calibration_check, calibration_overall, dataset_seeds, generate_dataset,
                                       preset, rejection_interval, run_study, simulate_one, study_scheme,
                                       summarize_scenario, upper_confidence_bound)
from rcps.analysis.permutation import frozen_scheme, require_frozen_scheme

SCHEME = frozen_scheme()
NULL = Scenario("null", 0.0, 0.0, 2, 2)
CONF = Scenario("null_conf", 0.0, 0.8, 2, 2)
SIGNAL = Scenario("strong", 1.0, 0.0, 2, 2)
TINY = SimulationDesign("tiny", (NULL, SIGNAL), master_seed=7, alpha=0.05)


def ds(scenario=NULL, seed=11):
    return generate_dataset(SCHEME, scenario, seed)


# ------------------------------------------------------------------ generator
def test_shapes_finite_and_reproducible():
    a, b = ds(), ds()
    assert a.x.shape == (18, 68, 2) and a.y.shape == (18, 68) and a.subject_ids == SCHEME.canonical_subjects
    assert np.all(np.isfinite(a.x)) and np.all(np.isfinite(a.y))
    np.testing.assert_array_equal(a.x, b.x)
    np.testing.assert_array_equal(a.y, b.y)
    assert not a.x.flags.writeable and not a.y.flags.writeable


def test_different_seeds_give_different_datasets():
    a, b = ds(seed=11), ds(seed=12)
    assert not np.array_equal(a.x, b.x) and not np.array_equal(a.y, b.y)
    seeds = {(i, j): dataset_seeds(7, i, j) for i in range(3) for j in range(4)}
    data_states = {tuple(d.generate_state(4)) for d, _ in seeds.values()}
    perm_seeds = {p for _, p in seeds.values()}
    assert len(data_states) == len(perm_seeds) == 12
    assert 20260929 not in perm_seeds


def test_nondegenerate_variation():
    d = ds()
    assert np.all(d.x.std(axis=0) > 0) and np.all(d.y.std(axis=0) > 0)   # between-subject, every ROI/feature
    assert np.all(d.y.std(axis=1) > 0)                                    # between-ROI within subject


def test_only_x_to_y_term_is_the_planted_own_subject_signal():
    null, strong = ds(NULL), ds(SIGNAL)
    np.testing.assert_array_equal(null.x, strong.x)       # same seed, same X
    np.testing.assert_allclose(strong.y - null.y, 1.0 * cal.SIGMA_Y * null.signal, rtol=0, atol=1e-12)
    z = (null.x - null.roi_means[None]) / cal.SD_X
    np.testing.assert_allclose(null.signal, (z[..., 0] + z[..., 1]) / math.sqrt(2), atol=1e-12)
    for s in range(18):                                   # direction: own-subject features raise y
        assert np.corrcoef(strong.y[s] - null.y[s], null.x[s, :, 0] - null.roi_means[:, 0])[0, 1] > 0


def test_null_y_does_not_depend_on_x(monkeypatch):
    """beta=0, kappa=0: scaling the subject-specific MRI components leaves y unchanged."""
    base = ds(NULL)
    monkeypatch.setattr(cal, "SIGMA_E", cal.SIGMA_E * 3)
    monkeypatch.setattr(cal, "SIGMA_U", cal.SIGMA_U * 3)
    changed = ds(NULL)
    assert not np.array_equal(base.x, changed.x)
    np.testing.assert_array_equal(base.y, changed.y)


def test_confounded_null_links_x_and_y_only_through_stratum_effects(monkeypatch):
    """kappa > 0: y depends on X's realized stratum effects (so X and y are not independent given only the
    stratum label), but not on the subject-specific MRI components u, e."""
    base = ds(CONF)
    monkeypatch.setattr(cal, "SIGMA_E", cal.SIGMA_E * 3)
    monkeypatch.setattr(cal, "SIGMA_U", cal.SIGMA_U * 3)
    subject_scaled = ds(CONF)
    assert not np.array_equal(base.x, subject_scaled.x)
    np.testing.assert_array_equal(base.y, subject_scaled.y)
    monkeypatch.setattr(cal, "SIGMA_DELTA", cal.SIGMA_DELTA * 2)
    monkeypatch.setattr(cal, "SD_X", np.sqrt(cal.SIGMA_DELTA**2 + cal.SIGMA_U**2 + cal.SIGMA_E**2))
    stratum_scaled = ds(CONF)
    np.testing.assert_array_equal(base.y, stratum_scaled.y)      # gamma uses delta / sigma_delta: scale-free
    unconfounded = ds(NULL)
    assert not np.array_equal(base.y, unconfounded.y)            # kappa changes y only via stratum effects
    index = {s: i for i, s in enumerate(SCHEME.canonical_subjects)}
    for stratum in SCHEME.strata:                                  # constant shift within each stratum
        rows = [index[s] for s in stratum]
        shift = base.y[rows] - unconfounded.y[rows]
        np.testing.assert_allclose(shift, shift[0, 0], atol=1e-12)


def test_stratum_structure_follows_frozen_membership(monkeypatch):
    for name in ("SIGMA_U", "SIGMA_E"):
        monkeypatch.setattr(cal, name, np.zeros(2))
    monkeypatch.setattr(cal, "SIGMA_V", 0.0)
    monkeypatch.setattr(cal, "SIGMA_EPS", 0.0)
    d = ds(CONF)
    index = {s: i for i, s in enumerate(SCHEME.canonical_subjects)}
    for stratum in SCHEME.strata:
        rows = [index[s] for s in stratum]
        for r in rows[1:]:
            np.testing.assert_array_equal(d.x[r], d.x[rows[0]])
            np.testing.assert_array_equal(d.y[r], d.y[rows[0]])
    firsts = [index[st[0]] for st in SCHEME.strata]
    assert len({d.x[i, 0, 0] for i in firsts}) == 4 and len({d.y[i, 0] for i in firsts}) == 4


def test_invalid_scenarios_rejected():
    for bad in ((-0.1, 0.0), (np.nan, 0.0), (0.5, 1.0), (0.5, -0.1)):
        with pytest.raises(ValueError):
            Scenario("x", bad[0], bad[1], 1, 1)
    with pytest.raises(ValueError):
        Scenario("x", 0.0, 0.0, 0, 1)
    with pytest.raises(ValueError):
        SimulationDesign("d", (NULL, NULL), master_seed=1, alpha=0.05)


# ------------------------------------------------------------------ production boundary
def test_study_scheme_keeps_frozen_strata_but_is_not_production():
    s = study_scheme(19, 123)
    assert (s.strata, s.canonical_subjects, s.b, s.seed) == (SCHEME.strata, SCHEME.canonical_subjects, 19, 123)
    with pytest.raises(ValueError, match="not the frozen"):
        require_frozen_scheme(s)
    assert frozen_scheme().b == 9999 and frozen_scheme().seed == 20260929


def test_no_real_data_interface():
    text = Path(cal.__file__).read_text()
    assert "rcps.panel" not in text and "from ..panel" not in text and "CanonicalPanel" not in text
    for fn in (run_study, simulate_one, generate_dataset, cal.main):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"x", "y", "panel", "panel_path", "subject_ids"}


def test_presets_are_prespecified():
    quick, full = preset("quick"), preset("full")
    for d in (quick, full):
        assert [s.name for s in d.scenarios] == ["null", "null_stratum_confounded", "weak", "moderate", "strong"]
        assert [s.beta for s in d.scenarios] == [0.0, 0.0, 0.25, 0.5, 1.0]
        assert d.alpha == 0.05 and d.master_seed == 20261001
        for s in d.scenarios:   # attainable level equals alpha: (B + 1) * alpha is an integer
            assert math.isclose((s.permutation_b + 1) * d.alpha, round((s.permutation_b + 1) * d.alpha))
    assert d.to_json()["label"] == SYNTHETIC_LABEL and d.to_json()["production_B_not_used"] == 9999
    with pytest.raises(ValueError):
        preset("other")


def test_full_preset_is_pinned():
    # Final full design; any change here must be a deliberate, reviewed decision.
    full = preset("full")
    assert [(s.name, s.beta, s.kappa, s.n_simulations, s.permutation_b) for s in full.scenarios] == [
        ("null", 0.0, 0.0, 500, 39),
        ("null_stratum_confounded", 0.0, 0.8, 500, 39),
        ("weak", 0.25, 0.0, 200, 99),
        ("moderate", 0.5, 0.0, 200, 99),
        ("strong", 1.0, 0.0, 200, 99),
    ]
    assert cal.PRESET_SIZES["full"] == (500, 39, 200, 99)
    assert full.name == "full" and full.master_seed == 20261001 and full.alpha == 0.05
    assert full.calibration_confidence == 0.95
    assert full.calibration_upper_confidence == 0.975 and full.calibration_upper_tolerance == 0.075
    assert frozen_scheme().b == 9999 and frozen_scheme().seed == 20260929
    assert all(s.permutation_b != frozen_scheme().b for s in full.scenarios)


# ------------------------------------------------------------------ orchestration (tiny, real engine)
@pytest.fixture(scope="module")
def serial():
    return run_study(TINY, workers=1)


def test_records_order_validity_and_engine_use(serial):
    assert [(r.scenario, r.sim_index) for r in serial] == [("null", 0), ("null", 1), ("strong", 0), ("strong", 1)]
    for r in serial:
        assert r.b == 2 and r.n_evaluations + r.n_cache_hits == 2
        assert 1 / 3 <= r.p_value <= 1 and r.p_value == (1 + r.k) / 3
        assert r.reject == (r.p_value <= 0.05)
        assert math.isfinite(r.t_obs) and 0 <= r.frac_outer_lambda_inf <= 1
    assert len({r.assignments_sha256 for r in serial}) == 4 and len({r.permutation_seed for r in serial}) == 4


def test_every_replicate_calls_the_phase4_engine(monkeypatch):
    calls = []
    real = cal.run_permutation_test

    def spy(ids, x, y, assignments, **kw):
        calls.append((assignments.sha256, x.copy()))
        return real(ids, x, y, assignments, **kw)

    monkeypatch.setattr(cal, "run_permutation_test", spy)
    design = SimulationDesign("t", (Scenario("null", 0.0, 0.0, 2, 1),), master_seed=3, alpha=0.05)
    run_study(design)
    assert len(calls) == 2 and calls[0][0] != calls[1][0]
    assert not np.array_equal(calls[0][1], calls[1][1])   # a fresh dataset per simulation


def test_rerun_and_worker_count_reproduce_exactly(serial):
    strip = [dataclasses.replace(r, runtime_s=0.0) for r in serial]
    assert [dataclasses.replace(r, runtime_s=0.0) for r in run_study(TINY, workers=2)] == strip


# ------------------------------------------------------------------ summaries
def _records(rejects, beta=0.0, b=19):
    return [SimulationRecord("s", i, beta, 0.0, i, "h", 0.1 * i, 0 if r else 5, b, 0.05 if r else 0.3, r, 1, 0,
                             0.5, 1.0, 0.0) for i, r in enumerate(rejects)]


def test_summary_counts_and_rates():
    design = SimulationDesign("d", (NULL,), master_seed=1, alpha=0.05)
    rejects = [True, False, False, True, False]
    out = summarize_scenario(_records(rejects), design)
    assert out["n_simulations"] == 5 and out["n_rejected"] == 2 and out["rejection_rate"] == 0.4
    assert out["rejection_rate_se"] == pytest.approx(math.sqrt(0.4 * 0.6 / 5))
    assert "calibration_check" in out
    assert "calibration_check" not in summarize_scenario(_records(rejects, beta=1.0), design)


def test_rejection_interval_boundaries():
    assert rejection_interval(0, 50)[0] == 0 and rejection_interval(0, 50)[1] == pytest.approx(1 - 0.025 ** (1 / 50))
    assert rejection_interval(50, 50)[1] == 1 and rejection_interval(50, 50)[0] == pytest.approx(0.025 ** (1 / 50))
    for bad in ((-1, 5), (6, 5), (0, 0)):
        with pytest.raises(ValueError):
            rejection_interval(*bad)


def test_calibration_check_reports_attainable_level_and_tolerance():
    design = SimulationDesign("d", (NULL,), master_seed=1, alpha=0.05)
    c = calibration_check(25, 500, 19, design)
    assert c["nominal_alpha"] == 0.05 and c["attainable_level"] == 0.05
    assert calibration_check(25, 500, 29, design)["attainable_level"] == 1 / 30   # floor(0.05 * 30) / 30
    assert c["engineering_upper_tolerance"] == 0.075 and "not frozen methodology" in c["status"]
    assert c["upper_bound"] == pytest.approx(stats.beta.ppf(0.975, 26, 475))


def test_acceptable_and_excessive_rejection_counts():
    design = SimulationDesign("d", (NULL,), master_seed=1, alpha=0.05)
    ok = calibration_check(25, 500, 19, design)          # rate exactly 0.05
    assert ok["calibration_demonstrated"] and ok["result"] == "calibration demonstrated"
    bad = calibration_check(50, 500, 19, design)         # rate 0.10
    assert not bad["calibration_demonstrated"]
    assert bad["result"] == "calibration not demonstrated / possible excessive rejection"


def test_boundary_behaviour():
    design = SimulationDesign("d", (NULL,), master_seed=1, alpha=0.05)
    passes = [calibration_check(k, 500, 19, design)["calibration_demonstrated"] for k in range(60)]
    k_star = max(k for k, ok in enumerate(passes) if ok)
    assert all(passes[:k_star + 1]) and not any(passes[k_star + 1:])            # monotone threshold
    assert upper_confidence_bound(k_star, 500, 0.975) <= 0.075 < upper_confidence_bound(k_star + 1, 500, 0.975)
    exact = upper_confidence_bound(20, 400, 0.975)                               # tolerance equal to the bound
    at = SimulationDesign("d", (NULL,), master_seed=1, alpha=0.05, calibration_upper_tolerance=exact)
    assert calibration_check(20, 400, 19, at)["calibration_demonstrated"]       # <= is inclusive
    assert upper_confidence_bound(10, 10, 0.975) == 1.0
    assert upper_confidence_bound(0, 500, 0.975) == pytest.approx(1 - 0.025 ** (1 / 500))


def test_conservative_rates_do_not_fail_but_are_flagged():
    design = SimulationDesign("d", (NULL,), master_seed=1, alpha=0.05)
    for k in (0, 3, 10):
        c = calibration_check(k, 500, 19, design)
        assert c["calibration_demonstrated"]
    assert calibration_check(0, 500, 19, design)["pronounced_conservatism"]
    assert not calibration_check(25, 500, 19, design)["pronounced_conservatism"]


def test_two_null_scenarios_interpretation():
    design = SimulationDesign("d", (NULL, CONF), master_seed=1, alpha=0.05)
    good, bad = calibration_check(22, 500, 19, design), calibration_check(55, 500, 19, design)
    both = calibration_overall([good, good], design)
    assert both["calibration_demonstrated"] and both["n_null_scenarios"] == 2
    assert both["simultaneous_coverage_lower_bound"] == pytest.approx(0.95)    # Bonferroni: 1 - 2 * 0.025
    assert not calibration_overall([good, bad], design)["calibration_demonstrated"]
    assert not calibration_overall([], design)["calibration_demonstrated"]


def test_old_exact_containment_rule_removed():
    """A clearly conservative but valid procedure must not fail (the old rule failed 3/500)."""
    design = SimulationDesign("d", (NULL,), master_seed=1, alpha=0.05)
    assert calibration_check(3, 500, 19, design)["calibration_demonstrated"]


@pytest.mark.parametrize("kwargs", [
    {"alpha": 0.0}, {"alpha": 1.0}, {"alpha": float("nan")}, {"alpha": True},
    {"calibration_confidence": 1.5}, {"calibration_upper_confidence": 0.0},
    {"calibration_upper_tolerance": 0.04}, {"calibration_upper_tolerance": float("inf")},
    {"master_seed": -1}, {"master_seed": 1.5}, {"master_seed": True},
    {"scenarios": ()}, {"scenarios": [NULL]}, {"scenarios": ("null",)},
])
def test_design_validation(kwargs):
    base = {"name": "d", "scenarios": (NULL,), "master_seed": 1, "alpha": 0.05}
    with pytest.raises(ValueError):
        SimulationDesign(**{**base, **kwargs})


@pytest.mark.parametrize("args", [("x", 0.0, 0.0, 2.0, 5), ("x", 0.0, 0.0, 2, 5.0), ("x", 0.0, 0.0, True, 5),
                                  ("", 0.0, 0.0, 2, 5), ("x", "0.1", 0.0, 2, 5)])
def test_scenario_type_validation(args):
    with pytest.raises(ValueError):
        Scenario(*args)


def test_design_written_before_simulation(monkeypatch, tmp_path):
    """An interrupted run keeps its design and a 'started' run record."""
    from rcps.config import Paths
    monkeypatch.setattr(cal, "load_paths", lambda: Paths(tmp_path, tmp_path, tmp_path, tmp_path, tmp_path))
    monkeypatch.setattr(cal, "preset", lambda name: TINY)

    def interrupted(design, workers=1):
        raise KeyboardInterrupt

    monkeypatch.setattr(cal, "run_study", interrupted)
    with pytest.raises(KeyboardInterrupt):
        cal.main(["--preset", "quick"])
    (run_dir,) = list(tmp_path.glob("*_calibration-synthetic-tiny_*"))
    design = json.loads((run_dir / "simulation_design.json").read_text())
    assert design["label"] == SYNTHETIC_LABEL and design["name"] == "tiny"
    meta = json.loads((run_dir / "logs" / "run_metadata.json").read_text())
    assert meta["status"] == "started" and meta["inputs"] == {"real_data": None}
    assert not (run_dir / "summary.json").exists()
