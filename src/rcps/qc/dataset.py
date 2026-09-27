"""Phase A: dataset inventory, verification against the published OpenNeuro release, manifest, eligibility."""
from __future__ import annotations

import csv
import difflib
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from ..runrecord import sha256_file

TOP_META = ("dataset_description.json", "participants.tsv", "participants.json", "README", "CHANGES",
            "sessions.json", "recording-manual_blood.json", ".bidsignore")
ANNEX_KEY_RE = re.compile(r"SHA256E-s(\d+)--([0-9a-f]{64})")


def git_blob_sha1(path: Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def read_participants(path: Path) -> list[str]:
    with open(path, newline="") as fh:
        return [row["participant_id"] for row in csv.DictReader(fh, delimiter="\t")]


# ------------------------------------------------------------------ A1 inventory
def inventory_copy(root: Path) -> dict:
    root = Path(root)
    top = sorted(p.name for p in root.iterdir() if p.name != ".DS_Store")
    inv = {"path": str(root), "top_level": top, "metadata": {}, "subjects": {}, "derivatives": {}}
    for name in TOP_META:
        f = root / name
        if f.exists():
            inv["metadata"][name] = {"sha256": sha256_file(f), "bytes": f.stat().st_size,
                                     "mtime": f.stat().st_mtime, "text": f.read_text(errors="replace")}
    dl = root / ".datalad" / "config"
    inv["datalad_config"] = dl.read_text() if dl.exists() else None
    for sub in sorted(root.glob("sub-*")):
        if sub.is_dir():
            inv["subjects"][sub.name] = sorted(p.name for p in sub.iterdir() if p.name != ".DS_Store")
    der = root / "derivatives"
    if der.exists():
        for d in sorted(p for p in der.iterdir() if p.is_dir()):
            files = [p for p in d.rglob("*") if p.is_file() and p.name != ".DS_Store"]
            ext = Counter("".join(p.suffixes[-2:]) if p.name.endswith(".nii.gz") else (p.suffix or p.name) for p in files)
            subs = sorted(p.name for p in d.glob("sub-*") if p.is_dir())
            sessions = Counter(s.name for sub in d.glob("sub-*") for s in sub.glob("ses-*") if s.is_dir())
            inv["derivatives"][d.name] = {"n_files": len(files), "n_subjects": len(subs), "subjects": subs,
                                          "sessions": dict(sessions), "files_by_type": dict(ext.most_common())}
    return inv


# ------------------------------------------------------------------ A2 published release (OpenNeuro GitHub mirror)
def _gh(*args: str) -> str:
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=True)
    return r.stdout


def published_file_text(repo: str, tag: str, path: str) -> str | None:
    try:
        return _gh("-H", "Accept: application/vnd.github.raw", f"repos/{repo}/contents/{path}?ref={tag}")
    except subprocess.CalledProcessError:
        return None


def published_tree(repo: str, tag: str) -> dict[str, dict]:
    data = json.loads(_gh(f"repos/{repo}/git/trees/{tag}?recursive=1"))
    if data.get("truncated"):
        raise RuntimeError("GitHub tree listing truncated; cannot verify completely")
    return {e["path"]: e for e in data["tree"] if e["type"] == "blob"}


def published_link_targets(repo: str, tag: str, paths: list[str], batch: int = 60) -> dict[str, str]:
    """Symlink (git-annex) targets via GraphQL Blob.text, batched."""
    owner, name = repo.split("/")
    out = {}
    for i in range(0, len(paths), batch):
        chunk = paths[i:i + batch]
        fields = " ".join(f'f{j}: object(expression: {json.dumps(tag + ":" + p)}) {{ ... on Blob {{ text }} }}'
                          for j, p in enumerate(chunk))
        q = f'query {{ repository(owner: "{owner}", name: "{name}") {{ {fields} }} }}'
        res = json.loads(_gh("graphql", "-f", f"query={q}"))["data"]["repository"]
        for j, p in enumerate(chunk):
            node = res.get(f"f{j}")
            out[p] = node["text"] if node else None
    return out


def verify_against_published(local_root: Path, rel_paths: list[str], tree: dict, link_targets: dict) -> list[dict]:
    rows = []
    for rel in rel_paths:
        local = local_root / rel
        e = tree.get(rel)
        row = {"relpath": rel, "in_published": e is not None, "local_exists": local.exists(),
               "storage": None, "match": None, "detail": ""}
        if e is None or not local.exists():
            row["match"] = False
            rows.append(row)
            continue
        if e["mode"] == "120000":  # annexed: compare SHA256 + size from the annex key
            row["storage"] = "annex"
            m = ANNEX_KEY_RE.search(link_targets.get(rel) or "")
            if not m:
                row["detail"] = "annex key not parsed"
                row["match"] = False
            else:
                size, sha = int(m.group(1)), m.group(2)
                row["match"] = (local.stat().st_size == size and sha256_file(local) == sha)
                row["detail"] = f"published sha256={sha} size={size}"
        else:
            row["storage"] = "git"
            row["match"] = git_blob_sha1(local) == e["sha"]
            row["detail"] = f"published git blob={e['sha']}"
        rows.append(row)
    return rows


def unified_diff(a_text: str, b_text: str, a_name: str, b_name: str) -> str:
    return "".join(difflib.unified_diff(a_text.splitlines(True), b_text.splitlines(True), a_name, b_name))


# ------------------------------------------------------------------ A4 manifest scope
def manifest_scope(root: Path, fs_rel: str, rcps_rel: str, petprep_rel: str) -> list[str]:
    root = Path(root)
    rels: list[str] = []

    def add(pattern: str):
        rels.extend(str(p.relative_to(root)) for p in sorted(root.glob(pattern)) if p.is_file())

    for name in TOP_META + (".datalad/config", ".gitattributes"):
        if (root / name).exists():
            rels.append(name)
    add("sub-*/*_sessions.tsv")
    add("sub-*/ses-MRI/anat/*_T1w.nii.gz")
    add("sub-*/ses-MRI/anat/*_T1w.json")
    add(f"{rcps_rel}/dataset_description.json")
    add(f"{rcps_rel}/sub-*/ses-*/*")
    add(f"{fs_rel}/dataset_description.json")
    for f in ("stats/lh.aparc.stats", "stats/rh.aparc.stats", "stats/aseg.stats", "mri/aparc+aseg.mgz",
              "mri/aseg.mgz", "mri/orig.mgz", "mri/rawavg.mgz", "mri/brainmask.mgz", "mri/T1.mgz",
              "scripts/recon-all.done", "scripts/build-stamp.txt", "scripts/recon-all.cmd"):
        add(f"{fs_rel}/sub-*/{f}")
    add(f"{petprep_rel}/dataset_description.json")
    add(f"{petprep_rel}/sub-*/ses-*/pet/*_from-pet_to-T1w_reg.lta")
    return [r for r in rels if not r.endswith(".DS_Store")]


def write_manifest(root: Path, rels: list[str], out_tsv: Path) -> list[dict]:
    rows = []
    for rel in rels:
        p = Path(root) / rel
        st = p.stat()
        rows.append({"relpath": rel, "bytes": st.st_size, "mtime_epoch": int(st.st_mtime), "sha256": sha256_file(p)})
    with open(out_tsv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return rows


# ------------------------------------------------------------------ A5 eligibility
def eligibility(root: Path, fs: Path, rcps: Path, conditions: list[str],
                participants_local: list[str], participants_published: dict[str, list[str]]) -> list[dict]:
    subs = sorted({p.name for p in Path(root).glob("sub-*") if p.is_dir()} |
                  {p.name for p in fs.glob("sub-*") if p.is_dir()} | {p.name for p in rcps.glob("sub-*") if p.is_dir()})
    rows = []
    for s in subs:
        r = {"subject_id": s, "listed_in_local_participants_tsv": s in participants_local}
        for tag, plist in participants_published.items():
            r[f"listed_in_published_{tag}_participants_tsv"] = s in plist
        r["T1w_present"] = any((Path(root) / s / "ses-MRI" / "anat").glob(f"{s}_ses-MRI_T1w.nii.gz"))
        for c in conditions:
            maps = list((rcps / s / f"ses-{c}").glob("*_stat-rCPS_statmap.nii.gz"))
            r[f"{c}_rCPS_present"] = len(maps) == 1
            r[f"{c}_rCPS_n_maps"] = len(maps)
        r["FreeSurfer_recon_done"] = (fs / s / "scripts" / "recon-all.done").exists()
        r["lh_aparc_stats_present"] = (fs / s / "stats" / "lh.aparc.stats").exists()
        r["rh_aparc_stats_present"] = (fs / s / "stats" / "rh.aparc.stats").exists()
        r["aparc_aseg_present"] = (fs / s / "mri" / "aparc+aseg.mgz").exists()
        r["sessions_tsv_present"] = (Path(root) / s / f"{s}_sessions.tsv").exists()
        inputs_ok = all([r["T1w_present"], r["FreeSurfer_recon_done"], r["lh_aparc_stats_present"],
                         r["rh_aparc_stats_present"], r["aparc_aseg_present"]] +
                        [r[f"{c}_rCPS_present"] for c in conditions])
        r["required_inputs_complete"] = inputs_ok
        r["preliminary_eligible_primary_as_planned_N17"] = inputs_ok and r["listed_in_local_participants_tsv"]
        r["preliminary_eligible_SP06_sensitivity"] = inputs_ok if s == "sub-SP06" else None
        r["notes"] = ""
        rows.append(r)
    return rows
