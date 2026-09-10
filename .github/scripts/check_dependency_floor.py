# Enforce the shared dependency floor across every service lockfile.

# Run with --update to force rewriting recorded floors to what is currently shipped.

from __future__ import annotations

import glob
import os
import re
import sys
import tomllib
from collections import defaultdict

from packaging.version import InvalidVersion, Version

FLOOR_FILE = os.path.join(os.path.dirname(__file__), "..", "dependency-floor.toml")
PACKAGE_RE = re.compile(r"^name = \"(.+?)\"", re.M)
VERSION_RE = re.compile(r"^version = \"(.+?)\"", re.M)
SOURCE_RE = re.compile(r"^source = \{ (\w+) = ", re.M)


def read_locks(root: str = "src") -> dict[str, dict[str, str]]:
    """service -> {package: resolved version} for every uv.lock under root."""
    out: dict[str, dict[str, str]] = {}
    for path in sorted(glob.glob(f"{root}/**/uv.lock", recursive=True)):
        service = os.path.relpath(os.path.dirname(path), root).replace(os.sep, "/")
        text = open(path, encoding="utf-8", errors="replace").read()
        versions: dict[str, str] = {}
        for block in re.split(r"\n(?=\[\[package\]\])", text):
            name = PACKAGE_RE.search(block)
            ver = VERSION_RE.search(block)
            source = SOURCE_RE.search(block)
            # Only registry-sourced packages are real dependency floors. uv.lock
            # also carries the root project entry (source = virtual/editable)
            # and first-party path dependencies (source = directory), neither
            # of which is a versioned registry package.
            if name and ver and source and source.group(1) == "registry":
                versions[name.group(1).lower()] = ver.group(1)
        out[service] = versions
    return out


def parse(v: str) -> Version | None:
    try:
        return Version(v)
    except InvalidVersion:
        return None


def update_floors(locks: dict[str, dict[str, str]], floor: dict[str, str]) -> int:
    """Rewrite the [floor] values in place to the highest version now shipped."""
    text = open(FLOOR_FILE, encoding="utf-8").read()
    changed = []
    for pkg, want in floor.items():
        present = [
            v for versions in locks.values() if (v := versions.get(pkg)) and parse(v)
        ]
        if not present:
            continue
        highest = max(present, key=lambda v: parse(v))
        if parse(highest) > parse(want):
            text = re.sub(
                rf'^{re.escape(pkg)} = "{re.escape(want)}"$',
                f'{pkg} = "{highest}"',
                text,
                count=1,
                flags=re.M,
            )
            changed.append(f"{pkg}: {want} -> {highest}")
    if not changed:
        print("floors already match what is shipped; nothing to update")
        return 0
    open(FLOOR_FILE, "w", encoding="utf-8").write(text)
    for line in changed:
        print(f"  raised {line}")
    print(f"\nupdated {len(changed)} floor(s) in {os.path.normpath(FLOOR_FILE)}")
    return 0


def main() -> int:
    with open(FLOOR_FILE, "rb") as fh:
        cfg = tomllib.load(fh)
    floor: dict[str, str] = {k.lower(): v for k, v in cfg.get("floor", {}).items()}
    exceptions = cfg.get("exception", [])

    # package -> set of services allowed to sit below the floor
    excused: dict[str, set[str]] = defaultdict(set)
    for exc in exceptions:
        excused[exc["package"].lower()].update(exc.get("services", []))

    locks = read_locks()
    if not locks:
        print("::error::no uv.lock files found under src/", file=sys.stderr)
        return 1

    if "--update" in sys.argv:
        return update_floors(locks, floor)

    violations: list[str] = []
    excused_hits: dict[str, list[str]] = defaultdict(list)
    unused_exceptions: list[str] = []

    drift_only: list[str] = []
    for pkg, want in sorted(floor.items()):
        want_v = parse(want)
        if want_v is None:
            print(
                f"::error::floor for {pkg} is not a valid version: {want}",
                file=sys.stderr,
            )
            return 1

        present = {
            svc: parse(v)
            for svc, versions in locks.items()
            if (v := versions.get(pkg)) and parse(v)
        }
        if not present:
            continue

        # A fix that landed in one service raises the bar for every other
        # service shipping the same package, whether or not anyone edited
        # the floor.
        highest = max(present.values())
        target = max(want_v, highest)
        from_drift = highest > want_v

        for service, got_v in sorted(present.items()):
            if got_v >= target:
                continue
            got = locks[service][pkg]
            if service in excused[pkg]:
                excused_hits[pkg].append(f"{service}@{got}")
            elif from_drift:
                ahead = sorted(s for s, v in present.items() if v == highest)
                drift_only.append(
                    f"{pkg}: {service} has {got} but {', '.join(ahead)} already ships {highest}"
                )
            else:
                violations.append(f"{pkg}: {service} has {got}, floor is {want}")

    for exc in exceptions:
        pkg = exc["package"].lower()
        for service in exc.get("services", []):
            got = locks.get(service, {}).get(pkg)
            want_v = parse(floor.get(pkg, "0"))
            got_v = parse(got) if got else None
            if got is None or (got_v and want_v and got_v >= want_v):
                unused_exceptions.append(
                    f"{pkg}/{service} is excused but "
                    + (
                        "no longer present"
                        if got is None
                        else f"now at {got}, at or above the floor"
                    )
                )

    for pkg, hits in sorted(excused_hits.items()):
        print(f"  excused: {pkg} below floor in {', '.join(hits)}")
    print(f"\nchecked {len(floor)} floors across {len(locks)} lockfiles")

    if unused_exceptions:
        print()
        for line in unused_exceptions:
            print(
                f"::error::stale exception -- {line}. Remove it from dependency-floor.toml.",
                file=sys.stderr,
            )

    if drift_only:
        print()
        for line in drift_only:
            print(f"::error::drift -- {line}", file=sys.stderr)
        print(
            "::error::A fix landed in some services but not all. Raise the laggards, "
            "or add a documented exception to .github/dependency-floor.toml.",
            file=sys.stderr,
        )

    if violations:
        print()
        for line in violations:
            print(f"::error::below floor -- {line}", file=sys.stderr)
        print(
            f"::error::{len(violations)} service(s) below the shared dependency floor. "
            "Raise them, or add a documented exception to .github/dependency-floor.toml.",
            file=sys.stderr,
        )

    return 1 if (violations or drift_only or unused_exceptions) else 0


if __name__ == "__main__":
    sys.exit(main())
