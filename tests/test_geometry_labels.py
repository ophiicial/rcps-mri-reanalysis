import datetime as dt

import numpy as np
import pytest

from rcps import fsgeom, labels, runrecord, similarity
from rcps.config import load_paths

RCPS_AFFINE = np.array([[0, 1, 0, 30], [-1, 0, 0, 226], [0, 0, 1, 0], [0, 0, 0, 1]], float)


def test_fs_vox2ras_matches_nifti_affine():
    # volume-info fields as written by FreeSurfer for the ds004733 rCPS grid (256x196x256, cras 128,98,128)
    A = fsgeom.fs_vox2ras([256, 196, 256], [1, 1, 1], [0, -1, 0], [1, 0, 0], [0, 0, 1], [128, 98, 128])
    np.testing.assert_allclose(A, RCPS_AFFINE)


def test_lta_vox2vox_converts_to_ras2ras():
    src = RCPS_AFFINE
    dst = fsgeom.fs_vox2ras([256, 256, 256], [1, 1, 1], [-1, 0, 0], [0, 0, -1], [0, 1, 0], [128, 98, 128])
    T = fsgeom.rigid_matrix(tx=2, rz_deg=3, centre=(10, 20, 30))
    v2v = np.linalg.inv(dst) @ T @ src
    lta = {"type": 0, "matrix": v2v, "src_vox2ras": src, "dst_vox2ras": dst}
    np.testing.assert_allclose(fsgeom.lta_ras2ras(lta), T, atol=1e-10)


def test_rigid_matrix_rotation_fixes_centre():
    c = np.array([5.0, -3.0, 40.0])
    T = fsgeom.rigid_matrix(rx_deg=3, ry_deg=-2, rz_deg=1, centre=c)
    np.testing.assert_allclose(T[:3, :3] @ c + T[:3, 3], c, atol=1e-10)
    d = fsgeom.rigid_params_deviation(T, c)
    assert d["centre_displacement_mm"] < 1e-9 and d["rotation_deg"] > 0 and abs(d["det"] - 1) < 1e-9


def test_nn_label_resampling_is_exact_across_axis_permutation():
    rng = np.random.default_rng(0)
    lab = rng.integers(0, 50, size=(12, 10, 8)).astype(np.int32)
    lab_aff = np.diag([1.0, 1.0, 1.0, 1.0])
    # target grid: same world voxels, axes permuted/flipped (as between NIfTI rCPS and FreeSurfer conformed space)
    perm = np.array([[0, 1, 0, 0], [-1, 0, 0, 9], [0, 0, 1, 0], [0, 0, 0, 1]], float)  # target vox -> world
    out = labels.resample_labels_nn(lab, lab_aff, (10, 12, 8), perm)
    for i, j, k in [(0, 0, 0), (3, 5, 2), (9, 11, 7)]:
        w = perm @ [i, j, k, 1]
        assert out[i, j, k] == lab[tuple(int(round(x)) for x in w[:3])]
    assert set(np.unique(out)) <= set(np.unique(lab))  # no new label values are ever created


def test_nn_label_resampling_world_shift():
    lab = np.zeros((10, 10, 10), np.int32)
    lab[5, 5, 5] = 7
    T = fsgeom.rigid_matrix(tx=1.0)  # anatomy position = target world + 1 mm in x
    out = labels.resample_labels_nn(lab, np.eye(4), lab.shape, np.eye(4), world_transform=T)
    assert out[4, 5, 5] == 7 and out[5, 5, 5] == 0


def test_left_right_check_detects_flip():
    good = {1000 + i: np.array([-30.0, 0, 0]) for i in labels.DK_INDEX} | {2000 + i: np.array([30.0, 0, 0]) for i in labels.DK_INDEX}
    flipped = {k: v * np.array([-1, 1, 1]) for k, v in good.items()}
    assert all(r["lh_left_of_rh"] for r in labels.left_right_check(good))
    assert not any(r["lh_left_of_rh"] for r in labels.left_right_check(flipped))


@pytest.mark.parametrize("missing", [1001, 2035])
def test_left_right_check_missing_centroid_raises_key_error(missing):
    cents = {1000 + i: np.array([-30.0, 0, 0]) for i in labels.DK_INDEX} | {2000 + i: np.array([30.0, 0, 0]) for i in labels.DK_INDEX}
    del cents[missing]
    with pytest.raises(KeyError) as excinfo:
        labels.left_right_check(cents)
    assert excinfo.value.args == (missing,)


def test_dk_label_set_has_68_rois_without_unknown_or_cc():
    codes = labels.dk_cortical_labels()
    assert len(codes) == 68 and not {1000, 1004, 2000, 2004} & set(codes)


def test_nmi_prefers_aligned_images():
    rng = np.random.default_rng(1)
    a = rng.normal(size=20000)
    b = a + 0.1 * rng.normal(size=20000)
    assert similarity.nmi(a, b) > similarity.nmi(a, rng.permutation(b)) + 0.1


def test_anatomy_sampler_identity_reproduces_voxels():
    rng = np.random.default_rng(2)
    anat = rng.normal(size=(8, 9, 10)).astype(np.float32)
    vox = np.argwhere(np.ones_like(anat, bool))
    s = similarity.AnatomySampler(anat, RCPS_AFFINE, RCPS_AFFINE, vox, order=1)
    np.testing.assert_allclose(s.sample(np.eye(4)), anat[tuple(vox.T)], atol=1e-6)


def test_run_dir_refuses_reuse(tmp_path):
    now = dt.datetime(2026, 1, 1, 0, 0, 0)
    d = runrecord.create_run_dir(tmp_path, "unit", now=now)
    assert d.exists()
    with pytest.raises(FileExistsError):
        runrecord.create_run_dir(tmp_path, "unit", now=now)


# ---- data-dependent checks (skipped if no local dataset configured) ----
def _paths_or_skip():
    try:
        return load_paths()
    except (FileNotFoundError, ValueError):
        pytest.skip("no configs/paths.local.yaml")


def test_dk_names_match_freesurfer_aparc_stats():
    p = _paths_or_skip()
    stats = p.freesurfer / "sub-SP02" / "stats" / "lh.aparc.stats"
    names = [ln.split()[0] for ln in stats.read_text().splitlines() if ln and not ln.startswith("#")]
    assert sorted(names) == sorted(labels.DK_INDEX.values())
