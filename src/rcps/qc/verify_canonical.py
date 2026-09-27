"""Verify a canonical ds004733 v1.0.1 copy against configs/ds004733_v1.0.1_expected_sha256.tsv.

Usage: PYTHONPATH=src python -m rcps.qc.verify_canonical [--require-git]
Read-only on the dataset. Writes outputs/<ts>_verify-canonical_<sha>/ with a per-file table and summary.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from ..config import REPO_ROOT, load_paths
from ..runrecord import create_run_dir, sha256_file, write_run_metadata

EXPECTED = REPO_ROOT / "configs" / "ds004733_v1.0.1_expected_sha256.tsv"
RELEASE_COMMIT = "badd0108199e5b9f85451d317e472e5ee6105464"
EXPECTED_PARTICIPANTS = {f"sub-SP{n:02d}" for n in (2, 3, 5, 6, 9, 10, 11, 12, 14, 15, 16, 18, 20, 21, 22, 23, 26, 28)}


def read_expected(path: Path = EXPECTED) -> list[dict]:
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


def git_checks(root: Path) -> dict:
    def run(*a):
        r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
        return r.returncode, r.stdout.strip()

    rc, head = run("rev-parse", "HEAD")
    _, status = run("status", "--porcelain")
    return {"is_git": rc == 0, "head": head if rc == 0 else None, "head_is_release": head == RELEASE_COMMIT,
            "clean": rc == 0 and status == ""}


def participants_ok(root: Path) -> bool:
    with open(Path(root) / "participants.tsv", newline="") as fh:
        ids = {r["participant_id"] for r in csv.DictReader(fh, delimiter="\t")}
    return ids == EXPECTED_PARTICIPANTS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-git", action="store_true",
                    help="also require a git/DataLad checkout at the 1.0.1 release commit with a clean status")
    args = ap.parse_args(argv)
    P = load_paths()
    run_dir = create_run_dir(P.outputs_root, "verify-canonical")
    rows = check_files(P.bids_root, read_expected())
    with open(run_dir / "file_checks.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    g = git_checks(P.bids_root)
    summary = {"n_expected": len(rows), "n_ok": sum(r["status"] == "OK" for r in rows),
               "n_missing": sum(r["status"] == "MISSING" for r in rows),
               "n_mismatch": sum(r["status"] == "MISMATCH" for r in rows),
               "participants_match_v1_0_1": participants_ok(P.bids_root), "git": g}
    passed = (summary["n_ok"] == len(rows) and summary["participants_match_v1_0_1"]
              and (not args.require_git or (g["head_is_release"] and g["clean"])))
    summary["PASS"] = passed
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    write_run_metadata(run_dir, argv=sys.argv, config={"expected": str(EXPECTED.relative_to(REPO_ROOT))}, seeds={},
                       inputs={"bids_root": str(P.bids_root)}, extra={"summary": summary})
    print(json.dumps(summary, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
