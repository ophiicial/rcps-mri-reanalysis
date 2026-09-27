"""Native run provenance: repository state, canonical-dataset state, verifier result, manifest and config hashes.

Every scientific / QC run records `run_provenance(...)` under the `provenance` key of logs/run_metadata.json.
All paths recorded here are derived at run time; no machine-specific path is stored in code.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .config import REPO_ROOT
from .runrecord import git_state, sha256_file


def _git(root: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def dataset_git_state(root: Path) -> dict:
    """Tag/commit/clean status of the dataset checkout at `root` (a DataLad/git-annex clone)."""
    rc, commit = _git(root, "rev-parse", "HEAD")
    if rc != 0:
        return {"is_git": False, "commit": None, "tag": None, "tags_at_head": [], "clean": False, "n_status_entries": None}
    _, tags = _git(root, "tag", "--points-at", "HEAD")
    rc_t, exact = _git(root, "describe", "--tags", "--exact-match")
    _, status = _git(root, "status", "--porcelain")
    lines = [ln for ln in status.splitlines() if ln]
    return {"is_git": True, "commit": commit, "tag": exact if rc_t == 0 else None,
            "tags_at_head": sorted(t for t in tags.splitlines() if t), "clean": not lines,
            "n_status_entries": len(lines)}


def canonical_json_sha256(obj) -> str:
    """SHA-256 of a JSON-serialisable object with sorted keys (order-independent)."""
    data = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(data).hexdigest()


def _rel(p: Path) -> str:
    p = Path(p).resolve()
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return p.name  # outside the repo (e.g. tests): record the name only, never an absolute path


def run_provenance(bids_root: Path, canonical: dict, config_files: dict[str, Path], resolved_config: dict,
                   verifier_summary: dict | None = None, run_verifier: bool = False) -> dict:
    """Assemble the provenance block. If no verifier summary is given and run_verifier=True, run it (read-only)."""
    if verifier_summary is None and run_verifier:
        from .qc.verify_canonical import verify  # local import avoids a cycle
        verifier_summary, _ = verify(bids_root, canonical, require_git=True)
    manifest = Path(canonical["expected_manifest_path"])
    ds = dataset_git_state(bids_root)
    return {
        "repository": git_state(),
        "dataset": {"accession": canonical.get("accession"), "release_tag_expected": canonical.get("release_tag"),
                    "release_commit_expected": canonical.get("release_commit"), **ds,
                    "head_is_release": ds["commit"] == canonical.get("release_commit")},
        "canonical_verifier": ({"ran": True, "PASS": verifier_summary.get("PASS"),
                                "require_git": verifier_summary.get("require_git"),
                                "n_ok": verifier_summary.get("n_ok"), "n_expected": verifier_summary.get("n_expected")}
                               if verifier_summary is not None else {"ran": False}),
        "expected_manifest": {"path": _rel(manifest), "sha256": sha256_file(manifest)},
        "config_hashes": {name: {"path": _rel(p), "sha256": sha256_file(p)} for name, p in config_files.items()},
        "resolved_config_sha256": canonical_json_sha256(resolved_config),
    }
