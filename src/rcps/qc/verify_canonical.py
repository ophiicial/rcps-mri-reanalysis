"""Verify a canonical ds004733 copy against configs/canonical_dataset.yaml and its expected-hash manifest.

Usage: PYTHONPATH=src python -m rcps.qc.verify_canonical [--require-git]
Read-only on the dataset. Writes outputs/<ts>_verify-canonical_<sha>/ with a per-file table and summary.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from ..config import REPO_ROOT, load_paths, load_yaml
from ..provenance import dataset_git_state, run_provenance
from ..runrecord import create_run_dir, sha256_file, write_run_metadata

CANONICAL_CONFIG = REPO_ROOT / "configs" / "canonical_dataset.yaml"


def load_canonical(path: Path = CANONICAL_CONFIG) -> dict:
    cfg = load_yaml(path)
    cfg["expected_manifest_path"] = (REPO_ROOT / cfg["expected_manifest"]).resolve()
    return cfg


def read_expected(path: Path | None = None) -> list[dict]:
    path = path or load_canonical()["expected_manifest_path"]
    with open(path) as fh:
        lines = [ln for ln in fh if not ln.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def check_files(root: Path, expected: list[dict]) -> list[dict]:
    rows = []
    for e in expected:
        p = Path(root) / e["relpath"]
        if not p.exists():
            rows.append({**e, "status": "MISSING"})
            continue
        size_ok = p.stat().st_size == int(e["bytes"])
        rows.append({**e, "status": "OK" if size_ok and sha256_file(p) == e["sha256"] else "MISMATCH"})
    return rows


def participants_ok(root: Path, expected_ids) -> bool:
    with open(Path(root) / "participants.tsv", newline="") as fh:
        ids = {r["participant_id"] for r in csv.DictReader(fh, delimiter="\t")}
    return ids == set(expected_ids)


def verify(root: Path, canonical: dict, require_git: bool) -> tuple[dict, list[dict]]:
    """Return (summary, per-file rows). Pure read-only check."""
    rows = check_files(root, read_expected(canonical["expected_manifest_path"]))
    g = dataset_git_state(root)
    head_is_release = g["commit"] == canonical["release_commit"]
    summary = {"n_expected": len(rows), "n_ok": sum(r["status"] == "OK" for r in rows),
               "n_missing": sum(r["status"] == "MISSING" for r in rows),
               "n_mismatch": sum(r["status"] == "MISMATCH" for r in rows),
               "participants_match": participants_ok(root, canonical["expected_participants"]),
               "release_tag_expected": canonical["release_tag"], "release_commit_expected": canonical["release_commit"],
               "git": {**g, "head_is_release": head_is_release}, "require_git": require_git}
    summary["PASS"] = bool(summary["n_ok"] == len(rows) and summary["participants_match"]
                           and (not require_git or (head_is_release and g["clean"])))
    return summary, rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-git", action="store_true",
                    help="also require a git/DataLad checkout at the release commit with a clean status")
    args = ap.parse_args(argv)
    P = load_paths()
    canonical = load_canonical()
    run_dir = create_run_dir(P.outputs_root, "verify-canonical")
    summary, rows = verify(P.bids_root, canonical, args.require_git)
    with open(run_dir / "file_checks.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    prov = run_provenance(P.bids_root, canonical, config_files={"canonical_dataset": CANONICAL_CONFIG},
                          resolved_config={"require_git": args.require_git}, verifier_summary=summary)
    write_run_metadata(run_dir, argv=sys.argv, config={"require_git": args.require_git}, seeds={},
                       inputs={"bids_root": str(P.bids_root)}, provenance=prov, extra={"summary": summary})
    print(json.dumps(summary, indent=2))
    return 0 if summary["PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
