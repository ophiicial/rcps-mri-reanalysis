"""Read-only investigation of zero-valued rCPS voxels (docs/qc_decisions.md D3).

Usage: PYTHONPATH=src python -m rcps.qc.investigate_zeros [--workers N]
Writes one run directory outputs/<ts>_zero-investigation_<sha>/. No ROI means, no modelling.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import cast

import numpy as np
import pandas as pd
from scipy import ndimage

from .. import labels
from ..config import load_paths
from ..provenance import run_provenance
from ..runrecord import create_run_dir, write_run_metadata
from .verify_canonical import CANONICAL_CONFIG, load_canonical
from . import dataset as ds
from . import spatial

CONDS = ["Awake", "SleepDeprived", "Asleep"]
DIST_BINS_MM = [(0, 2), (2, 5), (5, 10), (10, 999)]


def one_scan(args) -> dict:
    subject, cond, P = args
    img = spatial.load_spatial_image(spatial.rcps_map(P.rcps, subject, cond))
    d = np.asarray(img.dataobj, np.float32)
    ap = spatial.load_spatial_image(P.freesurfer / subject / "mri" / "aparc+aseg.mgz")
    bm = spatial.load_spatial_image(P.freesurfer / subject / "mri" / "brainmask.mgz")
    lab = labels.resample_labels_nn(np.asarray(ap.dataobj).astype(np.int32), ap.affine, d.shape, img.affine)
    B = labels.resample_labels_nn((np.asarray(bm.dataobj) > 0).astype(np.uint8), bm.affine, d.shape, img.affine) > 0
    mm_img = spatial.load_spatial_image(P.petprep / subject / f"ses-{cond}" / "pet" / f"{subject}_ses-{cond}_desc-mc_mean.nii.gz")
    m = np.asarray(mm_img.dataobj, np.float32)
    ctx = np.isin(lab, list(labels.dk_cortical_labels()))
    z = d == 0
    pos = d[B & (d > 0)]
    cv = d[ctx]
    r = {"subject": subject, "condition": cond,
         "mcmean_on_rcps_grid": bool(np.allclose(mm_img.affine, img.affine) and m.shape == d.shape),
         "n_negative": int((d < 0).sum()), "n_nonfinite": int((~np.isfinite(d)).sum()),
         "brainmask_zero_frac": float(z[B].mean()), "cortex_zero_frac": float(z[ctx].mean()),
         "pos_min": float(pos.min()), "pos_frac_lt_0p02": float((pos < 0.02).mean()),
         "pos_frac_lt_0p1": float((pos < 0.1).mean()), "pos_median": float(np.median(pos)),
         "ctx_n": int(ctx.sum()), "ctx_zero_n": int((cv == 0).sum()),
         "ctx_pos_0_0p02_n": int(((cv > 0) & (cv < 0.02)).sum()),
         "ctx_pos_0p02_0p04_n": int(((cv >= 0.02) & (cv < 0.04)).sum()),
         "ctx_pos_0p2_0p22_n": int(((cv >= 0.2) & (cv < 0.22)).sum())}
    dist = ndimage.distance_transform_edt(B)  # mm (1 mm voxels) to the nearest non-brain voxel
    for lo, hi in DIST_BINS_MM:
        sel = B & (dist > lo) & (dist <= hi)  # pyright: ignore[reportOperatorIssue] -- scipy types EDT output as optional/tuple; default flags return an ndarray
        r[f"zero_frac_dist_{lo}_{hi}mm"] = float(z[sel].mean())
    for ax in range(3):  # block structure: in-brain positive voxels equal to their +1 neighbour
        a = np.take(d, range(d.shape[ax] - 1), axis=ax)
        b = np.take(d, range(1, d.shape[ax]), axis=ax)
        sel = (a > 0) & np.take(B, range(d.shape[ax] - 1), axis=ax)
        r[f"equal_neighbour_frac_axis{ax}"] = float((a[sel] == b[sel]).mean())
    # zero relation to the curators' mean PET (activity) image, same grid
    r["mcmean_zero_frac_where_rcps_zero"] = float((m[B & z] == 0).mean())
    r["mcmean_zero_frac_where_rcps_pos"] = float((m[B & ~z] == 0).mean())
    r["mcmean_median_ratio_ctx_zero_vs_pos"] = float(np.median(m[ctx & z]) / np.median(m[ctx & ~z]))
    q = np.quantile(m[ctx], [0.1, 0.9])
    mc = m[ctx]
    r["ctx_zero_frac_pet_bottom10"] = float((cv[mc <= q[0]] == 0).mean())
    r["ctx_zero_frac_pet_middle80"] = float((cv[(mc > q[0]) & (mc < q[1])] == 0).mean())
    r["ctx_zero_frac_pet_top10"] = float((cv[mc >= q[1]] == 0).mean())
    # zero-cluster structure in cortex
    cc, n = cast(tuple[np.ndarray, int], ndimage.label(z & ctx))
    sizes = np.bincount(cc.ravel())[1:]
    r["ctx_zero_clusters"] = int(n)
    r["ctx_zero_frac_in_clusters_ge100"] = float(sizes[sizes >= 100].sum() / max(sizes.sum(), 1))
    r["ctx_zero_largest_cluster"] = int(sizes.max()) if n else 0
    return r


def cross_condition(args) -> dict:
    subject, P = args
    zs = {c: np.asarray(spatial.load_spatial_image(spatial.rcps_map(P.rcps, subject, c)).dataobj, np.float32) == 0 for c in CONDS}
    bm = spatial.load_spatial_image(P.freesurfer / subject / "mri" / "brainmask.mgz")
    ref = spatial.load_spatial_image(spatial.rcps_map(P.rcps, subject, CONDS[0]))
    B = labels.resample_labels_nn((np.asarray(bm.dataobj) > 0).astype(np.uint8), bm.affine, ref.shape, ref.affine) > 0
    out = {"subject": subject}
    for a, b in (("Awake", "SleepDeprived"), ("Awake", "Asleep"), ("SleepDeprived", "Asleep")):
        inter = (zs[a] & zs[b] & B).sum()
        union = ((zs[a] | zs[b]) & B).sum()
        out[f"jaccard_{a}_{b}"] = float(inter / union)
    out["zero_in_all3_frac_of_any"] = float((zs["Awake"] & zs["SleepDeprived"] & zs["Asleep"] & B).sum() /
                                            ((zs["Awake"] | zs["SleepDeprived"] | zs["Asleep"]) & B).sum())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    P = load_paths()
    run_dir = create_run_dir(P.outputs_root, "zero-investigation")
    subs = ds.read_participants(P.bids_root / "participants.tsv")
    subs = sorted(set(subs) | {"sub-SP06"})
    cfg = {"conditions": CONDS, "dist_bins_mm": DIST_BINS_MM}
    prov = run_provenance(P.bids_root, load_canonical(), config_files={"canonical_dataset": CANONICAL_CONFIG},
                          resolved_config=cfg, run_verifier=True)
    write_run_metadata(run_dir, argv=sys.argv, config=cfg, seeds={},
                       inputs={"bids_root": str(P.bids_root), "subjects": subs}, provenance=prov)
    with ProcessPoolExecutor(args.workers) as ex:
        scans = list(ex.map(one_scan, [(s, c, P) for s in subs for c in CONDS]))
        cross = list(ex.map(cross_condition, [(s, P) for s in subs]))
    pd.DataFrame(scans).to_csv(run_dir / "zero_voxels_by_scan.tsv", sep="\t", index=False)
    pd.DataFrame(cross).to_csv(run_dir / "zero_voxels_cross_condition.tsv", sep="\t", index=False)
    print(run_dir)
    return run_dir


if __name__ == "__main__":
    main()
