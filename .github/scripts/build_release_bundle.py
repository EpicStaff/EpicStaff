#!/usr/bin/env python3
"""Build the release bundle: everything a release needs to run without a clone of the source.

The archive `epicstaff-<tag>.tar.gz` mirrors the repository layout under `epicstaff-<tag>/`, so
`scripts/envtool.py` and the compose file run from it unchanged. It holds the given (stripped,
digest-pinned) compose file, every file that compose file bind-mounts, the files envtool needs,
and INSTALL.md. Only git-tracked files are packed, so nothing local (certificates, a generated
`.env`) can leak into a release.

Usage: build_release_bundle.py <repo_root> <compose_file> <tag> <output_dir>
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

from ruamel.yaml import YAML

ENVTOOL_KIT = (
    "scripts/envtool.py",
    "src/env.yaml",
    "src/.env.example",
    "src/shared/__init__.py",
    "src/shared/humanize.py",
    "src/shared/envtools.py",
)
INSTALL_DOC = ".github/release-bundle/INSTALL.md"
# Compose resolves bind sources against the compose file's directory, which is src/ in the repo.
COMPOSE_DIRECTORY = "src"


class BundleError(Exception):
    pass


def bind_source(volume) -> str | None:
    """The host path of a bind mount, or None for a named volume or any other volume type."""
    if isinstance(volume, str):
        source = volume.split(":", 1)[0]
        return source if source.startswith((".", "/", "~", "$")) else None
    if isinstance(volume, dict) and volume.get("type") == "bind":
        return str(volume.get("source", ""))
    return None


def collect_bind_sources(compose: dict) -> list[str]:
    """Every bind-mount source of every service, relative to the compose file's directory."""
    sources = set()
    for service_name, service in (compose.get("services") or {}).items():
        for volume in (service or {}).get("volumes") or []:
            source = bind_source(volume)
            if source is None:
                continue
            if "$" in source:
                raise BundleError(
                    f"{service_name}: bind source {source!r} uses a variable; the bundle cannot ship it"
                )
            if source.startswith(("/", "~")):
                raise BundleError(
                    f"{service_name}: bind source {source!r} is a host path outside the repository; the bundle cannot ship it"
                )
            parts = []
            for part in PurePosixPath(source).parts:
                if part == "..":
                    if not parts:
                        raise BundleError(
                            f"{service_name}: bind source {source!r} is outside {COMPOSE_DIRECTORY}/"
                        )
                    parts.pop()
                elif part != ".":
                    parts.append(part)
            if not parts:
                raise BundleError(
                    f"{service_name}: bind source {source!r} is the compose directory itself"
                )
            sources.add("/".join(parts))
    return sorted(sources)


def normalize_member(member: tarfile.TarInfo) -> tarfile.TarInfo:
    """Root ownership and fixed modes: a root `tar -x` keeps archive owners, so the CI runner's
    uid must not end up owning the files nginx and postgres run as root."""
    member.uid = member.gid = 0
    member.uname = member.gname = "root"
    member.mode = 0o755 if member.mode & 0o100 else 0o644
    return member


def tracked_files(repo_root: Path, path: str) -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--", path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [name for name in output.split("\0") if name]


def build_bundle(repo_root: Path, compose_file: Path, tag: str, output_dir: Path) -> Path:
    if not tag or "/" in tag or "\\" in tag or tag in (".", ".."):
        raise BundleError(f"invalid tag {tag!r}")
    compose = YAML(typ="safe").load(compose_file.read_text(encoding="utf-8"))

    repository_paths = list(ENVTOOL_KIT)
    for source in collect_bind_sources(compose):
        files = tracked_files(repo_root, f"{COMPOSE_DIRECTORY}/{source}")
        if not files:
            raise BundleError(
                f"{COMPOSE_DIRECTORY}/{source} is bind-mounted but has no git-tracked file"
            )
        repository_paths.extend(files)
    for path in (*ENVTOOL_KIT, INSTALL_DOC):
        if not tracked_files(repo_root, path):
            raise BundleError(f"{path} is not git-tracked")

    top = f"epicstaff-{tag}"
    compose_path = f"{COMPOSE_DIRECTORY}/docker-compose.yaml"
    archive_path = output_dir / f"{top}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(repo_root / INSTALL_DOC, arcname=f"{top}/INSTALL.md", filter=normalize_member)
        archive.add(compose_file, arcname=f"{top}/{compose_path}", filter=normalize_member)
        for path in sorted(set(repository_paths) - {compose_path}):
            archive.add(
                repo_root / path, arcname=f"{top}/{path}", recursive=False, filter=normalize_member
            )
    return archive_path


def main() -> int:
    if len(sys.argv) != 5:
        print(
            "usage: build_release_bundle.py <repo_root> <compose_file> <tag> <output_dir>",
            file=sys.stderr,
        )
        return 2
    repo_root, compose_file, tag, output_dir = sys.argv[1:]
    try:
        archive_path = build_bundle(Path(repo_root), Path(compose_file), tag, Path(output_dir))
    except BundleError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"wrote {archive_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
