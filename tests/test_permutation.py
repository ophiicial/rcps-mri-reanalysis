"""Phase 4 synthetic tests: stratified whole-subject permutation engine. No real data."""
import copy
import math

import numpy as np
import pytest
from scipy import stats

import rcps.analysis.cv as cv
import rcps.analysis.permutation as perm
from rcps.analysis.cv import nested_loso, summarize_loso
from rcps.analysis.permutation import (PermutationAssignments, exceedance_count, frozen_scheme,
                                       generate_assignments, identity_assignment, load_scheme,
                                       monte_carlo_uncertainty, panel_donor_positions, permutation_p_value,
                                       permute_mri, permuted_folds, replicate_statistic, require_frozen_scheme,
                                       run_permutation_test, validate_assignment, verify_block_permutation)
from rcps.analysis.ridge import fit_preprocessing
from rcps.config import REPO_ROOT, load_yaml

CFG = load_yaml(REPO_ROOT / "configs" / "analysis.yaml")
FROZEN_STRATA = (
    ("sub-SP02", "sub-SP06", "sub-SP10"),
    ("sub-SP03", "sub-SP05", "sub-SP11", "sub-SP12", "sub-SP15"),
    ("sub-SP09", "sub-SP14"),
    ("sub-SP16", "sub-SP18", "sub-SP20", "sub-SP21", "sub-SP22", "sub-SP23", "sub-SP26", "sub-SP28"),
)
# Regression guard for the frozen Monte Carlo sequence (seed 20260929, PCG64, construction of plan §11.4).
# A change here means the generator, construction, strata, subject order or B changed.
FROZEN_SHA256 = "d72dc968e292d533a93dbe7b6cc51068533c5904b002e06f40797676b900302c"
FROZEN_ROW0 = [0, 7, 2, 5, 8, 3, 9, 6, 4, 1, 16, 14, 15, 17, 10, 12, 13, 11]


def small_config(sizes=(3, 3), b=12, seed=7):
    """Synthetic scheme for fast evaluation tests (never the production scheme)."""
    cfg = copy.deepcopy(CFG)
    subjects = [f"sub-T{i:02d}" for i in range(sum(sizes))]
    cfg["cohort"]["primary"].update(subjects=subjects, n=len(subjects))
    strata, start = [], 0
    for k, n in enumerate(sizes):
        strata.append({"name": f"stratum{k}", "subjects": subjects[start:start + n]})
        start += n
    p = cfg["permutation"]
    p.update(strata=strata, group_size=math.prod(math.factorial(n) for n in sizes), B=b)
    p["rng"]["seed"] = seed
    return cfg


def coded_panel(ids, seed=0, signal=0.0):
    """Deterministic synthetic panel; `signal` scales a planted linear MRI effect on y."""
    n = len(ids)
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 68, 2))
    y = 5 + np.arange(68)[None, :] / 20 + rng.normal(scale=0.3, size=(n, 68)) + signal * (x @ np.array([1.0, -0.5]))
    return x, y


def recognisable_x(n):
    s, r, f = np.meshgrid(np.arange(n), np.arange(68), np.arange(2), indexing="ij")
    return (1000.0 * s + 10.0 * r + f).astype(float)


# ------------------------------------------------------------------ A. strata integrity
def test_frozen_scheme():
    scheme = load_scheme()
    assert scheme.strata == FROZEN_STRATA
    assert scheme.strata_names == ("wave1_siemens_3T_flash", "wave1_philips_1p5T_ffe", "wave1_philips_3T_ffe",
                                   "wave2_philips_3T_tfe")
    assert scheme.group_size == 58_060_800 == 6 * 120 * 2 * 40320
    assert scheme.b == 9999 and scheme.seed == 20260929
    assert scheme.canonical_subjects == tuple(CFG["cohort"]["primary"]["subjects"])
    assert sorted(s for st in scheme.strata for s in st) == sorted(scheme.canonical_subjects)


def _mutated(path, value):
    cfg = copy.deepcopy(CFG)
    node = cfg
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return cfg


@pytest.mark.parametrize("path, value, match", [
    (("permutation", "strata", 0, "subjects"), ["sub-SP02", "sub-SP06"], "partition|group size"),
    (("permutation", "strata", 0, "subjects"), ["sub-SP02", "sub-SP06", "sub-SP10", "sub-SP03"], "more than one"),
    (("permutation", "strata", 2, "subjects"), ["sub-SP09", "sub-SP99"], "partition"),
    (("permutation", "strata", 2, "subjects"), [], "nonempty"),
    (("permutation", "group_size"), 58060801, "group size"),
    (("permutation", "exceedance"), "T_b > T_obs", "frozen contract"),
    (("permutation", "one_global_assignment_per_replicate"), False, "frozen contract"),
    (("permutation", "rng", "generator"), "numpy.random.MT19937", "frozen contract"),
    (("cohort", "primary", "subjects", 0), "sub-SP03", "unique"),
])
def test_malformed_strata_or_contract_rejected(path, value, match):
    with pytest.raises(ValueError, match=match):
        load_scheme(_mutated(path, value))


def test_subjects_sorted_within_stratum_before_generation():
    shuffled = _mutated(("permutation", "strata", 3, "subjects"), list(reversed(FROZEN_STRATA[3])))
    a, b = load_scheme(shuffled), load_scheme()
    assert a.strata == b.strata
    assert generate_assignments(a).sha256 == generate_assignments(b).sha256


# ------------------------------------------------------------------ B. within-stratum restriction
def test_generated_assignments_never_cross_strata():
    scheme = load_scheme()
    a = generate_assignments(scheme)
    strata = np.array(scheme.stratum_index)
    assert a.donors.shape == (9999, 18) and not a.donors.flags.writeable
    assert np.array_equal(strata[a.donors], np.broadcast_to(strata, a.donors.shape))
    assert all(sorted(row) == list(range(18)) for row in a.donors.tolist())


@pytest.mark.parametrize("mutate, match", [
    (lambda r: r.__setitem__(slice(0, 2), [1, 0]), "crosses"),       # SP02 <-> SP03, different strata
    (lambda r: r.__setitem__(1, 1) or r.__setitem__(2, 1), "exactly once"),
    (lambda r: r.__setitem__(0, 18), "exactly once"),
])
def test_invalid_assignment_rows_rejected(mutate, match):
    scheme = load_scheme()
    row = identity_assignment(scheme).copy()
    mutate(row)
    with pytest.raises(ValueError, match=match):
        validate_assignment(scheme, row)
    with pytest.raises(ValueError):
        validate_assignment(scheme, np.arange(17))


# ------------------------------------------------------------------ C/P. whole-block movement, no ROI-row shuffle
def test_whole_blocks_move_together():
    scheme = load_scheme()
    x = recognisable_x(18)
    for row in generate_assignments(scheme).donors[:50]:
        xp = permute_mri(x, row)
        donor = np.round(xp[:, 0, 0] / 1000).astype(int)
        np.testing.assert_array_equal(donor, row)
        np.testing.assert_array_equal(xp - 1000.0 * row[:, None, None], x - 1000.0 * np.arange(18)[:, None, None])


def test_roi_row_or_feature_shuffle_is_detected():
    x = recognisable_x(6)
    row = np.array([1, 2, 0, 3, 5, 4])
    good = x[row]
    verify_block_permutation(x, good, row)
    rows_shuffled = good.copy()
    rows_shuffled[2, [5, 9]] = rows_shuffled[2, [9, 5]]
    cols_shuffled = good.copy()
    cols_shuffled[4] = cols_shuffled[4][:, ::-1]
    for bad in (rows_shuffled, cols_shuffled):
        with pytest.raises(ValueError, match="intact MRI block"):
            verify_block_permutation(x, bad, row)


# ------------------------------------------------------------------ D/E. y immutability and one global assignment
def test_y_ids_and_roi_axis_never_permuted(monkeypatch):
    scheme = load_scheme(small_config())
    ids = scheme.canonical_subjects
    x, y = coded_panel(ids)
    y_before, x_before = y.copy(), x.copy()
    seen = {}

    def spy(subject_ids, x_arg, y_arg, **kwargs):
        seen.update(ids=tuple(subject_ids), x=np.array(x_arg), y=np.array(y_arg))
        return nested_loso(subject_ids, x_arg, y_arg, **kwargs)

    monkeypatch.setattr(perm, "nested_loso", spy)
    row = np.array([2, 0, 1, 4, 5, 3])
    permuted_folds(ids, x, y, row)
    assert seen["ids"] == ids
    np.testing.assert_array_equal(seen["y"], y_before)
    np.testing.assert_array_equal(seen["x"], x_before[row])
    np.testing.assert_array_equal(y, y_before)
    np.testing.assert_array_equal(x, x_before)


def test_every_fit_sees_the_same_global_assignment(monkeypatch):
    """Instrument every inner/outer/candidate fit: each training row pairs outcome s with donor(s) only."""
    scheme = load_scheme()
    ids = scheme.canonical_subjects
    x = recognisable_x(18)
    y = 100.0 * np.arange(18)[:, None] + np.linspace(0, 1, 68)[None, :]  # y row identifies the outcome subject
    row = generate_assignments(scheme).donors[3]
    calls = []

    def recording_fit(x_train, y_train, lam):
        outcome = np.round(y_train[:, 0] / 100).astype(int)
        donor = np.round(x_train[:, 0, 0] / 1000).astype(int)
        calls.append((tuple(outcome), tuple(donor), lam))
        return real_fit(x_train, y_train, lam)

    real_fit = cv.fit_ridge
    monkeypatch.setattr(cv, "fit_ridge", recording_fit)
    permuted_folds(ids, x, y, row)
    assert len(calls) == 18 * 17 * 7 + 18
    for outcome, donor, _ in calls:
        assert donor == tuple(int(row[s]) for s in outcome)


# ------------------------------------------------------------------ F/G. determinism and seeds
def test_frozen_sequence_is_deterministic_and_pinned():
    a, b = generate_assignments(load_scheme()), generate_assignments(load_scheme())
    assert a.sha256 == b.sha256 == FROZEN_SHA256
    assert a.donors.tobytes() == b.donors.tobytes()
    assert a.donors[0].tolist() == FROZEN_ROW0
    assert a.numpy_version == np.__version__


def test_different_test_seed_changes_sequence_only_in_test_config():
    alt = load_scheme(_mutated(("permutation", "rng", "seed"), 12345))
    a = generate_assignments(alt)
    assert a.sha256 != FROZEN_SHA256 and not np.array_equal(a.donors, generate_assignments(load_scheme()).donors)
    assert load_scheme().seed == 20260929 and CFG["permutation"]["rng"]["seed"] == 20260929


def test_checksum_covers_provenance():
    scheme = load_scheme()
    donors = generate_assignments(scheme).donors
    renamed = load_scheme(_mutated(("permutation", "strata", 0, "name"), "renamed"))
    assert PermutationAssignments.from_donors(renamed, donors).sha256 != FROZEN_SHA256


# ------------------------------------------------------------------ H/K. identity
def test_identity_equals_direct_nested_loso():
    scheme = load_scheme()
    ids = scheme.canonical_subjects
    x, y = coded_panel(ids, seed=3, signal=0.5)
    identity = identity_assignment(scheme)
    validate_assignment(scheme, identity)
    np.testing.assert_array_equal(permute_mri(x, identity), x)
    direct, via = nested_loso(ids, x, y), permuted_folds(ids, x, y, identity)
    for a, b in zip(direct, via, strict=True):
        assert (a.subject_id, a.selected_lambda, a.d_s) == (b.subject_id, b.selected_lambda, b.d_s)
        np.testing.assert_array_equal(a.inner_losses, b.inner_losses)
        np.testing.assert_array_equal(a.ridge_prediction, b.ridge_prediction)
        np.testing.assert_array_equal(a.fit.coefficients, b.fit.coefficients)
    assert replicate_statistic(ids, x, y, identity) == summarize_loso(direct).t


# ------------------------------------------------------------------ J. full refitting under permutation
def test_permutation_refits_everything():
    scheme = load_scheme(small_config())
    ids = scheme.canonical_subjects
    x, y = coded_panel(ids, seed=5, signal=1.0)
    row = np.array([1, 2, 0, 5, 3, 4])
    observed = nested_loso(ids, x, y)
    permuted = permuted_folds(ids, x, y, row)
    fresh = nested_loso(ids, x[row], y)
    again = nested_loso(ids, x, y)
    for o, p, f, o2 in zip(observed, permuted, fresh, again, strict=True):
        np.testing.assert_array_equal(p.inner_losses, f.inner_losses)
        assert p.selected_lambda == f.selected_lambda and p.d_s == f.d_s
        train = list(p.training_indices)
        np.testing.assert_array_equal(p.fit.preprocessing.roi_means, fit_preprocessing(x[row][train]).roi_means)
        assert not np.array_equal(p.fit.preprocessing.roi_means, o.fit.preprocessing.roi_means)
        assert not np.array_equal(p.inner_losses, o.inner_losses)
        np.testing.assert_array_equal(o.inner_losses, o2.inner_losses)  # observed state never mutated
        np.testing.assert_array_equal(p.fit.baseline.roi_means, o.fit.baseline.roi_means)  # outcome-only


# ------------------------------------------------------------------ I. duplicates and cache multiplicity
def test_cache_preserves_multiplicity():
    scheme = load_scheme(small_config(b=10))
    ids = scheme.canonical_subjects
    x, y = coded_panel(ids, seed=9, signal=0.3)
    a, b_, c = [1, 2, 0, 3, 4, 5], [0, 1, 2, 3, 4, 5], [2, 0, 1, 5, 3, 4]
    rows = [a, a, b_, a, c, c, a, b_, a, a]  # a x6, identity x2, c x2
    assignments = PermutationAssignments.from_donors(scheme, rows)
    cached = run_permutation_test(ids, x, y, assignments, cache=True)
    uncached = run_permutation_test(ids, x, y, assignments, cache=False)
    np.testing.assert_array_equal(cached.null, uncached.null)
    assert (cached.k, cached.p_value, cached.b) == (uncached.k, uncached.p_value, uncached.b) and cached.b == 10
    assert (cached.n_evaluations, cached.n_cache_hits) == (3, 7)
    assert (uncached.n_evaluations, uncached.n_cache_hits) == (10, 0)
    values, counts = np.unique(cached.null, return_counts=True)
    assert sorted(counts.tolist()) == [2, 2, 6]
    assert np.sum(cached.null == cached.t_obs) == 2  # identity draws kept and tie with T_obs
    assert cached.k == exceedance_count(uncached.null, uncached.t_obs)


def test_evaluate_null_calls_and_order():
    scheme = load_scheme(small_config(b=5))
    rows = [[1, 2, 0, 3, 4, 5], [0, 1, 2, 3, 4, 5], [1, 2, 0, 3, 4, 5], [2, 0, 1, 3, 4, 5], [0, 1, 2, 3, 4, 5]]
    assignments = PermutationAssignments.from_donors(scheme, rows)
    calls = []

    def fake(row):
        calls.append(tuple(row))
        return float(row[0])

    null, n_eval, hits = perm.evaluate_null(assignments, fake, cache=True)
    assert null.tolist() == [1.0, 0.0, 1.0, 2.0, 0.0] and (n_eval, hits) == (3, 2)
    assert calls == [tuple(rows[0]), tuple(rows[1]), tuple(rows[3])]


def test_b_mismatch_rejected():
    scheme = load_scheme(small_config(b=4))
    ids = scheme.canonical_subjects
    x, y = coded_panel(ids)
    with pytest.raises(ValueError, match="B=4"):
        run_permutation_test(ids, x, y, PermutationAssignments.from_donors(scheme, [list(range(6))] * 3))


# ------------------------------------------------------------------ L. subject-order safety
def test_panel_order_does_not_change_subject_keyed_results():
    scheme = load_scheme(small_config())
    ids = scheme.canonical_subjects
    x, y = coded_panel(ids, seed=11, signal=0.7)
    row = np.array([2, 0, 1, 4, 5, 3])
    order = [4, 1, 5, 0, 3, 2]
    ids_r = tuple(ids[i] for i in order)
    ref = {f.subject_id: f for f in permuted_folds(ids, x, y, panel_donor_positions(scheme, ids, row))}
    got = {f.subject_id: f for f in
           permuted_folds(ids_r, x[order], y[order], panel_donor_positions(scheme, ids_r, row))}
    assert ref.keys() == got.keys()
    for s in ref:
        assert got[s].d_s == pytest.approx(ref[s].d_s, rel=1e-9, abs=1e-12)
        assert got[s].selected_lambda == ref[s].selected_lambda
        np.testing.assert_allclose(got[s].ridge_prediction, ref[s].ridge_prediction, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(got[s].baseline_prediction, ref[s].baseline_prediction, rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(panel_donor_positions(scheme, ids, row), row)
    with pytest.raises(ValueError, match="canonical cohort"):
        panel_donor_positions(scheme, (*ids[:-1], "sub-X"), row)


# ------------------------------------------------------------------ M/N/O. p-value and Monte Carlo uncertainty
def test_ties_count_as_exceedances():
    null = np.array([0.5, 1.0, 1.0, 2.0, -1.0])
    assert exceedance_count(null, 1.0) == 3
    assert permutation_p_value(3, 5) == 4 / 6
    with pytest.raises(ValueError):
        exceedance_count([np.nan, 1.0], 0.0)


def test_p_value_boundaries():
    assert permutation_p_value(0, 9999) == 1 / 10000
    assert permutation_p_value(9999, 9999) == 1.0
    for k, b in ((-1, 10), (11, 10), (0, 0)):
        with pytest.raises(ValueError):
            permutation_p_value(k, b)


@pytest.mark.parametrize("k, b", [(0, 9999), (1, 9999), (37, 9999), (500, 9999), (9999, 9999), (5, 10), (0, 1)])
def test_clopper_pearson_against_binomial_tails(k, b):
    mc = monte_carlo_uncertainty(k, b)
    lo, hi = mc.clopper_pearson_95
    assert mc.q_hat == k / b and mc.mc_se == pytest.approx(math.sqrt(k / b * (1 - k / b) / b))
    assert 0 <= lo <= k / b <= hi <= 1
    if k == 0:
        assert lo == 0 and hi == pytest.approx(1 - 0.025 ** (1 / b), rel=1e-9)
    else:
        assert stats.binom.sf(k - 1, b, lo) == pytest.approx(0.025, rel=1e-6)   # P(X >= k | lo)
    if k == b:
        assert hi == 1 and lo == pytest.approx(0.025 ** (1 / b), rel=1e-9)
    else:
        assert stats.binom.cdf(k, b, hi) == pytest.approx(0.025, rel=1e-6)     # P(X <= k | hi)


def test_clopper_pearson_textbook_case():
    lo, hi = monte_carlo_uncertainty(5, 10).clopper_pearson_95
    assert (round(lo, 4), round(hi, 4)) == (0.1871, 0.8129)


# ------------------------------------------------------------------ Q/R. end-to-end synthetic sanity
def test_null_construction_runs_end_to_end():
    scheme = load_scheme(small_config(sizes=(3, 3), b=15, seed=3))
    ids = scheme.canonical_subjects
    x, y = coded_panel(ids, seed=21, signal=0.0)
    assignments = generate_assignments(scheme)
    result = run_permutation_test(ids, x, y, assignments)
    assert result.b == 15 and result.null.shape == (15,) and np.all(np.isfinite(result.null))
    assert 0 <= result.k <= 15 and result.p_value == (1 + result.k) / 16
    identity = np.all(assignments.donors == np.arange(6), axis=1)
    np.testing.assert_array_equal(result.null[identity], result.t_obs)
    assert result.assignments_sha256 == assignments.sha256
    assert result.n_evaluations + result.n_cache_hits == 15


def test_planted_signal_exceeds_typical_null():
    """Implementation sanity only (not a power claim)."""
    scheme = load_scheme(small_config(sizes=(4, 4), b=20, seed=5))
    ids = scheme.canonical_subjects
    rng = np.random.default_rng(8)
    x = rng.normal(size=(8, 68, 2)) + rng.normal(scale=2.0, size=(8, 1, 2))  # subject-level MRI differences
    y = 5 + np.arange(68)[None, :] / 20 + 2.0 * (x @ np.array([1.0, -0.5])) + rng.normal(scale=0.05, size=(8, 68))
    result = run_permutation_test(ids, x, y, generate_assignments(scheme))
    assert result.t_obs > 0 and result.t_obs > np.median(result.null)


# ------------------------------------------------------------------ Phase-4 audit fixes
def _masked(a, cell):
    m = np.ma.masked_array(a, mask=np.zeros(a.shape, bool))
    m[cell] = np.ma.masked
    return m


def test_masked_inputs_rejected_at_permutation_boundary():
    scheme = load_scheme(small_config(b=2))
    ids = scheme.canonical_subjects
    x, y = coded_panel(ids)
    row = np.array([1, 2, 0, 3, 4, 5])
    assignments = PermutationAssignments.from_donors(scheme, [row, row])
    for bad_x, bad_y in ((_masked(x, (1, 5, 0)), y), (x, _masked(y, (2, 7))),
                         (np.ma.masked_array(x, mask=False), y)):  # a MaskedArray is rejected even unmasked
        with pytest.raises(ValueError, match="masked"):
            permuted_folds(ids, bad_x, bad_y, row)
        with pytest.raises(ValueError, match="masked"):
            run_permutation_test(ids, bad_x, bad_y, assignments)
    with pytest.raises(ValueError, match="masked"):
        permute_mri(_masked(x, (0, 0, 1)), row)
    # ordinary ndarrays are unchanged
    assert replicate_statistic(ids, x, y, row) == summarize_loso(nested_loso(ids, x[row], y)).t


@pytest.mark.parametrize("bad", [
    [1.9, 2.2, 0.1, 3.0, 4.0, 5.0],        # old bug: truncates to the valid [1, 2, 0, 3, 4, 5]
    [1.0, 2.0, 0.0, 3.0, 4.0, 5.0],        # integer-valued floats are rejected (integer dtype required)
    [np.nan, 2, 0, 3, 4, 5], [np.inf, 2, 0, 3, 4, 5],
    [True, False, True, False, True, False],
    np.array([1, 2, 0, 3, 4, 5], dtype=object),
])
def test_non_integer_donors_rejected_before_coercion(bad):
    scheme = load_scheme(small_config(b=1))
    with pytest.raises(ValueError, match="integer dtype"):
        PermutationAssignments.from_donors(scheme, [bad])
    with pytest.raises(ValueError, match="integer dtype"):
        validate_assignment(scheme, bad)
    with pytest.raises(ValueError, match="integer dtype"):
        permute_mri(coded_panel(scheme.canonical_subjects)[0], bad)


@pytest.mark.parametrize("bad", [[-1, 2, 0, 3, 4, 5], [1, 2, 6, 3, 4, 5], [1, 1, 0, 3, 4, 5]])
def test_out_of_range_or_duplicate_integer_donors_rejected(bad):
    scheme = load_scheme(small_config(b=1))
    with pytest.raises(ValueError, match="exactly once"):
        PermutationAssignments.from_donors(scheme, [bad])
    with pytest.raises(ValueError, match="permutation"):
        permute_mri(coded_panel(scheme.canonical_subjects)[0], np.array(bad))


def test_integer_donor_dtypes_accepted():
    scheme = load_scheme(small_config(b=1))
    for dtype in (np.int8, np.int32, np.uint16, np.int64):
        a = PermutationAssignments.from_donors(scheme, np.array([[1, 2, 0, 3, 4, 5]], dtype=dtype))
        assert a.donors.dtype == np.int64 and a.donors[0].tolist() == [1, 2, 0, 3, 4, 5]


@pytest.mark.parametrize("confidence", [0, 1, -0.5, 1.5, float("nan"), float("inf"), True, "0.95"])
def test_invalid_confidence_rejected(confidence):
    with pytest.raises(ValueError, match="confidence"):
        monte_carlo_uncertainty(3, 100, confidence)


def test_default_confidence_unchanged():
    assert monte_carlo_uncertainty(5, 10) == monte_carlo_uncertainty(5, 10, 0.95)
    assert monte_carlo_uncertainty(5, 10, np.float64(0.95)) == monte_carlo_uncertainty(5, 10)


def test_frozen_gate_accepts_frozen_scheme():
    scheme = frozen_scheme()
    assert scheme == load_scheme() and require_frozen_scheme(scheme) is scheme
    assert generate_assignments(scheme).sha256 == FROZEN_SHA256


def test_frozen_gate_rejects_swapped_strata_membership():
    cfg = copy.deepcopy(CFG)
    strata = cfg["permutation"]["strata"]
    strata[0]["subjects"] = ["sub-SP03", "sub-SP06", "sub-SP10"]
    strata[1]["subjects"] = ["sub-SP02", "sub-SP05", "sub-SP11", "sub-SP12", "sub-SP15"]
    swapped = load_scheme(cfg)   # structurally valid: partition and group size still hold
    assert swapped.group_size == 58_060_800
    with pytest.raises(ValueError, match="strata"):
        require_frozen_scheme(swapped)


@pytest.mark.parametrize("path, value", [
    (("permutation", "rng", "seed"), 1), (("permutation", "B"), 999),
    (("permutation", "strata", 0, "name"), "renamed")])
def test_frozen_gate_rejects_other_departures(path, value):
    with pytest.raises(ValueError, match="not the frozen"):
        require_frozen_scheme(load_scheme(_mutated(path, value)))


def test_synthetic_schemes_still_supported_but_not_frozen():
    scheme = load_scheme(small_config())
    assert len(generate_assignments(scheme).donors) == 12
    with pytest.raises(ValueError, match="not the frozen"):
        require_frozen_scheme(scheme)


def test_zero_scale_omission_is_recomputed_under_permutation():
    """Feature 1 varies across subjects only through one subject's block; permutation moves that block."""
    scheme = load_scheme(small_config())
    ids = scheme.canonical_subjects
    x, y = coded_panel(ids, seed=4)
    x[:, :, 1] = np.arange(68) + 0.1
    x[2, :, 1] += 1                       # only donor 2 carries feature-1 variation
    row = np.array([2, 0, 1, 3, 4, 5])    # outcome 0 receives donor 2's block
    carrier = {"observed": 2, "permuted": 0}
    for label, folds in (("observed", nested_loso(ids, x, y)), ("permuted", permuted_folds(ids, x, y, row))):
        for f in folds:
            for r, v in enumerate(f.inner_validation_indices):
                expected = carrier[label] in (f.held_out_index, v)
                np.testing.assert_array_equal(f.inner_omitted[r, :, 1], expected)
            assert bool(f.fit.preprocessing.omitted[1]) == (f.held_out_index == carrier[label])


def test_fabricated_null_with_identity_rows_and_duplicates():
    scheme = load_scheme(small_config(b=6))
    ids = scheme.canonical_subjects
    x, y = coded_panel(ids, seed=13, signal=0.4)
    identity, other = list(range(6)), [0, 2, 1, 4, 3, 5]
    rows = [identity, other, identity, other, other, identity]
    res = run_permutation_test(ids, x, y, PermutationAssignments.from_donors(scheme, rows))
    t_other = replicate_statistic(ids, x, y, np.array(other))
    np.testing.assert_array_equal(res.null, [res.t_obs, t_other, res.t_obs, t_other, t_other, res.t_obs])
    assert res.k == 3 + (3 if t_other >= res.t_obs else 0)
    assert res.p_value == (1 + res.k) / 7 and (res.n_evaluations, res.n_cache_hits) == (2, 4)
