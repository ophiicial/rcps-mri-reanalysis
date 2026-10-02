"""Production orchestration on fabricated canonical tables; never reads real outcomes."""
import csv
import json
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from rcps.analysis import permutation as perm
from rcps.analysis import run_primary as runner
from rcps.config import load_yaml
from rcps.panel.assemble import (CONDITION_COLUMNS, MRI_COLUMNS, build_long_table, panel_from_long_table,
                                 read_table_tsv, table_tsv)
from rcps.panel.build import panel_manifest
from rcps.panel.spec import canonical_rois
from rcps.provenance import canonical_json_sha256
from rcps.qc.verify_canonical import load_canonical
from rcps.runrecord import sha256_file


@pytest.fixture
def artifact(tmp_path):
    cfg = load_yaml(runner.ANALYSIS_CONFIG)
    canonical = load_canonical()
    subjects = cfg["cohort"]["primary"]["subjects"]
    rois = canonical_rois(cfg)
    conditions = cfg["target"]["conditions"]
    rng = np.random.default_rng(81)
    mri = pd.DataFrame([(s, r.name, rng.uniform(1, 4), rng.uniform(200, 4000), "synthetic")
                        for s in subjects for r in rois], columns=MRI_COLUMNS)
    cond = pd.DataFrame([(s, c, r.name, rng.uniform(1, 5), 10, 0, 0.0, "synthetic")
                         for s in subjects for c in conditions for r in rois], columns=CONDITION_COLUMNS)
    long = build_long_table(mri, cond, subjects, rois, conditions)
    panel = panel_from_long_table(long, subjects, rois, conditions)
    manifest = panel_manifest(panel, rois, long, cond, [], canonical, cfg)
    directory = tmp_path / "source" / "panel"
    directory.mkdir(parents=True)
    (directory / "long_table.tsv").write_text(table_tsv(long))
    (directory / "condition_roi_values.tsv").write_text(table_tsv(cond))
    (directory / "panel_manifest.json").write_text(json.dumps(manifest))
    source = {"panel_manifest_sha256": canonical_json_sha256(manifest),
              "usable_for_reported_results": True,
              "git": {"sha": "synthetic-build", "has_commits": True, "dirty": False},
              "provenance": {"canonical_verifier": {"ran": True, "PASS": True, "require_git": True,
                                                     "n_ok": 444, "n_expected": 444},
                             "dataset": {"accession": canonical["accession"], "commit": canonical["release_commit"],
                                         "tag": canonical["release_tag"], "clean": True, "head_is_release": True},
                             "expected_manifest": {"sha256": manifest["dataset"]["expected_manifest_sha256"]},
                             "config_hashes": {"analysis": {"sha256": manifest["spec"]["analysis_yaml_sha256"]}}}}
    logs = directory.parent / "logs"
    logs.mkdir()
    (logs / "run_metadata.json").write_text(json.dumps(source))
    return directory


@pytest.fixture
def production(monkeypatch, artifact, tmp_path):
    monkeypatch.setattr(runner, "PANEL_DIR", artifact)
    monkeypatch.setattr(runner, "require_clean_tree", lambda: "synthetic-code")
    monkeypatch.setattr(runner, "load_paths", lambda: SimpleNamespace(outputs_root=tmp_path / "results"))
    # Exercise the real metadata writer without using the intentionally dirty development tree.
    monkeypatch.setattr("rcps.runrecord.git_state", lambda: {
        "sha": "synthetic-code", "short_sha": "syntheti", "has_commits": True,
        "dirty": False, "status_porcelain": []})
    return artifact


def test_load_reconstructs_canonical_panel(artifact):
    panel, manifest, source, inputs = runner.load_panel_artifact(artifact)
    assert panel.x.shape == (18, 68, 2) and panel.y.shape == (18, 68)
    assert list(panel.subject_ids) == manifest["subjects"]
    assert source["provenance"]["canonical_verifier"]["PASS"]
    assert len(inputs) == 4


@pytest.mark.parametrize("field", ["subjects", "rois", "subject_roster_sha256", "roi_roster_sha256",
                                   "spec", "dimensions", "features", "feature_names", "target", "conditions",
                                   "dataset", "spatial", "schema"])
def test_manifest_mismatch_fails_before_modeling(production, monkeypatch, field):
    path = production / "panel_manifest.json"
    manifest = json.loads(path.read_text())
    manifest[field] = "WRONG"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(runner, "primary_loso", lambda *a: pytest.fail("modeling was reached"))
    with pytest.raises(ValueError, match="manifest"):
        runner.run_primary("observed")


@pytest.mark.parametrize("key", ["x_float64_le", "y_float64_le"])
def test_array_hash_mismatch(production, monkeypatch, key):
    path = production / "panel_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["content_sha256"][key] = "0" * 64
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(runner, "primary_loso", lambda *a: pytest.fail("modeling was reached"))
    with pytest.raises(ValueError, match="content_sha256"):
        runner.run_primary("observed")


def test_corrupt_table_rejected(artifact):
    with (artifact / "long_table.tsv").open("a") as fh:
        fh.write("corrupt\n")
    with pytest.raises(ValueError, match="long_table_tsv"):
        runner.load_panel_artifact(artifact)


def test_changed_array_with_updated_table_hash_is_rejected(artifact):
    path = artifact / "long_table.tsv"
    table = read_table_tsv(path)
    table.loc[0, "thickness_mm"] += 1
    path.write_text(table_tsv(table))
    manifest_path = artifact / "panel_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["content_sha256"]["long_table_tsv"] = sha256_file(path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="content_sha256"):
        runner.load_panel_artifact(artifact)


@pytest.mark.parametrize("dirty", [" M source.py\n", "?? untracked.py\n"])
def test_dirty_tree_refusal(monkeypatch, dirty):
    def git(cmd, **kwargs):
        return SimpleNamespace(stdout=dirty if "status" in cmd else "commit\n")
    monkeypatch.setattr(runner.subprocess, "run", git)
    monkeypatch.setattr(runner, "load_panel_artifact", lambda *a: pytest.fail("loaded panel before Git gate"))
    with pytest.raises(RuntimeError, match="clean committed"):
        runner.run_primary("observed")


def test_git_failure_fails_closed(monkeypatch):
    def git(*args, **kwargs):
        raise subprocess.CalledProcessError(128, "git")
    monkeypatch.setattr(runner.subprocess, "run", git)
    with pytest.raises(subprocess.CalledProcessError):
        runner.require_clean_tree()


@pytest.mark.parametrize("field,value", [("b", 39), ("seed", 7), ("strata", ())])
def test_frozen_permutation_gate(production, monkeypatch, field, value):
    scheme = replace(perm.frozen_scheme(), **{field: value})
    monkeypatch.setattr(runner, "frozen_scheme", lambda: scheme)
    monkeypatch.setattr(runner, "primary_loso", lambda *a: pytest.fail("modeling was reached"))
    with pytest.raises(ValueError, match="not the frozen"):
        runner.run_primary("observed")


@pytest.mark.parametrize("flag", ["--B", "--seed", "--strata", "--lambdas", "--cohort", "--features", "--target",
                                  "--panel-dir"])
def test_no_scientific_cli_overrides(flag):
    with pytest.raises(SystemExit) as exc:
        runner.main(["observed", flag, "1"])
    assert exc.value.code == 2


def test_observed_and_permutation_outputs(production, monkeypatch):
    observed_dir = runner.run_primary("observed", argv=["test", "observed"])
    summary = json.loads((observed_dir / "summary.json").read_text())
    with (observed_dir / "outer_folds.tsv").open() as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len(rows) == 18
    assert list(rows[0]) == ["subject_id", "selected_lambda", "baseline_mse", "ridge_mse", "D_s"]
    assert [r["subject_id"] for r in rows] == summary["descriptive"]["subject_ids"]
    assert summary["T_obs"] == np.mean([float(r["D_s"]) for r in rows])
    assert summary["mean_baseline_mse"] == np.mean([float(r["baseline_mse"]) for r in rows])
    assert summary["mean_ridge_mse"] == np.mean([float(r["ridge_mse"]) for r in rows])
    diagnostics = json.loads((observed_dir / "fold_diagnostics.json").read_text())["folds"]
    assert len(diagnostics) == 18 and len(diagnostics[0]["inner_rank"]) == 17
    metadata = json.loads((observed_dir / "logs/run_metadata.json").read_text())
    assert metadata["status"] == "complete" and metadata["usable_for_reported_results"]
    assert metadata["argv"] == ["test", "observed"]
    assert metadata["identity"]["frozen_commit"] == perm.FROZEN_SPEC_COMMIT

    # Keep real generation of all 9999 assignments and real identity nested LOSO.
    # Substitute only expensive null evaluations; no real data or full simulation.
    def cheap_null(assignments, evaluate, **kwargs):
        assert assignments.scheme == perm.frozen_scheme()
        assert assignments.donors.shape == (9999, 18)
        assert kwargs["workers"] in (1, 2)
        return np.full(9999, summary["T_obs"]), 1, 9998
    monkeypatch.setattr(perm, "evaluate_null", cheap_null)
    perm_dir = runner.run_primary("permutation", observed_run=observed_dir, workers=2)
    result = json.loads((perm_dir / "summary.json").read_text())
    assert result["T_obs_hex"] == summary["T_obs_hex"]
    assert result["K"] == result["B"] == 9999 and result["p"] == 1
    assert result["monte_carlo"]["q_hat"] == 1
    assert np.load(perm_dir / "null_statistics.npy").shape == (9999,)
    donors = np.load(perm_dir / "assignments.npy")
    assert result["assignment_sha256"] == perm.assignments_sha256(perm.frozen_scheme(), donors)
    assert result["numpy_version"] == np.__version__
    assert result["scheme"]["seed"] == 20260929 and result["scheme"]["bit_generator"] == "PCG64"
    assert result["execution"] == {"workers": 2} and "workers" not in result["scheme"]
    perm_metadata = json.loads((perm_dir / "logs/run_metadata.json").read_text())
    assert perm_metadata["execution"] == {"workers": 2}
    assert perm_dir != observed_dir

    # Also enforce agreement with the engine's own observed statistic after it returns.
    engine = runner.run_permutation_test
    def inconsistent_engine(*args, **kwargs):
        value = engine(*args, **kwargs)
        return replace(value, t_obs=float(np.nextafter(value.t_obs, np.inf)))
    monkeypatch.setattr(runner, "run_permutation_test", inconsistent_engine)
    with pytest.raises(ValueError, match="exact agreement"):
        runner.run_primary("permutation", observed_run=observed_dir)

    # A one-ULP discrepancy must fail before null evaluation, even if file checksums are updated.
    summary["T_obs"] = float(np.nextafter(summary["T_obs"], np.inf))
    summary["T_obs_hex"] = summary["T_obs"].hex()
    runner._write_json(observed_dir / "summary.json", summary)
    metadata["artifact_sha256"]["summary.json"] = sha256_file(observed_dir / "summary.json")
    runner._write_json(observed_dir / "logs/run_metadata.json", metadata)
    monkeypatch.setattr(runner, "generate_assignments", lambda *a: pytest.fail("null generation reached"))
    with pytest.raises(ValueError, match="exact agreement"):
        runner.run_primary("permutation", observed_run=observed_dir)


def test_exact_t_mismatch():
    runner.require_same_t(0.1, 0.1)
    for other in [float(np.nextafter(0.1, 1)), float("nan"), float("inf")]:
        with pytest.raises(ValueError, match="exact agreement"):
            runner.require_same_t(0.1, other)


def test_reference_required_before_any_modeling(monkeypatch):
    monkeypatch.setattr(runner, "require_clean_tree", lambda: pytest.fail("entered analysis"))
    with pytest.raises(ValueError, match="required only"):
        runner.run_primary("permutation")


@pytest.mark.parametrize("failure", ["dirty", "unverified", "wrong_commit", "manifest_checksum"])
def test_invalid_build_provenance(artifact, failure):
    path = artifact.parent / "logs/run_metadata.json"
    record = json.loads(path.read_text())
    if failure == "dirty":
        record["git"]["dirty"] = True
    elif failure == "unverified":
        record["provenance"]["canonical_verifier"]["require_git"] = False
    elif failure == "wrong_commit":
        record["provenance"]["dataset"]["commit"] = "wrong"
    else:
        record["panel_manifest_sha256"] = "wrong"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        runner.load_panel_artifact(artifact)


@pytest.mark.parametrize("argv", [["observed", "--workers", "1"],
                                  ["permutation", "--observed-run", "unused", "--workers", "0"],
                                  ["permutation", "--observed-run", "unused", "--workers", "-2"]])
def test_workers_cli_rejects_invalid_execution_options(argv, monkeypatch):
    monkeypatch.setattr(runner, "run_primary", lambda *a, **k: pytest.fail("analysis reached"))
    with pytest.raises(SystemExit) as exc:
        runner.main(argv)
    assert exc.value.code == 2


def test_workers_cli_forwarding(monkeypatch, tmp_path):
    calls = []
    def run(mode, **kwargs):
        calls.append((mode, kwargs))
        return tmp_path
    monkeypatch.setattr(runner, "run_primary", run)
    runner.main(["permutation", "--observed-run", str(tmp_path), "--workers", "3"])
    assert calls[0][0] == "permutation" and calls[0][1]["workers"] == 3
    runner.main(["observed"])
    assert calls[1][1]["workers"] is None
