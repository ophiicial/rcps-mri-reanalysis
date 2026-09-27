"""FreeSurfer / NIfTI geometry helpers.

Coordinate conventions (documented because they are not interchangeable):
- NIfTI world = the sform (or qform) affine: voxel -> scanner RAS (mm).
- MGH/MGZ ``img.affine`` in nibabel = vox2ras in *scanner* RAS (NOT tkregister RAS).
- FreeSurfer tkregister RAS (``header.get_vox2ras_tkr()``) is a volume-centred frame used by surfaces;
  it is recorded but never used for volume-to-volume mapping here.
- LTA files store either VOX->VOX (type 0) or RAS->RAS (type 1, scanner RAS, src -> dst).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def fs_vox2ras(dims, voxelsize, xras, yras, zras, cras) -> np.ndarray:
    """Scanner vox2ras from FreeSurfer 'volume info' fields (xras/yras/zras direction cosines, c_ras)."""
    M = np.column_stack([np.asarray(xras, float) * voxelsize[0],
                         np.asarray(yras, float) * voxelsize[1],
                         np.asarray(zras, float) * voxelsize[2]])
    centre = np.asarray(dims, float) / 2.0
    P0 = np.asarray(cras, float) - M @ centre
    A = np.eye(4)
    A[:3, :3] = M
    A[:3, 3] = P0
    return A


def _parse_volinfo(lines: list[str]) -> dict:
    info = {}
    for ln in lines:
        if "=" not in ln:
            continue
        k, v = [s.strip() for s in ln.split("=", 1)]
        v = v.split("#")[0].strip()
        if k in ("volume", "voxelsize", "xras", "yras", "zras", "cras"):
            info[k] = [float(x) for x in v.split()]
        elif k in ("valid", "filename"):
            info[k] = v
    return info


def read_lta(path: Path | str) -> dict:
    """Parse a single-transform FreeSurfer LTA file. Returns type, matrix, src/dst volume info and vox2ras."""
    text = Path(path).read_text().splitlines()
    ltype = None
    mat_rows: list[list[float]] = []
    src, dst = [], []
    section = None
    for i, ln in enumerate(text):
        s = ln.strip()
        if s.startswith("type"):
            ltype = int(s.split("=")[1].split("#")[0])
        elif s == "1 4 4":
            mat_rows = [[float(x) for x in text[i + k].split()] for k in range(1, 5)]
        elif s.startswith("src volume info"):
            section = "src"
        elif s.startswith("dst volume info"):
            section = "dst"
        elif section == "src":
            src.append(s)
        elif section == "dst":
            dst.append(s)
    if ltype is None or len(mat_rows) != 4:
        raise ValueError(f"Could not parse LTA {path}")
    out = {"type": ltype, "matrix": np.array(mat_rows), "src": _parse_volinfo(src), "dst": _parse_volinfo(dst)}
    for side in ("src", "dst"):
        vi = out[side]
        out[side + "_vox2ras"] = fs_vox2ras(vi["volume"], vi["voxelsize"], vi["xras"], vi["yras"], vi["zras"], vi["cras"])
    return out


def lta_ras2ras(lta: dict) -> np.ndarray:
    """Return the scanner RAS->RAS (src -> dst) matrix for an LTA of type 0 (VOX2VOX) or 1 (RAS2RAS)."""
    if lta["type"] == 1:
        return lta["matrix"]
    if lta["type"] == 0:
        return lta["dst_vox2ras"] @ lta["matrix"] @ np.linalg.inv(lta["src_vox2ras"])
    raise ValueError(f"Unsupported LTA type {lta['type']}")


def rigid_params_deviation(T: np.ndarray, centre: np.ndarray) -> dict:
    """Describe a (near-)rigid 4x4 world transform: rotation angle (deg) and displacement of `centre` (mm)."""
    R = T[:3, :3]
    cos_theta = np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)
    angle = float(np.degrees(np.arccos(cos_theta)))
    c = np.asarray(centre, float)
    disp = T[:3, :3] @ c + T[:3, 3] - c
    return {"rotation_deg": angle, "centre_displacement_mm": float(np.linalg.norm(disp)),
            "centre_displacement_xyz": disp.tolist(), "det": float(np.linalg.det(R))}


def rigid_matrix(tx=0.0, ty=0.0, tz=0.0, rx_deg=0.0, ry_deg=0.0, rz_deg=0.0, centre=(0.0, 0.0, 0.0)) -> np.ndarray:
    """World-space rigid transform: rotate about `centre` (x, then y, then z axes), then translate."""
    rx, ry, rz = np.radians([rx_deg, ry_deg, rz_deg])
    Rx = np.array([[1, 0, 0], [0, np.cos(rx), -np.sin(rx)], [0, np.sin(rx), np.cos(rx)]])
    Ry = np.array([[np.cos(ry), 0, np.sin(ry)], [0, 1, 0], [-np.sin(ry), 0, np.cos(ry)]])
    Rz = np.array([[np.cos(rz), -np.sin(rz), 0], [np.sin(rz), np.cos(rz), 0], [0, 0, 1]])
    R = Rz @ Ry @ Rx
    c = np.asarray(centre, float)
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = c - R @ c + np.array([tx, ty, tz], float)
    return T


def displacement_stats(T: np.ndarray, points_world: np.ndarray) -> dict:
    """Mean / max displacement (mm) of world points under transform T (points: N x 3)."""
    p = np.asarray(points_world, float)
    moved = p @ T[:3, :3].T + T[:3, 3]
    d = np.linalg.norm(moved - p, axis=1)
    return {"mean_mm": float(d.mean()), "max_mm": float(d.max())}
