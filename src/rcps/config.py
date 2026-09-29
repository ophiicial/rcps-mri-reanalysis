"""Configuration loading. No machine-specific paths live in code."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve(p: str, base: Path) -> Path:
    path = Path(p).expanduser()
    return path if path.is_absolute() else (base / path)


def _resolve_optional(p: str | None, base: Path) -> Path | None:
    return None if p is None else _resolve(p, base)


@dataclass(frozen=True)
class Paths:
    bids_root: Path
    freesurfer: Path
    rcps: Path
    petprep: Path
    outputs_root: Path
    comparison_roots: tuple[Path, ...] = field(default_factory=tuple)
    historical_finaltry: Path | None = None


def load_yaml(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def load_paths(path: Path | str = REPO_ROOT / "configs" / "paths.local.yaml") -> Paths:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy configs/paths.example.yaml to configs/paths.local.yaml and fill it in."
        )
    cfg = load_yaml(path)
    if "<" in str(cfg.get("bids_root", "<")):
        raise ValueError("bids_root is still a placeholder in " + str(path))
    if not isinstance(cfg["bids_root"], str) or not cfg["bids_root"].strip():
        raise ValueError("bids_root must be a non-empty path string in " + str(path))
    bids = _resolve(cfg["bids_root"], REPO_ROOT)
    der = cfg.get("derivatives", {})
    return Paths(
        bids_root=bids,
        freesurfer=_resolve(der.get("freesurfer", "derivatives/freesurfer"), bids),
        rcps=_resolve(der.get("rcps", "derivatives/rCPS"), bids),
        petprep=_resolve(der.get("petprep", "derivatives/rcps-modified-petprep"), bids),
        outputs_root=_resolve(cfg.get("outputs_root", "outputs"), REPO_ROOT),
        comparison_roots=tuple(_resolve(p, REPO_ROOT) for p in cfg.get("comparison_roots") or []),
        historical_finaltry=_resolve_optional(cfg.get("historical_finaltry"), REPO_ROOT),
    )
