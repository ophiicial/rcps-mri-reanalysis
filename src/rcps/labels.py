"""Desikan-Killiany label table and nearest-neighbour label resampling into a target grid."""
from __future__ import annotations

import numpy as np
from scipy import ndimage

# FreeSurferColorLUT aparc indices (lh = 1000 + i, rh = 2000 + i). 0 = unknown, 4 = corpuscallosum (excluded).
DK_INDEX = {
    1: "bankssts", 2: "caudalanteriorcingulate", 3: "caudalmiddlefrontal", 5: "cuneus", 6: "entorhinal",
    7: "fusiform", 8: "inferiorparietal", 9: "inferiortemporal", 10: "isthmuscingulate", 11: "lateraloccipital",
    12: "lateralorbitofrontal", 13: "lingual", 14: "medialorbitofrontal", 15: "middletemporal",
    16: "parahippocampal", 17: "paracentral", 18: "parsopercularis", 19: "parsorbitalis", 20: "parstriangularis",
    21: "pericalcarine", 22: "postcentral", 23: "posteriorcingulate", 24: "precentral", 25: "precuneus",
    26: "rostralanteriorcingulate", 27: "rostralmiddlefrontal", 28: "superiorfrontal", 29: "superiorparietal",
    30: "superiortemporal", 31: "supramarginal", 32: "frontalpole", 33: "temporalpole", 34: "transversetemporal",
    35: "insula",
}


def dk_cortical_labels() -> dict[int, str]:
    """The 68 primary cortical ROIs: {aparc+aseg code: 'ctx-<hemi>-<name>'}."""
    out = {}
    for base, hemi in ((1000, "lh"), (2000, "rh")):
        for idx, name in DK_INDEX.items():
            out[base + idx] = f"ctx-{hemi}-{name}"
    assert len(out) == 68
    return out


def resample_labels_nn(label_data: np.ndarray, label_affine: np.ndarray,
                       target_shape: tuple, target_affine: np.ndarray,
                       world_transform: np.ndarray | None = None) -> np.ndarray:
    """Nearest-neighbour resampling of a discrete label volume into a target grid via world coordinates.

    For each target voxel v: world p = target_affine @ v; optional world_transform maps p to the label
    image's world frame (anatomy position of that target voxel); label voxel = inv(label_affine) @ p.
    Only labels are resampled; target intensities are never touched. Out-of-FOV -> 0.
    """
    T = np.eye(4) if world_transform is None else world_transform
    vox2vox = np.linalg.inv(label_affine) @ T @ target_affine
    out = ndimage.affine_transform(label_data, vox2vox[:3, :3], offset=vox2vox[:3, 3],
                                   output_shape=tuple(target_shape[:3]), order=0, mode="constant", cval=0,
                                   prefilter=False)
    return out.astype(label_data.dtype, copy=False)


def roi_centroids_world(label_img: np.ndarray, affine: np.ndarray, codes) -> dict[int, np.ndarray]:
    """World-space centroid of each label code (NaN if absent)."""
    cents = {}
    idx = np.array(list(codes))
    com = ndimage.center_of_mass(np.ones_like(label_img, dtype=np.uint8), label_img, idx)
    for code, c in zip(idx, com):
        c = np.asarray(c, float)
        cents[int(code)] = (affine @ np.r_[c, 1.0])[:3] if np.all(np.isfinite(c)) else np.full(3, np.nan)
    return cents


def left_right_check(centroids: dict[int, np.ndarray], x_axis_sign: float = 1.0) -> list[dict]:
    """For each homologous DK pair, check lh centroid is on the left (smaller RAS x) of the rh centroid."""
    rows = []
    for idx, name in DK_INDEX.items():
        lh, rh = centroids.get(1000 + idx), centroids.get(2000 + idx)
        ok = bool(np.isfinite(lh).all() and np.isfinite(rh).all() and (lh[0] - rh[0]) * x_axis_sign < 0)
        rows.append({"roi": name, "lh_x": float(lh[0]), "rh_x": float(rh[0]), "lh_left_of_rh": ok})
    return rows
