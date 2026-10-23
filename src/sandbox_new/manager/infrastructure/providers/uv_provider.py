import asyncio
import re
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from packaging.utils import canonicalize_name

from manager.application.ports import AbstractUVProvider
from manager.domain.errors import (
    BaseError,
    UVBuildError,
    UVDependencyResolutionError,
    UVPackageNotFoundError,
    UVVersionNotFoundError,
)
from manager.domain.types import LibraryString

__all__ = ["UVProvider"]

PIN_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==(?P<version>[^\s;]+)"
)

PACKAGE_NAME_RE = r"[A-Za-z0-9][A-Za-z0-9._-]*"
EXTRAS_RE = r"(?:\[[^\]]*\])?"
SPECIFICATION_RE = r"(?P<specification>[<>=!~]\S*)"

PARSED_COMMANDS = frozenset({("pip", "compile"), ("pip", "sync")})

RESOLUTION_FAILURE = "No solution found when resolving dependencies"

PACKAGE_NOT_FOUND_PATTERN = re.compile(
    rf"\b(?P<name>{PACKAGE_NAME_RE}) was not found in the package registry"
)
MISSING_VERSION_PATTERN = re.compile(
    rf"\bthere is no version of (?P<name>{PACKAGE_NAME_RE}){EXTRAS_RE}{SPECIFICATION_RE}"
)
UNSATISFIED_RANGE_PATTERN = re.compile(
    rf"\bis available and you require (?P<name>{PACKAGE_NAME_RE}){EXTRAS_RE}{SPECIFICATION_RE}"
)
CONFLICT_PATTERN = re.compile(rf"\b(?P<name>{PACKAGE_NAME_RE}){EXTRAS_RE}\S* depends on ")


def _normalize(stderr: str) -> str:
    """Flatten uv's report onto one line.

    uv wraps its explanation to the terminal width, mid-sentence, so the sentences
    below cannot be matched line by line. Collapsing whitespace also reduces the
    markers each uv version decorates the report with (0.11 draws a box, 0.12 writes
    `error:`/`cause:`) to tokens the patterns step over.
    """
    return " ".join(stderr.split())


def _parse_stderr(args: Sequence[str], stderr: str) -> BaseError:
    """Turn the stderr of a failed uv command into a domain error.

    Only dependency resolution (`uv pip compile` and `uv pip sync`) reports failures a
    user can act on; every other command and every unrecognised cause falls back to the
    generic build error.
    """
    if tuple(args[:2]) not in PARSED_COMMANDS:
        return UVBuildError()

    cause = _normalize(stderr)
    if RESOLUTION_FAILURE not in cause:
        return UVBuildError()

    not_found = PACKAGE_NOT_FOUND_PATTERN.search(cause)
    if not_found is not None:
        return UVPackageNotFoundError(package=canonicalize_name(not_found["name"]))

    for pattern in (MISSING_VERSION_PATTERN, UNSATISFIED_RANGE_PATTERN):
        no_version = pattern.search(cause)
        if no_version is not None:
            return UVVersionNotFoundError(
                package=canonicalize_name(no_version["name"]),
                specification=no_version["specification"].rstrip(",."),
            )

    conflict = CONFLICT_PATTERN.search(cause)
    if conflict is not None:
        return UVDependencyResolutionError(package=canonicalize_name(conflict["name"]))

    return UVBuildError()


class UVProvider(AbstractUVProvider):
    PYTHON_VERSION = "3.12"

    @staticmethod
    async def run(
        *args: str,
        input=None,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    ):
        process = await asyncio.create_subprocess_exec(
            "uv",
            *args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )
        if input is not None:
            input = input.encode()
        _, error = await process.communicate(input)
        if process.returncode != 0:
            if stderr == asyncio.subprocess.PIPE:
                error = error.decode()
            logger.error("uv {} failed:\n{}", " ".join(args), error)
            raise _parse_stderr(args, error or "")

    @classmethod
    async def init_venv(cls, venv_path: Path):
        if venv_path.exists():
            raise ValueError("Venv was inited yet.")
        await cls.run(
            "venv",
            "--no-config",
            "--no-progress",
            "--python",
            cls.PYTHON_VERSION,
            str(venv_path),
        )

    @classmethod
    async def apply(cls, venv_path: Path, *libs: LibraryString):
        if not venv_path.exists():
            raise ValueError(f"Venv is not initialized yet. Paht: {venv_path}")
        python_binary = cls.get_python_binary(venv_path)
        lock_file = cls.get_lock_file(venv_path)

        await cls.run(
            "pip",
            "compile",
            "--no-config",
            "--no-progress",
            "--generate-hashes",
            "--no-header",
            "--no-annotate",
            "--python",
            str(python_binary),
            "--output-file",
            str(lock_file),
            "-",
            input="\n".join(libs),
        )
        await cls.run(
            "pip",
            "sync",
            "--no-config",
            "--no-progress",
            "--python",
            str(python_binary),
            str(lock_file),
        )

    @classmethod
    def read_resolved_versions(cls, venv_path: Path) -> dict[str, str]:
        lock_file = cls.get_lock_file(venv_path)
        if not lock_file.is_file():
            return {}

        resolved: dict[str, str] = {}
        for line in lock_file.read_text().splitlines():
            match = PIN_PATTERN.match(line.strip())
            if match is not None:
                resolved[canonicalize_name(match["name"])] = match["version"]
        return resolved

    @classmethod
    async def install_local(cls, venv_path: Path, *packages: Path):
        if not packages:
            return
        python_binary = cls.get_python_binary(venv_path)
        await cls.run(
            "pip",
            "install",
            "--no-config",
            "--no-progress",
            "--python",
            str(python_binary),
            *(str(package) for package in packages),
        )
