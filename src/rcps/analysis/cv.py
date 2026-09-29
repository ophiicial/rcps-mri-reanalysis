"""Nested subject LOSO for complete, already-transformed cortical panels.

Phase 2 is exercised on synthetic data only. This module does not load data,
verify dataset provenance, construct targets/features, or perform inference.
Caller order is preserved throughout; indices always refer to that order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from rcps.analysis.ridge import (
    LAMBDA_GRID, RidgeFit, _panel, _readonly, candidate_score, fit_ridge,
    parse_lambda, select_lambda, subject_mse,
)
from rcps.config import REPO_ROOT, load_yaml


@dataclass(frozen=True)
class InnerFitDiagnostic:
    """Test/diagnostic-only view of one inner candidate fit.

    Production code must not rely on, retain, or reuse these fits; the
    provenance required by the plan is persisted as plain arrays in OuterFold.
    """
    outer_index: int
    validation_index: int
    training_indices: tuple[int, ...]
    fit: RidgeFit
    prediction: np.ndarray
    mse: float


@dataclass(frozen=True)
class OuterFold:
    held_out_index: int
    subject_id: str
    training_indices: tuple[int, ...]
    inner_validation_indices: tuple[int, ...]
    lambdas: tuple[float, ...]
    inner_losses: np.ndarray             # inner subject × candidate
    inner_scores: np.ndarray             # candidate, paired with lambdas
    inner_omitted: np.ndarray            # inner subject × candidate × feature; zero-variance events
    inner_rank: np.ndarray               # inner subject; numerical rank of the lambda=0 fit
    selected_lambda: float
    fit: RidgeFit                        # fresh outer-training fit
    baseline_prediction: np.ndarray      # ROI
    ridge_prediction: np.ndarray         # ROI
    baseline_mse: float
    ridge_mse: float
    d_s: float


@dataclass(frozen=True)
class LOSOSummary:
    """Equal-subject descriptive means; no uncertainty or formal inference."""
    subject_ids: tuple[str, ...]
    d_s: np.ndarray
    t: float
    mean_baseline_mse: float
    mean_ridge_mse: float


def _validate_panel(subject_ids, x, y):
    if isinstance(subject_ids, (str, bytes)):
        raise ValueError("subject_ids must be a sequence of unique nonempty strings")
    ids = tuple(subject_ids)
    if any(not isinstance(s, str) or not s.strip() for s in ids):
        raise ValueError("subject_ids must be unique nonempty strings")
    if len(set(ids)) != len(ids):
        raise ValueError("subject_ids must be unique")
    if np.ma.isMaskedArray(x) or np.ma.isMaskedArray(y):
        raise ValueError("masked panels are not supported; complete panels required")
    # Private read-only snapshots: later caller mutation cannot reach any fold.
    x, y = _readonly(_panel(x, 3, "x")), _readonly(_panel(y, 2, "y"))
    if x.shape[:2] != y.shape or len(ids) != x.shape[0]:
        raise ValueError("subject IDs and feature/outcome subject/ROI axes must match")
    if len(ids) < 3:
        raise ValueError("nested LOSO requires at least three subjects")
    return ids, x, y


def nested_loso(subject_ids, x, y, *, lambdas=LAMBDA_GRID,
                on_inner_fit: Callable[[InnerFitDiagnostic], None] | None = None
                ) -> tuple[OuterFold, ...]:
    """Evaluate every subject once, tuning with LOSO only inside its training set.

    Inputs: unique string IDs, x[subject, 68, feature], y[subject, 68].
    Every frozen lambda must occur exactly once, in any caller-supplied order.
    ``on_inner_fit`` is test/diagnostic-only: production code must not rely on
    it or retain/reuse the fits it exposes. Inner fits are never retained or
    reused by the orchestrator; their zero-variance events and lambda=0 ranks
    are persisted in each OuterFold as plain arrays.
    """
    ids, x, y = _validate_panel(subject_ids, x, y)
    penalties = tuple(parse_lambda(value) for value in lambdas)
    # Hardened API validates the entire candidate set before any fitting.
    select_lambda(penalties, np.zeros(len(penalties)))
    folds = []
    for outer in range(len(ids)):
        training = tuple(i for i in range(len(ids)) if i != outer)
        losses = np.empty((len(training), len(penalties)))
        omitted = np.empty((len(training), len(penalties), x.shape[2]), dtype=bool)
        ranks = np.empty(len(training), dtype=np.int64)
        for row, validation in enumerate(training):
            inner_training = tuple(i for i in training if i != validation)
            for column, lam in enumerate(penalties):
                fit = fit_ridge(x[list(inner_training)], y[list(inner_training)], lam)
                prediction = fit.predict(x[validation:validation + 1])
                loss = float(subject_mse(y[validation:validation + 1], prediction)[0])
                losses[row, column] = loss
                omitted[row, column] = fit.preprocessing.omitted
                if lam == 0:
                    ranks[row] = fit.numerical_rank
                if on_inner_fit is not None:
                    on_inner_fit(InnerFitDiagnostic(
                        outer, validation, inner_training, fit,
                        _readonly(prediction[0]), loss))
        scores = np.array([candidate_score(losses[:, j]) for j in range(len(penalties))])
        selected = select_lambda(penalties, scores)
        # Fresh fit: no preprocessing, outcome means, or coefficients from tuning.
        fit = fit_ridge(x[list(training)], y[list(training)], selected)
        baseline = fit.baseline.predict(1)
        prediction = fit.predict(x[outer:outer + 1])
        baseline_mse = float(subject_mse(y[outer:outer + 1], baseline)[0])
        ridge_mse = float(subject_mse(y[outer:outer + 1], prediction)[0])
        folds.append(OuterFold(
            held_out_index=outer, subject_id=ids[outer], training_indices=training,
            inner_validation_indices=training, lambdas=penalties,
            inner_losses=_readonly(losses), inner_scores=_readonly(scores),
            inner_omitted=_readonly(omitted), inner_rank=_readonly(ranks),
            selected_lambda=selected, fit=fit,
            baseline_prediction=_readonly(baseline[0]), ridge_prediction=_readonly(prediction[0]),
            baseline_mse=baseline_mse, ridge_mse=ridge_mse, d_s=baseline_mse - ridge_mse))
    return tuple(folds)


def primary_loso(subject_ids, x, y, *, lambdas=LAMBDA_GRID,
                 on_inner_fit: Callable[[InnerFitDiagnostic], None] | None = None
                 ) -> tuple[OuterFold, ...]:
    """P1-shaped orchestration (18 subjects, two transformed MRI features).

    ``on_inner_fit`` is test/diagnostic-only, as in ``nested_loso``.

    Synthetic IDs are accepted for testing. This is not a real-data runner:
    canonical cohort, target and feature provenance must be verified upstream.
    """
    ids, x, y = _validate_panel(subject_ids, x, y)
    config = load_yaml(REPO_ROOT / "configs" / "analysis.yaml")
    if len(ids) != config["cohort"]["primary"]["n"]:
        raise ValueError("P1 requires exactly 18 subjects")
    if x.shape[2] != len(config["features"]["primary"]):
        raise ValueError("P1 requires two transformed MRI features: thickness, ln_area")
    return nested_loso(ids, x, y, lambdas=lambdas, on_inner_fit=on_inner_fit)


def summarize_loso(folds) -> LOSOSummary:
    """Summarize a complete outer LOSO result, weighting subjects equally."""
    folds = tuple(folds)
    ids = tuple(f.subject_id for f in folds)
    indices = {f.held_out_index for f in folds}
    if not folds or len(set(ids)) != len(ids) or indices != set(range(len(folds))):
        raise ValueError("summary requires all outer folds, exactly once per subject")
    for fold in folds:
        if set(fold.training_indices) != indices - {fold.held_out_index}:
            raise ValueError("incomplete outer LOSO result")
    differences = _readonly([f.d_s for f in folds])
    return LOSOSummary(ids, differences, float(differences.mean()),
                       candidate_score([f.baseline_mse for f in folds]),
                       candidate_score([f.ridge_mse for f in folds]))
