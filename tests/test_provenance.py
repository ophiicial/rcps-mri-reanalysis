import hashlib
import json
import subprocess

import pytest

from rcps import provenance, runrecord
from rcps.qc import verify_canonical as vc


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example.invalid", "HOME": str(root), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


@pytest.fixture
def fake_dataset(tmp_path):
    """Tiny git 'dataset' tagged 1.0.1 with a participants.tsv and one data file, plus a matching manifest."""
    root = tmp_path / "ds"
    root.mkdir()
    (root / "participants.tsv").write_text("participant_id\tage\nsub-A\t20\nsub-B\t21\n")
    (root / "data.txt").write_bytes(b"rcps")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "release")
    _git(root, "tag", "1.0.1")
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    manifest = tmp_path / "expected.tsv"
    rows = [("participants.tsv", (root / "participants.tsv").read_bytes()), ("data.txt", b"rcps")]
    manifest.write_text("# test\nrelpath\tbytes\tsha256\tverified_against\n" + "".join(
        f"{p}\t{len(b)}\t{hashlib.sha256(b).hexdigest()}\ttest\n" for p, b in rows))
    canonical = {"accession": "dsTEST", "release_tag": "1.0.1", "release_commit": commit,
                 "expected_manifest_path": manifest, "expected_participants": ["sub-A", "sub-B"]}
    return root, canonical


def test_dataset_git_state_tag_commit_clean_and_dirty(fake_dataset):
    root, canonical = fake_dataset
    g = provenance.dataset_git_state(root)
    assert g["is_git"] and g["tag"] == "1.0.1" and g["commit"] == canonical["release_commit"] and g["clean"]
    (root / "untracked.txt").write_text("x")
    g2 = provenance.dataset_git_state(root)
    assert not g2["clean"] and g2["n_status_entries"] == 1


def test_dataset_git_state_non_git(tmp_path):
    g = provenance.dataset_git_state(tmp_path)
    assert g["is_git"] is False and g["commit"] is None and g["clean"] is False


def test_verify_pass_and_release_commit_requirement(fake_dataset):
    root, canonical = fake_dataset
    summary, _ = vc.verify(root, canonical, require_git=True)
    assert summary["PASS"] and summary["git"]["head_is_release"]
    wrong = {**canonical, "release_commit": "0" * 40}
    assert vc.verify(root, wrong, require_git=True)[0]["PASS"] is False
    assert vc.verify(root, wrong, require_git=False)[0]["PASS"] is True   # content alone still verifies


def test_canonical_json_hash_is_order_independent_and_sensitive():
    a = provenance.canonical_json_sha256({"x": 1, "y": [1, 2]})
    assert a == provenance.canonical_json_sha256({"y": [1, 2], "x": 1})
    assert a != provenance.canonical_json_sha256({"x": 2, "y": [1, 2]})


def test_run_metadata_records_native_provenance(fake_dataset, tmp_path):
    root, canonical = fake_dataset
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text("a: 1\n")
    prov = provenance.run_provenance(root, canonical, config_files={"cfg": cfg_file}, resolved_config={"a": 1},
                                     run_verifier=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rec = json.loads(runrecord.write_run_metadata(run_dir, argv=["x"], config={"a": 1}, seeds={}, inputs={},
                                                  provenance=prov).read_text())
    p = rec["provenance"]
    assert {"sha", "dirty"} <= set(p["repository"]) and {"sha", "dirty"} <= set(rec["git"])
    assert p["dataset"]["tag"] == "1.0.1" and p["dataset"]["commit"] == canonical["release_commit"]
    assert p["dataset"]["clean"] is True and p["dataset"]["head_is_release"] is True
    assert p["canonical_verifier"]["ran"] and p["canonical_verifier"]["PASS"] is True
    assert p["expected_manifest"]["sha256"] == runrecord.sha256_file(canonical["expected_manifest_path"])
    assert p["config_hashes"]["cfg"]["sha256"] == hashlib.sha256(b"a: 1\n").hexdigest()
    assert p["resolved_config_sha256"] == provenance.canonical_json_sha256({"a": 1})
    # no absolute paths recorded for files outside the repository
    assert not p["expected_manifest"]["path"].startswith("/") and not p["config_hashes"]["cfg"]["path"].startswith("/")


def test_committed_canonical_config_points_to_committed_manifest():
    c = vc.load_canonical()
    assert c["release_tag"] == "1.0.1" and len(c["release_commit"]) == 40 and len(c["expected_participants"]) == 18
    assert c["expected_manifest_path"].exists()
