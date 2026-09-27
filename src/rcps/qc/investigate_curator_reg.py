"""Read-only evaluation of the dataset curators' PET->T1 transforms (rcps-modified-petprep
`*_from-pet_to-T1w_reg.lta`, created by `mri_coreg` of the mean PET to the T1 and applied by the curators to the
rCPS statmaps in `kinsurf.m` / `kinvol.m`) with the SAME criteria as the QC alignment checks.

Usage: PYTHONPATH=src python -m rcps.qc.investigate_curator_reg [--workers N]
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor

import nibabel as nib
import numpy as np
import pandas as pd

from .. import fsgeom, labels
from ..config import REPO_ROOT, load_paths, load_yaml
from ..runrecord import create_run_dir, write_run_metadata
from . import dataset as ds
from . import spatial

CONDS = ["Awake", "SleepDeprived", "Asleep"]


def one_scan(args) -> dict:
    s, c, P, cfg = args
    fs = P.freesurfer / s
    t1 = nib.load(P.bids_root / s / "ses-MRI" / "anat" / f"{s}_ses-MRI_T1w.nii.gz")
    t1d = np.asarray(t1.dataobj, np.float32)
    ap = nib.load(fs / "mri" / "aparc+aseg.mgz")
    aparc = np.asarray(ap.dataobj).astype(np.int32)
    bm_img = nib.load(fs / "mri" / "brainmask.mgz")
    bmb = np.asarray(bm_img.dataobj) > 0
    centre = (bm_img.affine @ np.r_[np.argwhere(bmb).mean(0), 1])[:3]
    img = nib.load(spatial.rcps_map(P.rcps, s, c))
    d = np.asarray(img.dataobj, np.float32)
    lab = labels.resample_labels_nn(aparc, ap.affine, d.shape, img.affine)
    bm = labels.resample_labels_nn(bmb.astype(np.uint8), bm_img.affine, d.shape, img.affine) > 0
    tissue = spatial.tissue_class_volume(aparc, cfg["tissue_classes"])
    problems, centre, ctx_world = spatial.build_problems(d, img, lab, bm, t1d, t1, tissue, ap, centre, cfg["similarity"])
    lta = fsgeom.read_lta(P.petprep / s / f"ses-{c}" / "pet" / f"{s}_ses-{c}_from-pet_to-T1w_reg.lta")
    C = fsgeom.lta_ras2ras(lta)
    dev = fsgeom.rigid_params_deviation(C, centre)
    disp = fsgeom.displacement_stats(C, ctx_world)
    row = {"subject": s, "condition": c, "lta_type": lta["type"],
           "src_matches_rcps_grid": bool(np.allclose(lta["src_vox2ras"], img.affine, atol=1e-3)),
           "dst_matches_orig_grid": bool(np.allclose(lta["dst_vox2ras"], ap.affine, atol=1e-3)),
           "rotation_deg": dev["rotation_deg"], "centroid_displacement_mm": dev["centre_displacement_mm"],
           "cortex_disp_mean_mm": disp["mean_mm"], "cortex_disp_max_mm": disp["max_mm"]}
    for metric, prob in problems.items():
        row[f"{metric}_header"] = prob(np.eye(4))
        row[f"{metric}_curator"] = prob(C)
        row[f"{metric}_curator_inverse_diag"] = prob(np.linalg.inv(C))
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    P = load_paths()
    cfg = load_yaml(REPO_ROOT / "configs" / "qc.yaml")
    run_dir = create_run_dir(P.outputs_root, "curator-reg-investigation")
    subs = sorted(set(ds.read_participants(P.bids_root / "participants.tsv")) | {"sub-SP06"})
    write_run_metadata(run_dir, argv=sys.argv, config={"qc": cfg}, seeds={}, inputs={"bids_root": str(P.bids_root)})
    with ProcessPoolExecutor(args.workers) as ex:
        rows = list(ex.map(one_scan, [(s, c, P, cfg) for s in subs for c in CONDS]))
    pd.DataFrame(rows).to_csv(run_dir / "curator_transform_comparison.tsv", sep="\t", index=False)
    print(run_dir)


if __name__ == "__main__":
    main()
