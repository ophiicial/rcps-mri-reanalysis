"""Phase 2 synthetic orchestration tests; no real outcomes or inference."""
import dataclasses

import numpy as np
import pytest

import rcps.analysis.ridge as ridge
from rcps.analysis.cv import _validate_panel, nested_loso, primary_loso, summarize_loso
from rcps.analysis.ridge import LAMBDA_GRID, fit_ridge, select_lambda, subject_mse


@pytest.fixture(scope="module")
def panel():
    rng = np.random.default_rng(20260929)
    ids = tuple(f"synthetic-{i:02d}" for i in range(18))
    x = rng.normal(size=(18, 68, 2)) + rng.normal(size=(1, 68, 2))
    y = 10 + np.arange(68)[None, :] / 10 + x @ np.array([2., -1.])
    return ids, x, y


@pytest.fixture(scope="module")
def evaluated(panel):
    diagnostics = []
    folds = primary_loso(*panel, on_inner_fit=diagnostics.append)
    return folds, diagnostics


def assert_fit_equal(a, b):
    for left, right in [
        (a.preprocessing.roi_means, b.preprocessing.roi_means),
        (a.preprocessing.scales, b.preprocessing.scales),
        (a.preprocessing.omitted, b.preprocessing.omitted),
        (a.baseline.roi_means, b.baseline.roi_means),
        (a.coefficients, b.coefficients),
    ]:
        np.testing.assert_array_equal(left, right)
    assert a.preprocessing.n_train_subjects == b.preprocessing.n_train_subjects
    assert a.baseline.n_train_subjects == b.baseline.n_train_subjects
    assert a.lambda_value == b.lambda_value
    assert a.sklearn_alpha == b.sklearn_alpha
    assert a.numerical_rank == b.numerical_rank


def test_fold_counts_membership_scores_and_fresh_refit(panel, evaluated):
    ids, x, y = panel
    folds, diagnostics = evaluated
    assert len(folds) == 18
    assert [f.subject_id for f in folds] == list(ids)
    assert [f.held_out_index for f in folds] == list(range(18))
    assert len(diagnostics) == 18 * 17 * len(LAMBDA_GRID)
    for f in folds:
        expected = tuple(i for i in range(18) if i != f.held_out_index)
        assert f.training_indices == f.inner_validation_indices == expected
        assert f.inner_losses.shape == (17, 7)
        np.testing.assert_allclose(f.inner_scores, f.inner_losses.mean(axis=0), rtol=1e-14)
        assert select_lambda(f.lambdas, f.inner_scores) == f.selected_lambda
        assert f.inner_omitted.shape == (17, 7, 2) and f.inner_omitted.dtype == bool
        assert f.inner_rank.shape == (17,)
        assert not f.inner_omitted.flags.writeable and not f.inner_rank.flags.writeable
        inner = [d for d in diagnostics if d.outer_index == f.held_out_index]
        for lam in LAMBDA_GRID:
            candidates = [d for d in inner if d.fit.lambda_value == lam]
            assert tuple(d.validation_index for d in candidates) == expected
        for d in inner:
            assert len(d.training_indices) == 16
            assert set(d.training_indices) == set(expected) - {d.validation_index}
            assert d.fit.preprocessing.n_train_subjects == d.fit.baseline.n_train_subjects == 16
            assert d.fit is not f.fit
            assert d.fit.preprocessing is not f.fit.preprocessing
            assert d.fit.baseline is not f.fit.baseline
            assert d.mse == subject_mse(y[d.validation_index:d.validation_index + 1],
                                       d.prediction[None])[0]
            assert d.mse == f.inner_losses[expected.index(d.validation_index),
                                          f.lambdas.index(d.fit.lambda_value)]
        assert f.fit.preprocessing.n_train_subjects == f.fit.baseline.n_train_subjects == 17
        direct = fit_ridge(x[list(expected)], y[list(expected)], f.selected_lambda)
        assert_fit_equal(f.fit, direct)
        np.testing.assert_array_equal(f.ridge_prediction, direct.predict(x[f.held_out_index:f.held_out_index + 1])[0])
        assert f.d_s == f.baseline_mse - f.ridge_mse


def test_every_inner_fit_reconstructed_from_independent_indices(panel, evaluated):
    """Each inner fit must equal a direct fit on the 16 subjects it should use."""
    ids, x, y = panel
    folds, diagnostics = evaluated
    n = len(ids)
    by_key = {}
    for d in diagnostics:
        key = (d.outer_index, d.validation_index, d.fit.lambda_value)
        assert key not in by_key
        by_key[key] = d
    assert len(by_key) == n * (n - 1) * len(LAMBDA_GRID)
    for f in folds:
        outer = f.held_out_index
        for row, validation in enumerate(v for v in range(n) if v != outer):
            train = [i for i in range(n) if i not in (outer, validation)]
            assert len(train) == 16
            for column, lam in enumerate(f.lambdas):
                d = by_key[(outer, validation, lam)]
                assert d.training_indices == tuple(train)
                direct = fit_ridge(x[train], y[train], lam)
                assert_fit_equal(d.fit, direct)
                prediction = direct.predict(x[validation:validation + 1])
                np.testing.assert_array_equal(d.prediction, prediction[0])
                loss = subject_mse(y[validation:validation + 1], prediction)[0]
                assert d.mse == loss == f.inner_losses[row, column]
                np.testing.assert_array_equal(f.inner_omitted[row, column], direct.preprocessing.omitted)
                if lam == 0:
                    assert f.inner_rank[row] == direct.numerical_rank


def test_inner_zero_variance_events_and_ranks_persisted(panel):
    ids, x, y = panel
    ids, x, y = ids[:5], x[:5].copy(), y[:5]
    # Feature 1 varies across subjects only through subject 2: any training
    # set without subject 2 has zero variance and must omit that feature.
    x[:, :, 1] = np.arange(68) + 0.1
    x[2, :, 1] += 1
    for f in nested_loso(ids, x, y):
        training = [i for i in range(5) if i != f.held_out_index]
        for row, validation in enumerate(training):
            expected = f.held_out_index == 2 or validation == 2
            np.testing.assert_array_equal(f.inner_omitted[row, :, 0], False)
            np.testing.assert_array_equal(f.inner_omitted[row, :, 1], expected)
            assert f.inner_rank[row] == (1 if expected else 2)
        assert f.fit.preprocessing.omitted.tolist() == [False, f.held_out_index == 2]


def test_finite_positive_lambda_outer_refit(monkeypatch):
    """Code-path coverage for the sklearn Ridge outer refit; not a power claim."""
    rng = np.random.default_rng(20260929)
    ids = tuple(f"synthetic-{i:02d}" for i in range(18))
    x = rng.normal(size=(18, 68, 2)) + rng.normal(size=(1, 68, 2))
    y = (10 + np.arange(68)[None, :] / 10 + x @ np.array([0.2, -0.1])
         + rng.normal(scale=1.0, size=(18, 68)))
    calls = []

    class SpyRidge(ridge.Ridge):
        def fit(self, X, y, sample_weight=None):
            calls.append((X.shape[0], self.alpha))
            return super().fit(X, y, sample_weight)

    monkeypatch.setattr(ridge, "Ridge", SpyRidge)
    folds = primary_loso(ids, x, y)
    finite_positive = [f for f in folds if 0 < f.selected_lambda < np.inf]
    assert finite_positive
    for f in finite_positive:
        assert select_lambda(f.lambdas, f.inner_scores) == f.selected_lambda
        alpha = 17 * 68 * f.selected_lambda
        assert f.fit.sklearn_alpha == alpha and f.fit.numerical_rank is None
        assert (17 * 68, alpha) in calls  # outer refit rows, not a 16-subject inner fit
        train = [i for i in range(18) if i != f.held_out_index]
        direct = fit_ridge(x[train], y[train], f.selected_lambda)
        assert_fit_equal(f.fit, direct)
        np.testing.assert_array_equal(
            f.ridge_prediction, direct.predict(x[f.held_out_index:f.held_out_index + 1])[0])


def test_inputs_snapshotted_read_only(panel):
    ids, x, y = panel
    _, x_internal, y_internal = _validate_panel(ids, x, y)
    for internal, caller in [(x_internal, x), (y_internal, y)]:
        assert internal.dtype == np.float64 and not internal.flags.writeable
        assert not np.shares_memory(internal, caller)
    ids, x, y = ids[:4], x[:4].copy(), y[:4].copy()
    reference = nested_loso(ids, x, y)

    def mutate_caller(_):
        x[...] += 1000
        y[...] -= 1000

    mutated = nested_loso(ids, x, y, on_inner_fit=mutate_caller)
    assert len(mutated) == len(reference)
    for a, b in zip(reference, mutated, strict=True):
        assert a.subject_id == b.subject_id
        np.testing.assert_array_equal(a.inner_losses, b.inner_losses)
        assert a.selected_lambda == b.selected_lambda
        assert_fit_equal(a.fit, b.fit)
        np.testing.assert_array_equal(a.ridge_prediction, b.ridge_prediction)
        assert a.d_s == b.d_s


@pytest.mark.parametrize("perturb", ["x", "y"])
def test_outer_leakage(panel, evaluated, perturb):
    ids, x, y = panel
    changed_x, changed_y = x.copy(), y.copy()
    if perturb == "x":
        changed_x[0] += 100
    else:
        changed_y[0] += 100
    captured = []
    changed = primary_loso(ids, changed_x, changed_y, on_inner_fit=captured.append)[0]
    original = evaluated[0][0]
    np.testing.assert_array_equal(changed.inner_scores, original.inner_scores)
    np.testing.assert_array_equal(changed.inner_losses, original.inner_losses)
    assert changed.selected_lambda == original.selected_lambda
    assert_fit_equal(changed.fit, original.fit)
    original_inner = [d for d in evaluated[1] if d.outer_index == 0]
    changed_inner = [d for d in captured if d.outer_index == 0]
    assert len(original_inner) == len(changed_inner) == 17 * 7
    for a, b in zip(original_inner, changed_inner, strict=True):
        assert_fit_equal(a.fit, b.fit)
    np.testing.assert_array_equal(changed.baseline_prediction, original.baseline_prediction)
    if perturb == "y":
        np.testing.assert_array_equal(changed.ridge_prediction, original.ridge_prediction)
        assert changed.ridge_mse != original.ridge_mse
    else:
        assert not np.allclose(changed.ridge_prediction, original.ridge_prediction)


@pytest.mark.parametrize("perturb", ["x", "y"])
def test_inner_leakage(panel, evaluated, perturb):
    ids, x, y = panel
    changed_x, changed_y = x.copy(), y.copy()
    if perturb == "x":
        changed_x[1] += 100
    else:
        changed_y[1] += 100
    captured = []
    primary_loso(ids, changed_x, changed_y, on_inner_fit=captured.append)
    original = [d for d in evaluated[1] if d.outer_index == 0 and d.validation_index == 1]
    changed = [d for d in captured if d.outer_index == 0 and d.validation_index == 1]
    assert len(original) == len(changed) == 7
    for a, b in zip(original, changed, strict=True):
        assert_fit_equal(a.fit, b.fit)
        if perturb == "y":
            np.testing.assert_array_equal(a.prediction, b.prediction)
            assert a.mse != b.mse
        elif np.isfinite(a.fit.lambda_value):
            assert not np.allclose(a.prediction, b.prediction)
            assert a.mse != b.mse


def test_signal_and_equal_subject_summary(evaluated):
    folds, _ = evaluated
    summary = summarize_loso(folds)
    assert summary.t > 0  # deterministic planted signal, not a power claim
    assert summary.t == np.mean([f.d_s for f in folds])
    np.testing.assert_array_equal(summary.d_s, [f.d_s for f in folds])
    assert summary.mean_baseline_mse == np.mean([f.baseline_mse for f in folds])
    assert summary.mean_ridge_mse == np.mean([f.ridge_mse for f in folds])
    assert not hasattr(summary, "p_value")


def test_no_signal_infinity_and_zero_improvement(panel):
    ids, x, _ = panel
    # Exact shared ROI means: no intersubject outcome information to predict.
    y = np.tile(np.arange(68, dtype=float), (18, 1))
    folds = primary_loso(ids, x, y)
    for f in folds:
        assert f.selected_lambda == np.inf
        np.testing.assert_array_equal(f.ridge_prediction, f.baseline_prediction)
        assert f.d_s == 0
    assert summarize_loso(folds).t == 0


@pytest.mark.parametrize("reorder", ["subjects", "rois", "candidates"])
def test_order_invariance(panel, evaluated, reorder):
    ids, x, y = panel
    rng = np.random.default_rng(721)
    roi_order = np.arange(68)
    kwargs = {}
    if reorder == "subjects":
        order = rng.permutation(18)
        ids, x, y = tuple(ids[i] for i in order), x[order], y[order]
    elif reorder == "rois":
        roi_order = rng.permutation(68)
        x, y = x[:, roi_order], y[:, roi_order]
    else:
        kwargs["lambdas"] = tuple(reversed(LAMBDA_GRID))
    changed = primary_loso(ids, x, y, **kwargs)
    assert tuple(f.subject_id for f in changed) == ids
    by_id = {f.subject_id: f for f in evaluated[0]}
    assert len(changed) == len(by_id)
    for b in changed:
        a = by_id[b.subject_id]
        assert select_lambda(b.lambdas, b.inner_scores) == b.selected_lambda
        assert a.selected_lambda == b.selected_lambda
        for lam in LAMBDA_GRID:
            np.testing.assert_allclose(a.inner_scores[a.lambdas.index(lam)],
                                       b.inner_scores[b.lambdas.index(lam)], atol=1e-12)
        np.testing.assert_allclose(b.ridge_prediction, a.ridge_prediction[roi_order], atol=1e-12)
        np.testing.assert_allclose(b.baseline_prediction, a.baseline_prediction[roi_order], atol=1e-12)
        np.testing.assert_allclose([b.baseline_mse, b.ridge_mse, b.d_s],
                                   [a.baseline_mse, a.ridge_mse, a.d_s], atol=1e-12)
    np.testing.assert_allclose(summarize_loso(changed).t, summarize_loso(evaluated[0]).t, atol=1e-12)


@pytest.mark.parametrize("bad", ["duplicates", "id_count", "empty_id", "rois", "y_subjects",
                                      "nan_x", "inf_y", "empty_features", "masked", "too_few"])
def test_input_validation(panel, bad):
    ids, x, y = panel
    x, y = x.copy(), y.copy()
    if bad == "duplicates":
        ids = (ids[1], *ids[1:])
    elif bad == "id_count":
        ids = ids[:-1]
    elif bad == "empty_id":
        ids = ("", *ids[1:])
    elif bad == "rois":
        x, y = x[:, :-1], y[:, :-1]
    elif bad == "y_subjects":
        y = y[:-1]
    elif bad == "nan_x":
        x[0, 0, 0] = np.nan
    elif bad == "inf_y":
        y[0, 0] = np.inf
    elif bad == "empty_features":
        x = x[..., :0]
    elif bad == "masked":
        mask = np.zeros(x.shape, dtype=bool)
        mask[0, 0, 0] = True
        x = np.ma.array(x, mask=mask)
    else:
        ids, x, y = ids[:2], x[:2], y[:2]
    with pytest.raises(ValueError):
        nested_loso(ids, x, y)


def test_primary_shape_guards_and_generic_count(panel):
    ids, x, y = panel
    with pytest.raises(ValueError, match="18"):
        primary_loso(ids[:-1], x[:-1], y[:-1])
    with pytest.raises(ValueError, match="two"):
        primary_loso(ids, x[..., :1], y)
    assert len(nested_loso(ids[:3], x[:3], y[:3])) == 3


@pytest.mark.parametrize("lambdas", [LAMBDA_GRID[:-1], (*LAMBDA_GRID, 0), (*LAMBDA_GRID[:-1], 2)])
def test_invalid_candidates_fail_before_fitting(panel, lambdas, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("validation must precede fitting")
    monkeypatch.setattr("rcps.analysis.cv.fit_ridge", forbidden)
    with pytest.raises(ValueError):
        primary_loso(*panel, lambdas=lambdas)


def test_grid_without_lambda_zero_fails_before_fitting(panel, monkeypatch):
    """inner_rank is part of the contract, so a grid without lambda=0 must never run."""
    ids, x, y = panel
    no_zero = tuple(lam for lam in LAMBDA_GRID if lam != 0)
    assert len(no_zero) == len(LAMBDA_GRID) - 1

    def forbidden(*args, **kwargs):
        raise AssertionError("validation must precede fitting")
    monkeypatch.setattr("rcps.analysis.cv.fit_ridge", forbidden)
    with pytest.raises(ValueError, match="missing lambdas"):
        nested_loso(ids[:3], x[:3], y[:3], lambdas=no_zero)


def test_frozen_grid_unchanged_and_every_inner_rank_recorded(panel):
    ids, x, y = panel
    assert LAMBDA_GRID == (0.0, 0.01, 0.1, 1.0, 10.0, 100.0, np.inf)  # frozen plan §7
    for f in nested_loso(ids[:4], x[:4], y[:4]):
        assert f.lambdas == LAMBDA_GRID and 0.0 in f.lambdas
        for row, validation in enumerate(f.inner_validation_indices):
            train = [i for i in f.training_indices if i != validation]
            assert f.inner_rank[row] == fit_ridge(x[train], y[train], 0.0).numerical_rank


def test_summary_rejects_incomplete_or_duplicate_folds(evaluated):
    folds, _ = evaluated
    for invalid in [(), folds[:-1], (*folds, folds[0])]:
        with pytest.raises(ValueError):
            summarize_loso(invalid)


def test_no_input_mutation(panel):
    ids, x, y = panel
    x_before, y_before = x.copy(), y.copy()
    folds = nested_loso(ids[:3], x[:3], y[:3])
    np.testing.assert_array_equal(x, x_before)
    np.testing.assert_array_equal(y, y_before)
    assert not folds[0].inner_losses.flags.writeable
    assert not folds[0].ridge_prediction.flags.writeable


def test_missing_lambda_zero_rank_fails_explicitly(panel, monkeypatch):
    """Contract guard: a lambda=0 fit without a recorded rank must not be stored as a rank."""
    ids, x, y = panel

    def rank_dropping_fit(x_train, y_train, lambda_value):
        fit = fit_ridge(x_train, y_train, lambda_value)
        return dataclasses.replace(fit, numerical_rank=None) if fit.lambda_value == 0 else fit

    monkeypatch.setattr("rcps.analysis.cv.fit_ridge", rank_dropping_fit)
    with pytest.raises(RuntimeError, match="numerical rank"):
        nested_loso(ids[:3], x[:3], y[:3])
