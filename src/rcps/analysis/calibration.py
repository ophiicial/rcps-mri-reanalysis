"""SYNTHETIC calibration and planted-signal power study of the frozen P1 procedure (analysis_plan §15 item 13).

This module never reads real data: it has no panel, path or array input, and generates every dataset itself.
Each simulated dataset goes through the production stack unchanged: `nested_loso` for the observed fit
diagnostics, and `run_permutation_test` (Phase-4 engine) for T_obs, K and p, with one global
whole-subject assignment per replicate inside the frozen four strata. Only the permutation count B and
the permutation seed are study parameters. They are labelled as such, and the production scheme
(B = 9999, seed 20260929) is neither used nor modified.

Synthetic data-generating process (all constants fixed below, not fitted to real data):
  stratum k (frozen E2 membership), subject s in k, ROI r, feature f in {thickness-like, ln-area-like}
  X[s,r,f] = mu[r,f] + delta[k,f] + u[s,f] + e[s,r,f]
  y[s,r]   = alpha[r] + gamma[k] + v[s] + eps[s,r] + beta * sigma_y * signal[s,r]
  gamma[k] = kappa * sigma_gamma * delta[k,0] / sigma_delta[0] + sqrt(1 - kappa^2) * sigma_gamma * g[k]
  signal[s,r] = (Z[s,r,0] + Z[s,r,1]) / sqrt(2),  Z[s,r,f] = (X[s,r,f] - mu[r,f]) / sd_f
  sd_f = sqrt(sigma_delta_f^2 + sigma_u_f^2 + sigma_e_f^2)   (within-ROI SD of X around mu)
  sigma_y = sqrt(sigma_gamma^2 + sigma_v^2 + sigma_eps^2)    (within-ROI SD of the y noise)
Null (beta = 0). Given the realized stratum-level effects (delta, gamma), the subject-specific MRI
components (u, e) and outcome components (v, eps) are independent, and subjects within a stratum are i.i.d.
Subjects are therefore exchangeable within each stratum, and the joint distribution of (X, y) is invariant to
any within-stratum permutation of whole MRI blocks. This is what makes the restricted permutation null
operationally valid. With kappa = 0 the stratum effects of X and y are also independent of each other.
With kappa > 0 (`null_stratum_confounded`) the shared stratum effects correlate delta and gamma. Across
generated datasets X and y are then NOT independent given only the stratum label; the association is
stratum-level (acquisition-family confounding), and the restricted permutation preserves it.
beta is the planted-signal SD in units of the y noise SD.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from ..config import REPO_ROOT, load_paths, load_yaml
from ..runrecord import create_run_dir, write_run_metadata
from .cv import nested_loso, summarize_loso
from .permutation import (FROZEN_SPEC_COMMIT, FROZEN_SPEC_TAG, PermutationScheme, frozen_scheme,
                          generate_assignments, run_permutation_test)

SYNTHETIC_LABEL = "SYNTHETIC SIMULATION - NOT REAL-DATA INFERENCE"
N_ROIS = 68

# Generator constants (fixed before any study run; thickness-like mm and ln(mm^2)-like units).
MU_RANGES = {"thickness": (2.0, 3.5), "ln_area": (6.5, 8.8)}                 # ROI means ~ U(range)
SIGMA_DELTA = np.array([0.15, 0.15])    # stratum offsets of X
SIGMA_U = np.array([0.15, 0.10])        # subject offsets of X
SIGMA_E = np.array([0.12, 0.08])        # ROI-level residuals of X
ALPHA_RANGE = (1.2, 2.4)                # ROI effects of y (nmol/g/min-like)
SIGMA_GAMMA, SIGMA_V, SIGMA_EPS = 0.10, 0.15, 0.15
SD_X = np.sqrt(SIGMA_DELTA**2 + SIGMA_U**2 + SIGMA_E**2)
SIGMA_Y = math.sqrt(SIGMA_GAMMA**2 + SIGMA_V**2 + SIGMA_EPS**2)


@dataclass(frozen=True)
class Scenario:
    name: str
    beta: float          # planted signal SD / y-noise SD; 0 = null
    kappa: float         # stratum-level X-y association in [0, 1); allowed under the conditional null
    n_simulations: int   # independent datasets
    permutation_b: int   # study B for this scenario (NOT the production B)

    def __post_init__(self):
        if not (isinstance(self.name, str) and self.name
                and _real(self.beta) and self.beta >= 0 and _real(self.kappa) and 0 <= self.kappa < 1
                and _count(self.n_simulations) and _count(self.permutation_b)):
            raise ValueError(f"invalid scenario {self}")

    @property
    def is_null(self) -> bool:
        return self.beta == 0


@dataclass(frozen=True)
class SimulationDesign:
    name: str
    scenarios: tuple[Scenario, ...]
    master_seed: int
    alpha: float                            # nominal level, read from the frozen config
    calibration_confidence: float = 0.95    # two-sided descriptive interval for every scenario
    calibration_upper_confidence: float = 0.975   # one-sided upper bound used by the null criterion
    calibration_upper_tolerance: float = 0.075    # engineering tolerance, NOT the nominal alpha

    def __post_init__(self):
        if not (isinstance(self.scenarios, tuple) and self.scenarios
                and all(isinstance(s, Scenario) for s in self.scenarios)
                and len({s.name for s in self.scenarios}) == len(self.scenarios)):
            raise ValueError("scenarios must be a nonempty tuple of uniquely named Scenario objects")
        if not (isinstance(self.master_seed, int) and not isinstance(self.master_seed, bool) and self.master_seed >= 0):
            raise ValueError("master_seed must be a nonnegative integer")
        for name in ("alpha", "calibration_confidence", "calibration_upper_confidence",
                     "calibration_upper_tolerance"):
            value = getattr(self, name)
            if not (_real(value) and 0 < value < 1):
                raise ValueError(f"{name} must be a finite number in (0, 1), got {value!r}")
        if not self.calibration_upper_tolerance >= self.alpha:
            raise ValueError("calibration_upper_tolerance must not be below alpha")

    def to_json(self) -> dict:
        return {"label": SYNTHETIC_LABEL, **dataclasses.asdict(self),
                "production_B_not_used": frozen_config()["permutation"]["B"],
                "generator_constants": generator_constants()}


def _real(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def frozen_config() -> dict:
    return load_yaml(REPO_ROOT / "configs" / "analysis.yaml")


def generator_constants() -> dict:
    return {"MU_RANGES": MU_RANGES, "SIGMA_DELTA": SIGMA_DELTA.tolist(), "SIGMA_U": SIGMA_U.tolist(),
            "SIGMA_E": SIGMA_E.tolist(), "ALPHA_RANGE": ALPHA_RANGE, "SIGMA_GAMMA": SIGMA_GAMMA,
            "SIGMA_V": SIGMA_V, "SIGMA_EPS": SIGMA_EPS, "SD_X": SD_X.tolist(), "SIGMA_Y": SIGMA_Y}


EFFECT_LEVELS = (("weak", 0.25), ("moderate", 0.5), ("strong", 1.0))
NULLS = (("null", 0.0), ("null_stratum_confounded", 0.8))
# Study sizes: (n_null, B_null, n_power, B_power). A Monte Carlo permutation p-value is valid for any B,
# so null calibration can use a small B (B + 1 divisible by 1/alpha, so the attainable level equals alpha).
# Power estimated with a study B may differ from power with the production B = 9999; no direction is assumed.
# `full` is final (fixed before execution): nulls 500 datasets at B = 39, power 200 datasets at B = 99.
PRESET_SIZES = {"quick": (2, 19, 2, 19), "full": (500, 39, 200, 99)}


def preset(name: str) -> SimulationDesign:
    """Prespecified designs: `quick` is a smoke benchmark, `full` is the final calibration/power study."""
    if name not in PRESET_SIZES:
        raise ValueError(f"unknown preset {name!r}")
    n_null, b_null, n_power, b_power = PRESET_SIZES[name]
    scenarios = (tuple(Scenario(n, 0.0, k, n_null, b_null) for n, k in NULLS)
                 + tuple(Scenario(n, b, 0.0, n_power, b_power) for n, b in EFFECT_LEVELS))
    return SimulationDesign(name, scenarios, master_seed=20261001, alpha=frozen_config()["permutation"]["alpha"])


# ------------------------------------------------------------------ seeds and data
def dataset_seeds(master_seed: int, scenario_index: int, sim_index: int) -> tuple[np.random.SeedSequence, int]:
    """Independent (data SeedSequence, integer permutation seed) per scenario x simulation."""
    root = np.random.SeedSequence(master_seed, spawn_key=(scenario_index, sim_index))
    data_ss, perm_ss = root.spawn(2)
    return data_ss, int(perm_ss.generate_state(1, np.uint64)[0])


@dataclass(frozen=True)
class SyntheticDataset:
    subject_ids: tuple[str, ...]
    x: np.ndarray
    y: np.ndarray
    signal: np.ndarray          # planted standardized signal (zero contribution when beta = 0)
    roi_means: np.ndarray       # mu[r, f], generator diagnostics only


def generate_dataset(scheme: PermutationScheme, scenario: Scenario, data_seed: np.random.SeedSequence | int
                     ) -> SyntheticDataset:
    rng = np.random.Generator(np.random.PCG64(data_seed))
    ids = scheme.canonical_subjects
    n, k_strata = len(ids), len(scheme.strata)
    stratum = np.array(scheme.stratum_index)
    mu = np.column_stack([rng.uniform(*MU_RANGES["thickness"], N_ROIS), rng.uniform(*MU_RANGES["ln_area"], N_ROIS)])
    delta = rng.normal(size=(k_strata, 2)) * SIGMA_DELTA
    u = rng.normal(size=(n, 2)) * SIGMA_U
    e = rng.normal(size=(n, N_ROIS, 2)) * SIGMA_E
    x = mu[None] + delta[stratum][:, None, :] + u[:, None, :] + e
    alpha = rng.uniform(*ALPHA_RANGE, N_ROIS)
    g = rng.normal(size=k_strata)
    gamma = SIGMA_GAMMA * (scenario.kappa * delta[:, 0] / SIGMA_DELTA[0] + math.sqrt(1 - scenario.kappa**2) * g)
    v = rng.normal(size=n) * SIGMA_V
    eps = rng.normal(size=(n, N_ROIS)) * SIGMA_EPS
    z = (x - mu[None]) / SD_X
    signal = (z[..., 0] + z[..., 1]) / math.sqrt(2)
    y = alpha[None] + gamma[stratum][:, None] + v[:, None] + eps
    if scenario.beta:
        y = y + scenario.beta * SIGMA_Y * signal
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise RuntimeError("nonfinite synthetic data")
    for a in (x, y, signal, mu):
        a.setflags(write=False)
    return SyntheticDataset(ids, x, y, signal, mu)


# ------------------------------------------------------------------ one simulated dataset
@dataclass(frozen=True)
class SimulationRecord:
    scenario: str
    sim_index: int
    beta: float
    kappa: float
    permutation_seed: int
    assignments_sha256: str
    t_obs: float
    k: int
    b: int
    p_value: float
    reject: bool
    n_evaluations: int
    n_cache_hits: int
    frac_outer_lambda_inf: float
    median_outer_lambda: float
    runtime_s: float


def study_scheme(permutation_b: int, permutation_seed: int) -> PermutationScheme:
    """Frozen strata and contract (gated), with the study's B and seed substituted explicitly."""
    return dataclasses.replace(frozen_scheme(), b=permutation_b, seed=permutation_seed)


def simulate_one(design: SimulationDesign, scenario_index: int, sim_index: int) -> SimulationRecord:
    start = time.perf_counter()
    scenario = design.scenarios[scenario_index]
    data_ss, perm_seed = dataset_seeds(design.master_seed, scenario_index, sim_index)
    scheme = study_scheme(scenario.permutation_b, perm_seed)
    data = generate_dataset(scheme, scenario, data_ss)
    assignments = generate_assignments(scheme)
    result = run_permutation_test(data.subject_ids, data.x, data.y, assignments)
    folds = nested_loso(data.subject_ids, data.x, data.y)          # observed-fit diagnostics only
    if summarize_loso(folds).t != result.t_obs:
        raise RuntimeError("observed nested LOSO disagrees with the permutation engine's T_obs")
    lambdas = np.array([f.selected_lambda for f in folds])
    return SimulationRecord(
        scenario.name, sim_index, scenario.beta, scenario.kappa, perm_seed, assignments.sha256, result.t_obs,
        result.k, result.b, result.p_value, bool(result.p_value <= design.alpha), result.n_evaluations,
        result.n_cache_hits, float(np.mean(np.isinf(lambdas))), float(np.median(lambdas)),
        time.perf_counter() - start)


def _task(args) -> SimulationRecord:
    return simulate_one(*args)


def run_study(design: SimulationDesign, workers: int = 1) -> tuple[SimulationRecord, ...]:
    """All scenarios x simulations, returned in (scenario, simulation) index order for any worker count."""
    tasks = [(design, i, j) for i, s in enumerate(design.scenarios) for j in range(s.n_simulations)]
    if workers <= 1:
        return tuple(_task(t) for t in tasks)
    with ProcessPoolExecutor(workers) as pool:
        return tuple(pool.map(_task, tasks))   # map preserves submission order


# ------------------------------------------------------------------ summaries
def rejection_interval(n_reject: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Clopper-Pearson interval for the rejection probability ACROSS simulated datasets."""
    if not (0 <= n_reject <= n and n > 0 and 0 < confidence < 1):
        raise ValueError("require 0 <= rejections <= n, n > 0, 0 < confidence < 1")
    a = 1 - confidence
    lo = 0.0 if n_reject == 0 else float(stats.beta.ppf(a / 2, n_reject, n - n_reject + 1))
    hi = 1.0 if n_reject == n else float(stats.beta.ppf(1 - a / 2, n_reject + 1, n - n_reject))
    return lo, hi


def summarize_scenario(records: Sequence[SimulationRecord], design: SimulationDesign) -> dict:
    n = len(records)
    rejects = sum(r.reject for r in records)
    rate = rejects / n
    lo, hi = rejection_interval(rejects, n, design.calibration_confidence)
    t = np.array([r.t_obs for r in records])
    p = np.array([r.p_value for r in records])
    out = {"n_simulations": n, "n_rejected": rejects, "rejection_rate": rate,
           "rejection_rate_se": math.sqrt(rate * (1 - rate) / n),
           f"rejection_rate_clopper_pearson_{design.calibration_confidence:g}": [lo, hi],
           "t_obs": {"mean": float(t.mean()), "median": float(np.median(t)), "frac_positive": float(np.mean(t > 0))},
           "p_value": {"median": float(np.median(p)), "min": float(p.min()), "max": float(p.max())},
           "mean_frac_outer_lambda_inf": float(np.mean([r.frac_outer_lambda_inf for r in records]))}
    if records[0].beta == 0:
        out["calibration_check"] = calibration_check(rejects, n, records[0].b, design)
    return out


def upper_confidence_bound(n_reject: int, n: int, confidence: float) -> float:
    """One-sided Clopper-Pearson upper bound for the rejection probability across simulated datasets."""
    if not (0 <= n_reject <= n and n > 0 and 0 < confidence < 1):
        raise ValueError("require 0 <= rejections <= n, n > 0, 0 < confidence < 1")
    return 1.0 if n_reject == n else float(stats.beta.ppf(confidence, n_reject + 1, n - n_reject))


def calibration_check(n_rejected: int, n: int, permutation_b: int, design: SimulationDesign) -> dict:
    """Prespecified engineering false-positive-control criterion (NOT frozen methodology).

    Calibration is demonstrated for a null scenario only if the one-sided `calibration_upper_confidence`
    (97.5%) Clopper-Pearson upper bound of its rejection probability is <= `calibration_upper_tolerance`
    (0.075). The tolerance is an engineering validation margin, not the nominal alpha. A conservative
    rejection rate below alpha does not fail; pronounced conservatism is flagged for investigation.
    """
    attainable = math.floor(design.alpha * (permutation_b + 1) + 1e-9) / (permutation_b + 1)
    upper = upper_confidence_bound(n_rejected, n, design.calibration_upper_confidence)
    lo, hi = rejection_interval(n_rejected, n, design.calibration_confidence)
    demonstrated = upper <= design.calibration_upper_tolerance
    return {"criterion": (f"one-sided {design.calibration_upper_confidence:g} Clopper-Pearson upper bound of the "
                          f"null rejection probability <= {design.calibration_upper_tolerance:g}"),
            "status": "engineering/simulation validation, not frozen methodology",
            "nominal_alpha": design.alpha, "attainable_level": attainable,
            "engineering_upper_tolerance": design.calibration_upper_tolerance,
            "rejection_rate": n_rejected / n, "upper_bound": upper,
            "calibration_demonstrated": bool(demonstrated),
            "result": ("calibration demonstrated" if demonstrated
                       else "calibration not demonstrated / possible excessive rejection"),
            "pronounced_conservatism": bool(hi < attainable),   # two-sided interval entirely below the level
            "note": "report and investigate pronounced conservatism; it does not fail the criterion"}


def calibration_overall(null_checks: Sequence[dict], design: SimulationDesign) -> dict:
    """All null scenarios must pass. Bonferroni: m one-sided bounds at level c give simultaneous coverage
    >= 1 - m (1 - c); two null scenarios at 97.5% give >= 95%."""
    m = len(null_checks)
    return {"n_null_scenarios": m,
            "simultaneous_coverage_lower_bound": 1 - m * (1 - design.calibration_upper_confidence),
            "calibration_demonstrated": bool(m > 0 and all(c["calibration_demonstrated"] for c in null_checks)),
            "decided_before_full_study": True}


def records_frame(records: Sequence[SimulationRecord]) -> pd.DataFrame:
    df = pd.DataFrame([dataclasses.asdict(r) for r in records])
    df.insert(0, "label", SYNTHETIC_LABEL)
    return df


# ------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Synthetic calibration/power study (NOT real-data inference).")
    ap.add_argument("--preset", choices=["quick", "full"], required=True)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args(argv)
    design = preset(args.preset)
    # load_paths() is used only for the configured outputs_root (it also requires bids_root to be configured;
    # no dataset file is read).
    paths = load_paths()
    run_dir = create_run_dir(paths.outputs_root, f"calibration-synthetic-{design.name}")
    metadata = {"argv": sys.argv, "config": {"label": SYNTHETIC_LABEL, **design.to_json()},
                "seeds": {"master_seed": design.master_seed, "production_seed_untouched": True},
                "inputs": {"real_data": None}}
    frozen = {"tag": FROZEN_SPEC_TAG, "commit": FROZEN_SPEC_COMMIT}
    # Design and provenance are written before simulating, so an interrupted run keeps its intended design.
    (run_dir / "simulation_design.json").write_text(json.dumps(design.to_json(), indent=2) + "\n")
    write_run_metadata(run_dir, **metadata, extra={"frozen_spec": frozen, "status": "started",
                                                     "workers": args.workers})
    start = time.perf_counter()
    records = run_study(design, workers=args.workers)
    elapsed = time.perf_counter() - start
    frame = records_frame(records)
    null_names = {s.name for s in design.scenarios if s.is_null}
    frame[frame.scenario.isin(null_names)].to_csv(run_dir / "null_results.tsv", sep="\t", index=False)
    frame[~frame.scenario.isin(null_names)].to_csv(run_dir / "power_results.tsv", sep="\t", index=False)
    scenarios = {s.name: summarize_scenario([r for r in records if r.scenario == s.name], design)
                 for s in design.scenarios}
    null_checks = [v["calibration_check"] for v in scenarios.values() if "calibration_check" in v]
    summary = {"label": SYNTHETIC_LABEL, "design": design.name,
               "permutation_b_study": {s.name: s.permutation_b for s in design.scenarios}, "alpha": design.alpha,
               "elapsed_s": elapsed, "workers": args.workers,
               "calibration_overall": calibration_overall(null_checks, design), "scenarios": scenarios}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_run_metadata(run_dir, **metadata, extra={"frozen_spec": frozen, "status": "completed",
                                                     "workers": args.workers, "elapsed_s": elapsed})
    print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
