"""Canonical input resolution: only files listed in the committed v1.0.1 expected-hash manifest are readable.

Every returned file is hash-checked against that manifest at use time, so no historical table, merged CSV
or re-registered map can enter the panel, and a path that the manifest does not list fails explicitly.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..runrecord import sha256_file


@dataclass(frozen=True)
class SourceFile:
    relpath: str      # dataset-relative, as in the manifest
    path: Path
    sha256: str


class CanonicalSources:
    def __init__(self, bids_root: Path, manifest_rows: list[dict], freesurfer: Path, rcps: Path):
        self.bids_root = Path(bids_root).resolve()
        relpaths = [r["relpath"] for r in manifest_rows]
        if len(set(relpaths)) != len(relpaths):
            raise ValueError("expected manifest has duplicate relpaths")
        self._manifest = {r["relpath"]: r for r in manifest_rows}
        self.freesurfer_rel = self._inside(freesurfer, "freesurfer derivative")
        self.rcps_rel = self._inside(rcps, "rCPS derivative")

    def _inside(self, directory: Path, what: str) -> str:
        try:
            return Path(directory).resolve().relative_to(self.bids_root).as_posix()
        except ValueError:
            raise ValueError(f"{what} directory is outside the canonical bids_root; "
                             "only the canonical dataset may be used") from None

    def _contained(self, relpath: str) -> Path:
        """Reject absolute or escaping relpaths; the fully resolved file (symlinks followed) must lie in bids_root.

        git-annex content symlinks into the dataset's own .git/annex remain inside bids_root and are accepted.
        """
        rel = PurePosixPath(relpath)
        if rel.is_absolute() or Path(relpath).is_absolute() or ".." in rel.parts:
            raise ValueError(f"non-canonical source path (absolute or traversal): {relpath}")
        path = self.bids_root / rel
        if not path.resolve().is_relative_to(self.bids_root):
            raise ValueError(f"source resolves outside the canonical bids_root: {relpath}")
        return path

    def get(self, relpath: str) -> SourceFile:
        row = self._manifest.get(relpath)
        if row is None:
            raise ValueError(f"not a canonical v1.0.1 source (absent from expected manifest): {relpath}")
        path = self._contained(relpath)
        if not path.is_file():
            raise FileNotFoundError(f"canonical source missing on disk: {relpath}")
        digest = sha256_file(path)
        if digest != row["sha256"]:
            raise ValueError(f"canonical source hash mismatch: {relpath}")
        return SourceFile(relpath, path, digest)

    def aparc_stats(self, subject: str, hemi: str) -> SourceFile:
        return self.get(f"{self.freesurfer_rel}/{subject}/stats/{hemi}.aparc.stats")

    def aparc_aseg(self, subject: str) -> SourceFile:
        return self.get(f"{self.freesurfer_rel}/{subject}/mri/aparc+aseg.mgz")

    def rcps_map(self, subject: str, condition: str) -> SourceFile:
        """The single supplied rCPS statmap for subject x condition; ambiguity fails."""
        session = f"{self.rcps_rel}/{subject}/ses-{condition}"
        pattern = f"{session}/*_stat-rCPS_statmap.nii.gz"
        listed = sorted(p for p in self._manifest if fnmatch.fnmatch(p, pattern) and "/" not in p[len(session) + 1:])
        on_disk = sorted(p.relative_to(self.bids_root).as_posix()
                         for p in (self.bids_root / session).glob("*_stat-rCPS_statmap.nii.gz"))
        if len(listed) != 1 or on_disk != listed:
            raise ValueError(f"{subject} {condition}: expected exactly one canonical rCPS map; "
                             f"manifest={listed} disk={on_disk}")
        return self.get(listed[0])

    def rcps_sidecar(self, statmap: SourceFile) -> SourceFile:
        return self.get(statmap.relpath[:-len(".nii.gz")] + ".json")
