#!/usr/bin/env python3
"""
Generates scripts/python-notices-partial.md.

Scope: production Python dependencies of every backend microservice under
src/. For each service that has a pyproject.toml the script reconciles its
.venv via `python -m poetry install --no-root --without <groups>` (regenerating
if needed), installs pip-licenses into that venv, scrapes license metadata and
license texts, then removes pip-licenses.

The `--without` groups are computed per service, not hardcoded: the script
parses each service's own `[tool.poetry.group.<name>.dependencies]` tables and
excludes only dev/test TOOLING groups (dev, test, tests, lint, typing, docs).
Non-dev PRODUCTION groups — e.g. knowledge's `graphrag` (pulls networkx,
pyarrow via a vendored path dependency) or crew's `crew` / `dotdict` — are
deliberately INCLUDED, because the corresponding Dockerfiles install them too
(`poetry install` / `--only crew,dotdict` there, not `--only main`). Excluding
them previously caused real shipped dependencies to be missing from the
notices. Packages present in multiple services are deduplicated by name +
version.

The output is a partial Markdown fragment intended to be stitched into
THIRD-PARTY-NOTICES.md by scripts/merge-notices.py. Idempotent — re-running
overwrites the partial in place.

Usage (from repository root):
    python scripts/generate-python-notices.py

Requires: Python 3.12+ with poetry installed (`python -m poetry` must work).
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
    "src/voice_app",
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

FIRST_PARTY_NAMES: frozenset[str] = frozenset({"dotdict"})
FIRST_PARTY_AUTHOR_DOMAINS: tuple[str, ...] = ("hys-enterprise.com",)

# Poetry dependency-group names treated as dev/test TOOLING and excluded via
# `poetry install --without`. Anything else a service declares (graphrag,
# crew, dotdict, ...) is a production group and stays installed, matching
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
    lock = svc_dir / "poetry.lock"
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


def poetry_group_names(svc_dir: Path) -> set[str]:
    """Names of `[tool.poetry.group.<name>.dependencies]` tables declared by
    this service's pyproject.toml, e.g. {"dev", "graphrag"} for knowledge,
    {"dev", "crew", "dotdict"} for crew."""
    data = load_pyproject(svc_dir)
    groups = data.get("tool", {}).get("poetry", {}).get("group", {})
    return set(groups.keys())


def poetry_without_groups(svc_dir: Path) -> list[str]:
    """Groups to pass to `poetry install --without` for this service: only
    the dev/test tooling groups it declares (see DEV_GROUP_NAMES).
    Production-only groups (graphrag, crew, dotdict, ...) are intentionally
    kept installed — they ship in the service's Docker image and must be
    captured in the notices."""
    declared = poetry_group_names(svc_dir)
    excluded = {g for g in declared if g.lower() in DEV_GROUP_NAMES}
    return sorted(excluded)


def poetry_root_name(svc_dir: Path) -> str | None:
    """The service's own root/self package name, e.g. "webhook",
    "crewai-sheets-ui" for crew, "backend" for realtime, "knowledge",
    "voice-app". Used to exclude a service's own first-party package from
    the notices even if it ended up installed in the venv (stale venv
    predating `--no-root`, or a developer running a plain `poetry install`).

    Poetry 2.x projects declare the name either the legacy way
    (`[tool.poetry].name`) or via PEP 621 (`[project].name`, used by e.g.
    knowledge and voice_app here) — both are checked, legacy takes
    precedence if a project somehow declares both."""
    data = load_pyproject(svc_dir)
    name = data.get("tool", {}).get("poetry", {}).get("name") or data.get(
        "project", {}
    ).get("name")
    return normalize_name(name) if name else None


def poetry_install_cmd(svc_dir: Path, dry_run: bool = False) -> list[str]:
    """Build the `poetry install --no-root [--without ...] [--dry-run]`
    command for this service. Excludes only the dev/test tooling groups it
    declares, so production-only groups install the same way the service's
    own Dockerfile installs them."""
    cmd = [sys.executable, "-m", "poetry", "install", "--no-root"]
    without = poetry_without_groups(svc_dir)
    if without:
        cmd += ["--without", ",".join(without)]
    if dry_run:
        cmd.append("--dry-run")
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


def poetry_venv_path(svc_dir: Path) -> Path | None:
    """Ask poetry where the venv for this service lives. Returns None on error."""
    try:
        proc = run(
            [sys.executable, "-m", "poetry", "env", "info", "--path"],
            cwd=svc_dir,
            check=True,
        )
        p = proc.stdout.strip()
        return Path(p) if p else None
    except subprocess.CalledProcessError:
        return None


def uninstall_stale_root_package(venv_dir: Path, svc_dir: Path) -> None:
    """Best-effort removal of the service's own root package from its venv.

    `--no-root` only stops a *fresh* `poetry install` from installing the
    root package — it does not retroactively remove one that is already
    present (e.g. a venv created before this script passed --no-root, or by
    a developer running a plain `poetry install`). Left in place, that
    self-package (e.g. webhook 0.1.0) leaks into the notices as a first-party
    package with no license. Uninstalling it here is idempotent: a no-op if
    it was never installed."""
    root_name = poetry_root_name(svc_dir)
    if not root_name:
        return
    py = venv_python(venv_dir)
    run([str(py), "-m", "pip", "uninstall", "--quiet", "-y", root_name], check=False)


def bootstrap_venv(svc_dir: Path) -> Path | None:
    """Ensure the venv has exactly the production dependency groups
    installed (main + any non-dev/test groups such as graphrag, crew,
    dotdict) and no leftover root/self package.
    Returns the venv directory Path on success, None on failure.

    Strategy:
    1. If lock is outdated (pyproject.toml changed), regenerate with `poetry lock`.
    2. Install with `poetry install --no-root --without <dev/test groups>`.
       This always runs, even if a .venv already exists — a stale venv
       (created before this fix, with the wrong group scope, or with the
       root package installed) must reconcile to the correct scope rather
       than being reused as-is.
    3. Locate the venv via `poetry env info --path` (works whether in-project or cached).
    4. Remove any stale root-package install left over from before --no-root.
    """
    pyproject = svc_dir / "pyproject.toml"
    if not pyproject.exists():
        log(f"  skip {svc_dir.name}: no pyproject.toml")
        return None

    in_project_venv = svc_dir / ".venv"
    already_has_venv = (
        in_project_venv.exists() and venv_python(in_project_venv).exists()
    )
    without = poetry_without_groups(svc_dir)
    without_desc = ",".join(without) if without else "(none)"
    if already_has_venv:
        log(f"  {svc_dir.name}: .venv exists — reconciling (--without {without_desc})")
    else:
        log(f"  {svc_dir.name}: no .venv — bootstrapping (--without {without_desc})")

    # If lock is outdated regenerate it (Poetry 2.x dropped --no-update flag).
    try:
        run(poetry_install_cmd(svc_dir, dry_run=True), cwd=svc_dir)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        if "poetry.lock was last generated" in stderr or "lock" in stderr.lower():
            log(f"  {svc_dir.name}: lock outdated — running poetry lock")
            try:
                run([sys.executable, "-m", "poetry", "lock"], cwd=svc_dir)
            except subprocess.CalledProcessError as lock_exc:
                log(
                    f"  {svc_dir.name}: poetry lock failed: {lock_exc.stderr.strip()[:400]}"
                )
                return None

    # Install deps (production groups only).
    try:
        run(poetry_install_cmd(svc_dir), cwd=svc_dir)
        log(f"  {svc_dir.name}: poetry install done")
    except subprocess.CalledProcessError as exc:
        log(f"  {svc_dir.name}: poetry install failed: {exc.stderr.strip()[:400]}")
        return None

    # Locate the venv (may be in-project or in poetry cache).
    venv_dir = poetry_venv_path(svc_dir)
    if venv_dir is None or not venv_python(venv_dir).exists():
        log(f"  {svc_dir.name}: could not locate venv after install")
        return None

    uninstall_stale_root_package(venv_dir, svc_dir)

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
        run([str(py), "-m", "pip", "install", "--quiet", "pip-licenses"], check=True)
    except subprocess.CalledProcessError as exc:
        log(
            f"  pip install pip-licenses failed for {svc_dir.name}: {exc.stderr.strip()[:300]}"
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
                    str(py),
                    "-m",
                    "pip",
                    "uninstall",
                    "--quiet",
                    "-y",
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
    caught by name (FIRST_PARTY_NAMES / a service's own poetry_root_name) or
    by author domain — e.g. a future service added without updating those
    lists. Deliberately narrow: internal scaffold packages are version
    0.1.0 (poetry's default for a new project) AND ship no SPDX license AND
    no license text. A real PyPI package matching all three simultaneously
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

    # Each service's own root package name (e.g. "webhook", "crewai-sheets-ui"
    # for crew, "backend" for realtime) — read dynamically from each
    # pyproject.toml rather than hardcoded, so it stays correct if a
    # service's poetry project name ever changes.
    first_party_root_names = {
        root_name
        for svc_rel in SERVICES
        if (root_name := poetry_root_name(REPO_ROOT / svc_rel)) is not None
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
        "`src/sandbox`, `src/webhook`, `src/voice_app`). Dev / test dependencies are excluded. "
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
