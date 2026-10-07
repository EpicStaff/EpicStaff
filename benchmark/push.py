"""Copy run folders into a clone of EpicStaff/epicstaff-benchmarks, rebuild the index, commit and push."""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
from pathlib import Path

NEVER_PUSHED = {"events_full.csv.gz"}


def contains_secret(run_dir: Path, secret: str | None) -> bool:
    if not secret:
        return False
    needle = secret.encode()
    for path in run_dir.iterdir():
        data = path.read_bytes()
        if path.suffix == ".gz":
            data = gzip.decompress(data)
        if needle in data:
            return True
    return False


def build_index(benchmarks_dir: Path, previous: dict | None) -> dict:
    numbers = {run["folder"]: run["number"] for run in (previous or {}).get("runs", [])}
    metas = []
    for meta_path in benchmarks_dir.glob("*/meta.json"):
        metas.append((meta_path.parent.name, json.loads(meta_path.read_text(encoding="utf-8"))))
    metas.sort(key=lambda item: item[1].get("created_at", ""))
    next_number = max(numbers.values(), default=0) + 1
    runs = []
    for folder, meta in metas:
        if folder not in numbers:
            numbers[folder], next_number = next_number, next_number + 1
        runs.append(
            {
                "number": numbers[folder],
                "folder": folder,
                "created_at": meta.get("created_at"),
                "kind": meta.get("kind"),
                "case": meta.get("case", {}).get("name"),
                "variant": meta.get("case", {}).get("variant"),
                "ref": meta.get("git", {}).get("ref"),
                "sha": (meta.get("git", {}).get("sha") or "")[:7],
                "host": meta.get("host", {}).get("hostname"),
                "note": meta.get("note"),
                "labels": meta.get("labels", []),
                "verdicts": {
                    phase["name"]: phase.get("verdict", {}) for phase in meta.get("phases", [])
                },
            }
        )
    return {"schema_version": 1, "runs": sorted(runs, key=lambda run: run["number"])}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def push(
    run_dirs: list[Path],
    repo: str | None,
    viewer_src: Path,
    api_key: str | None,
    assume_yes: bool,
    ask=input,
) -> None:
    for run_dir in run_dirs:
        if contains_secret(run_dir, api_key):
            raise SystemExit(f"{run_dir}: contains the API key — refusing to push")
    if not repo:
        raise SystemExit("BENCH_RESULTS_REPO is not set (path of your epicstaff-benchmarks clone)")
    repo_path = Path(repo)
    if _git(repo_path, "status", "--porcelain"):
        raise SystemExit(f"{repo_path} has uncommitted changes")
    _git(repo_path, "pull", "--ff-only")
    benchmarks = repo_path / "benchmarks"
    benchmarks.mkdir(exist_ok=True)
    for run_dir in run_dirs:
        target = benchmarks / run_dir.name
        shutil.copytree(
            run_dir,
            target,
            dirs_exist_ok=True,
            ignore=lambda _dir, names: [n for n in names if n in NEVER_PUSHED],
        )
    index_path = benchmarks / "index.json"
    previous = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else None
    index = build_index(benchmarks, previous)
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    shutil.copy2(viewer_src, repo_path / "index.html")
    numbers = {run["folder"]: run["number"] for run in index["runs"]}
    message = "; ".join(f"run #{numbers[d.name]}: {d.name}" for d in run_dirs)
    commands = [
        ["add", "benchmarks", "index.html"],
        ["commit", "-m", message],
        ["push"],
    ]
    print("\n".join("git -C " + str(repo_path) + " " + " ".join(command) for command in commands))
    if not assume_yes and ask("Run these commands? [y/N] ").strip().lower() != "y":
        print(
            "Not pushed. The files are copied; run the commands yourself or `git -C … checkout .` to undo."
        )
        return
    for command in commands:
        _git(repo_path, *command)
    print(f"Pushed {len(run_dirs)} run(s).")
