"""The wheels `pack` puts in `backend/wheels/`: downloaded for the lock, or given locally.

The node installs a backend offline, so the package carries a wheel of every locked
distribution for every platform it may run on. `pip download` fetches them, told the target
platform and Python. Two things pip leaves to its caller, so they are done here:

- it evaluates a requirement's environment marker on the machine it runs on, so the lock is
  filtered per target platform before pip sees it;
- it takes a `manylinux_X_Y` tag literally, while a node with that C library also runs every
  older manylinux wheel, so pip is given each compatible tag.
"""

import dataclasses
import hashlib
import importlib.util
import re
import subprocess
import sys
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from email.message import Message
from email.parser import BytesHeaderParser
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import (
    InvalidWheelFilename,
    NormalizedName,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

from epicstaff_plugin.cli.output import UsageError
from epicstaff_plugin.package_layout import BACKEND_REQUIREMENTS, BACKEND_WHEELS_DIRECTORY
from epicstaff_plugin.package_source import PackageSource, SourceFile
from epicstaff_plugin.problems import MANIFEST_LOC, PackageProblemsError, Problem, archive_file_loc
from epicstaff_plugin.requirements_lock import RequirementsLock, lock_line, parse_requirements_lock

DEFAULT_PLATFORMS = ("manylinux_2_28_x86_64", "manylinux_2_28_aarch64")
# The node is Linux; a platform tag names the C library baseline and the machine.
_LINUX_PLATFORM = re.compile(
    r"^(?P<library>manylinux_(?P<glibc>2_[0-9]+)|manylinux1|manylinux2010|manylinux2014"
    r"|musllinux_(?P<musl>1_[0-9]+))_(?P<machine>x86_64|aarch64|i686|armv7l|ppc64le|s390x|riscv64)$"
)
# The legacy manylinux names (PEP 600) and the glibc version each stands for.
_LEGACY_MANYLINUX = {"manylinux2014": 17, "manylinux2010": 12, "manylinux1": 5}
_LEGACY_MANYLINUX_MACHINES = {
    "manylinux2014": {"x86_64", "i686", "aarch64", "armv7l", "ppc64le", "s390x"},
    "manylinux2010": {"x86_64", "i686"},
    "manylinux1": {"x86_64", "i686"},
}
# The oldest glibc each machine has manylinux wheels for, as `packaging.tags` lists them.
_OLDEST_GLIBC_MINOR = {"x86_64": 5, "i686": 5}
_OLDEST_GLIBC_MINOR_OTHER_MACHINES = 17
LOCAL_WHEELS_COMMENT = "# Added by epicstaff-plugin pack --local-wheel."
_HASH_CHUNK_BYTES = 1024 * 1024
_LOCK_LOC = archive_file_loc(BACKEND_REQUIREMENTS)


@dataclass(frozen=True)
class LocalWheel:
    """A wheel given with `--local-wheel`: a distribution no index has, such as a local SDK build."""

    path: Path
    name: NormalizedName
    version: Version
    sha256: str
    requires: tuple[Requirement, ...]


def linux_machine(platform: str) -> str:
    """Return the machine (`x86_64`, `aarch64`, ...) a Linux wheel platform tag names.

    Raises:
        UsageError: The tag is not a manylinux or musllinux tag.
    """
    match = _LINUX_PLATFORM.match(platform)
    if match is None:
        raise UsageError(
            f"--platform {platform!r} is not a Linux wheel platform such as "
            f"{DEFAULT_PLATFORMS[0]}; EpicStaff runs plugin backends on Linux"
        )
    return match.group("machine")


def compatible_platforms(platform: str) -> list[str]:
    """Return every wheel platform tag a node of `platform` runs, newest first.

    A glibc 2.28 node also runs `manylinux_2_17` (`manylinux2014`) wheels, and so on down;
    a musl 1.2 node runs `musllinux_1_1` wheels.

    Raises:
        UsageError: The tag is not a manylinux or musllinux tag.
    """
    linux_machine(platform)
    match = _LINUX_PLATFORM.match(platform)
    machine = match.group("machine")
    if match.group("musl"):
        newest = int(match.group("musl").split("_")[1])
        return [f"musllinux_1_{minor}_{machine}" for minor in range(newest, 0, -1)]
    library = match.group("library")
    newest = (
        int(match.group("glibc").split("_")[1])
        if match.group("glibc")
        else _LEGACY_MANYLINUX[library]
    )
    tags = []
    oldest = _OLDEST_GLIBC_MINOR.get(machine, _OLDEST_GLIBC_MINOR_OTHER_MACHINES)
    for minor in range(newest, oldest - 1, -1):
        tags.append(f"manylinux_2_{minor}_{machine}")
        tags.extend(
            f"{legacy}_{machine}"
            for legacy, legacy_minor in _LEGACY_MANYLINUX.items()
            if legacy_minor == minor and machine in _LEGACY_MANYLINUX_MACHINES[legacy]
        )
    return tags


def target_environment(python: str, platform: str) -> dict[str, str]:
    """Return the PEP 508 marker environment of a node with this Python and platform.

    The patch release is unknown, so `python_full_version` is `<python>.0`.
    """
    return {
        "implementation_name": "cpython",
        "implementation_version": f"{python}.0",
        "os_name": "posix",
        "platform_machine": linux_machine(platform),
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": "Linux",
        "platform_version": "",
        "python_full_version": f"{python}.0",
        "python_version": python,
        "sys_platform": "linux",
    }


def read_local_wheel(path: Path) -> LocalWheel:
    """Read a wheel's name, version, digest and requirements.

    Raises:
        UsageError: The file is missing, not named like a wheel, or has no readable metadata.
    """
    try:
        name, version, _, _ = parse_wheel_filename(path.name)
    except InvalidWheelFilename:
        raise UsageError(f"--local-wheel {path} is not named like a wheel") from None
    try:
        sha256 = _file_sha256(path)
        metadata = _wheel_metadata(path, name, version)
    except (OSError, zipfile.BadZipFile) as error:
        raise UsageError(f"cannot read --local-wheel {path}: {error}") from None
    try:
        requires = tuple(Requirement(text) for text in metadata.get_all("Requires-Dist") or [])
    except InvalidRequirement as error:
        raise UsageError(f"--local-wheel {path} has an invalid requirement: {error}") from None
    return LocalWheel(path, name, version, sha256, requires)


def with_backend_wheels(
    source: PackageSource,
    work_directory: Path,
    *,
    download: bool,
    platforms: Sequence[str],
    local_wheels: Sequence[LocalWheel],
) -> PackageSource:
    """Return `source` with the backend's wheels added and the local ones pinned in its lock.

    Downloads go to `work_directory`, as does the packaged lock: the source's lock with a
    `<name>==<version> --hash=sha256:<hex>` line appended for each local wheel. The source
    directory itself is never written.

    Raises:
        PackageProblemsError: The lock is missing or invalid, already pins a local wheel, does
            not pin what a local wheel requires, or pip could not download a wheel.
        UsageError: `download` is asked for a source that already ships `backend/wheels/`, or
            pip is not installed.
    """
    if source.manifest.backend is None:
        raise PackageProblemsError(
            [Problem(f"{MANIFEST_LOC}.backend", "is missing, but wheels were asked for")]
        )
    lock_file = source.file(BACKEND_REQUIREMENTS)
    if lock_file is None:
        raise PackageProblemsError([Problem(_LOCK_LOC, "is missing")])
    lock_bytes = lock_file.source.read_bytes()
    lock = parse_requirements_lock(lock_bytes)
    if download and any(file.path.startswith(BACKEND_WHEELS_DIRECTORY) for file in source.files):
        raise UsageError(
            "the source already has backend/wheels/; remove it, or pack without --download-wheels"
        )
    python = source.manifest.backend.python
    environments = [target_environment(python, platform) for platform in platforms]
    if problems := _local_wheel_problems(local_wheels, lock, environments):
        raise PackageProblemsError(problems)

    wheels: dict[str, Path] = {}
    if download:
        skipped = {wheel.name for wheel in local_wheels}
        wheels.update(_download(lock, python, platforms, work_directory / "downloads", skipped))
    wheels.update({wheel.path.name: wheel.path for wheel in local_wheels})

    files = [file for file in source.files if file.path != BACKEND_REQUIREMENTS]
    files.append(
        SourceFile(BACKEND_REQUIREMENTS, _packaged_lock(lock_bytes, local_wheels, work_directory))
    )
    files.extend(
        SourceFile(BACKEND_WHEELS_DIRECTORY + file_name, path) for file_name, path in wheels.items()
    )
    return dataclasses.replace(source, files=tuple(sorted(files, key=lambda file: file.path)))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_metadata(path: Path, name: str, version: Version) -> Message:
    with zipfile.ZipFile(path) as archive:
        for entry in archive.namelist():
            folder, _, file_name = entry.partition("/")
            if file_name != "METADATA" or not folder.endswith(".dist-info"):
                continue
            distribution, _, folder_version = folder.removesuffix(".dist-info").rpartition("-")
            if canonicalize_name(distribution) == name and _same_version(folder_version, version):
                return BytesHeaderParser().parsebytes(archive.read(entry))
    raise UsageError(f"--local-wheel {path} has no {name}-{version}.dist-info/METADATA")


def _same_version(text: str, version: Version) -> bool:
    try:
        return Version(text) == version
    except InvalidVersion:
        return False


def _local_wheel_problems(
    local_wheels: Sequence[LocalWheel], lock: RequirementsLock, environments: list[dict[str, str]]
) -> list[Problem]:
    problems = []
    seen: set[str] = set()
    for wheel in local_wheels:
        if wheel.name in seen:
            problems.append(Problem(_LOCK_LOC, f"--local-wheel names {wheel.name} more than once"))
        seen.add(wheel.name)
        if lock.pins(wheel.name):
            problems.append(
                Problem(
                    _LOCK_LOC,
                    f"already pins {wheel.name}; remove it from the lock or drop --local-wheel "
                    f"{wheel.path.name}",
                )
            )
    local_names = {wheel.name for wheel in local_wheels}
    for wheel in local_wheels:
        for requirement in wheel.requires:
            if canonicalize_name(requirement.name) in local_names:
                continue
            if not all(
                _pinned(requirement, lock, environment)
                for environment in environments
                if requirement.marker is None or requirement.marker.evaluate(environment)
            ):
                problems.append(
                    Problem(
                        _LOCK_LOC,
                        f"does not pin {requirement}, which {wheel.path.name} requires; add it to "
                        "the requirements the lock is compiled from",
                    )
                )
    return problems


def _pinned(requirement: Requirement, lock: RequirementsLock, environment: dict[str, str]) -> bool:
    return any(
        requirement.specifier.contains(pin.version, prereleases=True)
        for pin in lock.pins(requirement.name)
        if pin.applies_to(environment)
    )


def _download(
    lock: RequirementsLock,
    python: str,
    platforms: Iterable[str],
    directory: Path,
    skipped: set[str],
) -> dict[str, Path]:
    if importlib.util.find_spec("pip") is None:
        raise UsageError("--download-wheels runs pip, which is not installed for this Python")
    wheels: dict[str, Path] = {}
    digests: dict[str, str] = {}
    for platform in platforms:
        environment = target_environment(python, platform)
        lines = [
            f"{requirement.name}=={requirement.version} "
            + " ".join(f"--hash=sha256:{digest}" for digest in requirement.sha256)
            for requirement in lock.requirements
            if requirement.name not in skipped and requirement.applies_to(environment)
        ]
        if not lines:
            continue
        platform_directory = directory / platform
        platform_directory.mkdir(parents=True)
        requirements_file = directory / f"{platform}.txt"
        requirements_file.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        completed = subprocess.run(
            _pip_download_command(python, platform, platform_directory, requirements_file),
            check=False,
        )
        if completed.returncode != 0:
            raise PackageProblemsError(
                [Problem(_LOCK_LOC, f"pip could not download every wheel for {platform}")]
            )
        for wheel in sorted(platform_directory.glob("*.whl")):
            digest = _file_sha256(wheel)
            if digests.setdefault(wheel.name, digest) != digest:
                raise PackageProblemsError(
                    [Problem(_LOCK_LOC, f"pip downloaded two different files named {wheel.name}")]
                )
            wheels.setdefault(wheel.name, wheel)
    return wheels


def _pip_download_command(
    python: str, platform: str, destination: Path, requirements_file: Path
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--disable-pip-version-check",
        "--no-input",
        "--no-deps",
        "--only-binary=:all:",
        "--require-hashes",
        *(option for tag in compatible_platforms(platform) for option in ("--platform", tag)),
        "--python-version",
        python,
        "--implementation",
        "cp",
        "--abi",
        "cp" + python.replace(".", ""),
        "--dest",
        str(destination),
        "--requirement",
        str(requirements_file),
    ]


def _packaged_lock(
    lock_bytes: bytes, local_wheels: Sequence[LocalWheel], work_directory: Path
) -> Path:
    text = lock_bytes.decode("utf-8")
    if local_wheels:
        if not text.endswith("\n"):
            text += "\n"
        text += LOCAL_WHEELS_COMMENT + "\n"
        text += "".join(
            lock_line(wheel.name, str(wheel.version), wheel.sha256) + "\n" for wheel in local_wheels
        )
    path = work_directory / "requirements.lock"
    # Bytes, not text: a text write would turn "\n" into "\r\n" on Windows.
    path.write_bytes(text.encode("utf-8"))
    return path
