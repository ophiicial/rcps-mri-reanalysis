import hashlib
import subprocess

from rcps.qc import dataset as ds
from rcps.qc import verify_canonical as vc


def test_git_blob_sha1_matches_git(tmp_path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"participant_id\tage\nsub-SP02\t23\n")
    expected = subprocess.run(["git", "hash-object", str(f)], capture_output=True, text=True, check=True).stdout.strip()
    assert ds.git_blob_sha1(f) == expected


def test_annex_verification_detects_match_and_tamper(tmp_path):
    data = b"\x00\x01rcps"
    f = tmp_path / "sub-X_T1w.nii.gz"
    f.write_bytes(data)
    key = f"../../.git/annex/objects/aa/bb/SHA256E-s{len(data)}--{hashlib.sha256(data).hexdigest()}.nii.gz"
    tree = {"sub-X_T1w.nii.gz": {"mode": "120000", "sha": "unused"}}
    ok = ds.verify_against_published(tmp_path, ["sub-X_T1w.nii.gz"], tree, {"sub-X_T1w.nii.gz": key})
    assert ok[0]["match"] is True
    f.write_bytes(data + b"!")
    bad = ds.verify_against_published(tmp_path, ["sub-X_T1w.nii.gz"], tree, {"sub-X_T1w.nii.gz": key})
    assert bad[0]["match"] is False


def test_check_files_reports_ok_missing_mismatch(tmp_path):
    (tmp_path / "a").write_bytes(b"abc")
    (tmp_path / "b").write_bytes(b"xyz")
    exp = [{"relpath": "a", "bytes": "3", "sha256": hashlib.sha256(b"abc").hexdigest()},
           {"relpath": "b", "bytes": "3", "sha256": hashlib.sha256(b"abc").hexdigest()},
           {"relpath": "c", "bytes": "1", "sha256": "0" * 64}]
    assert [r["status"] for r in vc.check_files(tmp_path, exp)] == ["OK", "MISMATCH", "MISSING"]


def test_expected_table_is_well_formed():
    rows = vc.read_expected()
    assert len(rows) == 444 and len({r["relpath"] for r in rows}) == 444
    assert all(len(r["sha256"]) == 64 and not r["relpath"].startswith("/") for r in rows)
    readme = next(r for r in rows if r["relpath"] == "README")
    assert readme["verified_against"] == "published 1.0.1 git text"
