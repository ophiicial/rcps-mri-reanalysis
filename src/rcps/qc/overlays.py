"""Standardised QC overlays. Display-only reorientation to RAS (pure axis permutation/flip; no interpolation)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import nibabel as nib  # noqa: E402
import numpy as np  # noqa: E402

from .. import labels  # noqa: E402

LOBES = {
    "frontal": ["superiorfrontal", "rostralmiddlefrontal", "caudalmiddlefrontal", "parsopercularis", "parsorbitalis",
                "parstriangularis", "lateralorbitofrontal", "medialorbitofrontal", "precentral", "paracentral",
                "frontalpole"],
    "temporal": ["superiortemporal", "middletemporal", "inferiortemporal", "bankssts", "fusiform",
                 "transversetemporal", "entorhinal", "temporalpole", "parahippocampal"],
    "parietal": ["superiorparietal", "inferiorparietal", "supramarginal", "postcentral", "precuneus"],
    "occipital": ["lateraloccipital", "lingual", "cuneus", "pericalcarine"],
    "cingulate": ["rostralanteriorcingulate", "caudalanteriorcingulate", "posteriorcingulate", "isthmuscingulate"],
    "insula": ["insula"],
}
LOBE_COLOURS = {"frontal": (1, 0.2, 0.2), "temporal": (0.2, 0.9, 0.2), "parietal": (0.3, 0.5, 1),
                "occipital": (1, 0.8, 0), "cingulate": (1, 0.3, 1), "insula": (0, 1, 1)}


def to_ras(data: np.ndarray, affine: np.ndarray) -> np.ndarray:
    ornt = nib.orientations.io_orientation(affine)
    return nib.orientations.apply_orientation(data, ornt)


def _lobe_map(lab: np.ndarray) -> np.ndarray:
    out = np.zeros(lab.shape, np.uint8)
    name_to_idx = {v: k for k, v in labels.DK_INDEX.items()}
    for li, (lobe, rois) in enumerate(LOBES.items(), start=1):
        codes = [base + name_to_idx[r] for r in rois for base in (1000, 2000)]
        out[np.isin(lab, codes)] = li
    return out


def _boundary(lab2d: np.ndarray) -> np.ndarray:
    b = np.zeros(lab2d.shape, bool)
    b[:-1, :] |= lab2d[:-1, :] != lab2d[1:, :]
    b[1:, :] |= lab2d[1:, :] != lab2d[:-1, :]
    b[:, :-1] |= lab2d[:, :-1] != lab2d[:, 1:]
    b[:, 1:] |= lab2d[:, 1:] != lab2d[:, :-1]
    return b & (lab2d > 0)


def _rgba_boundaries(lab2d, lobe2d, colour=None, alpha=1.0):
    b = _boundary(lab2d)
    rgba = np.zeros(lab2d.shape + (4,))
    if colour is not None:
        rgba[b] = (*colour, alpha)
    else:
        for li, lobe in enumerate(LOBES, start=1):
            m = b & (lobe2d == li)
            rgba[m] = (*LOBE_COLOURS[lobe], alpha)
    return rgba


def _slice(vol, plane, idx):
    if plane == "axial":
        return vol[:, :, idx].T
    if plane == "coronal":
        return vol[:, idx, :].T
    return vol[idx, :, :].T


def _slice_indices(ctx_mask_ras, cfg_ov):
    idx = {}
    for plane, axis, key in (("axial", 2, "axial_fractions"), ("coronal", 1, "coronal_fractions"),
                             ("sagittal", 0, "sagittal_fractions")):
        present = np.where(ctx_mask_ras.any(axis=tuple(a for a in range(3) if a != axis)))[0]
        lo, hi = present.min(), present.max()
        idx[plane] = [int(round(lo + f * (hi - lo))) for f in cfg_ov[key]]
    return idx


def _show(ax, img2d, vmin, vmax, overlay=None, title=""):
    ax.imshow(img2d, cmap="gray", vmin=vmin, vmax=vmax, origin="lower", interpolation="nearest")
    if overlay is not None:
        ax.imshow(overlay, origin="lower", interpolation="nearest")
    ax.set_title(title, fontsize=7)
    ax.set_xticks([]), ax.set_yticks([])


def subject_condition_figure(subject, cond, rcps_img, t1_img, lab, cfg_ov, out_png: Path):
    r = to_ras(np.asarray(rcps_img.dataobj, np.float32), rcps_img.affine)
    t = to_ras(np.asarray(t1_img.dataobj, np.float32), t1_img.affine)
    L = to_ras(lab, rcps_img.affine)
    ctx = np.isin(L, list(labels.dk_cortical_labels()))
    Lc = np.where(ctx, L, 0)
    lobe = _lobe_map(Lc)
    idx = _slice_indices(ctx, cfg_ov)
    rv = r[r > 0]
    rmax = np.percentile(rv, 99) if rv.size else 1
    tlo, thi = np.percentile(t[t > 0], [1, 99])
    fig, axes = plt.subplots(3, 6, figsize=(15, 8))
    for row, plane in enumerate(("axial", "coronal", "sagittal")):
        for k, si in enumerate(idx[plane]):
            ov = _rgba_boundaries(_slice(Lc, plane, si), _slice(lobe, plane, si))
            _show(axes[row, k], _slice(r, plane, si), 0, rmax, ov, f"rCPS {plane} {si}")
            _show(axes[row, 3 + k], _slice(t, plane, si), tlo, thi, ov, f"T1w {plane} {si}")
    fig.suptitle(f"{subject} {cond}: aparc DK boundaries (NN labels on rCPS grid). Display RAS, neurological "
                 f"(left=L). Colours: frontal red, temporal green, parietal blue, occipital yellow, cingulate magenta, "
                 f"insula cyan", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=70)
    plt.close(fig)


def small_roi_figure(subject, cond, rcps_img, lab, cfg_ov, out_png: Path):
    r = to_ras(np.asarray(rcps_img.dataobj, np.float32), rcps_img.affine)
    L = to_ras(lab, rcps_img.affine)
    Lc = np.where(np.isin(L, list(labels.dk_cortical_labels())), L, 0)
    name_to_idx = {v: k for k, v in labels.DK_INDEX.items()}
    rois = cfg_ov["small_rois"]
    half = cfg_ov["small_roi_box_mm"] // 2
    rv = r[r > 0]
    rmax = np.percentile(rv, 99) if rv.size else 1
    fig, axes = plt.subplots(4, len(rois), figsize=(2.4 * len(rois), 9.5))
    for j, roi in enumerate(rois):
        for h, (hemi, base) in enumerate((("lh", 1000), ("rh", 2000))):
            code = base + name_to_idx[roi]
            vox = np.argwhere(Lc == code)
            for p, plane in enumerate(("axial", "coronal")):
                ax = axes[2 * h + p, j]
                if len(vox) == 0:
                    ax.set_title(f"{hemi}-{roi}: ABSENT", fontsize=7, color="red")
                    ax.axis("off")
                    continue
                c = np.round(vox.mean(0)).astype(int)
                si = c[2] if plane == "axial" else c[1]
                img2d, lab2d = _slice(r, plane, si), _slice(Lc, plane, si)
                cx, cy = (c[0], c[1]) if plane == "axial" else (c[0], c[2])
                ys, xs = slice(max(cy - half, 0), cy + half), slice(max(cx - half, 0), cx + half)
                ov = _rgba_boundaries(lab2d, None, colour=(0.6, 0.6, 0.6), alpha=0.6)
                tb = _boundary(np.where(lab2d == code, 1, 0))
                ov[tb] = (1, 1, 0, 1)
                _show(ax, img2d[ys, xs], 0, rmax, ov[ys, xs], f"{hemi}-{roi} {plane} n={len(vox)}")
    fig.suptitle(f"{subject} {cond}: small cortical ROIs (yellow = target ROI; grey = other DK boundaries; "
                 f"{2 * half} mm box through ROI centroid)", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=70)
    plt.close(fig)


def contact_sheet(subject, rimgs: dict, t1_img, lab_by_cond: dict, cfg_ov, out_png: Path):
    conds = list(rimgs)
    first = rimgs[conds[0]]
    L0 = to_ras(lab_by_cond[conds[0]], first.affine)
    ctx = np.isin(L0, list(labels.dk_cortical_labels()))
    idx = _slice_indices(ctx, cfg_ov)
    picks = [("axial", idx["axial"][1]), ("coronal", idx["coronal"][1]), ("sagittal", idx["sagittal"][0]),
             ("sagittal", idx["sagittal"][2])]
    rows = [("T1w", to_ras(np.asarray(t1_img.dataobj, np.float32), t1_img.affine), L0)] + \
           [(f"rCPS {c}", to_ras(np.asarray(rimgs[c].dataobj, np.float32), rimgs[c].affine),
             to_ras(lab_by_cond[c], rimgs[c].affine)) for c in conds]
    fig, axes = plt.subplots(len(rows), len(picks), figsize=(3 * len(picks), 2.8 * len(rows)))
    for i, (name, vol, L) in enumerate(rows):
        Lc = np.where(np.isin(L, list(labels.dk_cortical_labels())), L, 0)
        lobe = _lobe_map(Lc)
        pos = vol[vol > 0]
        lo, hi = (0, np.percentile(pos, 99)) if name != "T1w" else tuple(np.percentile(pos, [1, 99]))
        for j, (plane, si) in enumerate(picks):
            ov = _rgba_boundaries(_slice(Lc, plane, si), _slice(lobe, plane, si), alpha=0.8)
            _show(axes[i, j], _slice(vol, plane, si), lo, hi, ov, f"{name} {plane} {si}")
    fig.suptitle(f"{subject} contact sheet (same slices for all rows; display RAS neurological)", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_png, dpi=70)
    plt.close(fig)


def historical_figure(subject, cond, rcps_img, lab_header, lab_hist, cfg_ov, out_png: Path):
    r = to_ras(np.asarray(rcps_img.dataobj, np.float32), rcps_img.affine)
    ctxset = list(labels.dk_cortical_labels())
    La = to_ras(np.where(np.isin(lab_header, ctxset), lab_header, 0), rcps_img.affine)
    Lb = to_ras(np.where(np.isin(lab_hist, ctxset), lab_hist, 0), rcps_img.affine)
    idx = _slice_indices(La > 0, cfg_ov)
    picks = [("axial", idx["axial"][1]), ("coronal", idx["coronal"][1]), ("sagittal", idx["sagittal"][0])]
    rmax = np.percentile(r[r > 0], 99)
    fig, axes = plt.subplots(1, len(picks), figsize=(5 * len(picks), 5))
    for j, (plane, si) in enumerate(picks):
        ov = _rgba_boundaries(_slice(La, plane, si), None, colour=(0, 1, 1), alpha=0.9)
        ovb = _rgba_boundaries(_slice(Lb, plane, si), None, colour=(1, 0, 1), alpha=0.9)
        m = ovb[..., 3] > 0
        ov[m] = ovb[m]
        _show(axes[j], _slice(r, plane, si), 0, rmax, ov, f"{plane} {si}")
    fig.suptitle(f"{subject} {cond}: cyan = header/NN labels; magenta = labels under historical bbregister transform",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(out_png, dpi=70)
    plt.close(fig)
