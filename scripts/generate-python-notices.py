#!/usr/bin/env python3
"""
Generates scripts/python-notices-partial.md.

Scope: production Python dependencies of every backend microservice under
src/. For each service that has a pyproject.toml the script ensures a .venv
exists (bootstrapping it via `python -m poetry install --only main --no-root`
if needed), installs pip-licenses into that venv, scrapes license metadata and
license texts, then removes pip-licenses. Dev / test groups are excluded.
Packages present in multiple services are deduplicated by name + version.

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
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
OUTPUT_FILE = SCRIPTS_DIR / "python-notices-partial.md"

SERVICES = [
    "src/django_app",
    "src/crew",
    "src/manager",
    "src/knowledge",
    "src/realtime",
    "src/sandbox",
    "src/webhook",
    "src/tool",
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

# C6 — SPDX overrides for packages whose PyPI metadata declares the wrong license.
# Each entry confirmed by reading the actual shipped LICENSE body text from the wheel.
SPDX_OVERRIDES: dict[str, str] = {
    "pywin32": "LGPL-2.1",  # metadata says PSF; wheel ships GNU LGPL v2.1 text
    "chroma-hnswlib": "Apache-2.0",  # metadata UNKNOWN; wheel ships Apache-2.0 text
    "crewai-tools": "MIT",  # metadata UNKNOWN; wheel ships MIT text
    "embedchain": "Apache-2.0",  # metadata Other/Proprietary; wheel ships Apache-2.0 text
}

VENDORED = [
    {
        "name": "crewAI",
        "version": "vendored fork",
        "license": "MIT",
        "copyright": "Copyright (c) 2025 crewAI, Inc.",
        "source": "https://github.com/crewAIInc/crewAI",
        "note": "vendored, unmodified",
    },
    {
        "name": "mem0",
        "version": "vendored fork",
        "license": "Apache-2.0",
        "copyright": "Copyright (c) 2024 Mem0 AI",
        "source": "https://github.com/mem0ai/mem0",
        "note": "vendored, unmodified",
    },
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


def bootstrap_venv(svc_dir: Path) -> Path | None:
    """Ensure a venv exists and main deps are installed.
    Returns the venv directory Path on success, None on failure.

    Strategy:
    1. If lock is outdated (pyproject.toml changed), regenerate with `poetry lock`.
    2. Install with `poetry install --only main --no-root`.
    3. Locate the venv via `poetry env info --path` (works whether in-project or cached).
    """
    pyproject = svc_dir / "pyproject.toml"
    if not pyproject.exists():
        log(f"  skip {svc_dir.name}: no pyproject.toml")
        return None

    # Fast path: existing .venv in project dir.
    in_project_venv = svc_dir / ".venv"
    if in_project_venv.exists() and venv_python(in_project_venv).exists():
        return in_project_venv

    log(f"  {svc_dir.name}: no .venv — bootstrapping via poetry")

    # If lock is outdated regenerate it (Poetry 2.x dropped --no-update flag).
    try:
        run(
            [
                sys.executable,
                "-m",
                "poetry",
                "install",
                "--only",
                "main",
                "--no-root",
                "--dry-run",
            ],
            cwd=svc_dir,
        )
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

    # Install main deps.
    try:
        run(
            [sys.executable, "-m", "poetry", "install", "--only", "main", "--no-root"],
            cwd=svc_dir,
        )
        log(f"  {svc_dir.name}: poetry install done")
    except subprocess.CalledProcessError as exc:
        log(f"  {svc_dir.name}: poetry install failed: {exc.stderr.strip()[:400]}")
        return None

    # Locate the venv (may be in-project or in poetry cache).
    venv_dir = poetry_venv_path(svc_dir)
    if venv_dir is None or not venv_python(venv_dir).exists():
        log(f"  {svc_dir.name}: could not locate venv after install")
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


def collect_packages() -> dict[tuple[str, str], dict]:
    """Scan each service's .venv with pip-licenses and return a deduplicated
    dict keyed by (normalized_name, version)."""
    packages: dict[tuple[str, str], dict] = {}
    skipped: list[str] = []

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
            author_raw = (entry.get("Author") or "").strip().lower()
            if any(domain in author_raw for domain in FIRST_PARTY_AUTHOR_DOMAINS):
                log(f"  skipping first-party package (author domain): {name}")
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
        "(`src/django_app`, `src/crew`, `src/manager`, `src/knowledge`, `src/realtime`, `src/sandbox`, "
        "`src/webhook`, `src/tool`, `src/voice_app`). Dev / test dependencies are excluded. "
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
    OUTPUT_FILE.write_text(md, encoding="utf-8")
    log(f"discovered {len(packages)} unique backend packages")
    log(f"wrote {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
