"""Canonical long tables, keyed validation and the model-facing CanonicalPanel.

Ordering is always rebuilt from explicit canonical keys (frozen subject order x frozen ROI order), never
from input row order. Nothing is joined, dropped, imputed, filled or sorted away: every key mismatch fails.
This module never calls CV/modelling code.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .mri import ln_area
from .spec import FEATURE_NAMES, ROI, TARGET_DEFINITION, condition_column

MRI_COLUMNS = ["subject_id", "roi", "thickness_mm", "area_mm2", "source_relpath"]
CONDITION_COLUMNS = ["subject_id", "condition", "roi", "rcps_roi_mean", "n_voxels", "n_zero", "zero_fraction",
                     "source_relpath"]


def long_columns(conditions: Sequence[str]) -> list[str]:
    return (["subject_id", "roi", "roi_index", "roi_code", "hemisphere", "thickness_mm", "area_mm2", "ln_area"]
            + [condition_column(c) for c in conditions] + ["rcps_mean"])


def _keyed(df: pd.DataFrame, keys: list[str], expected: pd.MultiIndex, what: str) -> pd.DataFrame:
    """Rows of `df` in `expected` key order; duplicate, missing or extra keys fail."""
    dup = df.duplicated(keys, keep=False)
    if dup.any():
        raise ValueError(f"{what}: duplicate keys {df.loc[dup, keys].drop_duplicates().values.tolist()[:5]}")
    got = pd.MultiIndex.from_arrays([df[k].to_numpy() for k in keys])
    missing, extra = expected.difference(got), got.difference(expected)
    if len(missing) or len(extra):
        raise ValueError(f"{what}: incomplete or non-canonical keys; missing={list(missing)[:5]} "
                         f"(n={len(missing)}) extra={list(extra)[:5]} (n={len(extra)})")
    return df.set_index(keys).reindex(expected)


def _require_columns(df: pd.DataFrame, columns: Sequence[str], what: str) -> None:
    if list(df.columns) != list(columns):
        raise ValueError(f"{what}: columns {list(df.columns)} != {list(columns)}")


def _finite(values: np.ndarray, what: str) -> np.ndarray:
    a = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(a)):
        raise ValueError(f"nonfinite {what}")
    return a


def validate_counts(n_voxels: np.ndarray, n_zero: np.ndarray, zero_fraction: np.ndarray) -> None:
    """Integer counts with 0 <= n_zero <= n_voxels, n_voxels > 0, and zero_fraction == n_zero / n_voxels exactly
    (float64 division; zero tolerance, since both sides use the same deterministic operation)."""
    for name, a in (("n_voxels", n_voxels), ("n_zero", n_zero)):
        if not np.issubdtype(np.asarray(a).dtype, np.integer):
            raise ValueError(f"condition table: {name} must be integer counts")
    n_voxels, n_zero = np.asarray(n_voxels, dtype=np.int64), np.asarray(n_zero, dtype=np.int64)
    if np.any(n_voxels <= 0) or np.any(n_zero < 0) or np.any(n_zero > n_voxels):
        raise ValueError("condition table: invalid voxel or zero counts")
    fraction = _finite(zero_fraction, "zero_fraction")
    if not np.array_equal(fraction, n_zero / n_voxels):
        raise ValueError("condition table: zero_fraction != n_zero / n_voxels")


def equal_weight_condition_mean(per_condition: np.ndarray) -> np.ndarray:
    """Mean over axis 1 (conditions), summed in canonical condition order and divided by the count."""
    total = np.zeros(per_condition.shape[:1] + per_condition.shape[2:])
    for i in range(per_condition.shape[1]):
        total = total + per_condition[:, i]
    return total / per_condition.shape[1]


def build_long_table(mri: pd.DataFrame, cond: pd.DataFrame, subjects: Sequence[str], rois: Sequence[ROI],
                     conditions: Sequence[str]) -> pd.DataFrame:
    """One row per subject x ROI in canonical order; target = equal-weight mean of the condition ROI means."""
    _require_columns(mri, MRI_COLUMNS, "MRI table")
    _require_columns(cond, CONDITION_COLUMNS, "condition table")
    roi_names = [r.name for r in rois]
    m = _keyed(mri, ["subject_id", "roi"], pd.MultiIndex.from_product([subjects, roi_names]), "MRI table")
    c = _keyed(cond, ["subject_id", "condition", "roi"],
               pd.MultiIndex.from_product([subjects, conditions, roi_names]), "condition table")
    validate_counts(c["n_voxels"].to_numpy(), c["n_zero"].to_numpy(), c["zero_fraction"].to_numpy())
    n_s, n_c, n_r = len(subjects), len(conditions), len(rois)
    rcps = _finite(c["rcps_roi_mean"].to_numpy(), "rCPS ROI mean").reshape(n_s, n_c, n_r)
    if np.any(rcps < 0):
        raise ValueError("negative rCPS ROI mean")
    area = _finite(m["area_mm2"].to_numpy(), "area")
    thickness = _finite(m["thickness_mm"].to_numpy(), "thickness")
    out = pd.DataFrame({
        "subject_id": np.repeat(list(subjects), n_r),
        "roi": np.tile(roi_names, n_s),
        "roi_index": np.tile([r.index for r in rois], n_s),
        "roi_code": np.tile([r.code for r in rois], n_s),
        "hemisphere": np.tile([r.hemisphere for r in rois], n_s),
        "thickness_mm": thickness,
        "area_mm2": area,
        "ln_area": ln_area(area),
    })
    for i, condition in enumerate(conditions):
        out[condition_column(condition)] = rcps[:, i, :].ravel()
    out["rcps_mean"] = equal_weight_condition_mean(rcps).ravel()
    validate_long_table(out, subjects, rois, conditions)
    return out


def validate_long_table(df: pd.DataFrame, subjects: Sequence[str], rois: Sequence[ROI],
                        conditions: Sequence[str]) -> pd.DataFrame:
    """Check a long table against the canonical contract; return it in canonical key order."""
    _require_columns(df, long_columns(conditions), "long table")
    roi_names = [r.name for r in rois]
    t = _keyed(df, ["subject_id", "roi"], pd.MultiIndex.from_product([subjects, roi_names]), "long table")
    n_s, n_r = len(subjects), len(rois)
    for column, attribute in (("roi_index", "index"), ("roi_code", "code"), ("hemisphere", "hemisphere")):
        expected = np.tile([getattr(r, attribute) for r in rois], n_s)
        if not np.array_equal(t[column].to_numpy(), expected):
            raise ValueError(f"long table: {column} inconsistent with the canonical ROI roster")
    _finite(t["thickness_mm"].to_numpy(), "thickness")
    area = _finite(t["area_mm2"].to_numpy(), "area")
    if not np.array_equal(_finite(t["ln_area"].to_numpy(), "ln_area"), ln_area(area)):
        raise ValueError("ln_area != natural log of area_mm2")
    per_condition = np.stack([_finite(t[condition_column(c)].to_numpy(), f"rCPS {c}") for c in conditions])
    if np.any(per_condition < 0):
        raise ValueError("negative rCPS ROI mean")
    per_condition = per_condition.reshape(len(conditions), n_s, n_r).transpose(1, 0, 2)
    target = _finite(t["rcps_mean"].to_numpy(), "rcps_mean").reshape(n_s, n_r)
    if not np.array_equal(target, equal_weight_condition_mean(per_condition)):
        raise ValueError("rcps_mean != equal-weight mean of the condition ROI means")
    return t.reset_index()


def _readonly(a: np.ndarray) -> np.ndarray:
    out = np.array(a, dtype=np.float64, copy=True)
    out.setflags(write=False)
    return out


@dataclass(frozen=True)
class CanonicalPanel:
    """Model-facing primary panel: x[subject, roi, feature], y[subject, roi]; arrays read-only.

    Axis order is the frozen subject roster and the frozen `dk_cortical_labels()` ROI order.
    Construct with `panel_from_long_table`; this object never runs CV or models.
    """
    subject_ids: tuple[str, ...]
    roi_names: tuple[str, ...]
    roi_codes: tuple[int, ...]
    feature_names: tuple[str, ...]
    conditions: tuple[str, ...]
    target_definition: str
    x: np.ndarray
    y: np.ndarray

    def __post_init__(self):
        n_s, n_r, n_f = len(self.subject_ids), len(self.roi_names), len(self.feature_names)
        if len(set(self.subject_ids)) != n_s or len(set(self.roi_names)) != n_r or len(self.roi_codes) != n_r:
            raise ValueError("panel subject/ROI identifiers must be unique and aligned")
        x, y = _readonly(self.x), _readonly(self.y)
        if x.shape != (n_s, n_r, n_f) or y.shape != (n_s, n_r):
            raise ValueError(f"panel shapes x{x.shape} y{y.shape} != ({n_s}, {n_r}, {n_f}) / ({n_s}, {n_r})")
        if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
            raise ValueError("panel arrays must be finite")
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)


def panel_from_long_table(df: pd.DataFrame, subjects: Sequence[str], rois: Sequence[ROI],
                          conditions: Sequence[str]) -> CanonicalPanel:
    t = validate_long_table(df, subjects, rois, conditions)
    n_s, n_r = len(subjects), len(rois)
    x = np.stack([t["thickness_mm"].to_numpy(), t["ln_area"].to_numpy()], axis=-1).reshape(n_s, n_r, 2)
    return CanonicalPanel(subject_ids=tuple(subjects), roi_names=tuple(r.name for r in rois),
                          roi_codes=tuple(r.code for r in rois), feature_names=FEATURE_NAMES,
                          conditions=tuple(conditions), target_definition=TARGET_DEFINITION,
                          x=x, y=t["rcps_mean"].to_numpy().reshape(n_s, n_r))


def table_tsv(df: pd.DataFrame) -> str:
    """Deterministic TSV text (full float precision) used for both writing and hashing."""
    return df.to_csv(sep="\t", index=False, lineterminator="\n")


def read_table_tsv(path) -> pd.DataFrame:
    """Read a table written by `table_tsv`. Round-trip float parsing is required: pandas' default parser
    can change the last bit, which the exact ln_area / rcps_mean checks then (correctly) reject."""
    return pd.read_csv(path, sep="\t", float_precision="round_trip", keep_default_na=False, na_values=[])


def array_sha256(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a, dtype="<f8").tobytes()).hexdigest()
