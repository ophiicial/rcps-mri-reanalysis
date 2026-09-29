"""Frozen ROI-fixed-effect ridge primitives (analysis_plan sections 7–8).

Fit functions accept training arrays only. Features are already transformed
(primary: thickness, ln(area / 1 mm²)); extraction/log transformation belongs
upstream. Public arrays retain subject × ROI × feature or subject × ROI axes.
No function loads imaging/outcome data or performs cross-validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Real

import numpy as np
from sklearn.linear_model import Ridge

from rcps.config import REPO_ROOT, load_yaml


def parse_lambda(value: float | str) -> float:
    """Decode the config's explicit 'inf' sentinel; reject invalid penalties."""
    if isinstance(value, str):
        if value != "inf":
            raise ValueError("lambda string must be exactly 'inf'")
        return np.inf
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError("lambda must be a nonnegative number or 'inf'")
    result = float(value)
    if np.isnan(result) or result < 0:
        raise ValueError("lambda must be nonnegative and not NaN")
    return result


# Configuration is the source of numerical choices, not real data.
_CONFIG = load_yaml(REPO_ROOT / "configs" / "analysis.yaml")
N_ROIS = _CONFIG["rois"]["n"]
LAMBDA_GRID = tuple(parse_lambda(v) for v in _CONFIG["ridge"]["lambda_grid"])
TIE_RELATIVE_TOLERANCE = _CONFIG["ridge"]["tie_rule"]["relative_tolerance"]
_RIDGE_SOLVER = _CONFIG["ridge"]["solver"]["finite_positive"]["solver"]
_LSTSQ_RCOND = _CONFIG["ridge"]["solver"]["zero"]["rcond"]


def _finite(values, name: str) -> np.ndarray:
    raw = np.asarray(values)
    if np.iscomplexobj(raw):
        raise ValueError(f"{name} must be real-valued")
    array = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def _panel(values, ndim: int, name: str) -> np.ndarray:
    array = _finite(values, name)
    if array.ndim != ndim or any(n == 0 for n in array.shape):
        raise ValueError(f"{name} must be a nonempty {ndim}-dimensional panel")
    if array.shape[1] != N_ROIS:
        raise ValueError(f"{name} must have {N_ROIS} ROIs on axis 1")
    return array


def _readonly(values) -> np.ndarray:
    array = np.array(values, copy=True)
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class FeatureState:
    roi_means: np.ndarray               # ROI × feature
    scales: np.ndarray                  # feature; zero retained as a recorded event
    omitted: np.ndarray                 # feature boolean mask
    n_train_subjects: int


def fit_preprocessing(x_train) -> FeatureState:
    """Fit ROI means and pooled RMS scales on training subjects only."""
    x = _panel(x_train, 3, "x_train")
    means = x.mean(axis=0)
    # An exactly repeated value (e.g. 0.1) can acquire rounding residuals
    # through mean summation. Preserve its exact mean; do not use a tolerance
    # that would discard genuinely small, nonzero variance.
    constant_by_roi = np.all(x == x[0:1], axis=0)
    means = np.where(constant_by_roi, x[0], means)
    centred = x - means
    scales = np.sqrt(np.mean(centred ** 2, axis=(0, 1)))
    _finite(means, "fitted feature means")
    _finite(scales, "fitted feature scales")
    return FeatureState(_readonly(means), _readonly(scales),
                        _readonly(scales == 0), x.shape[0])


def transform_features(x, state: FeatureState) -> np.ndarray:
    """Transform with saved training state, forcing omitted columns to zero."""
    x = _panel(x, 3, "x")
    if x.shape[1:] != state.roi_means.shape:
        raise ValueError("x ROI/feature axes do not match fitted preprocessing")
    z = np.zeros_like(x)
    active = ~state.omitted
    z[..., active] = (x[..., active] - state.roi_means[:, active]) / state.scales[active]
    return _finite(z, "transformed features")


@dataclass(frozen=True)
class ROIBaseline:
    roi_means: np.ndarray
    n_train_subjects: int

    def predict(self, n_subjects: int) -> np.ndarray:
        if isinstance(n_subjects, bool) or not isinstance(n_subjects, (int, np.integer)) or n_subjects < 1:
            raise ValueError("n_subjects must be a positive integer")
        return np.broadcast_to(self.roi_means, (n_subjects, N_ROIS)).copy()


def fit_roi_baseline(y_train) -> ROIBaseline:
    y = _panel(y_train, 2, "y_train")
    means = _finite(y.mean(axis=0), "fitted outcome means")
    return ROIBaseline(_readonly(means), y.shape[0])


@dataclass(frozen=True)
class RidgeFit:
    preprocessing: FeatureState
    baseline: ROIBaseline
    coefficients: np.ndarray             # full feature axis; omitted slopes = 0
    lambda_value: float
    sklearn_alpha: float | None
    numerical_rank: int | None           # recorded for lambda=0

    def predict(self, x) -> np.ndarray:
        x = _panel(x, 3, "x")
        if x.shape[1:] != self.preprocessing.roi_means.shape:
            raise ValueError("x ROI/feature axes do not match fitted model")
        prediction = self.baseline.predict(x.shape[0])
        if np.isinf(self.lambda_value) or np.all(self.preprocessing.omitted):
            return prediction           # bit-for-bit baseline; no 0 * transformed values
        z = transform_features(x, self.preprocessing)
        return _finite(prediction + z @ self.coefficients, "predictions")


def fit_ridge(x_train, y_train, lambda_value: float | str) -> RidgeFit:
    """Fit one candidate on an explicitly supplied training panel.

    No validation arrays or outcomes are accepted. Each inner/outer fit must
    call this function with only that split's training subjects.
    """
    x = _panel(x_train, 3, "x_train")
    y = _panel(y_train, 2, "y_train")
    if x.shape[:2] != y.shape:
        raise ValueError("training feature and outcome subject/ROI axes must match")
    lam = parse_lambda(lambda_value)
    state = fit_preprocessing(x)
    baseline = fit_roi_baseline(y)
    coefficients = np.zeros(x.shape[2], dtype=np.float64)
    rank = None
    alpha = None
    if not np.isinf(lam):
        z = transform_features(x, state)[..., ~state.omitted]
        design = z.reshape(x.shape[0] * N_ROIS, z.shape[2])
        residual = _finite(y - baseline.roi_means, "outcome residuals").reshape(-1)
        if lam == 0:
            beta, _, rank, _ = np.linalg.lstsq(design, residual, rcond=_LSTSQ_RCOND)
            rank = int(rank)
            coefficients[~state.omitted] = beta
        else:
            alpha = x.shape[0] * N_ROIS * lam
            if not np.isfinite(alpha):
                raise ValueError("finite lambda produces nonfinite sklearn alpha")
            if design.shape[1]:
                estimator = Ridge(alpha=alpha, fit_intercept=False, solver=_RIDGE_SOLVER)
                estimator.fit(design, residual)
                coefficients[~state.omitted] = estimator.coef_
    _finite(coefficients, "fitted coefficients")
    return RidgeFit(state, baseline, _readonly(coefficients), lam, alpha, rank)


def subject_mse(y_true, y_pred) -> np.ndarray:
    """One loss per subject, averaging squared errors across all 68 ROIs."""
    truth = _panel(y_true, 2, "y_true")
    prediction = _panel(y_pred, 2, "y_pred")
    if truth.shape != prediction.shape:
        raise ValueError("outcome and prediction panels must have identical shape")
    return _finite(np.mean((truth - prediction) ** 2, axis=1), "subject MSE")


def candidate_score(subject_losses) -> float:
    """Equal-weight arithmetic mean of held-out subject losses (not RMSE)."""
    losses = _finite(subject_losses, "subject_losses")
    if losses.ndim != 1 or losses.size == 0 or np.any(losses < 0):
        raise ValueError("subject_losses must be a nonempty vector of nonnegative MSEs")
    return float(_finite(losses.mean(), "candidate score"))


def select_lambda(lambdas, candidate_scores) -> float:
    """Select from explicit paired lambdas/scores in any order.

    Every frozen candidate must occur exactly once. Pairing is supplied by
    the caller; selection never assumes the frozen grid's positional order.
    """
    penalties = tuple(parse_lambda(value) for value in lambdas)
    if len(set(penalties)) != len(penalties):
        raise ValueError("duplicate lambdas are not allowed")
    unknown = set(penalties) - set(LAMBDA_GRID)
    if unknown:
        raise ValueError(f"unknown lambdas: {sorted(unknown)}")
    missing = set(LAMBDA_GRID) - set(penalties)
    if missing:
        raise ValueError(f"missing lambdas: {sorted(missing)}")
    scores = _finite(candidate_scores, "candidate_scores")
    if scores.shape != (len(penalties),) or np.any(scores < 0):
        raise ValueError("one nonnegative MSE score is required per frozen lambda candidate")
    baseline_score = scores[penalties.index(np.inf)]
    tolerance = TIE_RELATIVE_TOLERANCE * baseline_score
    tied = scores - scores.min() <= tolerance  # exact equality when baseline_score=0
    return max(lam for lam, keep in zip(penalties, tied) if keep)
