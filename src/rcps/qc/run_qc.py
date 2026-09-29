"""Canonical dataset + imaging QC run.  Usage:  PYTHONPATH=src python -m rcps.qc.run_qc [--workers N]

Read-only on all source data. Writes one run-specific directory under outputs/. No predictive modelling.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from ..config import REPO_ROOT, load_paths, load_yaml
from ..provenance import run_provenance
from ..runrecord import create_run_dir, write_run_metadata
from .verify_canonical import CANONICAL_CONFIG, load_canonical
from . import dataset as ds
from . import overlays, spatial

log = logging.getLogger("qc")


def _json_default(o):
    """numpy scalars/arrays -> native Python for JSON."""
    return o.tolist() if hasattr(o, "tolist") else str(o)


def _tsv(rows, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, (list, dict))).any():  # pyright: ignore[reportGeneralTypeIssues] -- pandas types Series.any() as Series | bool; a Series returns bool
            df[col] = df[col].map(lambda v: json.dumps(v, default=_json_default) if isinstance(v, (list, dict)) else v)
    df.to_csv(path, sep="\t", index=False)
    return df


def _baseline_worker(args):
    subject, paths, cfg, conditions, run_dir = args
    lab_dir = run_dir / "labels" / "nn_label_images"
    lab_dir.mkdir(parents=True, exist_ok=True)
    res = spatial.audit_subject(subject, paths, cfg, conditions, lab_dir)
    import nibabel as nib
    t1 = nib.load(paths.bids_root / subject / "ses-MRI" / "anat" / f"{subject}_ses-MRI_T1w.nii.gz")
    rimgs = {c: nib.load(spatial.rcps_map(paths.rcps, subject, c)) for c in conditions}
    od = run_dir / "overlays" / subject
    od.mkdir(parents=True, exist_ok=True)
    for c in conditions:
        overlays.subject_condition_figure(subject, c, rimgs[c], t1, res["_labels"][c], cfg["overlays"],
                                          od / f"{subject}_{c}_multiplanar.png")
        overlays.small_roi_figure(subject, c, rimgs[c], res["_labels"][c], cfg["overlays"],
                                  od / f"{subject}_{c}_small_rois.png")
    overlays.contact_sheet(subject, rimgs, t1, res["_labels"], cfg["overlays"], od / f"{subject}_contact_sheet.png")
    res.pop("_labels")
    return res


def _historical_worker(args):
    subject, paths, cfg, conditions, run_dir, hist_root = args
    res = spatial.historical_subject(subject, paths, cfg, conditions, hist_root)
    import nibabel as nib
    od = run_dir / "alignment" / "historical_overlays"
    od.mkdir(parents=True, exist_ok=True)
    for c, labH in res["_hist_labels"].items():
        img = nib.load(spatial.rcps_map(paths.rcps, subject, c))
        overlays.historical_figure(subject, c, img, res["_labels"][c], labH, cfg["overlays"],
                                   od / f"{subject}_{c}_header_vs_bbregister.png")
    res.pop("_labels"), res.pop("_hist_labels")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paths", default=str(REPO_ROOT / "configs" / "paths.local.yaml"))
    ap.add_argument("--qc-config", default=str(REPO_ROOT / "configs" / "qc.yaml"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--skip-historical", action="store_true")
    args = ap.parse_args(argv)

    paths = load_paths(args.paths)
    cfg = load_yaml(Path(args.qc_config))
    conditions = cfg["conditions"]
    run_dir = create_run_dir(paths.outputs_root, "qc")
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(run_dir / "logs" / "qc_log.txt"), logging.StreamHandler()])
    log.info("run dir %s", run_dir)
    canonical = load_canonical()
    prov = run_provenance(paths.bids_root, canonical,
                          config_files={"qc": Path(args.qc_config), "canonical_dataset": CANONICAL_CONFIG},
                          resolved_config={"qc": cfg, "skip_historical": args.skip_historical, "workers": args.workers},
                          run_verifier=True)
    log.info("provenance: dataset tag=%s commit=%s clean=%s verifier PASS=%s", prov["dataset"]["tag"],
             prov["dataset"]["commit"], prov["dataset"]["clean"], prov["canonical_verifier"].get("PASS"))
    write_run_metadata(run_dir, argv=sys.argv, config={"qc": cfg, "paths_file": Path(args.paths).name}, seeds={},
                       inputs={"bids_root": str(paths.bids_root), "comparison_roots": [str(p) for p in paths.comparison_roots],
                               "historical_finaltry": str(paths.historical_finaltry)},
                       provenance=prov, extra={"status": "started"})

    # ---------------- Phase A
    dd = run_dir / "dataset"
    (dd / "local_vs_authoritative_metadata_diff").mkdir(parents=True)
    inv = {str(paths.bids_root): ds.inventory_copy(paths.bids_root)}
    for root in paths.comparison_roots:
        inv[str(root)] = ds.inventory_copy(root)
    (dd / "dataset_inventory.json").write_text(json.dumps(inv, indent=2, default=str))
    log.info("A1 inventory done for %d copies", len(inv))

    repo, tags = cfg["openneuro"]["github_mirror"], cfg["openneuro"]["releases"]
    meta_rows = []
    published_participants = {}
    for tag in tags:
        pdir = dd / "published" / tag
        pdir.mkdir(parents=True)
        for name in ("dataset_description.json", "participants.tsv", "participants.json", "README", "CHANGES",
                     "sessions.json", ".bidsignore", "recording-manual_blood.json"):
            pub = ds.published_file_text(repo, tag, name)
            loc = paths.bids_root / name
            if pub is not None:
                (pdir / name).write_text(pub)
            loc_text = loc.read_text() if loc.exists() else None
            same = (pub is not None and loc_text is not None and pub == loc_text)
            diff = "" if same or pub is None or loc_text is None else ds.unified_diff(pub, loc_text, f"published_{tag}/{name}", f"local/{name}")
            if diff:
                (dd / "local_vs_authoritative_metadata_diff" / f"{name}__published_{tag}_vs_local.diff").write_text(diff)
            meta_rows.append({"file": name, "release": tag, "published_present": pub is not None,
                              "local_present": loc_text is not None, "identical": same,
                              "n_changed_lines": sum(1 for ln in diff.splitlines() if ln[:1] in "+-" and ln[:3] not in ("+++", "---"))})
        if (pdir / "participants.tsv").exists():
            published_participants[tag] = ds.read_participants(pdir / "participants.tsv")
    _tsv(meta_rows, dd / "local_vs_published_metadata.tsv")
    log.info("A2 metadata comparison done")

    rels = ds.manifest_scope(paths.bids_root, str(paths.freesurfer.relative_to(paths.bids_root)),
                             str(paths.rcps.relative_to(paths.bids_root)), str(paths.petprep.relative_to(paths.bids_root)))
    manifest = ds.write_manifest(paths.bids_root, rels, dd / "source_manifest.tsv")
    manifest_hash = hashlib.sha256((dd / "source_manifest.tsv").read_bytes()).hexdigest()
    log.info("A4 manifest: %d files, sha256 %s", len(manifest), manifest_hash)

    trees = {tag: ds.published_tree(repo, tag) for tag in tags}
    ref = tags[0]
    annexed = [r for r in rels if r in trees[ref] and trees[ref][r]["mode"] == "120000"]
    targets = ds.published_link_targets(repo, ref, annexed)
    ver = ds.verify_against_published(paths.bids_root, rels, trees[ref], targets)
    for row in ver:
        for tag in tags[1:]:
            a, b = trees[ref].get(row["relpath"]), trees[tag].get(row["relpath"])
            row[f"same_blob_in_{tag}"] = (a is not None and b is not None and a["sha"] == b["sha"])
    local_sha = {m["relpath"]: m["sha256"] for m in manifest}
    for root in paths.comparison_roots:
        for row in ver:
            rel = row["relpath"]
            if rel.startswith("derivatives/") and (Path(root) / rel).exists():
                from ..runrecord import sha256_file
                row[f"identical_in_{Path(root).name}"] = sha256_file(Path(root) / rel) == local_sha[rel]
            else:
                row[f"identical_in_{Path(root).name}"] = None
    _tsv(ver, dd / "published_verification.tsv")
    (dd / "published" / f"annex_link_targets_{ref}.json").write_text(json.dumps(targets, indent=1))
    log.info("A2 file verification vs %s: %d/%d match", ref, sum(bool(r["match"]) for r in ver), len(ver))

    local_participants = ds.read_participants(paths.bids_root / "participants.tsv")
    elig = ds.eligibility(paths.bids_root, paths.freesurfer, paths.rcps, conditions, local_participants,
                          published_participants)
    _tsv(elig, dd / "subject_eligibility.tsv")
    log.info("A5 eligibility: %d subjects", len(elig))

    # ---------------- Phase B/C baseline (all subjects with complete inputs, incl. SP06)
    subjects = [r["subject_id"] for r in elig if r["required_inputs_complete"]]
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(_baseline_worker, [(s, paths, cfg, conditions, run_dir) for s in subjects]):
            log.info("baseline done %s", res["subject"])
            results.append(res)
    cat = lambda key: [r for res in results for r in res[key]]  # noqa: E731
    _tsv(cat("geometry"), run_dir / "geometry" / "image_geometry.tsv")
    _tsv(cat("affine_checks"), run_dir / "geometry" / "affine_checks.tsv")
    (run_dir / "geometry" / "coordinate_provenance.json").write_text(
        json.dumps([res["provenance"] for res in results], indent=2, default=_json_default))
    _tsv(cat("roi_counts"), run_dir / "labels" / "roi_voxel_counts.tsv")
    _tsv(cat("label_integrity"), run_dir / "labels" / "label_integrity.tsv")
    _tsv(cat("lr"), run_dir / "labels" / "left_right_check.tsv")
    _tsv(cat("zeros_by_tissue"), run_dir / "labels" / "zeros_by_tissue.tsv")
    _tsv(cat("alignment"), run_dir / "alignment" / "quantitative_metrics.tsv")
    _tsv(cat("profiles"), run_dir / "alignment" / "perturbation_profiles.tsv")
    log.info("baseline pass complete; tables written")

    # ---------------- C7 historical comparison (strictly after the baseline pass)
    if not args.skip_historical and paths.historical_finaltry is not None:
        hres = []
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for res in ex.map(_historical_worker, [(s, paths, cfg, conditions, run_dir, paths.historical_finaltry)
                                                   for s in subjects]):
                hres.append(res)
        _tsv([r for res in hres for r in res["historical"]], run_dir / "alignment" / "historical_bbregister_comparison.tsv")
        log.info("historical comparison complete")

    write_run_metadata(run_dir, argv=sys.argv, config={"qc": cfg, "paths_file": Path(args.paths).name}, seeds={},
                       inputs={"bids_root": str(paths.bids_root), "source_manifest_sha256": manifest_hash,
                               "n_manifest_files": len(manifest),
                               "comparison_roots": [str(p) for p in paths.comparison_roots],
                               "historical_finaltry": str(paths.historical_finaltry)},
                       provenance=prov, extra={"status": "completed", "subjects_processed": subjects})
    log.info("done")
    return run_dir


if __name__ == "__main__":
    main()
