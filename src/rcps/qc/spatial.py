"""Phases B-C: header geometry audit, coordinate provenance, NN label resampling, label integrity,
left-right checks, and quantitative alignment (NMI with anatomy as the moving image).

rCPS intensities are never interpolated or modified. Only anatomy/labels are resampled into the rCPS grid.
"""
from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Any, Protocol, cast

import nibabel as nib
import numpy as np
from scipy import ndimage, optimize

from .. import fsgeom, labels, similarity

AXES = ("tx", "ty", "tz", "rx", "ry", "rz")


class LoadedImage(Protocol):
    """Typing view of a NIfTI/MGH image loaded from file: its affine comes from the header, never None."""
    affine: np.ndarray
    dataobj: Any
    shape: tuple[int, ...]
    header: Any

    def get_data_dtype(self) -> np.dtype: ...


def load_spatial_image(path) -> LoadedImage:
    """``nib.load`` typed for NIfTI/MGH inputs (typing only; no runtime check)."""
    return cast(LoadedImage, nib.load(path))


def rcps_map(rcps_dir: Path, subject: str, cond: str) -> Path:
    hits = sorted(glob.glob(str(rcps_dir / subject / f"ses-{cond}" / "*_stat-rCPS_statmap.nii.gz")))
    if len(hits) != 1:
        raise FileNotFoundError(f"{subject} {cond}: expected 1 rCPS map, found {len(hits)}")
    return Path(hits[0])


def image_geometry(img, kind: str) -> dict:
    A = img.affine
    row = {
        "shape": list(img.shape[:3]),
        "zooms": [round(float(z), 6) for z in img.header.get_zooms()[:3]],
        "affine": np.round(A, 6).tolist(),
        "axcodes": "".join(nib.aff2axcodes(A)),
        "det": float(np.linalg.det(A[:3, :3])),
        "centre_world": (A @ np.r_[(np.array(img.shape[:3]) - 1) / 2.0, 1])[:3].round(4).tolist(),
    }
    if isinstance(img, nib.Nifti1Image):
        q, qc = img.header.get_qform(coded=True)
        s, sc = img.header.get_sform(coded=True)
        row.update(qform_code=int(qc), sform_code=int(sc),
                   qform=None if q is None else np.round(q, 6).tolist(),
                   sform=None if s is None else np.round(s, 6).tolist(),
                   qform_sform_maxabsdiff=None if (q is None or s is None) else float(np.abs(q - s).max()))
    else:  # MGH: scanner vox2ras is img.affine; tkregister vox2ras recorded for completeness only
        row.update(qform_code=None, sform_code=None, qform=None, sform=None, qform_sform_maxabsdiff=None,
                   vox2ras_tkr=np.round(img.header.get_vox2ras_tkr(), 6).tolist())
    row["kind"] = kind
    return row


def tissue_class_volume(aparc: np.ndarray, tc: dict) -> np.ndarray:
    """0 unlabelled/other, 1 cortical GM (DK), 2 WM, 3 subcortical GM + cerebellum, 4 CSF."""
    out = np.zeros(aparc.shape, np.uint8)
    out[np.isin(aparc, list(tc["cerebral_wm"]))] = 2
    out[np.isin(aparc, list(tc["subcortical_gm_cerebellum"]))] = 3
    out[np.isin(aparc, list(tc["csf"]))] = 4
    out[((aparc >= 1000) & (aparc < 1036)) | ((aparc >= 2000) & (aparc < 2036))] = 1
    return out


def recon_input(fs_subj: Path) -> str | None:
    cmd = fs_subj / "scripts" / "recon-all.cmd"
    if not cmd.exists():
        return None
    m = re.search(r"mri_convert\s+(\S+T1w\.nii\.gz)", cmd.read_text(errors="replace"))
    return m.group(1) if m else None


class NMIProblem:
    """NMI between fixed rCPS values (no interpolation) and anatomy sampled at transformed world positions."""

    def __init__(self, rcps_vals, sampler, bins, a_range, b_range):
        self.r, self.s, self.bins, self.ar, self.br = rcps_vals, sampler, bins, a_range, b_range

    def __call__(self, T: np.ndarray) -> float:
        return similarity.nmi(self.r, self.s.sample(T), bins=self.bins, a_range=self.ar, b_range=self.br)


def audit_subject(subject: str, paths, cfg: dict, conditions: list[str],
                  label_out: Path) -> dict:
    fs_subj = paths.freesurfer / subject
    t1_path = paths.bids_root / subject / "ses-MRI" / "anat" / f"{subject}_ses-MRI_T1w.nii.gz"
    t1_img = nib.load(t1_path)
    if not isinstance(t1_img, nib.Nifti1Image):  # qform/sform checks below are NIfTI-specific
        raise TypeError(f"{t1_path}: expected a NIfTI T1w image, got {type(t1_img).__name__}")
    t1 = cast(LoadedImage, t1_img)
    raw = load_spatial_image(fs_subj / "mri" / "rawavg.mgz")
    orig = load_spatial_image(fs_subj / "mri" / "orig.mgz")
    aparc_img = load_spatial_image(fs_subj / "mri" / "aparc+aseg.mgz")
    bm_img = load_spatial_image(fs_subj / "mri" / "brainmask.mgz")
    aparc = np.asarray(aparc_img.dataobj).astype(np.int32)
    t1_data = np.asarray(t1.dataobj, dtype=np.float32)
    res = {"subject": subject, "geometry": [], "affine_checks": [], "roi_counts": [], "label_integrity": [],
           "lr": [], "zeros_by_tissue": [], "alignment": [], "profiles": [], "historical": []}

    # ---------------- B: geometry
    for kind, img in (("T1w", t1), ("rawavg.mgz", raw), ("orig.mgz", orig), ("aparc+aseg.mgz", aparc_img),
                      ("brainmask.mgz", bm_img)):
        res["geometry"].append({"subject": subject, "image": kind, "condition": "", **image_geometry(img, kind)})
    rimgs = {}
    for c in conditions:
        p = rcps_map(paths.rcps, subject, c)
        img = load_spatial_image(p)
        d = np.asarray(img.dataobj, dtype=np.float32)
        g = image_geometry(img, "rCPS")
        g.update(finite_frac=float(np.isfinite(d).mean()), nonzero_frac=float((d != 0).mean()),
                 negative_count=int((d < 0).sum()), nonfinite_count=int((~np.isfinite(d)).sum()),
                 dtype=str(img.get_data_dtype()), file=p.name)
        res["geometry"].append({"subject": subject, "image": "rCPS", "condition": c, **g})
        rimgs[c] = (img, d)

    def chk(name, value, ok, note=""):
        res["affine_checks"].append({"subject": subject, "check": name, "value": value, "pass": bool(ok), "note": note})

    for c, (img, _) in rimgs.items():
        chk(f"rCPS_{c}_shape_equals_T1w", str(img.shape[:3]), img.shape[:3] == t1.shape[:3])
        dA = float(np.abs(img.affine - t1.affine).max())
        chk(f"rCPS_{c}_affine_maxabsdiff_vs_T1w", dA, dA < 1e-4, "header identity only; NOT proof of registration")
        q, qc = img.header.get_qform(coded=True)
        s, sc = img.header.get_sform(coded=True)
        qs = float(np.abs(q - s).max()) if q is not None and s is not None else np.nan
        chk(f"rCPS_{c}_qform_sform", f"qcode={qc} scode={sc} maxdiff={qs:.2e}", qc > 0 and sc > 0 and qs < 1e-4)
        chk(f"rCPS_{c}_axcodes_equal_T1w", "".join(nib.aff2axcodes(img.affine)),
            nib.aff2axcodes(img.affine) == nib.aff2axcodes(t1.affine))
    affs = [rimgs[c][0].affine for c in conditions]
    dcond = max(float(np.abs(a - affs[0]).max()) for a in affs)
    chk("rCPS_conditions_affine_identical", dcond, dcond < 1e-6)
    q, qc = t1.header.get_qform(coded=True)
    s, sc = t1.header.get_sform(coded=True)
    chk("T1w_qform_sform", f"qcode={qc} scode={sc} maxdiff={float(np.abs(q - s).max()):.2e}",
        qc > 0 and sc > 0 and float(np.abs(q - s).max()) < 1e-4)
    d_raw_aff = float(np.abs(raw.affine - t1.affine).max())
    chk("rawavg_affine_maxabsdiff_vs_T1w", d_raw_aff, d_raw_aff < 1e-3)
    raw_data = np.asarray(raw.dataobj, dtype=np.float32)
    same_shape = raw_data.shape == t1_data.shape
    vox_diff = float(np.abs(raw_data - t1_data).max()) if same_shape else np.nan
    chk("rawavg_voxels_identical_to_T1w", vox_diff, same_shape and vox_diff == 0.0,
        "tests that FreeSurfer was run on this exact T1w")
    for kind, img in (("aparc+aseg", aparc_img), ("brainmask", bm_img)):
        chk(f"{kind}_affine_equals_orig", float(np.abs(img.affine - orig.affine).max()),
            np.allclose(img.affine, orig.affine))
    c_off = float(np.linalg.norm(np.array(image_geometry(orig, "o")["centre_world"]) -
                                 np.array(image_geometry(t1, "t")["centre_world"])))
    chk("orig_vs_T1w_centre_offset_mm", c_off, c_off < 2.0, "FreeSurfer conform re-centres; <2 mm expected")

    # ---------------- C1: coordinate provenance
    prov = {"subject": subject, "recon_all_input": recon_input(fs_subj),
            "mapping": "rCPS voxel -> scanner RAS (NIfTI sform) -> aparc+aseg voxel (inverse MGH scanner vox2ras); "
                       "no tkregister RAS used"}
    petlta = sorted((paths.petprep / subject).glob("ses-*/pet/*_from-pet_to-T1w_reg.lta"))
    bm_bin = np.asarray(bm_img.dataobj) > 0
    bm_centroid = (bm_img.affine @ np.r_[np.argwhere(bm_bin).mean(0), 1])[:3]
    prov["brainmask_centroid_world"] = bm_centroid.round(3).tolist()
    prov["petprep_ltas"] = []
    for lp in petlta:
        lta = fsgeom.read_lta(lp)
        T = fsgeom.lta_ras2ras(lta)
        prov["petprep_ltas"].append({"file": lp.name, "type": lta["type"], "src": lta["src"].get("filename"),
                                     "dst": lta["dst"].get("filename"),
                                     **fsgeom.rigid_params_deviation(T, bm_centroid)})
    res["provenance"] = prov

    # ---------------- C2-C4: NN labels into each rCPS grid, integrity, left-right
    dk = labels.dk_cortical_labels()
    tc = cfg["tissue_classes"]
    native_counts = dict(zip(*np.unique(aparc, return_counts=True), strict=True))
    tissue_native = tissue_class_volume(aparc, tc)
    cache = {}
    for c in conditions:
        img, d = rimgs[c]
        key = tuple(np.round(img.affine, 6).ravel()) + tuple(img.shape[:3])
        if key not in cache:
            lab = labels.resample_labels_nn(aparc, aparc_img.affine, img.shape, img.affine)
            bm = labels.resample_labels_nn(bm_bin.astype(np.uint8), bm_img.affine, img.shape, img.affine) > 0
            cache[key] = (lab, bm)
            out = label_out / f"{subject}_space-rCPS{c}_desc-aparcaseg_nn_dseg.nii.gz"
            nib.save(nib.Nifti1Image(lab.astype(np.int16), img.affine), out)
        lab, bm = cache[key]
        present = set(np.unique(lab))
        cents = labels.roi_centroids_world(lab, img.affine, dk.keys())
        for code, name in dk.items():
            m = lab == code
            n = int(m.sum())
            vals = d[m]
            res["roi_counts"].append({
                "subject": subject, "condition": c, "code": code, "roi": name, "n_voxels_rcps_grid": n,
                "n_voxels_native_aparc": int(native_counts.get(code, 0)),
                "ratio_rcps_to_native": n / native_counts[code] if native_counts.get(code) else np.nan,
                "n_nonfinite": int((~np.isfinite(vals)).sum()), "n_zero": int((vals == 0).sum()),
                "n_negative": int((vals < 0).sum()),
                "frac_zero_or_nonfinite": float(((vals == 0) | ~np.isfinite(vals)).mean()) if n else np.nan,
                "centroid_x": float(cents[code][0]), "centroid_y": float(cents[code][1]),
                "centroid_z": float(cents[code][2])})
        counts = [r["n_voxels_rcps_grid"] for r in res["roi_counts"] if r["condition"] == c]
        res["label_integrity"].append({
            "subject": subject, "condition": c, "n_expected_cortical": 68,
            "n_present_cortical": int(sum(code in present for code in dk)),
            "missing_rois": ";".join(dk[k] for k in dk if k not in present),
            "n_zero_voxel_rois": int(sum(n == 0 for n in counts)), "min_roi_voxels": int(min(counts)),
            "median_roi_voxels": float(np.median(counts)),
            "labels_outside_rcps_support_voxels": int(((lab > 0) & (d == 0)).sum()),
            "cortical_voxels_zero_rcps": int((np.isin(lab, list(dk)) & (d == 0)).sum()),
            "cortical_voxels_total": int(np.isin(lab, list(dk)).sum()),
            "brainmask_voxels": int(bm.sum()), "brainmask_zero_rcps_frac": float((d[bm] == 0).mean()),
            "rcps_nonzero_outside_brainmask": int(((d != 0) & ~bm).sum()),
            "nonfinite_in_brainmask": int((~np.isfinite(d[bm])).sum())})
        lr = labels.left_right_check(cents)
        res["lr"].append({"subject": subject, "condition": c, "n_pairs": len(lr),
                          "n_pairs_lh_left_of_rh": int(sum(r["lh_left_of_rh"] for r in lr)),
                          "axcodes": "".join(nib.aff2axcodes(img.affine)),
                          "failing_pairs": ";".join(r["roi"] for r in lr if not r["lh_left_of_rh"])})
        tcl = labels.resample_labels_nn(tissue_native, aparc_img.affine, img.shape, img.affine)
        for k, nm in {1: "cortical_gm", 2: "wm", 3: "subcortical_gm_cerebellum", 4: "csf", 0: "unlabelled_in_brainmask"}.items():
            m = (tcl == k) & (bm if k == 0 else True)
            res["zeros_by_tissue"].append({"subject": subject, "condition": c, "tissue": nm, "n_voxels": int(m.sum()),
                                           "frac_zero_rcps": float((d[m] == 0).mean()) if m.any() else np.nan})

    # ---------------- C6: quantitative alignment (anatomy moves; rCPS fixed)
    sim = cfg["similarity"]
    ctx = {}
    for c in conditions:
        img, d = rimgs[c]
        lab, bm = cache[tuple(np.round(img.affine, 6).ravel()) + tuple(img.shape[:3])]
        problems, centre, ctx_world = build_problems(d, img, lab, bm, t1_data, t1, tissue_native, aparc_img,
                                                     bm_centroid, sim)
        _alignment_rows(res, subject, c, problems, centre, ctx_world, sim)
        ctx[c] = lab
    res["_labels"] = ctx
    return res


def build_problems(d, img, lab, bm, t1_data, t1, tissue_native, aparc_img, centre, sim):
    full_mask = ndimage.binary_dilation(bm, iterations=sim["mask_dilation_mm"])
    int_mask = ndimage.binary_erosion(bm, iterations=sim["mask_erosion_mm"])
    lo, hi = sim["intensity_clip_pct"]
    problems = {}
    for mname, m in (("full", full_mask), ("interior", int_mask)):
        vox = similarity.evaluation_voxels(m, sim["voxel_stride"])
        rv = d[tuple(vox.T)]
        t1s = similarity.AnatomySampler(t1_data, t1.affine, img.affine, vox, order=1)
        tcs = similarity.AnatomySampler(tissue_native.astype(np.float32), aparc_img.affine, img.affine, vox, order=0)
        r_rng = tuple(np.percentile(rv, [lo, hi]))
        t_rng = tuple(np.percentile(t1s.sample(np.eye(4)), [lo, hi]))
        problems[f"nmi_t1_{mname}"] = NMIProblem(rv, t1s, sim["bins"], r_rng, t_rng)
        problems[f"nmi_tissue_{mname}"] = NMIProblem(rv, tcs, [sim["bins"], 5], r_rng, (-0.5, 4.5))
    dk = labels.dk_cortical_labels()
    ctx_vox = np.argwhere(np.isin(lab, list(dk)))[::7]
    ctx_world = (img.affine @ np.c_[ctx_vox, np.ones(len(ctx_vox))].T)[:3].T
    return problems, np.asarray(centre, float), ctx_world


def _alignment_rows(res, subject, c, problems, centre, ctx_world, sim):
    for metric, prob in problems.items():
        base = prob(np.eye(4))
        row = {"subject": subject, "condition": c, "metric": metric, "nmi_header": base}
        for ax in AXES:
            grid = sim["profile_translations_mm"] if ax.startswith("t") else sim["profile_rotations_deg"]
            best = (None, -np.inf)
            for v in grid:
                kw = {ax if ax.startswith("t") else ax + "_deg": v}
                val = prob(fsgeom.rigid_matrix(centre=centre, **kw))
                res["profiles"].append({"subject": subject, "condition": c, "metric": metric, "axis": ax,
                                        "offset": v, "nmi": val, "nmi_minus_header": val - base})
                if val > best[1]:
                    best = (v, val)
            row[f"profile_argmax_{ax}"] = best[0]
        row["profile_argmax_max_abs"] = max(abs(row[f"profile_argmax_{ax}"]) for ax in AXES)
        Mref = np.eye(4)
        Mref[0, 0], Mref[0, 3] = -1.0, 2 * centre[0]      # L-R reflection of anatomy about brain-centroid plane
        row["nmi_lr_mirrored_anatomy"] = prob(Mref)
        if metric in sim["optimize_metrics"]:
            b = sim["optimize_bounds"]
            bounds = [(-b["translation_mm"], b["translation_mm"])] * 3 + [(-b["rotation_deg"], b["rotation_deg"])] * 3
            opt = optimize.minimize(lambda x: -prob(fsgeom.rigid_matrix(*x, centre=centre)), np.zeros(6),
                                    method="Powell", bounds=bounds, options={"xtol": 0.05, "ftol": 1e-6, "maxfev": 600})
            disp = fsgeom.displacement_stats(fsgeom.rigid_matrix(*opt.x, centre=centre), ctx_world)
            row.update({f"opt_{ax}": float(v) for ax, v in zip(AXES, opt.x, strict=True)})
            row.update(opt_nmi=float(-opt.fun), opt_gain=float(-opt.fun - base), opt_nfev=int(opt.nfev),
                       opt_cortex_disp_mean_mm=disp["mean_mm"], opt_cortex_disp_max_mm=disp["max_mm"])
        res["alignment"].append(row)


def historical_subject(subject: str, paths, cfg: dict, conditions: list[str], historical_root: Path) -> dict:
    """C7 (run only after the baseline pass): evaluate the historical bbregister transforms with the SAME criteria."""
    fs_subj = paths.freesurfer / subject
    t1 = load_spatial_image(paths.bids_root / subject / "ses-MRI" / "anat" / f"{subject}_ses-MRI_T1w.nii.gz")
    t1_data = np.asarray(t1.dataobj, dtype=np.float32)
    aparc_img = load_spatial_image(fs_subj / "mri" / "aparc+aseg.mgz")
    aparc = np.asarray(aparc_img.dataobj).astype(np.int32)
    bm_img = load_spatial_image(fs_subj / "mri" / "brainmask.mgz")
    bm_bin = np.asarray(bm_img.dataobj) > 0
    centre = (bm_img.affine @ np.r_[np.argwhere(bm_bin).mean(0), 1])[:3]
    tissue_native = tissue_class_volume(aparc, cfg["tissue_classes"])
    dk = labels.dk_cortical_labels()
    out = {"subject": subject, "historical": [], "_labels": {}, "_hist_labels": {}}
    for c in conditions:
        rp = rcps_map(paths.rcps, subject, c)
        hp = historical_root / "1.rCPS_alig" / f"{rp.name[:-7]}_bbregister.lta"
        if not hp.exists():
            out["historical"].append({"subject": subject, "condition": c, "note": f"missing {hp.name}"})
            continue
        lta = fsgeom.read_lta(hp)
        H = fsgeom.lta_ras2ras(lta)
        img = load_spatial_image(rp)
        d = np.asarray(img.dataobj, dtype=np.float32)
        lab = labels.resample_labels_nn(aparc, aparc_img.affine, img.shape, img.affine)
        bm = labels.resample_labels_nn(bm_bin.astype(np.uint8), bm_img.affine, img.shape, img.affine) > 0
        labH = labels.resample_labels_nn(aparc, aparc_img.affine, img.shape, img.affine, world_transform=H)
        problems, centre, ctx_world = build_problems(d, img, lab, bm, t1_data, t1, tissue_native, aparc_img, centre,
                                                     cfg["similarity"])
        dev = fsgeom.rigid_params_deviation(H, centre)
        dispH = fsgeom.displacement_stats(H, ctx_world)
        nH = [int((labH == code).sum()) for code in dk]
        row = {"subject": subject, "condition": c, "lta_type": lta["type"],
               "lta_src_matches_rcps_grid": bool(np.allclose(lta["src_vox2ras"], img.affine, atol=1e-3)),
               "lta_dst_matches_orig_grid": bool(np.allclose(lta["dst_vox2ras"], aparc_img.affine, atol=1e-3)),
               "rotation_deg": dev["rotation_deg"], "centroid_displacement_mm": dev["centre_displacement_mm"],
               "cortex_disp_mean_mm": dispH["mean_mm"], "cortex_disp_max_mm": dispH["max_mm"],
               "bbreg_min_roi_voxels": min(nH), "bbreg_n_zero_voxel_rois": sum(n == 0 for n in nH),
               "header_cortical_voxels_zero_rcps": int((np.isin(lab, list(dk)) & (d == 0)).sum()),
               "bbreg_cortical_voxels_zero_rcps": int((np.isin(labH, list(dk)) & (d == 0)).sum())}
        Hinv = np.linalg.inv(H)
        for metric, prob in problems.items():
            row[f"{metric}_header"] = prob(np.eye(4))
            row[f"{metric}_bbregister"] = prob(H)
            # Direction diagnostic: the LTA is RAS2RAS src(rCPS) -> dst(T1), so the anatomy for rCPS voxel p sits
            # at H(p). If the inverse scored higher, the direction convention would be suspect.
            row[f"{metric}_bbregister_inverse_diag"] = prob(Hinv)
        out["historical"].append(row)
        out["_labels"][c], out["_hist_labels"][c] = lab, labH
    return out
