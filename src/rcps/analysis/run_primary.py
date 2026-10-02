"""Production P1 entry point over the saved canonical panel; never rebuilds or reads raw data.

Usage: python -m rcps.analysis.run_primary observed
       python -m rcps.analysis.run_primary permutation --observed-run outputs/<observed-run>
The second mode requires a completed observed run from the same code commit and inputs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

from ..config import REPO_ROOT, load_paths, load_yaml
from ..panel.assemble import CanonicalPanel, panel_from_long_table, read_table_tsv
from ..panel.build import ANALYSIS_CONFIG, frozen_spec_provenance, panel_manifest
from ..panel.spec import canonical_rois, require_frozen_primary_contract
from ..provenance import canonical_json_sha256
from ..qc.verify_canonical import CANONICAL_CONFIG, load_canonical
from ..runrecord import create_run_dir, sha256_file, write_run_metadata
from .cv import primary_loso, summarize_loso
from .permutation import frozen_scheme, generate_assignments, require_frozen_scheme, run_permutation_test, validate_workers

PANEL_DIR = REPO_ROOT / "outputs" / "20260930-175425_panel_62eb246" / "panel"
SCHEMA = "rcps-primary-run/1"


def require_clean_tree() -> str:
    """Fail closed on Git errors, an unborn HEAD, or any tracked/untracked change."""
    def git(*args: str) -> str:
        return subprocess.run(["git", "--no-optional-locks", "-C", str(REPO_ROOT), *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    commit = git("rev-parse", "--verify", "HEAD^{commit}")
    status = git("status", "--porcelain", "--untracked-files=all")
    if status:
        raise RuntimeError(f"primary analysis requires a clean committed Git worktree:\n{status}")
    return commit


def _equal(got, expected, what: str) -> None:
    if got != expected:
        raise ValueError(f"{what} mismatch")


def load_panel_artifact(panel_dir: Path) -> tuple[CanonicalPanel, dict, dict, dict]:
    """Reconstruct through the panel API and check all manifest fields before any modeling.

    Canonical verification is inherited from the panel build, not represented as a fresh
    verification of raw data. Only repository configuration and saved artifacts are read.
    """
    frozen_spec_provenance()  # tag anchor and byte-for-byte working spec/config check
    cfg = load_yaml(ANALYSIS_CONFIG)
    require_frozen_primary_contract(cfg)
    canonical = load_canonical()
    subjects = tuple(cfg["cohort"]["primary"]["subjects"])
    _equal(list(subjects), canonical["expected_participants"], "canonical subject roster")
    rois = canonical_rois(cfg)
    conditions = tuple(cfg["target"]["conditions"])
    manifest_path = panel_dir / "panel_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    long_path = panel_dir / "long_table.tsv"
    condition_path = panel_dir / "condition_roi_values.tsv"
    # Check physical files, then independently reconstruct and hash the actual arrays.
    for key, path in (("long_table_tsv", long_path), ("condition_table_tsv", condition_path)):
        _equal(sha256_file(path), manifest["content_sha256"][key], f"panel {key}")
    long_table = read_table_tsv(long_path)
    cond = read_table_tsv(condition_path)
    panel = panel_from_long_table(long_table, subjects, rois, conditions)
    _equal(panel.x.shape, (18, 68, 2), "primary X dimensions")
    _equal(panel.y.shape, (18, 68), "primary Y dimensions")
    expected = panel_manifest(panel, rois, long_table, cond, manifest["sources"], canonical, cfg)
    for key, value in expected.items():
        _equal(manifest.get(key), value, f"panel manifest {key}")
    _equal(len(cond), 18 * 68 * len(conditions), "condition table rows")

    source_path = panel_dir.parent / "logs" / "run_metadata.json"
    source = json.loads(source_path.read_text())
    _equal(source["panel_manifest_sha256"], canonical_json_sha256(manifest), "build manifest checksum")
    if not (source["usable_for_reported_results"] and source["git"]["has_commits"]
            and not source["git"]["dirty"] and source["git"]["sha"]):
        raise ValueError("panel build must have clean committed provenance")
    prov = source["provenance"]
    verifier = prov["canonical_verifier"]
    if not (verifier["ran"] and verifier["PASS"] and verifier["require_git"]
            and verifier["n_ok"] == verifier["n_expected"] > 0):
        raise ValueError("panel build lacks successful canonical verification with Git required")
    dataset = prov["dataset"]
    for key, value in (("commit", canonical["release_commit"]), ("tag", canonical["release_tag"]),
                       ("accession", canonical["accession"]), ("clean", True), ("head_is_release", True)):
        _equal(dataset.get(key), value, f"panel build dataset {key}")
    _equal(prov["expected_manifest"]["sha256"], manifest["dataset"]["expected_manifest_sha256"],
           "build expected manifest")
    _equal(prov["config_hashes"]["analysis"]["sha256"], manifest["spec"]["analysis_yaml_sha256"],
           "build analysis config")
    files = {p.name: {"path": str(p.resolve()), "sha256": sha256_file(p)}
             for p in (manifest_path, long_path, condition_path, source_path)}
    return panel, manifest, source, files


def _json_value(value):
    """Portable JSON: infinity penalty is 'inf'; undefined descriptive numbers are null."""
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, dict):
        return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "inf" if value == math.inf else None
    return value


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(_json_value(value), indent=2, allow_nan=False) + "\n")


def require_same_t(observed: float, other: float) -> None:
    """Exact float equality, including the sign of zero; never a statistical tolerance."""
    if not (math.isfinite(observed) and math.isfinite(other)) or observed.hex() != other.hex():
        raise ValueError("observed and permutation T_obs mismatch (exact agreement required)")


def load_observed_reference(run_dir: Path, identity: dict) -> tuple[float, dict]:
    path = run_dir / "summary.json"
    summary = json.loads(path.read_text())
    metadata_path = run_dir / "logs" / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text())
    _equal(summary.get("schema"), SCHEMA, "observed schema")
    _equal(summary.get("mode"), "observed", "observed mode")
    _equal(summary.get("identity"), identity, "observed code/panel/spec identity")
    _equal(metadata.get("status"), "complete", "observed completion")
    _equal(metadata.get("usable_for_reported_results"), True, "observed reportability")
    _equal(metadata["git"]["sha"], identity["code_commit"], "observed metadata commit")
    _equal(metadata["artifact_sha256"]["summary.json"], sha256_file(path), "observed summary checksum")
    t = float(summary["T_obs"])
    _equal(t.hex(), summary["T_obs_hex"], "observed exact T encoding")
    return t, {"run_dir": str(run_dir.resolve()), "summary_sha256": sha256_file(path),
               "metadata_sha256": sha256_file(metadata_path)}


def run_primary(mode: str, *, observed_run: Path | None = None, argv: list[str] | None = None,
                workers: int | None = None) -> Path:
    """Run only the fixed production panel and scheme. Scientific CLI overrides do not exist."""
    if mode not in ("observed", "permutation"):
        raise ValueError("mode must be observed or permutation")
    if (mode == "permutation") != (observed_run is not None):
        raise ValueError("--observed-run is required only for permutation mode")
    if mode == "observed" and workers is not None:
        raise ValueError("workers is only available for permutation mode")
    worker_count = 1 if workers is None else workers
    validate_workers(worker_count)
    commit = require_clean_tree()
    panel, manifest, source, inputs = load_panel_artifact(PANEL_DIR)
    frozen = frozen_spec_provenance()
    cfg = load_yaml(ANALYSIS_CONFIG)
    scheme = require_frozen_scheme(frozen_scheme())
    identity = {"code_commit": commit, "panel_manifest_sha256": canonical_json_sha256(manifest),
                **frozen}
    reference = None
    expected_t = None
    if observed_run is not None:
        expected_t, reference = load_observed_reference(observed_run, identity)

    # The same observed API is used in both modes; fail before the long null evaluation.
    folds = primary_loso(panel.subject_ids, panel.x, panel.y)
    observed = summarize_loso(folds)
    if expected_t is not None:
        require_same_t(expected_t, observed.t)
    summary = {"schema": SCHEMA, "mode": mode, "identity": identity, "T_obs": observed.t,
               "T_obs_hex": observed.t.hex(), "mean_baseline_mse": observed.mean_baseline_mse,
               "mean_ridge_mse": observed.mean_ridge_mse,
               "descriptive": asdict(observed), "observed_reference": reference}
    assignments = None
    result = None
    if mode == "permutation":
        assignments = generate_assignments(scheme)
        result = run_permutation_test(panel.subject_ids, panel.x, panel.y, assignments, workers=worker_count)
        require_same_t(observed.t, result.t_obs)
        summary.update({"K": result.k, "B": result.b, "p": result.p_value,
                        "monte_carlo": asdict(result.monte_carlo),
                        "assignment_sha256": result.assignments_sha256, "numpy_version": result.numpy_version,
                        "scheme": scheme.provenance(), "n_evaluations": result.n_evaluations,
                        "n_cache_hits": result.n_cache_hits, "execution": {"workers": worker_count}})

    # Never publish completed reportable results if code or inputs changed during computation.
    _equal(require_clean_tree(), commit, "code commit during analysis")
    for entry in inputs.values():
        _equal(sha256_file(Path(entry["path"])), entry["sha256"], "panel input during analysis")
    out = create_run_dir(load_paths().outputs_root, f"primary-{mode}")
    _write_json(out / "summary.json", summary)
    with (out / "outer_folds.tsv").open("w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(["subject_id", "selected_lambda", "baseline_mse", "ridge_mse", "D_s"])
        for f in folds:
            writer.writerow([f.subject_id, f.selected_lambda, f.baseline_mse, f.ridge_mse, f.d_s])
    # Includes predictions, preprocessing, slopes, inner losses/ranks, zero-scale events,
    # training/validation indices and the fixed candidate grid for all observed outer folds.
    _write_json(out / "fold_diagnostics.json", {"folds": [asdict(f) for f in folds]})
    if result is not None and assignments is not None:
        np.save(out / "null_statistics.npy", result.null, allow_pickle=False)
        np.save(out / "assignments.npy", assignments.donors, allow_pickle=False)
    artifacts = {p.name: sha256_file(p) for p in out.iterdir() if p.is_file()}
    provenance = {"frozen_spec": frozen, "panel_build": source, "panel_manifest": manifest,
                  "canonical_verifier": {"source": "saved panel build", **source["provenance"]["canonical_verifier"]},
                  "dataset": source["provenance"]["dataset"],
                  "config_hashes": {"analysis": sha256_file(ANALYSIS_CONFIG),
                                    "canonical_dataset": sha256_file(CANONICAL_CONFIG)},
                  "resolved_config_sha256": canonical_json_sha256(cfg)}
    _equal(require_clean_tree(), commit, "code commit before report publication")
    write_run_metadata(out, argv=argv if argv is not None else sys.argv, config=cfg,
                       seeds={"permutation": scheme.seed} if mode == "permutation" else {},
                       inputs=inputs, provenance=provenance,
                       extra={"status": "complete", "mode": mode, "identity": identity,
                              "artifact_sha256": artifacts, "observed_reference": reference,
                              "execution": {"workers": worker_count} if mode == "permutation" else {}})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("observed", "permutation"))
    parser.add_argument("--observed-run", type=Path, help="completed observed run; required for permutation")
    parser.add_argument("--workers", type=int, help="permutation evaluation processes (default: 1)")
    args = parser.parse_args(argv)
    if args.workers is not None and (args.mode != "permutation" or args.workers < 1):
        parser.error("--workers requires permutation mode and a positive integer")
    if (args.mode == "permutation") != (args.observed_run is not None):
        parser.error("--observed-run is required only for permutation mode")
    out = run_primary(args.mode, observed_run=args.observed_run, workers=args.workers,
                      argv=sys.argv if argv is None else ["rcps.analysis.run_primary", *argv])
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
