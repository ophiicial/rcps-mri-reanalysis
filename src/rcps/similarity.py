"""Normalized mutual information and rigid-perturbation profiles for alignment QC.

The moving image is always ANATOMY (T1w intensity or a FreeSurfer tissue-class map); rCPS values stay on
their supplied grid and are never interpolated.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def nmi(a: np.ndarray, b: np.ndarray, bins: int = 64, a_range=None, b_range=None) -> float:
    """Studholme NMI = (H(A) + H(B)) / H(A, B). 1 = independent, 2 = identical."""
    h, _, _ = np.histogram2d(a, b, bins=bins, range=[a_range, b_range] if a_range and b_range else None)
    p = h / h.sum()
    pa, pb = p.sum(1), p.sum(0)

    def ent(x):
        x = x[x > 0]
        return -np.sum(x * np.log(x))

    hab = ent(p.ravel())
    return float((ent(pa) + ent(pb)) / hab) if hab > 0 else float("nan")


class AnatomySampler:
    """Samples an anatomy volume at the world positions of a fixed set of target (rCPS-grid) voxels."""

    def __init__(self, anat_data: np.ndarray, anat_affine: np.ndarray, target_affine: np.ndarray,
                 target_voxels: np.ndarray, order: int):
        self.anat = np.asarray(anat_data, dtype=np.float32)
        self.inv_anat = np.linalg.inv(anat_affine)
        vox_h = np.c_[target_voxels, np.ones(len(target_voxels))]
        self.world = (target_affine @ vox_h.T)[:3].T          # N x 3 world coords of target voxels
        self.order = order

    def sample(self, world_transform: np.ndarray) -> np.ndarray:
        p = self.world @ world_transform[:3, :3].T + world_transform[:3, 3]
        v = (self.inv_anat[:3, :3] @ p.T) + self.inv_anat[:3, 3:4]
        return ndimage.map_coordinates(self.anat, v, order=self.order, mode="constant", cval=0.0, prefilter=False)


def evaluation_voxels(mask: np.ndarray, stride: int) -> np.ndarray:
    """Fixed subsample (every `stride`-th voxel along each axis) of mask voxels, as N x 3 indices."""
    sub = np.zeros_like(mask, dtype=bool)
    sub[::stride, ::stride, ::stride] = True
    return np.argwhere(mask & sub)
