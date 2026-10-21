"""Build a plugin's venv offline, from the wheels its package carries.

`python -m venv` with the plugin's interpreter, then
`pip install --no-index --find-links <wheels> --require-hashes --only-binary=:all:
-r requirements.lock`: nothing is fetched, nothing is built from source, and every wheel
must match its pinned hash. A `.pth` file then puts the plugin's own code
(`plugins/<id>/<version>/backend/src`) on the venv's path, so `python -I` still finds it.

**The agent (UID 10000) never runs the venv's interpreter after plugin files are in it.** A
wheel's root `.pth` file runs its import line on every interpreter start, and a wheel's
`.data/scripts/python` would replace `venv/bin/python`: either would be the plugin's code
running as the agent. So the venv is built in a fresh empty directory (no `.pth` present when
pip starts), the site-packages path is derived from the trusted base interpreter's version
before any install, and after pip the `bin/python*` entries are checked to be the expected
symlinks to the base interpreter. Only the launcher, as the plugin's own UID, ever runs it.

A finished venv carries a marker naming the lock and the interpreter it was built from;
building the same again reuses it, so a restarted node does not reinstall every plugin.
"""

import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from es_plugins.packages.wheel_tag_check import check_wheel_tags

SOURCE_PATH_FILE_NAME = "epicstaff-plugin-source.pth"
MARKER_FILE_NAME = ".es_plugins-venv.json"
PIP_TIMEOUT_SECONDS = 15 * 60
_VENV_TIMEOUT_SECONDS = 5 * 60
_VERSION_TIMEOUT_SECONDS = 30
_OUTPUT_LINES_KEPT = 15
_PYTHON_VERSION_PROGRAM = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"


class VenvBuildError(Exception):
    """The venv could not be built; the message ends with pip's last lines."""


@dataclass(frozen=True)
class VenvRequest:
    interpreter: Path
    """The plugin's Python, e.g. /opt/plugin-python/3.13/bin/python3.13."""

    venv: Path
    backend: Path
    """The unpacked `backend/` directory: `requirements.lock` and `wheels/`."""

    source_path: Path
    """What the `.pth` file adds to the venv's path."""

    temporary_directory: Path
    """pip's TMPDIR: the container's /tmp is not writable."""


async def build_venv(request: VenvRequest) -> Path:
    """Build (or reuse) the venv and return its Python.

    Raises:
        IncompatibleWheelError: A wheel does not fit the interpreter (checked before pip).
        VenvBuildError: `venv` or pip failed, or a wheel replaced the venv's interpreter.
    """
    lock = request.backend / "requirements.lock"
    marker = _marker_for(request)
    python = request.venv / "bin" / "python"
    if venv_is_current(request):
        return python
    await check_wheel_tags(request.interpreter, request.backend / "wheels")
    # The trusted base interpreter's version names the venv's site-packages, read before any
    # plugin file exists, so the path is never derived by running the venv after an install.
    version = await _base_interpreter_version(request)
    environment = {
        "LANG": "C.UTF-8",
        "HOME": str(request.temporary_directory),
        "TMPDIR": str(request.temporary_directory),
        "PIP_NO_CACHE_DIR": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # A fresh, empty directory: pip never starts with a leftover build's plugin `.pth` present.
    if request.venv.exists():
        shutil.rmtree(request.venv)
    await _run(
        [str(request.interpreter), "-I", "-m", "venv", str(request.venv)],
        environment,
        _VENV_TIMEOUT_SECONDS,
        "creating the venv",
    )
    await _run(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(request.backend / "wheels"),
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            str(lock),
        ],
        environment,
        PIP_TIMEOUT_SECONDS,
        "installing the plugin's requirements",
    )
    _verify_interpreter_untouched(request.venv, request.interpreter, version)
    site_packages = request.venv / "lib" / f"python{version}" / "site-packages"
    if not site_packages.is_dir():
        raise VenvBuildError(f"the venv has no {site_packages.relative_to(request.venv)}")
    (site_packages / SOURCE_PATH_FILE_NAME).write_text(f"{request.source_path}\n")
    (request.venv / MARKER_FILE_NAME).write_text(json.dumps(marker))
    return python


def venv_is_current(request: VenvRequest) -> bool:
    """Whether `build_venv` would reuse the venv as it is, without installing anything."""
    python = request.venv / "bin" / "python"
    return _read_marker(request.venv) == _marker_for(request) and python.exists()


def _marker_for(request: VenvRequest) -> dict:
    lock = request.backend / "requirements.lock"
    return {
        "interpreter": str(request.interpreter),
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "source_path": str(request.source_path),
    }


def _verify_interpreter_untouched(venv: Path, interpreter: Path, version: str) -> None:
    """Fail unless `venv/bin/python*` are still symlinks to the base interpreter.

    A wheel that shipped a `.data/scripts/python` would have replaced one of them with a
    file of the plugin's choosing; the agent must never run that.
    """
    expected = os.path.realpath(interpreter)
    binary_directory = venv / "bin"
    for name in ("python", "python3", f"python{version}"):
        link = binary_directory / name
        try:
            if not stat.S_ISLNK(os.lstat(link).st_mode):
                raise VenvBuildError(f"bin/{name} is not a symlink; a wheel may have replaced it")
            if os.path.realpath(link) != expected:
                raise VenvBuildError(f"bin/{name} does not resolve to {expected}")
        except FileNotFoundError:
            raise VenvBuildError(f"bin/{name} is missing after the install") from None


async def _base_interpreter_version(request: VenvRequest) -> str:
    output = await _run(
        [str(request.interpreter), "-I", "-c", _PYTHON_VERSION_PROGRAM],
        {"LANG": "C.UTF-8"},
        _VERSION_TIMEOUT_SECONDS,
        "reading the interpreter version",
    )
    return output.strip()


def _read_marker(venv: Path) -> dict | None:
    try:
        return json.loads((venv / MARKER_FILE_NAME).read_text())
    except (FileNotFoundError, ValueError):
        return None


async def _run(argv: list[str], environment: dict[str, str], timeout: float, step: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=environment,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        # A timeout, a cancellation (the placement went away) or anything else: never leave
        # pip running unattended.
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        raise
    text = output.decode(errors="replace")
    if process.returncode != 0:
        tail = "\n".join(text.strip().splitlines()[-_OUTPUT_LINES_KEPT:])
        raise VenvBuildError(f"{step} failed (exit {process.returncode}):\n{tail}")
    return text
