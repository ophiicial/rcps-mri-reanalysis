"""Build and validate the canonical primary panel from the verified ds004733 v1.0.1 copy.

Usage: PYTHONPATH=src python -m rcps.panel.build
Read-only on the dataset. Requires `verify_canonical --require-git` to PASS before reading any input.
Writes outputs/<ts>_panel_<sha>/ with the long table, condition-level table, deterministic panel manifest,
data-validity summary and run record. It computes no model, CV, association or inferential quantity.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence

import numpy as np
import pandas as pd

from ..config import REPO_ROOT, load_paths, load_yaml
from ..provenance import canonical_json_sha256, run_provenance
from ..qc.dataset import read_participants
from ..qc.verify_canonical import CANONICAL_CONFIG, load_canonical, read_expected, verify
from ..runrecord import create_run_dir, sha256_file, write_run_metadata
from .assemble import (CONDITION_COLUMNS, MRI_COLUMNS, CanonicalPanel, array_sha256, build_long_table,
                       panel_from_long_table, table_tsv)
from .mri import parse_aparc_stats
from .rcps_roi import LabelGrids, check_sidecar_units, load_rcps, roi_statistics
from .sources import CanonicalSources
from .spec import (PRIMARY_SPATIAL, ROI, SPEC_VERSION, TARGET_DEFINITION, canonical_rois, canonical_subjects,
                   condition_column, require_frozen_primary_contract)

ANALYSIS_CONFIG = REPO_ROOT / "configs" / "analysis.yaml"
FROZEN_SPEC_TAG = "analysis-plan-v3.0"
FROZEN_SPEC_COMMIT = "80d951fbfb6929e9470786b0a0fbcb2c81630055"
FROZEN_SPEC_FILES = ("docs/analysis_plan.md", "configs/analysis.yaml")


def extract_mri(sources: CanonicalSources, subjects: Sequence[str], rois: Sequence[ROI]) -> tuple[pd.DataFrame, list]:
    rows, used = [], []
    for subject in subjects:
        for hemi in ("lh", "rh"):
            src = sources.aparc_stats(subject, hemi)
            used.append({"subject_id": subject, "kind": f"{hemi}.aparc.stats", "condition": "",
                         "relpath": src.relpath, "sha256": src.sha256})
            for row in parse_aparc_stats(src.path.read_text(), subject, hemi, rois):
                rows.append({"subject_id": subject, **row, "source_relpath": src.relpath})
    return pd.DataFrame(rows, columns=MRI_COLUMNS), used


def extract_rcps(sources: CanonicalSources, subjects: Sequence[str], rois: Sequence[ROI],
                 conditions: Sequence[str], units: str) -> tuple[pd.DataFrame, list]:
    codes = [r.code for r in rois]
    rows, used = [], []
    for subject in subjects:
        aparc = sources.aparc_aseg(subject)
        used.append({"subject_id": subject, "kind": "aparc+aseg", "condition": "", "relpath": aparc.relpath,
                     "sha256": aparc.sha256})
        grids = LabelGrids(aparc.path)
        for condition in conditions:
            statmap = sources.rcps_map(subject, condition)
            sidecar = sources.rcps_sidecar(statmap)
            check_sidecar_units(sidecar.path, units)
            used += [{"subject_id": subject, "kind": kind, "condition": condition, "relpath": s.relpath,
                      "sha256": s.sha256} for kind, s in (("rCPS", statmap), ("rCPS sidecar", sidecar))]
            values, affine = load_rcps(statmap.path)
            try:
                stats = roi_statistics(values, grids.on_grid(values.shape, affine), codes)
            except ValueError as exc:
                raise ValueError(f"{subject} {condition}: {exc}") from None
            for i, roi in enumerate(rois):
                rows.append({"subject_id": subject, "condition": condition, "roi": roi.name,
                             "rcps_roi_mean": stats["mean"][i], "n_voxels": int(stats["n_voxels"][i]),
                             "n_zero": int(stats["n_zero"][i]),
                             "zero_fraction": stats["n_zero"][i] / stats["n_voxels"][i],
                             "source_relpath": statmap.relpath})
    return pd.DataFrame(rows, columns=CONDITION_COLUMNS), used


def panel_manifest(panel: CanonicalPanel, rois: Sequence[ROI], long_table: pd.DataFrame, cond: pd.DataFrame,
                   used: list, canonical: dict, analysis_cfg: dict) -> dict:
    """Deterministic description of the panel: no timestamps, machine paths or repository state."""
    roi_rows = [{"index": r.index, "code": r.code, "name": r.name} for r in rois]
    return {
        "schema": "rcps-primary-panel/1",
        "spec": {"spec_version": analysis_cfg["spec_version"], "frozen_on": analysis_cfg["frozen_on"],
                 "analysis_yaml_sha256": sha256_file(ANALYSIS_CONFIG), **frozen_spec_provenance()},
        "dataset": {k: canonical[k] for k in ("accession", "release_tag", "release_commit", "doi")}
        | {"expected_manifest_sha256": sha256_file(canonical["expected_manifest_path"])},
        "subjects": list(panel.subject_ids),
        "subject_roster_sha256": canonical_json_sha256(list(panel.subject_ids)),
        "rois": roi_rows,
        "roi_roster_sha256": canonical_json_sha256(roi_rows),
        "conditions": list(panel.conditions),
        "features": [dict(f) for f in analysis_cfg["features"]["primary"]],
        "feature_names": list(panel.feature_names),
        "area_transform": "ln_area = natural log(SurfArea / 1 mm^2); log1p is not used",
        "target": {"definition": TARGET_DEFINITION, **{k: analysis_cfg["target"][k] for k in
                   ("roi_value", "zero_handling", "condition_aggregation", "units")},
                   "condition_columns": [condition_column(c) for c in panel.conditions]},
        "spatial": PRIMARY_SPATIAL,
        "dimensions": {"n_subjects": len(panel.subject_ids), "n_rois": len(panel.roi_names),
                       "n_features": len(panel.feature_names), "n_conditions": len(panel.conditions),
                       "x_shape": list(panel.x.shape), "y_shape": list(panel.y.shape),
                       "long_table_rows": len(long_table), "condition_table_rows": len(cond)},
        "sources": sorted(used, key=lambda s: s["relpath"]),
        "content_sha256": {"x_float64_le": array_sha256(panel.x), "y_float64_le": array_sha256(panel.y),
                           "long_table_tsv": _text_sha(table_tsv(long_table)),
                           "condition_table_tsv": _text_sha(table_tsv(cond))},
    }


def frozen_spec_provenance() -> dict:
    """Frozen tag, its commit and the tagged plan/config hashes; fails if the working copies differ from the tag."""
    def git(*args: str) -> bytes:
        return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, check=True).stdout

    commit = git("rev-parse", f"{FROZEN_SPEC_TAG}^{{commit}}").decode().strip()
    if commit != FROZEN_SPEC_COMMIT:
        raise RuntimeError(f"{FROZEN_SPEC_TAG} resolves to {commit}, expected {FROZEN_SPEC_COMMIT}")
    hashes = {}
    for rel in FROZEN_SPEC_FILES:
        tagged = hashlib.sha256(git("show", f"{FROZEN_SPEC_TAG}:{rel}")).hexdigest()
        if tagged != sha256_file(REPO_ROOT / rel):
            raise RuntimeError(f"{rel} differs from {FROZEN_SPEC_TAG}; an amendment is required first")
        hashes[rel] = tagged
    return {"frozen_tag": FROZEN_SPEC_TAG, "frozen_commit": commit, "frozen_file_sha256": hashes}


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _range(a) -> dict:
    a = np.asarray(a, dtype=np.float64)
    return {"min": float(a.min()), "median": float(np.median(a)), "max": float(a.max())}


def validity_summary(panel: CanonicalPanel, long_table: pd.DataFrame, cond: pd.DataFrame) -> dict:
    """Data-validity counts and ranges only (no association, model or inferential quantity)."""
    n_vox = cond.pivot_table(index=["subject_id", "roi"], columns="condition", values="n_voxels", aggfunc="first")
    return {
        "n_subjects": len(panel.subject_ids), "n_rois": len(panel.roi_names),
        "long_table_rows": len(long_table), "condition_table_rows": len(cond),
        "duplicate_subject_roi": int(long_table.duplicated(["subject_id", "roi"]).sum()),
        "duplicate_subject_condition_roi": int(cond.duplicated(["subject_id", "condition", "roi"]).sum()),
        "conditions_per_subject_roi": sorted(set(cond.groupby(["subject_id", "roi"])["condition"].nunique())),
        "nonfinite_x": int((~np.isfinite(panel.x)).sum()), "nonfinite_y": int((~np.isfinite(panel.y)).sum()),
        "thickness_mm": _range(long_table["thickness_mm"]), "area_mm2": _range(long_table["area_mm2"]),
        "ln_area": _range(long_table["ln_area"]),
        "rcps_by_condition": {c: _range(cond.loc[cond["condition"] == c, "rcps_roi_mean"])
                              for c in panel.conditions},
        "rcps_mean": _range(long_table["rcps_mean"]),
        "n_voxels": _range(cond["n_voxels"]),
        "n_voxels_identical_across_conditions": bool((n_vox.nunique(axis=1) == 1).all()),
        "zero_fraction": _range(cond["zero_fraction"]),
        "cells_with_zero_fraction_gt_0p5": int((cond["zero_fraction"] > 0.5).sum()),
        "cells_with_no_nonzero_voxel": int((cond["n_zero"] == cond["n_voxels"]).sum()),
        "total_voxels": int(cond["n_voxels"].to_numpy().sum()),
        "total_zero_voxels": int(cond["n_zero"].to_numpy().sum()),
    }


def build_panel(sources: CanonicalSources, subjects: Sequence[str], analysis_cfg: dict):
    """Extract, assemble and validate. Returns (long_table, condition_table, panel, rois, used_sources)."""
    require_frozen_primary_contract(analysis_cfg)
    rois = canonical_rois(analysis_cfg)
    conditions = tuple(analysis_cfg["target"]["conditions"])
    mri, used_mri = extract_mri(sources, subjects, rois)
    cond, used_rcps = extract_rcps(sources, subjects, rois, conditions, analysis_cfg["target"]["units"])
    long_table = build_long_table(mri, cond, subjects, rois, conditions)
    panel = panel_from_long_table(long_table, subjects, rois, conditions)
    return long_table, cond, panel, rois, used_mri + used_rcps


def main(argv=None) -> int:
    P = load_paths()
    canonical = load_canonical()
    analysis_cfg = load_yaml(ANALYSIS_CONFIG)
    require_frozen_primary_contract(analysis_cfg)
    summary, _ = verify(P.bids_root, canonical, require_git=True)
    if not summary["PASS"]:
        raise RuntimeError(f"canonical dataset verification failed; refusing to build the panel: {summary}")
    subjects = canonical_subjects(analysis_cfg, canonical, read_participants(P.bids_root / "participants.tsv"))
    sources = CanonicalSources(P.bids_root, read_expected(canonical["expected_manifest_path"]),
                               P.freesurfer, P.rcps)
    long_table, cond, panel, rois, used = build_panel(sources, subjects, analysis_cfg)

    run_dir = create_run_dir(P.outputs_root, "panel")
    out = run_dir / "panel"
    out.mkdir()
    (out / "long_table.tsv").write_text(table_tsv(long_table))
    (out / "condition_roi_values.tsv").write_text(table_tsv(cond))
    manifest = panel_manifest(panel, rois, long_table, cond, used, canonical, analysis_cfg)
    (out / "panel_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    validity = validity_summary(panel, long_table, cond)
    (out / "validity_summary.json").write_text(json.dumps(validity, indent=2) + "\n")
    config = {"stage": "phase3_panel_validation", "spec_version": SPEC_VERSION, "modelling": False}
    prov = run_provenance(P.bids_root, canonical,
                          config_files={"canonical_dataset": CANONICAL_CONFIG, "analysis": ANALYSIS_CONFIG},
                          resolved_config=config, verifier_summary=summary)
    write_run_metadata(run_dir, argv=sys.argv, config=config, seeds={},
                       inputs={"bids_root": str(P.bids_root), "n_sources": len(used)}, provenance=prov,
                       extra={"panel_manifest_sha256": canonical_json_sha256(manifest)})
    print(json.dumps({"run_dir": str(run_dir), **validity}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
