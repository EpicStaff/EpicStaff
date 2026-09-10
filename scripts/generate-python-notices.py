#!/usr/bin/env python3
"""
Generates scripts/python-notices-partial.md.

Scope: production Python dependencies of every backend microservice under
src/. For each service that has a pyproject.toml the script reconciles its
.venv via `uv sync --frozen --no-install-project --all-groups --no-group
<group>` for every dev/test group (regenerating the lock with `uv lock` first
if none is found), installs pip-licenses into that venv, scrapes license
metadata and license texts, then removes pip-licenses.

The excluded groups are computed per service, not hardcoded: the script reads
each service's own `[dependency-groups]` table and excludes only dev/test
TOOLING groups (dev, test, tests, lint, typing, docs). Non-dev PRODUCTION
groups — e.g. knowledge's `graphrag` (pulls networkx, pyarrow via a vendored
path dependency), crew's `dotdict`, or the `secfloor` group most services
declare — are deliberately INCLUDED, because the corresponding Dockerfiles
install them too (`uv sync --frozen --no-install-project --all-groups`
there, not a plain `uv sync`, which only installs main + the "dev" group).
Excluding them previously caused real shipped dependencies to be missing from
the notices. Packages present in multiple services are deduplicated by name +
version.

The output is a partial Markdown fragment intended to be stitched into
THIRD-PARTY-NOTICES.md by scripts/merge-notices.py. Idempotent — re-running
overwrites the partial in place.

Usage (from repository root):
    python scripts/generate-python-notices.py

Requires: Python 3.12+ with uv installed (`uv` must be on PATH).
Only stdlib is imported by this script itself.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
OUTPUT_FILE = SCRIPTS_DIR / "python-notices-partial.md"

SERVICES = [
    "src/django_app",
    "src/crew",
    "src/agent",
    "src/manager",
    "src/knowledge",
    "src/realtime",
    "src/sandbox",
    "src/webhook",
    "src/auditor",
]

BOOTSTRAP_PACKAGES = {
    "pip",
    "pip-licenses",
    "prettytable",
    "wcwidth",
    "setuptools",
    "wheel",
    "piplicenses",
}

# Vendored / local path dependencies (uv.lock `source = { directory = ... }`,
# already listed separately under VENDORED below where applicable) that must
# not also appear as a regular third-party package in the index: "dotdict"
# (src/shared/dotdict) and "graphrag" (src/knowledge/libraries/graphrag).
FIRST_PARTY_NAMES: frozenset[str] = frozenset({"dotdict", "graphrag"})
FIRST_PARTY_AUTHOR_DOMAINS: tuple[str, ...] = ("hys-enterprise.com",)

# Dependency-group names treated as dev/test TOOLING and excluded via
# `uv sync --no-group`. Anything else a service declares (graphrag,
# dotdict, secfloor, ...) is a production group and stays installed, matching
# what that service's Dockerfile actually ships.
DEV_GROUP_NAMES: frozenset[str] = frozenset(
    {"dev", "test", "tests", "lint", "typing", "docs"}
)

# C6 — SPDX overrides for packages whose PyPI metadata declares the wrong license.
# Each entry confirmed by reading the actual shipped LICENSE body text from the wheel.
SPDX_OVERRIDES: dict[str, str] = {
    "pywin32": "LGPL-2.1",  # metadata says PSF; wheel ships GNU LGPL v2.1 text
    "chroma-hnswlib": "Apache-2.0",  # metadata UNKNOWN; wheel ships Apache-2.0 text
    "embedchain": "Apache-2.0",  # metadata Other/Proprietary; wheel ships Apache-2.0 text
}

VENDORED = [
    {
        "name": "graphrag",
        "version": "vendored fork (modified)",
        "license": "MIT",
        "copyright": "Copyright (c) Microsoft Corporation",
        "source": "https://github.com/microsoft/graphrag",
        "note": "vendored with local modifications (see src/knowledge/libraries/graphrag/)",
    },
]


def log(msg: str) -> None:
    print(f"[python-notices] {msg}", file=sys.stderr)


def get_git_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()
    except subprocess.CalledProcessError:
        return "UNKNOWN"


def lock_hash(svc_dir: Path) -> str:
    lock = svc_dir / "uv.lock"
    if not lock.exists():
        return "no-lock"
    return hashlib.sha256(lock.read_bytes()).hexdigest()[:16]


def load_pyproject(svc_dir: Path) -> dict:
    """Parse a service's pyproject.toml. Returns {} if missing/unreadable."""
    pyproject = svc_dir / "pyproject.toml"
    if not pyproject.exists():
        return {}
    with pyproject.open("rb") as f:
        return tomllib.load(f)


def dependency_group_names(svc_dir: Path) -> set[str]:
    """Names of the `[dependency-groups]` table declared by this service's
    pyproject.toml, e.g. {"dev", "secfloor", "graphrag"} for knowledge,
    {"dev", "secfloor", "dotdict"} for crew."""
    data = load_pyproject(svc_dir)
    groups = data.get("dependency-groups", {})
    return set(groups.keys())


def dev_group_names(svc_dir: Path) -> list[str]:
    """Groups to pass to `uv sync --no-group` for this service: only the
    dev/test tooling groups it declares (see DEV_GROUP_NAMES).
    Production-only groups (graphrag, dotdict, secfloor, ...) are
    intentionally kept installed — they ship in the service's Docker image
    and must be captured in the notices."""
    declared = dependency_group_names(svc_dir)
    excluded = {g for g in declared if g.lower() in DEV_GROUP_NAMES}
    return sorted(excluded)


def project_name(svc_dir: Path) -> str | None:
    """The service's own root/self package name, e.g. "webhook",
    "epicstaff-graph" for crew, "realtime", "knowledge", "auditor". Used to
    exclude a service's own first-party package from the notices even if it
    ended up installed in the venv (stale venv predating
    `--no-install-project`, or a developer running a plain `uv sync
    --all-groups`).

    Read from PEP 621 `[project].name` — the only place these projects
    declare their name."""
    data = load_pyproject(svc_dir)
    name = data.get("project", {}).get("name")
    return normalize_name(name) if name else None


def uv_sync_cmd(svc_dir: Path) -> list[str]:
    """Build the `uv sync --frozen --no-install-project --all-groups
    [--no-group ...]` command for this service.

    `--all-groups` matches what the service's own Dockerfile installs (main +
    every dependency group) — a plain `uv sync` would install main + the
    "dev" group only. `--no-group` then strips back out just the dev/test
    tooling groups this service declares, so production-only groups
    (graphrag, dotdict, secfloor, ...) install the same way the Dockerfile
    installs them."""
    cmd = ["uv", "sync", "--frozen", "--no-install-project", "--all-groups"]
    for group in dev_group_names(svc_dir):
        cmd += ["--no-group", group]
    return cmd


def run(
    cmd: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    log("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=True,
        text=True,
    )


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def bootstrap_venv(svc_dir: Path) -> Path | None:
    """Ensure the venv has exactly the production dependency groups
    installed (main + any non-dev/test groups such as graphrag, dotdict,
    secfloor) and no project/self package.
    Returns the venv directory Path on success, None on failure.

    Strategy:
    1. Sync with `uv sync --frozen --no-install-project --all-groups
       --no-group <dev/test groups>`. This always runs, even if a .venv
       already exists — a stale venv (created before this fix, or with the
       wrong group scope) must reconcile to the correct scope rather than
       being reused as-is. `--no-install-project` never installs the
       service's own package, so there is no after-the-fact uninstall step
       to run.
    2. If no lock is found, regenerate one with `uv lock` and retry once.
    3. The venv always lands at the deterministic `.venv` under the service
       directory — that is where `uv sync` puts it, so there is nothing to
       query for.
    """
    pyproject = svc_dir / "pyproject.toml"
    if not pyproject.exists():
        log(f"  skip {svc_dir.name}: no pyproject.toml")
        return None

    venv_dir = svc_dir / ".venv"
    already_has_venv = venv_dir.exists() and venv_python(venv_dir).exists()
    excluded = dev_group_names(svc_dir)
    excluded_desc = ",".join(excluded) if excluded else "(none)"
    if already_has_venv:
        log(
            f"  {svc_dir.name}: .venv exists — reconciling (--no-group {excluded_desc})"
        )
    else:
        log(f"  {svc_dir.name}: no .venv — bootstrapping (--no-group {excluded_desc})")

    try:
        run(uv_sync_cmd(svc_dir), cwd=svc_dir)
        log(f"  {svc_dir.name}: uv sync done")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        if "lock" not in stderr.lower():
            log(f"  {svc_dir.name}: uv sync failed: {stderr[:400]}")
            return None
        log(f"  {svc_dir.name}: no usable lock — running uv lock")
        try:
            run(["uv", "lock"], cwd=svc_dir)
        except subprocess.CalledProcessError as lock_exc:
            log(f"  {svc_dir.name}: uv lock failed: {lock_exc.stderr.strip()[:400]}")
            return None
        try:
            run(uv_sync_cmd(svc_dir), cwd=svc_dir)
            log(f"  {svc_dir.name}: uv sync done")
        except subprocess.CalledProcessError as retry_exc:
            log(
                f"  {svc_dir.name}: uv sync failed after relock: {retry_exc.stderr.strip()[:400]}"
            )
            return None

    if not venv_dir.exists() or not venv_python(venv_dir).exists():
        log(f"  {svc_dir.name}: could not locate venv after sync")
        return None

    log(f"  {svc_dir.name}: venv at {venv_dir}")
    return venv_dir


def run_pip_licenses(py: Path) -> list[dict]:
    proc = run(
        [
            str(py),
            "-m",
            "piplicenses",
            "--format=json",
            "--with-license-file",
            "--with-notice-file",
            "--no-license-path",
            # Required for the FIRST_PARTY_AUTHOR_DOMAINS check below: without
            # --with-authors, pip-licenses' JSON rows never include an
            # "Author" key at all (it's not a default column), so
            # entry.get("Author") was always empty and that check never
            # fired for ANY package.
            "--with-authors",
        ],
        check=True,
    )
    return json.loads(proc.stdout)


def normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def scan_service_venv(svc_dir: Path) -> list[dict]:
    """Ensure venv exists, install pip-licenses, scan, uninstall.
    Returns raw pip-licenses JSON entries."""
    venv_dir = bootstrap_venv(svc_dir)
    if venv_dir is None:
        return []

    py = venv_python(venv_dir)

    log(f"  installing pip-licenses into {svc_dir.name}/.venv")
    try:
        # `uv pip install --python`, not `python -m pip install`: uv-managed
        # venvs are not seeded with pip by default, so the target venv's own
        # pip module may not exist at all.
        run(["uv", "pip", "install", "--python", str(py), "pip-licenses"], check=True)
    except subprocess.CalledProcessError as exc:
        log(
            f"  pip-licenses install failed for {svc_dir.name}: {exc.stderr.strip()[:300]}"
        )
        return []

    try:
        entries = run_pip_licenses(py)
        log(f"  {svc_dir.name}: found {len(entries)} packages")
        return entries
    except subprocess.CalledProcessError as exc:
        log(f"  pip-licenses failed for {svc_dir.name}: {exc.stderr.strip()[:300]}")
        return []
    finally:
        try:
            run(
                [
                    "uv",
                    "pip",
                    "uninstall",
                    "--python",
                    str(py),
                    "pip-licenses",
                    "prettytable",
                    "wcwidth",
                ],
                check=False,
            )
        except Exception:
            pass


def is_internal_placeholder_package(version: str, entry: dict) -> bool:
    """Secondary safety net for a first-party root/path package that isn't
    caught by name (FIRST_PARTY_NAMES / a service's own project_name) or
    by author domain — e.g. a future service added without updating those
    lists. Deliberately narrow: internal scaffold packages are version
    0.1.0 (the default for a freshly scaffolded project) AND ship no SPDX
    license AND no license text. A real PyPI package matching all three simultaneously
    would be extremely unusual for something actually used in production."""
    if version != "0.1.0":
        return False
    spdx = (entry.get("License") or "UNKNOWN").strip() or "UNKNOWN"
    license_text = (entry.get("LicenseText") or "UNKNOWN").strip() or "UNKNOWN"
    return spdx.upper() == "UNKNOWN" and license_text.upper() == "UNKNOWN"


def collect_packages() -> dict[tuple[str, str], dict]:
    """Scan each service's .venv with pip-licenses and return a deduplicated
    dict keyed by (normalized_name, version)."""
    packages: dict[tuple[str, str], dict] = {}
    skipped: list[str] = []

    # Each service's own project name (e.g. "webhook", "epicstaff-graph" for
    # crew, "realtime") — read dynamically from each pyproject.toml rather
    # than hardcoded, so it stays correct if a service's project name ever
    # changes.
    first_party_root_names = {
        root_name
        for svc_rel in SERVICES
        if (root_name := project_name(REPO_ROOT / svc_rel)) is not None
    }

    for svc_rel in SERVICES:
        svc = REPO_ROOT / svc_rel
        log(f"scanning {svc_rel}")
        entries = scan_service_venv(svc)
        if not entries:
            skipped.append(svc_rel)
            continue
        for entry in entries:
            name = entry.get("Name") or ""
            version = entry.get("Version") or ""
            if not name or normalize_name(name) in BOOTSTRAP_PACKAGES:
                continue
            if normalize_name(name) in FIRST_PARTY_NAMES:
                log(f"  skipping first-party package: {name}")
                continue
            if normalize_name(name) in first_party_root_names:
                log(f"  skipping first-party package (service root package): {name}")
                continue
            author_raw = (entry.get("Author") or "").strip().lower()
            if any(domain in author_raw for domain in FIRST_PARTY_AUTHOR_DOMAINS):
                log(f"  skipping first-party package (author domain): {name}")
                continue
            if is_internal_placeholder_package(version, entry):
                log(
                    f"  skipping first-party package (unversioned internal, no license): "
                    f"{name}@{version}"
                )
                continue
            key = (normalize_name(name), version)
            if key in packages:
                continue
            license_raw = (entry.get("LicenseText") or "").strip()
            notice_raw = (entry.get("NoticeText") or "").strip()
            spdx_raw = (entry.get("License") or "UNKNOWN").strip() or "UNKNOWN"
            spdx = spdx_raw.splitlines()[0].strip() if "\n" in spdx_raw else spdx_raw
            if len(spdx) > 120:
                spdx = spdx[:117] + "..."
            # C6 — apply known SPDX overrides
            spdx = SPDX_OVERRIDES.get(normalize_name(name), spdx)
            packages[key] = {
                "name": name,
                "version": version,
                "license": spdx,
                "license_text": "" if license_raw == "UNKNOWN" else license_raw,
                "license_text_missing": license_raw == "UNKNOWN",
                "notice_text": "" if notice_raw == "UNKNOWN" else notice_raw,
                "notice_text_missing": notice_raw == "UNKNOWN",
                "author": (entry.get("Author") or "").strip(),
                "url": (entry.get("URL") or "").strip(),
            }

    if skipped:
        log(
            f"services skipped (bootstrap failed or no pyproject.toml): {', '.join(skipped)}"
        )

    return packages


def derive_copyright(pkg: dict) -> str:
    text = pkg.get("license_text", "")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("copyright"):
            return stripped
    author = pkg.get("author") or ""
    if author and author.lower() not in ("unknown", "none"):
        return f"Copyright (c) {author}"
    return ""


def build_markdown(
    packages: dict[tuple[str, str], dict], provenance: dict[str, str]
) -> str:
    sorted_pkgs = sorted(
        packages.values(), key=lambda p: (p["name"].lower(), p["version"])
    )

    dist: dict[str, int] = defaultdict(int)
    for pkg in sorted_pkgs:
        dist[pkg["license"] or "UNKNOWN"] += 1

    lines: list[str] = []
    lines.append("<!-- AUTO-GENERATED — do not edit by hand -->")
    lines.append(f"<!-- generated: {provenance['date']} UTC -->")
    lines.append(f"<!-- commit: {provenance['sha']} -->")
    lines.append(f"<!-- lock-hashes: {provenance['lock_hashes']} -->")
    lines.append("")
    lines.append("## Backend (Python)")
    lines.append("")
    lines.append(
        "This section lists third-party Python packages bundled into EpicStaff backend microservices "
        "(`src/django_app`, `src/crew`, `src/agent`, `src/manager`, `src/knowledge`, `src/realtime`, "
        "`src/sandbox`, `src/webhook`, `src/auditor`). Dev / test dependencies are excluded. "
        "Packages present in multiple services are deduplicated by `name + version`."
    )
    lines.append("")

    lines.append("### Python license summary")
    lines.append("")
    lines.append("| License | Packages |")
    lines.append("|---|---|")
    for lic, cnt in sorted(dist.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {lic} | {cnt} |")
    lines.append(f"| **Total** | **{len(sorted_pkgs)}** |")
    lines.append("")

    lines.append("### Python package index")
    lines.append("")
    lines.append("| Package | Version | License | Copyright |")
    lines.append("|---|---|---|---|")
    for pkg in sorted_pkgs:
        cp = derive_copyright(pkg).replace("|", "\\|")
        lic = (pkg["license"] or "UNKNOWN").replace("|", "\\|")
        lines.append(f"| `{pkg['name']}` | {pkg['version']} | {lic} | {cp} |")
    lines.append("")

    lines.append("### Vendored Libraries")
    lines.append("")
    lines.append("| Package | Version | License | Note |")
    lines.append("|---|---|---|---|")
    for v in VENDORED:
        lines.append(
            f"| `{v['name']}` | {v['version']} | {v['license']} | {v['note']} |"
        )
    lines.append("")
    lines.append(
        "Vendored libraries live inside the repository tree (not pulled from PyPI at install time). "
        "Their upstream copyright notices and licenses are preserved in the corresponding source "
        "directories; the entries above record the SPDX identifier and upstream attribution."
    )
    lines.append("")

    lines.append("---")
    lines.append("<!-- LICENSE TEXTS -->")
    lines.append("")
    lines.append("### Python package notices")
    lines.append("")
    lines.append(
        "Per-package license texts. When the upstream package ships a LICENSE / NOTICE file, "
        "its verbatim text is included below; otherwise the SPDX identifier above is the binding "
        "record."
    )
    lines.append("")

    for pkg in sorted_pkgs:
        lines.append(f"#### {pkg['name']}@{pkg['version']}")
        lines.append("")
        lines.append(f"- **License:** {pkg['license'] or 'UNKNOWN'}")
        if pkg.get("author"):
            lines.append(f"- **Author:** {pkg['author']}")
        if pkg.get("url"):
            lines.append(f"- **URL:** {pkg['url']}")
        lines.append("")
        license_text = pkg.get("license_text", "")
        notice_text = pkg.get("notice_text", "")
        license_text_missing = pkg.get("license_text_missing", False)
        notice_text_missing = pkg.get("notice_text_missing", False)
        if not license_text and not notice_text:
            if license_text_missing:
                lines.append("> No LICENSE file shipped by upstream wheel.")
            else:
                lines.append("> :warning: License text not found — verify manually")
            if notice_text_missing:
                lines.append("> No NOTICE file shipped by upstream.")
            lines.append("")
            continue
        if license_text:
            safe = (
                license_text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            lines.append("<details><summary>License text</summary>")
            lines.append("")
            lines.append("<pre>")
            lines.append(safe)
            lines.append("</pre>")
            lines.append("")
            lines.append("</details>")
            lines.append("")
        elif license_text_missing:
            lines.append("> No LICENSE file shipped by upstream wheel.")
            lines.append("")
        if notice_text:
            safe = (
                notice_text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            lines.append("<details><summary>NOTICE</summary>")
            lines.append("")
            lines.append("<pre>")
            lines.append(safe)
            lines.append("</pre>")
            lines.append("")
            lines.append("</details>")
            lines.append("")
        elif notice_text_missing:
            lines.append("> No NOTICE file shipped by upstream.")
            lines.append("")

    lines.append("### Vendored library notices")
    lines.append("")
    for v in VENDORED:
        lines.append(f"#### {v['name']} ({v['version']})")
        lines.append("")
        lines.append(f"- **License:** {v['license']}")
        lines.append(f"- **Copyright:** {v['copyright']}")
        lines.append(f"- **Source:** {v['source']}")
        lines.append(f"- **Note:** {v['note']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    sha = get_git_sha()
    date = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    lock_hashes_str = ", ".join(
        f"{Path(svc).name}:{lock_hash(REPO_ROOT / svc)}" for svc in SERVICES
    )
    provenance = {"sha": sha, "date": date, "lock_hashes": lock_hashes_str}
    log(f"provenance: commit={sha[:12]}, date={date}")

    packages = collect_packages()
    md = build_markdown(packages, provenance)
    OUTPUT_FILE.write_text(md, encoding="utf-8", newline="\n")
    log(f"discovered {len(packages)} unique backend packages")
    log(f"wrote {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
