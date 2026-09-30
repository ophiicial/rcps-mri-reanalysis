"""Phase 3 synthetic tests: canonical panel construction and validation. No real data, no modelling."""
import copy
import hashlib
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
import pytest

from rcps.config import REPO_ROOT, load_yaml
from rcps.panel import build as pb
from rcps.panel.assemble import (CONDITION_COLUMNS, MRI_COLUMNS, array_sha256, build_long_table,
                                 panel_from_long_table, read_table_tsv, table_tsv, validate_long_table)
from rcps.panel.mri import ln_area, parse_aparc_stats
from rcps.panel.rcps_roi import roi_statistics
from rcps.panel.sources import CanonicalSources
from rcps.panel.spec import (canonical_rois, canonical_subjects, condition_column,
                             require_frozen_primary_contract)
from rcps.qc.verify_canonical import load_canonical

CFG = load_yaml(REPO_ROOT / "configs" / "analysis.yaml")
CANON = load_canonical()
SUBJECTS = tuple(CFG["cohort"]["primary"]["subjects"])
ROIS = canonical_rois(CFG)
CONDS = tuple(CFG["target"]["conditions"])


# ------------------------------------------------------------------ synthetic inputs
def stats_text(subject, hemi, values, *, surface="white", area_units="mm^2", annot="aparc", extra_rows=()):
    head = [
        "# Table of FreeSurfer cortical parcellation anatomical statistics",
        f"# cmdline mris_anatomical_stats -th3 -mgz -f ../stats/{hemi}.aparc.stats -b "
        f"-a ../label/{hemi}.{annot}.annot {subject} {hemi} {surface} ",
        "# anatomy_type surface", f"# subjectname {subject}", f"# hemi {hemi}",
        f"# AnnotationFile ../label/{hemi}.{annot}.annot",
        "# TableCol  3 ColHeader SurfArea", f"# TableCol  3 Units     {area_units}",
        "# TableCol  5 ColHeader ThickAvg ", "# TableCol  5 Units     mm",
        "# ColHeaders StructName NumVert SurfArea GrayVol ThickAvg ThickStd MeanCurv GausCurv FoldInd CurvInd",
    ]
    rows = [f"{name:<40} 100 {area} 1000 {thick} 0.5 0.1 0.02 1 0.5" for name, (area, thick) in values.items()]
    return "\n".join(head + rows + list(extra_rows)) + "\n"


def hemi_values(hemi, seed=0):
    rng = np.random.default_rng(seed)
    return {r.structure: (float(rng.integers(200, 5000)), round(float(rng.uniform(1.5, 3.5)), 3))
            for r in ROIS if r.hemisphere == hemi}


def synthetic_tables(n_subjects=4, seed=1):
    rng = np.random.default_rng(seed)
    subjects = SUBJECTS[:n_subjects]
    mri = pd.DataFrame([{"subject_id": s, "roi": r.name, "thickness_mm": float(rng.uniform(1.5, 3.5)),
                         "area_mm2": float(rng.uniform(200, 5000)), "source_relpath": f"stats/{s}"}
                        for s in subjects for r in ROIS], columns=MRI_COLUMNS)
    cond = pd.DataFrame([{"subject_id": s, "condition": c, "roi": r.name,
                          "rcps_roi_mean": float(rng.uniform(0.5, 3.0)), "n_voxels": 1000, "n_zero": 50,
                          "zero_fraction": 0.05, "source_relpath": f"rcps/{s}/{c}"}
                         for s in subjects for c in CONDS for r in ROIS], columns=CONDITION_COLUMNS)
    return subjects, mri, cond


# ------------------------------------------------------------------ frozen contract
def test_frozen_contract_accepts_config_and_rejects_departures():
    require_frozen_primary_contract(CFG)
    for path, value in [(("features", "primary", 1, "transform"), "log1p"),
                        (("target", "zero_handling"), "exclude_exact_zeros"),
                        (("target", "conditions"), ["Awake", "Asleep"]),
                        (("spatial", "registration"), "bbregister")]:
        cfg = copy.deepcopy(CFG)
        node = cfg
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        with pytest.raises(ValueError, match="frozen v3.0"):
            require_frozen_primary_contract(cfg)


# ------------------------------------------------------------------ A. subject roster
def test_canonical_roster_accepted_in_frozen_order():
    shuffled = list(reversed(SUBJECTS))
    assert canonical_subjects(CFG, CANON, shuffled) == SUBJECTS
    assert len(SUBJECTS) == 18 and len(set(SUBJECTS)) == 18


@pytest.mark.parametrize("participants", [
    SUBJECTS[:-1], (*SUBJECTS, "sub-SP99"), (*SUBJECTS, SUBJECTS[0]), (*SUBJECTS[:-1], "sub-SP99")])
def test_roster_missing_extra_duplicate_rejected(participants):
    with pytest.raises(ValueError, match="subject"):
        canonical_subjects(CFG, CANON, participants)


def test_roster_config_disagreement_rejected():
    canon = {**CANON, "expected_participants": list(reversed(SUBJECTS))}
    with pytest.raises(ValueError, match="expected_participants"):
        canonical_subjects(CFG, canon, SUBJECTS)


# ------------------------------------------------------------------ B. ROI roster
def test_canonical_roi_roster():
    assert len(ROIS) == 68 and [r.index for r in ROIS] == list(range(68))
    codes = [r.code for r in ROIS]
    assert codes == sorted(codes) and codes[0] == 1001 and codes[-1] == 2035
    assert not set(codes) & {1000, 1004, 2000, 2004}
    assert [r.hemisphere for r in ROIS] == ["lh"] * 34 + ["rh"] * 34
    assert all(r.name == f"ctx-{r.hemisphere}-{r.structure}" for r in ROIS)


def test_parse_stats_accepts_all_34_in_roster_order():
    values = hemi_values("rh")
    rows = parse_aparc_stats(stats_text("sub-SP02", "rh", dict(reversed(values.items()))), "sub-SP02", "rh", ROIS)
    assert [r["roi"] for r in rows] == [r.name for r in ROIS if r.hemisphere == "rh"]


@pytest.mark.parametrize("mutate, match", [
    (lambda v: v.pop("insula"), "missing"),
    (lambda v: v.update(unknown=(10.0, 1.0)), "non-canonical"),
    (lambda v: v.update(corpuscallosum=(10.0, 1.0)), "non-canonical"),
    (lambda v: v.update({"Left-Hippocampus": (10.0, 1.0)}), "non-canonical"),
])
def test_parse_stats_rejects_missing_or_noncanonical(mutate, match):
    values = hemi_values("lh")
    mutate(values)
    with pytest.raises(ValueError, match=match):
        parse_aparc_stats(stats_text("sub-SP02", "lh", values), "sub-SP02", "lh", ROIS)


def test_parse_stats_rejects_duplicate_structure():
    text = stats_text("sub-SP02", "lh", hemi_values("lh"), extra_rows=["insula 1 2 3 4 5 6 7 8 9"])
    with pytest.raises(ValueError, match="duplicate"):
        parse_aparc_stats(text, "sub-SP02", "lh", ROIS)


@pytest.mark.parametrize("kwargs, subject, hemi, match", [
    ({"surface": "pial"}, "sub-SP02", "lh", "white"),
    ({"area_units": "cm^2"}, "sub-SP02", "lh", "units"),
    ({"annot": "aparc.DKTatlas"}, "sub-SP02", "lh", "Desikan"),
    ({}, "sub-SP03", "lh", "mismatch"),
    ({}, "sub-SP02", "rh", "mismatch"),
])
def test_parse_stats_rejects_wrong_source_or_units(kwargs, subject, hemi, match):
    text = stats_text("sub-SP02", "lh", hemi_values("lh"), **kwargs)
    with pytest.raises(ValueError, match=match):
        parse_aparc_stats(text, subject, hemi, ROIS)


def test_long_table_rejects_noncanonical_roi_key():
    subjects, mri, cond = synthetic_tables()
    mri.loc[0, "roi"] = "Left-Hippocampus"
    with pytest.raises(ValueError, match="MRI table"):
        build_long_table(mri, cond, subjects, ROIS, CONDS)


# ------------------------------------------------------------------ C. MRI transformation
def test_thickness_preserved_and_natural_log_area_not_log1p():
    values = hemi_values("lh")
    values["insula"] = (1.0, 2.718)
    rows = {r["roi"]: r for r in parse_aparc_stats(stats_text("sub-SP02", "lh", values), "sub-SP02", "lh", ROIS)}
    assert rows["ctx-lh-insula"]["thickness_mm"] == 2.718
    assert rows["ctx-lh-insula"]["area_mm2"] == 1.0
    assert ln_area([1.0])[0] == 0.0 != np.log1p(1.0)
    subjects, mri, cond = synthetic_tables()
    long = build_long_table(mri, cond, subjects, ROIS, CONDS)
    np.testing.assert_array_equal(long["thickness_mm"], mri["thickness_mm"])
    np.testing.assert_array_equal(long["ln_area"], np.log(mri["area_mm2"]))
    assert not np.allclose(long["ln_area"], np.log1p(mri["area_mm2"]))


@pytest.mark.parametrize("area, thick", [(0.0, 2.0), (-5.0, 2.0), ("nan", 2.0), ("inf", 2.0), (100.0, "inf"),
                                         (100.0, "nan"), (100.0, "-inf")])
def test_invalid_feature_values_rejected(area, thick):
    values = hemi_values("lh")
    values["insula"] = (area, thick)
    with pytest.raises(ValueError, match="insula"):
        parse_aparc_stats(stats_text("sub-SP02", "lh", values), "sub-SP02", "lh", ROIS)


@pytest.mark.parametrize("thick", [0.0, -1.5])
def test_finite_thickness_not_rejected_for_sign(thick):
    """Frozen rule: thickness must be finite; no positivity threshold (plan §6)."""
    values = hemi_values("lh")
    values["insula"] = (100.0, thick)
    rows = {r["roi"]: r for r in parse_aparc_stats(stats_text("sub-SP02", "lh", values), "sub-SP02", "lh", ROIS)}
    assert rows["ctx-lh-insula"]["thickness_mm"] == thick
    subjects, mri, cond = synthetic_tables()
    mri.loc[3, "thickness_mm"] = thick
    long = build_long_table(mri, cond, subjects, ROIS, CONDS)
    panel = panel_from_long_table(long, subjects, ROIS, CONDS)
    assert panel.x[0, 3, 0] == thick


@pytest.mark.parametrize("bad", [0.0, -1.0, np.nan, np.inf])
def test_ln_area_and_long_table_reject_invalid_area(bad):
    with pytest.raises(ValueError):
        ln_area([10.0, bad])
    subjects, mri, cond = synthetic_tables()
    mri.loc[3, "area_mm2"] = bad
    with pytest.raises(ValueError):
        build_long_table(mri, cond, subjects, ROIS, CONDS)


# ------------------------------------------------------------------ D. target aggregation
def test_target_is_equal_weight_mean_of_three_condition_means():
    subjects, mri, cond = synthetic_tables()
    long = build_long_table(mri, cond, subjects, ROIS, CONDS)
    by = cond.set_index(["subject_id", "roi", "condition"])["rcps_roi_mean"]
    for _, row in long.sample(20, random_state=0).iterrows():
        a, s, z = (by[(row.subject_id, row.roi, c)] for c in ("Awake", "SleepDeprived", "Asleep"))
        assert row.rcps_awake == a and row.rcps_sleep_deprived == s and row.rcps_asleep == z
        assert row.rcps_mean == (a + s + z) / 3


def test_condition_row_order_does_not_change_target():
    subjects, mri, cond = synthetic_tables()
    reference = build_long_table(mri, cond, subjects, ROIS, CONDS)
    reordered = pd.concat([cond.loc[cond.condition == c] for c in reversed(CONDS)]).sample(frac=1, random_state=3)
    pd.testing.assert_frame_equal(build_long_table(mri, reordered, subjects, ROIS, CONDS), reference)


def test_voxel_weighting_is_not_used():
    subjects, mri, cond = synthetic_tables()
    cond.loc[cond.condition == "Awake", "n_voxels"] = 10_000
    cond.loc[cond.condition == "Awake", "n_zero"] = 0
    cond.loc[cond.condition == "Awake", "zero_fraction"] = 0.0
    _, mri0, cond0 = synthetic_tables()
    reference = build_long_table(mri0, cond0, subjects, ROIS, CONDS)
    np.testing.assert_array_equal(build_long_table(mri, cond, subjects, ROIS, CONDS)["rcps_mean"],
                                  reference["rcps_mean"])


def test_missing_duplicate_or_extra_condition_rejected():
    subjects, mri, cond = synthetic_tables()
    with pytest.raises(ValueError, match="missing"):
        build_long_table(mri, cond.drop(index=5), subjects, ROIS, CONDS)
    with pytest.raises(ValueError, match="duplicate"):
        build_long_table(mri, pd.concat([cond, cond.iloc[[5]]]), subjects, ROIS, CONDS)
    renamed = cond.copy()
    renamed.loc[renamed.condition == "Asleep", "condition"] = "Rest"
    with pytest.raises(ValueError, match="extra"):
        build_long_table(mri, renamed, subjects, ROIS, CONDS)
    with pytest.raises(ValueError, match="missing"):
        build_long_table(mri, cond.loc[cond.condition != "Asleep"], subjects, ROIS, CONDS)


@pytest.mark.parametrize("value", [np.nan, np.inf, -0.1])
def test_invalid_condition_means_rejected(value):
    subjects, mri, cond = synthetic_tables()
    cond.loc[7, "rcps_roi_mean"] = value
    with pytest.raises(ValueError):
        build_long_table(mri, cond, subjects, ROIS, CONDS)


@pytest.mark.parametrize("column, value", [
    ("n_voxels", 0), ("n_zero", -1), ("n_zero", 1001), ("zero_fraction", 0.0500001), ("zero_fraction", np.nan)])
def test_invalid_counts_rejected(column, value):
    subjects, mri, cond = synthetic_tables()
    cond.loc[9, column] = value
    with pytest.raises(ValueError, match="condition table|zero_fraction"):
        build_long_table(mri, cond, subjects, ROIS, CONDS)


def test_noninteger_counts_rejected():
    subjects, mri, cond = synthetic_tables()
    cond["n_voxels"] = cond["n_voxels"].astype(float)
    with pytest.raises(ValueError, match="integer"):
        build_long_table(mri, cond, subjects, ROIS, CONDS)


def test_condition_columns():
    assert [condition_column(c) for c in CONDS] == ["rcps_awake", "rcps_sleep_deprived", "rcps_asleep"]


# ------------------------------------------------------------------ E. zero handling
def test_exact_zeros_included_in_roi_mean():
    labels = np.array([[1001, 1001, 1001, 1001], [1002, 1002, 17, 0]])
    values = np.array([[0.0, 0.0, 3.0, 5.0], [0.0, 4.0, 99.0, 99.0]])
    stats = roi_statistics(values, labels, [1001, 1002])
    np.testing.assert_array_equal(stats["mean"], [2.0, 2.0])  # (0+0+3+5)/4, (0+4)/2
    np.testing.assert_array_equal(stats["n_voxels"], [4, 2])
    np.testing.assert_array_equal(stats["n_zero"], [2, 1])
    assert np.all(np.isfinite(stats["mean"]))
    assert values[0, 0] == 0.0  # caller array untouched


def test_all_zero_roi_mean_is_zero_not_missing():
    stats = roi_statistics(np.zeros((2, 2)), np.array([[1001, 1001], [1002, 1002]]), [1001, 1002])
    np.testing.assert_array_equal(stats["mean"], [0.0, 0.0])
    np.testing.assert_array_equal(stats["n_zero"], [2, 2])


@pytest.mark.parametrize("value, match", [(np.nan, "nonfinite"), (np.inf, "nonfinite"), (-1e-6, "negative")])
def test_invalid_voxels_in_labels_rejected(value, match):
    values = np.array([[1.0, value], [2.0, 3.0]])
    with pytest.raises(ValueError, match=match):
        roi_statistics(values, np.array([[1001, 1001], [1002, 1002]]), [1001, 1002])


@pytest.mark.parametrize("value, match", [(np.nan, "nonfinite"), (np.inf, "nonfinite"), (-np.inf, "nonfinite"),
                                          (-1e-6, "negative")])
def test_invalid_voxel_outside_all_labels_rejected(value, match):
    values = np.array([[1.0, 2.0, value], [2.0, 3.0, 0.0]])
    labels = np.array([[1001, 1001, 0], [1002, 1002, 17]])  # the bad voxel carries no cortical label
    with pytest.raises(ValueError, match=match):
        roi_statistics(values, labels, [1001, 1002])


def test_exact_zeros_allowed_inside_and_outside_labels():
    values = np.array([[0.0, 2.0, 0.0], [4.0, 0.0, 0.0]])
    labels = np.array([[1001, 1001, 0], [1002, 1002, 17]])
    stats = roi_statistics(values, labels, [1001, 1002])
    np.testing.assert_array_equal(stats["mean"], [1.0, 2.0])
    np.testing.assert_array_equal(stats["n_zero"], [1, 1])


def test_label_without_voxels_and_shape_mismatch_rejected():
    with pytest.raises(ValueError, match="no voxel"):
        roi_statistics(np.ones((2, 2)), np.array([[1001, 1001], [0, 0]]), [1001, 1002])
    with pytest.raises(ValueError, match="grid"):
        roi_statistics(np.ones((2, 3)), np.ones((2, 2), int), [1])


# ------------------------------------------------------------------ F/G. complete panel and tensor
def test_complete_panel_and_tensor_layout():
    subjects, mri, cond = synthetic_tables()
    long = build_long_table(mri, cond, subjects, ROIS, CONDS)
    assert len(long) == len(subjects) * 68
    panel = panel_from_long_table(long, subjects, ROIS, CONDS)
    assert panel.x.shape == (4, 68, 2) and panel.y.shape == (4, 68)
    assert panel.subject_ids == subjects and panel.roi_names == tuple(r.name for r in ROIS)
    assert panel.feature_names == ("thickness", "ln_area")
    for s_i, r_i in [(0, 0), (2, 33), (3, 34), (1, 67)]:
        row = long[(long.subject_id == subjects[s_i]) & (long.roi == ROIS[r_i].name)].iloc[0]
        assert panel.x[s_i, r_i, 0] == row.thickness_mm
        assert panel.x[s_i, r_i, 1] == row.ln_area
        assert panel.y[s_i, r_i] == row.rcps_mean


def test_long_table_duplicate_or_missing_cell_rejected():
    subjects, mri, cond = synthetic_tables()
    long = build_long_table(mri, cond, subjects, ROIS, CONDS)
    with pytest.raises(ValueError, match="duplicate"):
        validate_long_table(pd.concat([long, long.iloc[[10]]]), subjects, ROIS, CONDS)
    with pytest.raises(ValueError, match="missing"):
        validate_long_table(long.drop(index=10), subjects, ROIS, CONDS)
    with pytest.raises(ValueError, match="missing"):
        validate_long_table(long, SUBJECTS[:5], ROIS, CONDS)


@pytest.mark.parametrize("column, value, match", [
    ("roi_code", 17, "roi_code"), ("hemisphere", "rh", "hemisphere"), ("ln_area", 1.0, "natural log"),
    ("rcps_mean", 9.0, "equal-weight"), ("thickness_mm", np.nan, "nonfinite")])
def test_long_table_inconsistencies_rejected(column, value, match):
    subjects, mri, cond = synthetic_tables()
    long = build_long_table(mri, cond, subjects, ROIS, CONDS)
    long.loc[5, column] = value
    with pytest.raises(ValueError, match=match):
        validate_long_table(long, subjects, ROIS, CONDS)


# ------------------------------------------------------------------ H/I. row-order invariance, no mutation
def test_row_order_invariance_and_no_caller_mutation():
    subjects, mri, cond = synthetic_tables()
    mri_before, cond_before = mri.copy(), cond.copy()
    long = build_long_table(mri, cond, subjects, ROIS, CONDS)
    panel = panel_from_long_table(long, subjects, ROIS, CONDS)
    pd.testing.assert_frame_equal(mri, mri_before)
    pd.testing.assert_frame_equal(cond, cond_before)
    shuffled_long = build_long_table(mri.sample(frac=1, random_state=5), cond.sample(frac=1, random_state=6),
                                     subjects, ROIS, CONDS)
    pd.testing.assert_frame_equal(shuffled_long, long)
    long_before = long.copy()
    shuffled_panel = panel_from_long_table(long.sample(frac=1, random_state=7), subjects, ROIS, CONDS)
    pd.testing.assert_frame_equal(long, long_before)
    np.testing.assert_array_equal(shuffled_panel.x, panel.x)
    np.testing.assert_array_equal(shuffled_panel.y, panel.y)


def test_panel_arrays_read_only_and_detached():
    subjects, mri, cond = synthetic_tables()
    long = build_long_table(mri, cond, subjects, ROIS, CONDS)
    panel = panel_from_long_table(long, subjects, ROIS, CONDS)
    assert not panel.x.flags.writeable and not panel.y.flags.writeable
    y0 = panel.y.copy()
    long.loc[:, "rcps_mean"] = 0.0
    np.testing.assert_array_equal(panel.y, y0)


def test_subject_order_is_canonical_not_input_order():
    subjects, mri, cond = synthetic_tables()
    long = build_long_table(mri, cond, subjects, ROIS, CONDS)
    reordered = tuple(reversed(subjects))
    panel = panel_from_long_table(long, reordered, ROIS, CONDS)
    reference = panel_from_long_table(long, subjects, ROIS, CONDS)
    np.testing.assert_array_equal(panel.y, reference.y[::-1])


def test_tsv_round_trip_is_exact(tmp_path):
    subjects, mri, cond = synthetic_tables(seed=11)
    long = build_long_table(mri, cond, subjects, ROIS, CONDS)
    (tmp_path / "long.tsv").write_text(table_tsv(long))
    reread = read_table_tsv(tmp_path / "long.tsv")
    pd.testing.assert_frame_equal(reread, long, check_exact=True)
    a, b = (panel_from_long_table(t, subjects, ROIS, CONDS) for t in (long, reread))
    assert array_sha256(a.x) == array_sha256(b.x) and array_sha256(a.y) == array_sha256(b.y)


# ------------------------------------------------------------------ synthetic canonical dataset (end to end)
def _write_dataset(root, rng):
    """Tiny fake dataset with the canonical layout and a manifest of its files."""
    rel = []
    affine = np.diag([2.0, 2.0, 2.0, 1.0])
    codes = [r.code for r in ROIS]
    flat = np.array(codes * 2 + [17, 1004, 0, 0] + [0] * (216 - 140))
    labels = np.asarray(flat.reshape(6, 6, 6), dtype=np.int32)
    (root / "participants.tsv").write_text("participant_id\n" + "\n".join(SUBJECTS) + "\n")
    rel.append("participants.tsv")
    for s in SUBJECTS:
        fs = root / "derivatives" / "freesurfer" / s
        (fs / "stats").mkdir(parents=True)
        (fs / "mri").mkdir()
        for hemi in ("lh", "rh"):
            (fs / "stats" / f"{hemi}.aparc.stats").write_text(stats_text(s, hemi, hemi_values(hemi, int(rng.integers(1_000_000)))))
            rel.append(f"derivatives/freesurfer/{s}/stats/{hemi}.aparc.stats")
        nib.save(nib.MGHImage(labels, affine), fs / "mri" / "aparc+aseg.mgz")  # pyright: ignore[reportArgumentType] -- nibabel's ArrayLike stub rejects a typed int32 ndarray
        rel.append(f"derivatives/freesurfer/{s}/mri/aparc+aseg.mgz")
        for c in CONDS:
            d = root / "derivatives" / "rCPS" / s / f"ses-{c}"
            d.mkdir(parents=True)
            values = rng.uniform(0.1, 3.0, size=(6, 6, 6)).astype(np.float32)
            values[rng.random((6, 6, 6)) < 0.2] = 0.0
            stem = f"{s}_ses-{c}_desc-ArtIF_stat-rCPS_statmap"
            nib.save(nib.Nifti1Image(values, affine), d / f"{stem}.nii.gz")
            (d / f"{stem}.json").write_text(json.dumps({"Parameter": {"Name": "rCPS", "Units": "nmol/g/min"}}))
            rel += [f"derivatives/rCPS/{s}/ses-{c}/{stem}.nii.gz", f"derivatives/rCPS/{s}/ses-{c}/{stem}.json"]
    return [{"relpath": p, "sha256": hashlib.sha256((root / p).read_bytes()).hexdigest()} for p in rel]


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("ds004733")
    manifest = _write_dataset(root, np.random.default_rng(20260930))
    return root, manifest


def _sources(root, manifest):
    return CanonicalSources(root, manifest, root / "derivatives" / "freesurfer", root / "derivatives" / "rCPS")


def test_end_to_end_synthetic_build(dataset):
    root, manifest = dataset
    long, cond, panel, rois, used = pb.build_panel(_sources(root, manifest), SUBJECTS, CFG)
    assert len(long) == 18 * 68 and len(cond) == 18 * 3 * 68
    assert panel.x.shape == (18, 68, 2) and panel.y.shape == (18, 68)
    assert len(used) == 18 * (2 + 1 + 3 * 2)
    s, c = SUBJECTS[4], "SleepDeprived"
    img = nib.load(next((root / "derivatives" / "rCPS" / s / f"ses-{c}").glob("*.nii.gz")))
    values = np.asarray(img.dataobj, dtype=np.float64)  # pyright: ignore[reportAttributeAccessIssue]
    labels = np.asarray(nib.load(root / "derivatives" / "freesurfer" / s / "mri" / "aparc+aseg.mgz").dataobj)  # pyright: ignore[reportAttributeAccessIssue]
    for roi in (ROIS[0], ROIS[40]):
        expected = values[labels == roi.code]
        row = cond[(cond.subject_id == s) & (cond.condition == c) & (cond.roi == roi.name)].iloc[0]
        assert row.n_voxels == expected.size == 2
        assert row.n_zero == int((expected == 0).sum())
        assert row.rcps_roi_mean == pytest.approx(expected.mean(), rel=1e-15, abs=0)
    summary = pb.validity_summary(panel, long, cond)
    assert summary["duplicate_subject_roi"] == 0 and summary["conditions_per_subject_roi"] == [3]
    assert summary["nonfinite_x"] == summary["nonfinite_y"] == 0


def test_manifest_is_deterministic(dataset):
    root, manifest = dataset
    results = [pb.build_panel(_sources(root, manifest), SUBJECTS, CFG) for _ in range(2)]
    manifests = [pb.panel_manifest(p, rois, long, cond, used, CANON, CFG) for long, cond, p, rois, used in results]
    assert json.dumps(manifests[0], sort_keys=True) == json.dumps(manifests[1], sort_keys=True)
    m = manifests[0]
    assert m["subjects"] == list(SUBJECTS) and [r["code"] for r in m["rois"]] == [r.code for r in ROIS]
    assert m["dimensions"]["x_shape"] == [18, 68, 2] and m["dimensions"]["long_table_rows"] == 1224
    assert m["target"]["zero_handling"] == "include_exact_zeros"
    assert "log1p is not used" in m["area_transform"]
    assert m["spec"]["frozen_tag"] == "analysis-plan-v3.0"
    assert m["spec"]["frozen_commit"].startswith("80d951f")
    assert set(m["spec"]["frozen_file_sha256"]) == {"docs/analysis_plan.md", "configs/analysis.yaml"}
    assert all(str(root) not in json.dumps(v) for v in m.values())


# ------------------------------------------------------------------ K. canonical-source enforcement
def test_noncanonical_sources_rejected(dataset, tmp_path):
    root, manifest = dataset
    sources = _sources(root, manifest)
    (tmp_path / "ALL_subjects_combined_avg.csv").write_text("Subject,StructName,PET_Mean\n")
    with pytest.raises(ValueError, match="not a canonical"):
        sources.get("derivatives/ALL_subjects_combined_avg.csv")
    with pytest.raises(ValueError, match="outside the canonical"):
        CanonicalSources(root, manifest, tmp_path, root / "derivatives" / "rCPS")
    tampered = [dict(r) for r in manifest]
    target = next(r for r in tampered if r["relpath"].endswith("lh.aparc.stats"))
    target["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        _sources(root, tampered).get(target["relpath"])
    with pytest.raises(ValueError, match="duplicate"):
        _sources(root, manifest + manifest[:1])


def test_canonical_relative_path_accepted(dataset):
    root, manifest = dataset
    rel = next(r["relpath"] for r in manifest if r["relpath"].endswith("aparc+aseg.mgz"))
    assert _sources(root, manifest).get(rel).path == root.resolve() / rel


def _hashed_entry(relpath, data):
    return {"relpath": relpath, "sha256": hashlib.sha256(data).hexdigest()}


def test_traversal_absolute_and_symlink_escapes_rejected(dataset, tmp_path_factory):
    root, manifest = dataset
    outside = tmp_path_factory.mktemp("external")
    data = b"historical table\n"
    (outside / "ALL_subjects_combined_avg.csv").write_bytes(data)
    escape = f"../{outside.name}/ALL_subjects_combined_avg.csv"
    assert (root / escape).resolve().read_bytes() == data  # the escape exists and its hash would match
    for relpath in (escape, str(outside / "ALL_subjects_combined_avg.csv"), "derivatives/../../x"):
        with pytest.raises(ValueError, match="absolute or traversal"):
            _sources(root, manifest + [_hashed_entry(relpath, data)]).get(relpath)
    link = root / "derivatives" / "escape_link.csv"
    link.symlink_to(outside / "ALL_subjects_combined_avg.csv")
    try:
        entry = _hashed_entry("derivatives/escape_link.csv", data)
        with pytest.raises(ValueError, match="outside the canonical bids_root"):
            _sources(root, manifest + [entry]).get(entry["relpath"])
    finally:
        link.unlink()


def test_symlink_inside_root_accepted(dataset):
    """git-annex layout: content symlinks that stay inside bids_root remain valid."""
    root, manifest = dataset
    target = next(r for r in manifest if r["relpath"].endswith("lh.aparc.stats"))
    link = root / "derivatives" / "annexed_link.stats"
    link.symlink_to(root / target["relpath"])
    try:
        entry = {"relpath": "derivatives/annexed_link.stats", "sha256": target["sha256"]}
        assert _sources(root, manifest + [entry]).get(entry["relpath"]).sha256 == target["sha256"]
    finally:
        link.unlink()


def test_ambiguous_or_unlisted_rcps_map_rejected(dataset, tmp_path):
    root, manifest = dataset
    s = SUBJECTS[0]
    extra = root / "derivatives" / "rCPS" / s / "ses-Awake" / f"{s}_ses-Awake_desc-bbregister_stat-rCPS_statmap.nii.gz"
    extra.write_bytes(b"not canonical")
    try:
        with pytest.raises(ValueError, match="exactly one"):
            _sources(root, manifest).rcps_map(s, "Awake")
    finally:
        extra.unlink()
    unlisted = [r for r in manifest if not r["relpath"].startswith(f"derivatives/rCPS/{s}/ses-Asleep/")]
    with pytest.raises(ValueError, match="exactly one"):
        _sources(root, unlisted).rcps_map(s, "Asleep")


def test_wrong_rcps_units_rejected(dataset, tmp_path):
    from rcps.panel.rcps_roi import check_sidecar_units
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"Parameter": {"Units": "umol/g/min"}}))
    with pytest.raises(ValueError, match="units"):
        check_sidecar_units(f, "nmol/g/min")


def test_panel_builder_does_not_import_modelling():
    import rcps.panel.assemble as assemble
    import rcps.panel.build as build
    for module in (assemble, build):
        text = Path(str(module.__file__)).read_text()
        assert "rcps.analysis" not in text and "from ..analysis" not in text
