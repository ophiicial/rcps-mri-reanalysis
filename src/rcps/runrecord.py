"""Run-specific output directories and machine-readable run records (AGENTS.md §3)."""
from __future__ import annotations

import datetime as _dt
import hashlib
import importlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from .config import REPO_ROOT

TRACKED_PACKAGES = ("numpy", "scipy", "pandas", "sklearn", "nibabel", "matplotlib", "yaml")


def git_state(repo: Path = REPO_ROOT) -> dict:
    def run(*args):
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return r.returncode, r.stdout.strip()

    rc, sha = run("rev-parse", "HEAD")
    _, status = run("status", "--porcelain")
    return {
        "sha": sha if rc == 0 else None,
        "short_sha": sha[:7] if rc == 0 else None,
        "has_commits": rc == 0,
        "dirty": bool(status),
        "status_porcelain": status.splitlines(),
    }


def package_versions() -> dict:
    out = {"python": sys.version.replace("\n", " "), "executable": sys.executable, "platform": platform.platform()}
    for name in TRACKED_PACKAGES:
        try:
            out[name] = importlib.import_module(name).__version__
        except Exception as exc:  # recorded, not hidden
            out[name] = f"UNAVAILABLE: {type(exc).__name__}"
    return out


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def create_run_dir(outputs_root: Path, run_name: str, now: _dt.datetime | None = None) -> Path:
    """Create outputs/<YYYYMMDD-HHMMSS>_<run-name>_<shortsha|nocommit>/; refuse to reuse an existing dir."""
    now = now or _dt.datetime.now()
    g = git_state()
    tag = g["short_sha"] or "nocommit"
    run_dir = Path(outputs_root) / f"{now:%Y%m%d-%H%M%S}_{run_name}_{tag}"
    run_dir.mkdir(parents=True, exist_ok=False)  # raises if it already exists
    return run_dir


def write_run_metadata(run_dir: Path, *, argv: list[str], config: dict, seeds: dict | None,
                       inputs: dict, extra: dict | None = None) -> Path:
    g = git_state()
    record = {
        "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "git": g,
        "usable_for_reported_results": bool(g["has_commits"] and not g["dirty"]),
        "argv": argv,
        "config": config,
        "seeds": seeds or {},
        "environment": package_versions(),
        "inputs": inputs,
        "output_dir": str(run_dir),
    }
    if extra:
        record.update(extra)
    path = Path(run_dir) / "logs" / "run_metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, default=str))
    return path
