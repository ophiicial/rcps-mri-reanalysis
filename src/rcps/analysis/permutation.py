"""Stratified whole-subject MRI-block permutation inference (analysis_plan §11; analysis.yaml:permutation).

Assignments are pre-generated from the frozen strata and seed, then evaluated serially in replicate order.
One replicate is one global outcome-subject -> MRI-donor mapping, applied to X before nested LOSO; y,
subject IDs, ROI axis and folds never change. Every MRI-dependent quantity is refitted by `nested_loso`.

Representation: `donors[b, i] = j` means that in replicate b the outcome subject `canonical_subjects[i]`
receives the complete [ROI, feature] MRI block of `canonical_subjects[j]`. Canonical order is
analysis.yaml:cohort.primary.subjects, independent of any panel's axis order.
This module does not load real data and writes no artifacts.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import yaml
from scipy import stats

from ..config import REPO_ROOT, load_yaml
from .cv import OuterFold, nested_loso, summarize_loso
from .ridge import LAMBDA_GRID, _readonly

FROZEN_CONTRACT = {
    "type": "restricted_whole_subject_mri_block",
    "features_move_together": True,
    "preserve_roi_correspondence": True,
    "one_global_assignment_per_replicate": True,
    "sampling": {"independent": True, "uniform_over_group": True, "with_replacement": True},
    "identity_allowed": True,
    "duplicates": {"allowed": True, "keep_multiplicity": True, "cache_computation": True},
    "alternative": "upper_tail",
    "exceedance": "T_b >= T_obs",
    "p_value": "(1 + K) / (B + 1)",
}
BIT_GENERATOR = "PCG64"
# Production gate anchors (numbers only; subject lists are read from the tagged config, never hard-coded).
FROZEN_SPEC_TAG = "analysis-plan-v3.0"
FROZEN_SPEC_COMMIT = "80d951fbfb6929e9470786b0a0fbcb2c81630055"
FROZEN_B, FROZEN_SEED, FROZEN_GROUP_SIZE, FROZEN_N_STRATA = 9999, 20260929, 58_060_800, 4


def _require_contract(perm_cfg: dict) -> None:
    bad = {k: perm_cfg.get(k) for k, v in FROZEN_CONTRACT.items() if perm_cfg.get(k) != v}
    if perm_cfg.get("rng", {}).get("generator") != f"numpy.random.{BIT_GENERATOR}":
        bad["rng.generator"] = perm_cfg.get("rng", {}).get("generator")
    if bad:
        raise ValueError(f"permutation config departs from the frozen contract implemented here: {bad}")


@dataclass(frozen=True)
class PermutationScheme:
    """Frozen strata in listed order, subjects sorted within each; canonical subject order; B; seed."""
    canonical_subjects: tuple[str, ...]
    strata_names: tuple[str, ...]
    strata: tuple[tuple[str, ...], ...]
    stratum_index: tuple[int, ...]   # stratum of canonical_subjects[i]
    group_size: int
    b: int
    seed: int

    def provenance(self) -> dict:
        return {"canonical_subjects": list(self.canonical_subjects), "strata_names": list(self.strata_names),
                "strata": [list(s) for s in self.strata], "group_size": self.group_size, "B": self.b,
                "seed": self.seed, "bit_generator": BIT_GENERATOR}


def load_scheme(config: dict | None = None) -> PermutationScheme:
    """Build the scheme from analysis.yaml (default: the repository's frozen config)."""
    cfg = load_yaml(REPO_ROOT / "configs" / "analysis.yaml") if config is None else config
    perm = cfg["permutation"]
    _require_contract(perm)
    canonical = tuple(cfg["cohort"]["primary"]["subjects"])
    names = tuple(s["name"] for s in perm["strata"])
    strata = tuple(tuple(sorted(s["subjects"])) for s in perm["strata"])
    flat = [s for stratum in strata for s in stratum]
    if len(set(names)) != len(names) or any(len(s) == 0 for s in strata):
        raise ValueError("strata must have unique names and be nonempty")
    if len(flat) != len(set(flat)):
        raise ValueError(f"subject in more than one stratum or duplicated: {sorted({s for s in flat if flat.count(s) > 1})}")
    if len(canonical) != len(set(canonical)) or len(canonical) != cfg["cohort"]["primary"]["n"]:
        raise ValueError("cohort.primary.subjects must be unique and match n")
    missing, extra = sorted(set(canonical) - set(flat)), sorted(set(flat) - set(canonical))
    if missing or extra:
        raise ValueError(f"strata do not partition the primary cohort; missing={missing} extra={extra}")
    group_size = math.prod(math.factorial(len(s)) for s in strata)
    if group_size != perm["group_size"]:
        raise ValueError(f"group size {group_size} != configured {perm['group_size']}")
    lookup = {s: k for k, stratum in enumerate(strata) for s in stratum}
    b, seed = perm["B"], perm["rng"]["seed"]
    if not (isinstance(b, int) and b > 0 and isinstance(seed, int)):
        raise ValueError("B must be a positive integer and the seed an integer")
    return PermutationScheme(canonical, names, strata, tuple(lookup[s] for s in canonical), group_size, b, seed)


def _tagged_config() -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True,
                              check=True).stdout

    commit = git("rev-parse", f"{FROZEN_SPEC_TAG}^{{commit}}").strip()
    if commit != FROZEN_SPEC_COMMIT:
        raise RuntimeError(f"{FROZEN_SPEC_TAG} resolves to {commit}, expected {FROZEN_SPEC_COMMIT}")
    return yaml.safe_load(git("show", f"{FROZEN_SPEC_TAG}:configs/analysis.yaml"))


def require_frozen_scheme(scheme: PermutationScheme) -> PermutationScheme:
    """Production gate: the scheme must equal the one defined by the tagged frozen config.

    Checks canonical subjects, strata order and membership, group size, B, seed and (via the tagged config's
    contract) PCG64, with-replacement sampling, whole-subject blocks, `>=` exceedance and the p formula.
    Generic schemes remain usable for synthetic tests; any real-data entry point must call this gate.
    """
    tagged_cfg = _tagged_config()
    frozen = load_scheme(tagged_cfg)  # also enforces the frozen contract on the tagged permutation section
    anchors = (frozen.b, frozen.seed, frozen.group_size, len(frozen.strata))
    if anchors != (FROZEN_B, FROZEN_SEED, FROZEN_GROUP_SIZE, FROZEN_N_STRATA):
        raise RuntimeError(f"tagged permutation config does not match the frozen anchors: {anchors}")
    if tagged_cfg["permutation"]["rng"]["seed"] != FROZEN_SEED or tagged_cfg["permutation"]["B"] != FROZEN_B:
        raise RuntimeError("tagged config B/seed differ from the frozen anchors")
    if scheme != frozen:
        diff = [f for f in ("canonical_subjects", "strata_names", "strata", "stratum_index", "group_size", "b",
                            "seed") if getattr(scheme, f) != getattr(frozen, f)]
        raise ValueError(f"permutation scheme is not the frozen {FROZEN_SPEC_TAG} scheme; differs in {diff}")
    return scheme


def frozen_scheme() -> PermutationScheme:
    """The repository config's scheme, gated against the tagged frozen specification."""
    return require_frozen_scheme(load_scheme())


@dataclass(frozen=True)
class PermutationAssignments:
    """Read-only donor indices [B, N] in canonical subject order, with provenance and checksum."""
    scheme: PermutationScheme
    donors: np.ndarray
    numpy_version: str
    sha256: str

    @classmethod
    def from_donors(cls, scheme: PermutationScheme, donors) -> PermutationAssignments:
        """Validate and wrap an explicit donor array (e.g. a fabricated test list)."""
        d = _integer_indices(donors, "donor array")
        n = len(scheme.canonical_subjects)
        if d.ndim != 2 or d.shape[1] != n or d.shape[0] == 0:
            raise ValueError(f"donor array must have shape [B, {n}]")
        for row in d:
            validate_assignment(scheme, row)
        d.setflags(write=False)
        return cls(scheme, d, np.__version__, assignments_sha256(scheme, d))


def _reject_masked(**arrays) -> None:
    """Complete panels only: a masked array must never be unwrapped to its underlying values."""
    masked = [name for name, a in arrays.items() if np.ma.isMaskedArray(a)]
    if masked:
        raise ValueError(f"masked arrays are not supported (complete panels required): {masked}")


def _integer_indices(values, what: str) -> np.ndarray:
    """Donor indices must already have an integer dtype; floats (even 2.0), bools and objects are rejected
    before any coercion, so a fractional or nonfinite index can never be truncated into a valid one."""
    if np.ma.isMaskedArray(values):
        raise ValueError(f"{what}: masked arrays are not supported")
    a = np.asarray(values)
    if not np.issubdtype(a.dtype, np.integer):
        raise ValueError(f"{what} must have an integer dtype, got {a.dtype}")
    return np.array(a, dtype=np.int64, copy=True)


def validate_assignment(scheme: PermutationScheme, row) -> None:
    """One replicate: a bijection on canonical positions that never crosses a stratum."""
    row = _integer_indices(row, "assignment")
    n = len(scheme.canonical_subjects)
    if row.shape != (n,):
        raise ValueError(f"assignment must be {n} integer donor indices")
    if sorted(row.tolist()) != list(range(n)):
        raise ValueError("assignment must use every donor exactly once")
    strata = scheme.stratum_index
    crossing = [i for i, j in enumerate(row.tolist()) if strata[i] != strata[j]]
    if crossing:
        raise ValueError(f"assignment crosses strata at outcome positions {crossing}")


def assignments_sha256(scheme: PermutationScheme, donors: np.ndarray) -> str:
    header = json.dumps(scheme.provenance(), sort_keys=True, separators=(",", ":")).encode()
    body = np.ascontiguousarray(donors, dtype="<i8").tobytes()
    return hashlib.sha256(header + b"\n" + body).hexdigest()


def generate_assignments(scheme: PermutationScheme) -> PermutationAssignments:
    """Pre-generate all B assignments (plan §11.4 construction), before any evaluation.

    Per replicate and per stratum in listed order: pi = rng.permutation(n_stratum); outcome stratum[i]
    receives the MRI block of stratum[pi[i]]. Identity and duplicate draws are kept.
    """
    rng = np.random.Generator(np.random.PCG64(scheme.seed))
    position = {s: i for i, s in enumerate(scheme.canonical_subjects)}
    donors = np.empty((scheme.b, len(scheme.canonical_subjects)), dtype=np.int64)
    for b in range(scheme.b):
        for stratum in scheme.strata:
            pi = rng.permutation(len(stratum))
            for i, subject in enumerate(stratum):
                donors[b, position[subject]] = position[stratum[pi[i]]]
    return PermutationAssignments.from_donors(scheme, donors)


def identity_assignment(scheme: PermutationScheme) -> np.ndarray:
    return np.arange(len(scheme.canonical_subjects), dtype=np.int64)


def panel_donor_positions(scheme: PermutationScheme, subject_ids: Sequence[str], row) -> np.ndarray:
    """Translate a canonical donor row into positions on a panel whose subject axis is `subject_ids`."""
    ids = tuple(subject_ids)
    if len(set(ids)) != len(ids) or set(ids) != set(scheme.canonical_subjects):
        raise ValueError("panel subject IDs must be exactly the canonical cohort")
    validate_assignment(scheme, row)
    panel_pos = {s: k for k, s in enumerate(ids)}
    out = np.empty(len(ids), dtype=np.int64)
    for i, j in enumerate(_integer_indices(row, "assignment").tolist()):
        out[panel_pos[scheme.canonical_subjects[i]]] = panel_pos[scheme.canonical_subjects[j]]
    return out


def permute_mri(x: np.ndarray, donor_positions) -> np.ndarray:
    """X_perm[s] = X[donor(s)]: whole [ROI, feature] blocks move together; y is never touched."""
    _reject_masked(x=x)
    x = np.asarray(x)
    d = _integer_indices(donor_positions, "donor positions")
    if x.ndim != 3 or d.shape != (x.shape[0],) or sorted(d.tolist()) != list(range(x.shape[0])):
        raise ValueError("donor positions must be a permutation of the subject axis of x[subject, roi, feature]")
    permuted = _readonly(x[d])
    verify_block_permutation(x, permuted, d)
    return permuted


def verify_block_permutation(x: np.ndarray, x_perm: np.ndarray, donor_positions) -> None:
    """Fail unless every outcome subject holds its donor's complete, unreordered MRI block."""
    for s, j in enumerate(np.asarray(donor_positions).tolist()):
        if not np.array_equal(x_perm[s], x[j]):
            raise ValueError(f"subject position {s} does not hold the intact MRI block of donor {j}")


def permuted_folds(subject_ids, x, y, donor_positions, *, lambdas=LAMBDA_GRID) -> tuple[OuterFold, ...]:
    """Nested LOSO on the globally permuted X; every fit, scale, selection and refit is recomputed."""
    _reject_masked(x=x, y=y)
    return nested_loso(subject_ids, permute_mri(x, donor_positions), y, lambdas=lambdas)


def replicate_statistic(subject_ids, x, y, donor_positions, *, lambdas=LAMBDA_GRID) -> float:
    """T = equal-subject mean of D_s for one global assignment."""
    t = summarize_loso(permuted_folds(subject_ids, x, y, donor_positions, lambdas=lambdas)).t
    if not math.isfinite(t):
        raise ValueError("nonfinite permutation statistic")
    return t


@dataclass(frozen=True)
class MonteCarloUncertainty:
    """Uncertainty from sampling B assignments, NOT a population interval for the MRI improvement."""
    q_hat: float
    mc_se: float
    clopper_pearson_95: tuple[float, float]


@dataclass(frozen=True)
class PermutationResult:
    t_obs: float
    null: np.ndarray            # [B], replicate order, multiplicity retained
    k: int
    b: int
    p_value: float
    monte_carlo: MonteCarloUncertainty
    assignments_sha256: str
    numpy_version: str
    n_evaluations: int          # distinct nested-LOSO evaluations performed for the null
    n_cache_hits: int           # replicates served from the exact-duplicate cache


def exceedance_count(null, t_obs: float) -> int:
    """K = #{b : T_b >= T_obs}; ties count as exceedances."""
    null = np.asarray(null, dtype=np.float64)
    if not (np.all(np.isfinite(null)) and math.isfinite(t_obs)):
        raise ValueError("null and observed statistics must be finite")
    return int(np.count_nonzero(null >= t_obs))


def permutation_p_value(k: int, b: int) -> float:
    if not (0 <= k <= b and b > 0):
        raise ValueError("require 0 <= K <= B and B > 0")
    return (1 + k) / (b + 1)


def monte_carlo_uncertainty(k: int, b: int, confidence: float = 0.95) -> MonteCarloUncertainty:
    """q_hat = K/B, its binomial SE, and the Clopper-Pearson interval for the full-group exceedance probability."""
    if not (0 <= k <= b and b > 0):
        raise ValueError("require 0 <= K <= B and B > 0")
    if not (isinstance(confidence, (int, float)) and math.isfinite(confidence) and 0 < confidence < 1):
        raise ValueError(f"confidence must be a finite number in (0, 1), got {confidence!r}")
    alpha = 1 - confidence
    q = k / b
    lower = 0.0 if k == 0 else float(stats.beta.ppf(alpha / 2, k, b - k + 1))
    upper = 1.0 if k == b else float(stats.beta.ppf(1 - alpha / 2, k + 1, b - k))
    return MonteCarloUncertainty(q, math.sqrt(q * (1 - q) / b), (lower, upper))


Evaluator = Callable[[np.ndarray], float]


def evaluate_null(assignments: PermutationAssignments, evaluate: Evaluator, *, cache: bool = True
                  ) -> tuple[np.ndarray, int, int]:
    """Evaluate every pre-generated replicate in index order.

    `evaluate` maps a canonical donor row to T_b. With `cache`, an exact duplicate row reuses the stored
    T_b, but still occupies its own entry, so multiplicity in the null and in K is unchanged.
    """
    null = np.empty(assignments.donors.shape[0])
    memo: dict[bytes, float] = {}
    evaluations = hits = 0
    for b, row in enumerate(assignments.donors):
        key = row.tobytes()
        if cache and key in memo:
            null[b] = memo[key]
            hits += 1
            continue
        null[b] = evaluate(row)
        evaluations += 1
        if cache:
            memo[key] = null[b]
    return _readonly(null), evaluations, hits


def run_permutation_test(subject_ids, x, y, assignments: PermutationAssignments, *, lambdas=LAMBDA_GRID,
                         cache: bool = True) -> PermutationResult:
    """T_obs (identity assignment, same orchestration), the null over all B replicates, K, p and MC uncertainty."""
    _reject_masked(x=x, y=y)
    scheme = assignments.scheme
    if assignments.donors.shape[0] != scheme.b:
        raise ValueError(f"assignment list has {assignments.donors.shape[0]} replicates; the scheme fixes B={scheme.b}")

    def evaluate(row) -> float:
        return replicate_statistic(subject_ids, x, y, panel_donor_positions(scheme, subject_ids, row),
                                   lambdas=lambdas)

    t_obs = evaluate(identity_assignment(scheme))
    null, evaluations, hits = evaluate_null(assignments, evaluate, cache=cache)
    b = len(null)
    k = exceedance_count(null, t_obs)
    return PermutationResult(t_obs, null, k, b, permutation_p_value(k, b), monte_carlo_uncertainty(k, b),
                             assignments.sha256, assignments.numpy_version, evaluations, hits)
