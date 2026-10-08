"""Copy run folders into a clone of EpicStaff/epicstaff-benchmarks, rebuild the index, commit and push."""

from __future__ import annotations

import gzip
import json
import shlex
import shutil
import subprocess
import zlib
from pathlib import Path

NEVER_PUSHED = {"events_full.csv.gz"}
CHUNK_SIZE = 1024 * 1024  # 1 MiB chunks for secret scanning


def contains_secret(run_dir: Path, secret: str | None) -> bool:
    """Scan run_dir files for secret string with streaming chunks and overlap."""
    if not secret:
        return False
    needle = secret.encode()
    overlap = len(needle) - 1

    # every level: push copies subfolders too (copytree), so a secret there would be published
    for path in run_dir.rglob("*"):
        if path.is_dir() or path.name in NEVER_PUSHED:
            continue

        try:
            if path.suffix == ".gz":
                with gzip.open(path, "rb") as f:
                    buffer = b""
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        buffer += chunk
                        if needle in buffer:
                            return True
                        buffer = buffer[-overlap:]
            else:
                with open(path, "rb") as f:
                    buffer = b""
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        buffer += chunk
                        if needle in buffer:
                            return True
                        buffer = buffer[-overlap:]
        except (OSError, EOFError, gzip.BadGzipFile, zlib.error) as error:
            raise SystemExit(f"{path}: cannot be read ({error}) — refusing to push") from None

    return False


def build_index(
    benchmarks_dir: Path, previous: dict | None, extra_metas: list[tuple[str, dict]] | None = None
) -> dict:
    """Build index from existing benchmarks and optional extra run metadata.

    extra_metas: list of (folder_name, meta_dict) for runs not yet in benchmarks_dir or re-pushed runs.
    If a folder in extra_metas already exists in benchmarks_dir, it replaces the existing entry.
    """
    numbers = {run["folder"]: run["number"] for run in (previous or {}).get("runs", [])}
    metas = []
    for meta_path in benchmarks_dir.glob("*/meta.json"):
        metas.append((meta_path.parent.name, json.loads(meta_path.read_text(encoding="utf-8"))))

    # Add extra_metas (incoming runs being pushed), replacing any existing entry with same folder name
    if extra_metas:
        extra_folders = {folder for folder, _ in extra_metas}
        metas = [(folder, meta) for folder, meta in metas if folder not in extra_folders]
        metas.extend(extra_metas)

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
    """Run git command in repo_path, return stdout. Raise SystemExit on error with stderr."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except FileNotFoundError:
        raise SystemExit("git is not installed or not on PATH") from None
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"git {' '.join(args)} failed: {error.stderr.strip()}") from None


def push(
    run_dirs: list[Path],
    repo: str | None,
    viewer_src: Path,
    api_key: str | None,
    assume_yes: bool,
    ask=input,
) -> None:
    """Push runs to the results repo. Confirm all preconditions BEFORE touching the clone.

    Order: (a) secret scan; (b) validate repo/viewer/clone; (c) dry-run compute targets;
    (d) print plan; (e) ask; (f) only then copy and git.
    """
    # (a) Scan for secrets in all run dirs
    for run_dir in run_dirs:
        if contains_secret(run_dir, api_key):
            raise SystemExit(f"{run_dir}: contains the API key — refusing to push")

    # (b) Validate prerequisites
    if not repo:
        raise SystemExit("BENCH_RESULTS_REPO is not set (path of your epicstaff-benchmarks clone)")
    if not viewer_src.exists():
        raise SystemExit(f"viewer_src does not exist: {viewer_src}")

    repo_path = Path(repo)

    # Check clone is clean and pull
    status = _git(repo_path, "status", "--porcelain")
    if status:
        raise SystemExit(f"{repo_path} has uncommitted changes")
    _git(repo_path, "pull", "--ff-only")

    # (c) Dry-run: compute target folders and run numbers without writing
    benchmarks = repo_path / "benchmarks"
    previous = None
    index_path = benchmarks / "index.json"
    if index_path.exists():
        previous = json.loads(index_path.read_text(encoding="utf-8"))

    # Load metadata from incoming runs for dry-run index calculation
    extra_metas = []
    for run_dir in run_dirs:
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        extra_metas.append((run_dir.name, meta))

    dry_index = build_index(benchmarks, previous, extra_metas)
    numbers = {run["folder"]: run["number"] for run in dry_index["runs"]}

    # (d) Print the plan with shlex.join for proper quoting
    print(f"Will copy {len(run_dirs)} run(s):")
    for run_dir in run_dirs:
        print(f"  run #{numbers[run_dir.name]}: {run_dir.name}")

    message = "; ".join(f"run #{numbers[d.name]}: {d.name}" for d in run_dirs)
    commands = [
        ["add", "benchmarks", "index.html"],
        ["commit", "-m", message],
        ["push"],
    ]
    print(
        "\n".join(
            f"git -C {shlex.quote(str(repo_path))} {shlex.join(command)}" for command in commands
        )
    )

    # (e) Ask before writing anything
    if not assume_yes and ask("Run these commands? [y/N] ").strip().lower() != "y":
        print("Nothing was changed.")
        return

    # (f) Only now: copy, write, and git
    benchmarks.mkdir(exist_ok=True)
    for run_dir in run_dirs:
        target = benchmarks / run_dir.name
        shutil.copytree(
            run_dir,
            target,
            dirs_exist_ok=True,
            ignore=lambda _dir, names: [n for n in names if n in NEVER_PUSHED],
        )

    index_path.write_text(json.dumps(dry_index, indent=2), encoding="utf-8")
    shutil.copy2(viewer_src, repo_path / "index.html")

    # Check if anything is actually new to commit
    status_after = _git(repo_path, "status", "--porcelain")
    if not status_after:
        print("Nothing new to push.")
        return

    for command in commands:
        _git(repo_path, *command)
    print(f"Pushed {len(run_dirs)} run(s).")
