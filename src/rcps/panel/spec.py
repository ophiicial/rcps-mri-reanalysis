"""Frozen v3.0 panel contract: rosters, conditions, features and target rule read from config.

The panel layer implements exactly the analysis_plan v3.0 primary choices (§§3-6). Any config
value that differs from them is a spec change and fails here rather than being interpreted.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from ..labels import dk_cortical_labels

SPEC_VERSION = "3.0"
FEATURE_NAMES = ("thickness", "ln_area")
PRIMARY_FEATURES = (
    {"name": "thickness", "source": "ThickAvg", "transform": "none", "units": "mm"},
    {"name": "ln_area", "source": "SurfArea", "transform": "ln_over_1mm2", "require_positive": True},
)
PRIMARY_TARGET = {
    "conditions": ["Awake", "SleepDeprived", "Asleep"],
    "require_all_conditions": True,
    "condition_aggregation": "equal_weight_mean",
    "roi_value": "mean_all_label_voxels",
    "zero_handling": "include_exact_zeros",
    "nonfinite_or_negative_voxels": "fail",
    "units": "nmol/g/min",
}
PRIMARY_SPATIAL = {"registration": "none", "labels": "aparc+aseg",
                   "label_resampling": "nearest_neighbour_scanner_ras_header"}
TARGET_DEFINITION = ("equal-weight mean of the Awake, SleepDeprived and Asleep ROI means; each ROI mean is the "
                     "arithmetic mean of all label voxels on the supplied rCPS grid, exact zeros included")


@dataclass(frozen=True)
class ROI:
    index: int        # position on the ROI axis; also the fixed categorical code (analysis.yaml rois)
    code: int         # aparc+aseg label code
    name: str         # ctx-<hemi>-<name>
    hemisphere: str   # lh | rh
    structure: str    # aparc.stats StructName


def require_frozen_primary_contract(analysis_cfg: dict) -> None:
    """Fail unless the config carries exactly the v3.0 primary choices this module implements."""
    checks = {
        "spec_version": (analysis_cfg.get("spec_version"), SPEC_VERSION),
        "features.primary": (analysis_cfg["features"]["primary"], list(PRIMARY_FEATURES)),
        "features.nonfinite": (analysis_cfg["features"]["nonfinite"], "fail"),
        "features.pet_derived_features_allowed": (analysis_cfg["features"]["pet_derived_features_allowed"], False),
        "rois.n": (analysis_cfg["rois"]["n"], 68),
        "rois.categorical_mapping": (analysis_cfg["rois"]["categorical_mapping"], "dk_cortical_labels_order"),
        "spatial": (analysis_cfg["spatial"], PRIMARY_SPATIAL),
    }
    checks.update({f"target.{k}": (analysis_cfg["target"].get(k), v) for k, v in PRIMARY_TARGET.items()})
    bad = {k: got for k, (got, want) in checks.items() if got != want}
    if bad:
        raise ValueError(f"config departs from the frozen v3.0 primary contract implemented here: {bad}")


def _require_unique(values: Sequence[str], what: str) -> None:
    dup = sorted(v for v, n in Counter(values).items() if n > 1)
    if dup:
        raise ValueError(f"duplicate {what}: {dup}")


def canonical_subjects(analysis_cfg: dict, canonical_cfg: dict, participants: Sequence[str]) -> tuple[str, ...]:
    """Frozen primary roster, in frozen config order, after checking it against participants.tsv.

    Order is never discovered from the filesystem. `participants` is the participant_id column of the
    canonical participants.tsv.
    """
    frozen = tuple(analysis_cfg["cohort"]["primary"]["subjects"])
    _require_unique(frozen, "subjects in analysis.yaml cohort.primary")
    if len(frozen) != analysis_cfg["cohort"]["primary"]["n"]:
        raise ValueError("analysis.yaml cohort.primary: subject list length != n")
    if tuple(canonical_cfg["expected_participants"]) != frozen:
        raise ValueError("canonical_dataset.yaml expected_participants != analysis.yaml cohort.primary.subjects")
    if analysis_cfg["cohort"].get("qc_exclusions"):
        raise ValueError("qc_exclusions are not supported by the primary panel builder")
    validate_subject_ids(participants, frozen, "participants.tsv")
    return frozen


def validate_subject_ids(ids: Sequence[str], expected: Sequence[str], what: str) -> None:
    ids = list(ids)
    _require_unique(ids, f"subjects in {what}")
    missing, extra = sorted(set(expected) - set(ids)), sorted(set(ids) - set(expected))
    if missing or extra:
        raise ValueError(f"{what}: subject roster mismatch; missing={missing} extra={extra}")


def canonical_rois(analysis_cfg: dict) -> tuple[ROI, ...]:
    """The 68 DK cortical ROIs in the frozen `dk_cortical_labels()` order."""
    excluded = set(analysis_cfg["rois"]["exclude_codes"])
    rois = []
    for index, (code, name) in enumerate(dk_cortical_labels().items()):
        prefix, hemisphere, structure = name.split("-", 2)
        if prefix != "ctx" or hemisphere not in ("lh", "rh") or code in excluded:
            raise ValueError(f"non-cortical or excluded label in the cortical roster: {code} {name}")
        rois.append(ROI(index, code, name, hemisphere, structure))
    if len(rois) != analysis_cfg["rois"]["n"] or len({r.name for r in rois}) != len(rois):
        raise ValueError("canonical ROI roster must contain 68 unique ROIs")
    return tuple(rois)


def condition_column(condition: str) -> str:
    """'SleepDeprived' -> 'rcps_sleep_deprived'."""
    return "rcps_" + re.sub(r"(?<!^)(?=[A-Z])", "_", condition).lower()
