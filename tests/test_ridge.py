"""Synthetic complete-panel tests for Phase 1; no real outcome reads or CV."""
import numpy as np
import pytest

from rcps.analysis.ridge import (
    LAMBDA_GRID, N_ROIS, TIE_RELATIVE_TOLERANCE, candidate_score,
    fit_preprocessing, fit_ridge, fit_roi_baseline, parse_lambda,
    select_lambda, subject_mse, transform_features,
)
from rcps.config import REPO_ROOT, load_yaml


@pytest.fixture
def panel():
    rng = np.random.default_rng(81)
    x = rng.normal(size=(8, N_ROIS, 2)) + rng.normal(size=(1, N_ROIS, 2)) * 4
    y = rng.normal(size=(1, N_ROIS)) + x @ np.array([0.7, -0.3])
    y += rng.normal(scale=0.2, size=y.shape)
    return x, y


def test_training_roi_means_and_pooled_ddof_zero(panel):
    x, _ = panel
    train = x[:6]
    state = fit_preprocessing(train)
    expected_means = train.mean(axis=0)
    residual = train - expected_means
    expected_scale = np.sqrt(np.sum(residual ** 2, axis=(0, 1)) / (6 * N_ROIS))
    np.testing.assert_array_equal(state.roi_means, expected_means)
    np.testing.assert_allclose(state.scales, expected_scale, rtol=1e-14)
    np.testing.assert_allclose(state.scales, residual.reshape(-1, 2).std(axis=0, ddof=0))
    assert not np.allclose(state.scales, residual.reshape(-1, 2).std(axis=0, ddof=1), rtol=1e-5)
    np.testing.assert_allclose(transform_features(train, state).mean(axis=0), 0, atol=1e-14)
    np.testing.assert_allclose(np.mean(transform_features(train, state) ** 2, axis=(0, 1)), 1)
    assert state.n_train_subjects == 6


def test_held_out_features_use_saved_training_state(panel):
    x, _ = panel
    state = fit_preprocessing(x[:6])
    means, scales = state.roi_means.copy(), state.scales.copy()
    held_out = x[6:] + 100
    np.testing.assert_allclose(transform_features(held_out, state), (held_out - means) / scales)
    transform_features(held_out * -20, state)
    np.testing.assert_array_equal(state.roi_means, means)
    np.testing.assert_array_equal(state.scales, scales)
    assert not np.allclose(state.roi_means, np.concatenate([x[:6], held_out]).mean(axis=0))
    assert not state.roi_means.flags.writeable and not state.scales.flags.writeable


@pytest.mark.parametrize("lam", LAMBDA_GRID)
def test_fit_api_uses_supplied_training_arrays_only(panel, lam, monkeypatch):
    """API isolation, not an outer/inner leakage test (that belongs to Phase 2)."""
    import rcps.analysis.ridge as ridge

    x, y = panel
    train_x, train_y = x[:6].copy(), y[:6].copy()
    held_x, held_y = x[6:].copy(), y[6:].copy()
    preprocessing_calls, baseline_calls = [], []
    original_preprocessing = ridge.fit_preprocessing
    original_baseline = ridge.fit_roi_baseline

    def training_preprocessing(values):
        np.testing.assert_array_equal(values, train_x)
        assert not np.shares_memory(values, held_x)
        preprocessing_calls.append(values.shape[0])
        return original_preprocessing(values)

    def training_baseline(values):
        np.testing.assert_array_equal(values, train_y)
        assert not np.shares_memory(values, held_y)
        baseline_calls.append(values.shape[0])
        return original_baseline(values)

    monkeypatch.setattr(ridge, "fit_preprocessing", training_preprocessing)
    monkeypatch.setattr(ridge, "fit_roi_baseline", training_baseline)
    fit = ridge.fit_ridge(train_x, train_y, lam)
    means = fit.preprocessing.roi_means.copy()
    scales = fit.preprocessing.scales.copy()
    coefficients = fit.coefficients.copy()
    baseline = fit.baseline.roi_means.copy()
    prediction = fit.predict(held_x)
    old_loss = candidate_score(subject_mse(held_y, prediction))
    held_y += 1000
    held_x -= 1000
    fit.predict(held_x)
    assert candidate_score(subject_mse(held_y, prediction)) != old_loss
    # Prediction/scoring must not trigger another fit or mutate saved state.
    assert preprocessing_calls == baseline_calls == [6]
    np.testing.assert_array_equal(fit.preprocessing.roi_means, means)
    np.testing.assert_array_equal(fit.preprocessing.scales, scales)
    np.testing.assert_array_equal(fit.coefficients, coefficients)
    np.testing.assert_array_equal(fit.baseline.roi_means, baseline)


@pytest.mark.parametrize("lam", LAMBDA_GRID)
def test_training_perturbation_positive_control(panel, lam):
    x, y = panel
    original = fit_ridge(x[:6], y[:6], lam)
    perturbed = x[:6].copy()
    perturbed[0, :, 0] += 20
    changed = fit_ridge(perturbed, y[:6], lam)
    assert not np.allclose(original.preprocessing.roi_means, changed.preprocessing.roi_means)
    assert not np.allclose(original.preprocessing.scales, changed.preprocessing.scales)
    if np.isfinite(lam):
        assert not np.allclose(original.coefficients, changed.coefficients)
    else:
        # Infinity ignores MRI by definition, while its fitted feature state still changes.
        np.testing.assert_array_equal(original.predict(x[6:]), changed.predict(x[6:]))


def test_baseline_and_infinity_are_exact(panel, monkeypatch):
    x, y = panel
    baseline = fit_roi_baseline(y[:6])
    np.testing.assert_array_equal(baseline.roi_means, y[:6].mean(axis=0))
    def forbidden(*args, **kwargs):
        raise AssertionError("infinity must bypass the solver")
    monkeypatch.setattr("rcps.analysis.ridge.Ridge", forbidden)
    monkeypatch.setattr(np.linalg, "lstsq", forbidden)
    fit = fit_ridge(x[:6], y[:6], "inf")
    np.testing.assert_array_equal(fit.predict(x[6:]), baseline.predict(2))
    np.testing.assert_array_equal(fit.coefficients, [0, 0])
    assert fit.sklearn_alpha is None and fit.numerical_rank is None


@pytest.mark.parametrize("lam", [0.01, 0.1, 1, 10, 100])
def test_alpha_conversion_matches_normalised_closed_form(panel, lam):
    x, y = panel
    fit = fit_ridge(x, y, lam)
    z = transform_features(x, fit.preprocessing).reshape(-1, 2)
    u = (y - y.mean(axis=0)).reshape(-1)
    n = x.shape[0] * N_ROIS
    expected = np.linalg.solve(z.T @ z / n + lam * np.eye(2), z.T @ u / n)
    np.testing.assert_allclose(fit.coefficients, expected, rtol=1e-12, atol=1e-14)
    assert fit.sklearn_alpha == n * lam
    np.testing.assert_allclose(fit.predict(x), y.mean(axis=0) + (z @ expected).reshape(y.shape))


def test_zero_lambda_minimum_norm_rank_deficient(panel):
    x, y = panel
    x = np.repeat(x[..., :1], 2, axis=2)  # exactly collinear retained predictors
    fit = fit_ridge(x, y, 0)
    z = transform_features(x, fit.preprocessing).reshape(-1, 2)
    expected, _, rank, _ = np.linalg.lstsq(z, (y - y.mean(axis=0)).reshape(-1), rcond=None)
    np.testing.assert_array_equal(fit.coefficients, expected)
    assert fit.numerical_rank == rank == 1
    np.testing.assert_allclose(fit.coefficients[0], fit.coefficients[1])


@pytest.mark.parametrize("lam", [0, 0.1, 10])
def test_equivalence_to_explicit_unpenalised_roi_effects(panel, lam):
    x, y = panel
    train_x, train_y = x[:6], y[:6]
    fit = fit_ridge(train_x, train_y, lam)
    n = train_y.size
    roi_design = np.tile(np.eye(N_ROIS), (train_x.shape[0], 1))
    # Use uncentred, scaled predictors with explicit free ROI intercepts.
    scaled_x = (train_x / fit.preprocessing.scales).reshape(-1, 2)
    design = np.column_stack([roi_design, scaled_x])
    penalty_rows = np.zeros((2, N_ROIS + 2))
    penalty_rows[:, N_ROIS:] = np.sqrt(n * lam) * np.eye(2)
    coef = np.linalg.lstsq(np.vstack([design, penalty_rows]),
                           np.r_[train_y.reshape(-1), np.zeros(2)], rcond=None)[0]
    explicit_prediction = coef[:N_ROIS] + (x[6:] / fit.preprocessing.scales) @ coef[N_ROIS:]
    np.testing.assert_allclose(fit.predict(x[6:]), explicit_prediction, rtol=1e-10, atol=1e-11)
    np.testing.assert_allclose(fit.coefficients, coef[N_ROIS:], rtol=1e-10, atol=1e-11)


@pytest.mark.parametrize("lam", [0, 1, np.inf])
def test_zero_variance_feature_omitted_even_for_different_held_out_values(panel, lam):
    x, y = panel
    x = x.copy()
    x[:6, :, 1] = np.arange(N_ROIS) + 0.1  # varies across ROIs, never across training subjects
    fit = fit_ridge(x[:6], y[:6], lam)
    assert fit.preprocessing.omitted.tolist() == [False, True]
    assert fit.preprocessing.scales[1] == 0 and fit.coefficients[1] == 0
    if lam == 0:
        assert fit.numerical_rank == np.count_nonzero(~fit.preprocessing.omitted) == 1
    held_out = x[6:].copy()
    before = fit.predict(held_out)
    held_out[..., 1] += 1e6
    np.testing.assert_array_equal(fit.predict(held_out), before)
    np.testing.assert_array_equal(transform_features(held_out, fit.preprocessing)[..., 1], 0)


@pytest.mark.parametrize("lam", [0, 1, np.inf])
def test_all_features_zero_variance(panel, lam):
    _, y = panel
    x = np.full((8, N_ROIS, 2), 0.1)
    fit = fit_ridge(x, y, lam)
    assert fit.preprocessing.omitted.all()
    np.testing.assert_array_equal(fit.predict(x[:2] + 100), fit.baseline.predict(2))
    if lam == 0:
        assert fit.numerical_rank == 0


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_nonfinite_inputs_fail_in_fit_prediction_and_scoring(panel, bad):
    x, y = panel
    bad_x, bad_y = x.copy(), y.copy()
    bad_x[0, 0, 0] = bad
    bad_y[0, 0] = bad
    fit = fit_ridge(x, y, np.inf)
    for action in [lambda: fit_preprocessing(bad_x), lambda: fit_roi_baseline(bad_y),
                   lambda: fit_ridge(x, bad_y, 1), lambda: fit_ridge(bad_x, y, 1),
                   lambda: fit.predict(bad_x), lambda: transform_features(bad_x, fit.preprocessing),
                   lambda: subject_mse(bad_y, y), lambda: subject_mse(y, bad_y),
                   lambda: candidate_score([bad]), lambda: select_lambda(LAMBDA_GRID, [bad] * len(LAMBDA_GRID))]:
        with pytest.raises(ValueError, match="finite"):
            action()


def test_equal_subject_mse_and_candidate_score():
    truth = np.zeros((3, N_ROIS))
    prediction = np.broadcast_to(np.array([1., 2., 4.])[:, None], truth.shape)
    losses = subject_mse(truth, prediction)
    np.testing.assert_array_equal(losses, [1, 4, 16])
    assert candidate_score(losses) == 7
    with pytest.raises(ValueError):
        candidate_score(np.zeros((3, N_ROIS)))  # callers must supply one loss per subject


def test_ties_use_frozen_config_including_exact_zero_reference():
    cfg = load_yaml(REPO_ROOT / "configs" / "analysis.yaml")
    assert TIE_RELATIVE_TOLERANCE == cfg["ridge"]["tie_rule"]["relative_tolerance"]
    assert LAMBDA_GRID == tuple(parse_lambda(v) for v in cfg["ridge"]["lambda_grid"])
    assert select_lambda(LAMBDA_GRID, [1] * len(LAMBDA_GRID)) == np.inf
    scores = np.full(len(LAMBDA_GRID), 2.)
    scores[1] = 1
    scores[2] = 1 + 0.5 * TIE_RELATIVE_TOLERANCE * scores[-1]
    scores[3] = 1 + 2 * TIE_RELATIVE_TOLERANCE * scores[-1]
    assert select_lambda(LAMBDA_GRID, scores) == LAMBDA_GRID[2]
    # At the exact numerical boundary, inclusive comparison must keep lambda=100.
    scores = np.ones(len(LAMBDA_GRID))
    scores[0] = 0
    scores[-2] = TIE_RELATIVE_TOLERANCE
    assert select_lambda(LAMBDA_GRID, scores) == 100
    scores[-2] = np.nextafter(TIE_RELATIVE_TOLERANCE, np.inf)
    assert select_lambda(LAMBDA_GRID, scores) == 0
    scores[-1] = 0
    assert select_lambda(LAMBDA_GRID, scores) == np.inf


@pytest.mark.parametrize("value", [-1, -np.inf, np.nan, "Infinity", "0.1", True, None])
def test_invalid_lambda_rejected(value):
    with pytest.raises(ValueError):
        parse_lambda(value)


def test_shape_validation_and_no_input_mutation(panel):
    x, y = panel
    x_before, y_before = x.copy(), y.copy()
    fit = fit_ridge(x, y, 1)
    fit.predict(x)
    np.testing.assert_array_equal(x, x_before)
    np.testing.assert_array_equal(y, y_before)
    for action in [lambda: fit_preprocessing(x[:, :-1]), lambda: fit_preprocessing(x[0]),
                   lambda: fit_preprocessing(x[:0]), lambda: fit_ridge(x, y[:-1], 1),
                   lambda: fit.predict(x[..., :1]), lambda: subject_mse(y, y[:1]),
                   lambda: select_lambda(LAMBDA_GRID, [1, 2]), lambda: candidate_score([]),
                   lambda: candidate_score([-1]), lambda: fit.baseline.predict(0)]:
        with pytest.raises(ValueError):
            action()


@pytest.mark.parametrize("lam", LAMBDA_GRID)
def test_positive_feature_scale_invariance(panel, lam):
    x, y = panel
    scaled = x.copy()
    scaled[..., 0] *= 37.5
    original = fit_ridge(x[:6], y[:6], lam)
    changed = fit_ridge(scaled[:6], y[:6], lam)
    np.testing.assert_allclose(changed.preprocessing.scales[0], 37.5 * original.preprocessing.scales[0])
    np.testing.assert_allclose(changed.predict(scaled[6:]), original.predict(x[6:]), rtol=1e-11, atol=1e-12)


@pytest.mark.parametrize("lam", LAMBDA_GRID)
def test_roi_order_equivariance(panel, lam):
    x, y = panel
    order = np.random.default_rng(82).permutation(N_ROIS)
    original = fit_ridge(x[:6], y[:6], lam)
    reordered = fit_ridge(x[:6, order], y[:6, order], lam)
    np.testing.assert_allclose(reordered.preprocessing.roi_means, original.preprocessing.roi_means[order])
    np.testing.assert_allclose(reordered.preprocessing.scales, original.preprocessing.scales)
    np.testing.assert_allclose(reordered.predict(x[6:, order]), original.predict(x[6:])[:, order],
                               rtol=1e-11, atol=1e-12)


@pytest.mark.parametrize("lam", LAMBDA_GRID)
def test_training_subject_order_invariance(panel, lam):
    x, y = panel
    order = np.array([5, 2, 0, 4, 1, 3])
    original = fit_ridge(x[:6], y[:6], lam)
    reordered = fit_ridge(x[order], y[order], lam)
    np.testing.assert_allclose(reordered.preprocessing.roi_means, original.preprocessing.roi_means,
                               rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(reordered.preprocessing.scales, original.preprocessing.scales)
    np.testing.assert_array_equal(reordered.preprocessing.omitted, original.preprocessing.omitted)
    np.testing.assert_allclose(reordered.baseline.roi_means, original.baseline.roi_means)
    np.testing.assert_allclose(reordered.coefficients, original.coefficients, rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(reordered.predict(x[6:]), original.predict(x[6:]), rtol=1e-11, atol=1e-12)


def test_selection_pairs_explicit_lambdas_and_scores_in_any_order():
    # Infinity's score is deliberately different from the last shuffled score.
    scores = np.array([5., 1., 1. + 5e-12, 4., 3., 2., 10.])
    assert select_lambda(LAMBDA_GRID, scores) == 0.1
    for order in [np.arange(7)[::-1], np.array([6, 4, 1, 0, 5, 2, 3])]:
        penalties = [LAMBDA_GRID[i] for i in order]
        assert select_lambda(penalties, scores[order]) == 0.1
        assert select_lambda(penalties, np.ones(7)) == np.inf
    assert select_lambda(["inf", *LAMBDA_GRID[:-1]], [10., *scores[:-1]]) == 0.1


@pytest.mark.parametrize("penalties, message", [
    (LAMBDA_GRID[:-1], "missing"),
    ((0, *LAMBDA_GRID), "duplicate"),
    ((*LAMBDA_GRID, "inf"), "duplicate"),  # equivalent infinity encodings
    ((0.02, *LAMBDA_GRID[1:]), "unknown"),
])
def test_selection_rejects_invalid_candidate_sets(penalties, message):
    with pytest.raises(ValueError, match=message):
        select_lambda(penalties, np.ones(len(penalties)))


def test_selection_rejects_scores_without_explicit_lambdas():
    with pytest.raises(TypeError):
        select_lambda(np.ones(len(LAMBDA_GRID)))  # pyright: ignore[reportCallIssue] -- deliberately omits candidate_scores to assert TypeError
