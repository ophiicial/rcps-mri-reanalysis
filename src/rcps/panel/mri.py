"""Primary MRI features from FreeSurfer ?h.aparc.stats (curator recon-all; analysis_plan §6).

Thickness is ThickAvg (mm, untransformed). Area is the white-surface SurfArea (mm²); the model-facing
feature is ln(area / 1 mm²) with the natural log (never log1p). No standardisation happens here.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from .spec import ROI

REQUIRED_UNITS = {"ThickAvg": "mm", "SurfArea": "mm^2"}


def _header(lines: list[str]) -> dict[str, str]:
    out = {}
    for ln in lines:
        body = ln[1:].strip()
        if not body:
            continue
        key, _, value = body.partition(" ")
        out.setdefault(key, value.strip())
    return out


def parse_aparc_stats(text: str, subject: str, hemi: str, rois: Sequence[ROI]) -> list[dict]:
    """Return one row per ROI of `hemi` in roster order: roi, thickness_mm, area_mm2."""
    lines = text.splitlines()
    comments = [ln for ln in lines if ln.startswith("#")]
    head = _header(comments)
    if head.get("hemi") != hemi or head.get("subjectname") != subject:
        raise ValueError(f"{subject} {hemi}.aparc.stats: header hemi/subject mismatch "
                         f"({head.get('hemi')!r}, {head.get('subjectname')!r})")
    if not head.get("AnnotationFile", "").endswith(f"{hemi}.aparc.annot"):
        raise ValueError(f"{subject} {hemi}.aparc.stats: not the Desikan-Killiany aparc annotation")
    cmd = head.get("cmdline", "").split()
    if cmd[-3:] != [subject, hemi, "white"]:
        raise ValueError(f"{subject} {hemi}.aparc.stats: expected white-surface statistics, cmdline ends {cmd[-3:]}")

    units = {}
    for ln in comments:
        parts = ln[1:].split()
        if len(parts) >= 4 and parts[0] == "TableCol" and parts[2] in ("ColHeader", "Units"):
            units.setdefault(parts[1], {})[parts[2]] = " ".join(parts[3:])
    by_header = {u.get("ColHeader"): u.get("Units") for u in units.values()}
    for column, unit in REQUIRED_UNITS.items():
        if by_header.get(column) != unit:
            raise ValueError(f"{subject} {hemi}.aparc.stats: {column} units {by_header.get(column)!r} != {unit!r}")

    col_lines = [ln for ln in comments if ln[1:].split()[:1] == ["ColHeaders"]]
    if len(col_lines) != 1:
        raise ValueError(f"{subject} {hemi}.aparc.stats: expected one ColHeaders line")
    columns = col_lines[0][1:].split()[1:]
    i_name, i_area, i_thick = (columns.index(c) for c in ("StructName", "SurfArea", "ThickAvg"))

    expected = {r.structure: r for r in rois if r.hemisphere == hemi}
    seen: dict[str, dict] = {}
    for ln in lines:
        if ln.startswith("#") or not ln.strip():
            continue
        fields = ln.split()
        if len(fields) != len(columns):
            raise ValueError(f"{subject} {hemi}.aparc.stats: malformed row {ln!r}")
        name = fields[i_name]
        if name not in expected:
            raise ValueError(f"{subject} {hemi}.aparc.stats: non-canonical structure {name!r}")
        if name in seen:
            raise ValueError(f"{subject} {hemi}.aparc.stats: duplicate structure {name!r}")
        thickness, area = float(fields[i_thick]), float(fields[i_area])
        if not (math.isfinite(thickness) and math.isfinite(area)):
            raise ValueError(f"{subject} {expected[name].name}: nonfinite thickness/area")
        if area <= 0:
            raise ValueError(f"{subject} {expected[name].name}: nonpositive area ({area})")
        seen[name] = {"roi": expected[name].name, "thickness_mm": thickness, "area_mm2": area}
    missing = sorted(set(expected) - set(seen))
    if missing:
        raise ValueError(f"{subject} {hemi}.aparc.stats: missing ROIs {missing}")
    return [seen[r.structure] for r in rois if r.hemisphere == hemi]


def ln_area(area_mm2) -> np.ndarray:
    """ln(area / 1 mm²). Natural log of the raw area; nonpositive or nonfinite input fails."""
    a = np.asarray(area_mm2, dtype=np.float64)
    if not np.all(np.isfinite(a)) or np.any(a <= 0):
        raise ValueError("area must be finite and > 0 before the log transform")
    return np.log(a)
