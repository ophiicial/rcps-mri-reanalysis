"""Condition-specific cortical ROI-mean rCPS on the supplied grid (analysis_plan §5; qc_decisions §3, §3b).

rCPS intensities are never resampled or registered. aparc+aseg is nearest-neighbour resampled onto each
rCPS grid through the scanner-RAS headers. Every label voxel counts, exact zeros included.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import nibabel as nib
import numpy as np

from ..labels import resample_labels_nn
from ..qc.spatial import load_spatial_image


def validate_rcps_map(values: np.ndarray) -> None:
    """analysis_plan §5.3: any nonfinite or negative voxel anywhere in the supplied map fails. Exact zeros are valid."""
    values = np.asarray(values)
    if not np.all(np.isfinite(values)):
        raise ValueError(f"nonfinite rCPS voxels in the supplied map: {int((~np.isfinite(values)).sum())}")
    if np.any(values < 0):
        raise ValueError(f"negative rCPS voxels in the supplied map: {int((values < 0).sum())}")


def roi_statistics(values: np.ndarray, label_grid: np.ndarray, codes: Sequence[int]) -> dict[str, np.ndarray]:
    """Per-code mean over all label voxels, voxel count and exact-zero count, in `codes` order.

    The whole supplied map is validated first (`validate_rcps_map`); a code with no voxel fails.
    """
    values, label_grid = np.asarray(values), np.asarray(label_grid)
    validate_rcps_map(values)
    if values.shape != label_grid.shape:
        raise ValueError(f"rCPS grid {values.shape} != label grid {label_grid.shape}")
    code_arr = np.asarray(codes)
    if len(np.unique(code_arr)) != len(code_arr):
        raise ValueError("duplicate label codes")
    used = np.isin(label_grid, code_arr)
    v = values[used].astype(np.float64)
    order = np.argsort(code_arr)
    position = order[np.searchsorted(code_arr[order], label_grid[used])]
    n = np.bincount(position, minlength=len(code_arr))
    if np.any(n == 0):
        raise ValueError(f"labels with no voxel on the rCPS grid: {code_arr[n == 0].tolist()}")
    total = np.bincount(position, weights=v, minlength=len(code_arr))
    zeros = np.bincount(position, weights=(v == 0), minlength=len(code_arr)).astype(np.int64)
    return {"mean": total / n, "n_voxels": n.astype(np.int64), "n_zero": zeros}


def check_sidecar_units(sidecar: Path, units: str) -> None:
    got = json.loads(Path(sidecar).read_text())["Parameter"]["Units"]
    if got != units:
        raise ValueError(f"{Path(sidecar).name}: rCPS units {got!r} != {units!r}")


class LabelGrids:
    """aparc+aseg labels resampled onto each distinct rCPS grid of one subject (NN, scanner-RAS header)."""

    def __init__(self, aparc_path: Path):
        img = load_spatial_image(aparc_path)
        raw = np.asarray(img.dataobj)
        if raw.ndim != 3 or not np.array_equal(raw, np.round(raw)):
            raise ValueError(f"{Path(aparc_path).name}: expected a 3-D integer label volume")
        self._data, self._affine = raw.astype(np.int32), img.affine
        self._cache: dict[tuple, np.ndarray] = {}

    def on_grid(self, shape: tuple[int, ...], affine: np.ndarray) -> np.ndarray:
        key = (tuple(shape), np.asarray(affine, dtype=np.float64).tobytes())
        if key not in self._cache:
            self._cache[key] = resample_labels_nn(self._data, self._affine, shape, affine)
        return self._cache[key]


def load_rcps(path: Path) -> tuple[np.ndarray, np.ndarray]:
    img = load_spatial_image(path)
    if not isinstance(img, nib.Nifti1Image) or len(img.shape) != 3:
        raise ValueError(f"{Path(path).name}: expected a 3-D NIfTI rCPS map")
    return np.asarray(img.dataobj, dtype=np.float64), img.affine
