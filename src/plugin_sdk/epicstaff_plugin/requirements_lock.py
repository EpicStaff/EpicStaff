"""`backend/requirements.lock`: the hash-pinned list of everything a plugin's backend installs.

The node builds the backend's virtual environment offline with
`pip install --no-index --require-hashes --only-binary=:all: --no-deps -r backend/requirements.lock`,
from the wheels in `backend/wheels/`. So the lock may hold nothing but exact pins with
SHA-256 hashes: no index or link options, no URLs, no editable or nested requirement files.
`uv pip compile requirements.in --universal --generate-hashes` writes such a file.

The lock may not pin pip: the node installs with its own pip, never one a package brings.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from packaging.markers import Marker
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import (
    InvalidWheelFilename,
    NormalizedName,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

from epicstaff_plugin.problems import PackageProblemsError, Problem, archive_file_loc

REQUIREMENTS_LOCK_PATH = "backend/requirements.lock"
MAX_REQUIREMENTS_LOCK_BYTES = 1024 * 1024
SDK_DISTRIBUTION = canonicalize_name("epicstaff-plugin")
SERVER_DISTRIBUTION = canonicalize_name("uvicorn")
# The node runs the backend with `python -m epicstaff_plugin.serve`, which serves the app with
# uvicorn, so a backend cannot start without both.
REQUIRED_DISTRIBUTIONS = (SDK_DISTRIBUTION, SERVER_DISTRIBUTION)
INSTALLER_DISTRIBUTION = canonicalize_name("pip")

_HASH_OPTION = re.compile(r"^--hash=sha256:([0-9a-f]{64})$")
# pip's rule: a '#' at the start of a line or after whitespace starts a comment.
_COMMENT = re.compile(r"(^|\s+)#.*$")
_LOCK_LOC = archive_file_loc(REQUIREMENTS_LOCK_PATH)


@dataclass(frozen=True)
class LockedRequirement:
    """One pinned distribution of the lock."""

    name: NormalizedName
    version: Version
    marker: Marker | None
    sha256: tuple[str, ...]
    line_number: int

    def applies_to(self, environment: Mapping[str, str]) -> bool:
        """Whether pip installs this pin on a machine described by `environment` (PEP 508 names)."""
        return self.marker is None or self.marker.evaluate(dict(environment))


@dataclass(frozen=True)
class RequirementsLock:
    """A parsed `backend/requirements.lock`."""

    requirements: tuple[LockedRequirement, ...]

    def pins(self, name: str) -> tuple[LockedRequirement, ...]:
        """Every pin of the distribution `name` (a universal lock may pin it once per marker)."""
        normalized = canonicalize_name(name)
        return tuple(
            requirement for requirement in self.requirements if requirement.name == normalized
        )


def parse_requirements_lock(raw: bytes) -> RequirementsLock:
    """Parse a lock that pins every requirement exactly and with at least one SHA-256 hash.

    Raises:
        PackageProblemsError: Every line that breaks a rule, located at the lock file.
    """
    if len(raw) > MAX_REQUIREMENTS_LOCK_BYTES:
        raise PackageProblemsError(
            [Problem(_LOCK_LOC, f"is larger than {MAX_REQUIREMENTS_LOCK_BYTES} bytes")]
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PackageProblemsError([Problem(_LOCK_LOC, "is not UTF-8")]) from None
    requirements = []
    problems = []
    for line_number, line in _logical_lines(text):
        try:
            requirements.append(_parse_line(line, line_number))
        except ValueError as error:
            problems.append(Problem(_LOCK_LOC, f"line {line_number}: {error}"))
    if problems:
        raise PackageProblemsError(problems)
    return RequirementsLock(tuple(requirements))


def lock_line(name: str, version: str, sha256: str) -> str:
    """Return the lock line that pins one wheel: `<name>==<version> --hash=sha256:<hex>`."""
    return f"{canonicalize_name(name)}=={version} --hash=sha256:{sha256}"


def backend_lock_problems(
    raw: bytes, wheel_paths: Iterable[str], *, require_sdk_pin: bool = True
) -> list[Problem]:
    """Check a backend's lock and that it pins every wheel shipped next to it.

    `wheel_paths` are the package paths of the files in `backend/wheels/`. The lock must pin
    `uvicorn` and `epicstaff-plugin`; `require_sdk_pin=False` drops the second rule, for a
    source directory whose SDK wheel `pack --local-wheel` adds later.
    """
    try:
        lock = parse_requirements_lock(raw)
    except PackageProblemsError as error:
        return list(error.problems)
    required = REQUIRED_DISTRIBUTIONS if require_sdk_pin else (SERVER_DISTRIBUTION,)
    problems = [
        Problem(_LOCK_LOC, f"does not pin {name}, which every plugin backend needs")
        for name in required
        if not lock.pins(name)
    ]
    for path in sorted(wheel_paths):
        file_name = path.rpartition("/")[2]
        try:
            name, version, _, _ = parse_wheel_filename(file_name)
        except InvalidWheelFilename:
            problems.append(Problem(archive_file_loc(path), "is not a valid wheel file name"))
            continue
        if not any(requirement.version == version for requirement in lock.pins(name)):
            problems.append(
                Problem(
                    archive_file_loc(path),
                    f"is {name} {version}, which {REQUIREMENTS_LOCK_PATH} does not pin",
                )
            )
    return problems


def _logical_lines(text: str) -> Iterable[tuple[int, str]]:
    """Yield each requirement line with its first line number: comments removed, `\\` joined."""
    pending: list[str] = []
    start = 0
    for line_number, physical in enumerate(text.splitlines(), start=1):
        if not pending:
            start = line_number
        stripped = _COMMENT.sub("", physical).rstrip()
        if stripped.endswith("\\"):
            pending.append(stripped[:-1])
            continue
        pending.append(stripped)
        logical = " ".join(part.strip() for part in pending).strip()
        pending = []
        if logical:
            yield start, logical
    if pending and (logical := " ".join(part.strip() for part in pending).strip()):
        yield start, logical


def _parse_line(line: str, line_number: int) -> LockedRequirement:
    tokens = line.split()
    # As pip splits a line: the requirement runs up to the first option.
    first_option = next(
        (index for index, token in enumerate(tokens) if token.startswith("-")), len(tokens)
    )
    requirement_text = " ".join(tokens[:first_option])
    options = tokens[first_option:]
    if not requirement_text:
        raise ValueError(f"{options[0]!r} is not allowed; the lock may only pin requirements")
    try:
        requirement = Requirement(requirement_text)
    except InvalidRequirement as error:
        raise ValueError(f"{requirement_text!r} is not a requirement ({error})") from None
    if requirement.url:
        raise ValueError(f"{requirement.name} is a URL or path; pin a version from an index")
    if canonicalize_name(requirement.name) == INSTALLER_DISTRIBUTION:
        raise ValueError(
            f"{requirement.name} may not be pinned: the plugin node installs a backend with its "
            "own pip, never one from the package; remove it from the lock"
        )
    specifiers = list(requirement.specifier)
    if (
        len(specifiers) != 1
        or specifiers[0].operator != "=="
        or specifiers[0].version.endswith(".*")
    ):
        raise ValueError(f"{requirement.name} must be pinned to one exact version with ==")
    try:
        version = Version(specifiers[0].version)
    except InvalidVersion:
        raise ValueError(f"{requirement.name} has an invalid version") from None
    hashes = []
    for option in options:
        match = _HASH_OPTION.match(option)
        if match is None:
            raise ValueError(
                f"{option!r} is not allowed; the only option is --hash=sha256:<64 hex digits>"
            )
        hashes.append(match.group(1))
    if not hashes:
        raise ValueError(f"{requirement.name} has no --hash=sha256: digest")
    return LockedRequirement(
        name=canonicalize_name(requirement.name),
        version=version,
        marker=requirement.marker,
        sha256=tuple(hashes),
        line_number=line_number,
    )
