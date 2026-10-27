"""Build a plugin's venv offline, from the wheels its package carries.

**The agent (UID 10000) never imports or runs anything of a venv it builds.** A wheel is the
plugin's code: a root `.pth` file runs on every start of the venv's interpreter, a
`.data/scripts/python` would replace `venv/bin/python`, and a wheel may overwrite any file of the
venv's site-packages, pip's own included. So pip never runs from the venv, and the venv's
interpreter never runs as the agent:

1. `python -I -m venv --without-pip` with the plugin's interpreter (`/opt/plugin-python/<version>`,
   on the image's read-only root): a venv with no pip in it, and no run of its interpreter.
2. That same interpreter, isolated, runs the pip wheel its own standard library ships for
   `ensurepip` (`ensurepip/_bundled/pip-*.whl`, fixed by the image's digest): `pip install
   --prefix <venv> --ignore-installed --no-index --find-links <wheels> --require-hashes
   --only-binary=:all: -r requirements.lock`. Nothing is fetched, nothing is built from source,
   every wheel must match its pinned hash, and the lock's markers and the wheels' tags are those
   of the interpreter the plugin runs on. pip also resolves each wheel's requirements, from the
   wheels' metadata alone, and hash-checking mode fails the install on one the lock does not pin,
   naming it: a lock that misses a dependency fails the build rather than every start. The
   wheels pip installs land in the venv, never where pip itself is read from, and the venv is not
   on that interpreter's path.
3. `venv/bin/python*` must still be the symlinks to the plugin's interpreter, and the scripts pip
   wrote get the venv's `bin/python` in their first line instead of the interpreter pip ran on.
   A `.pth` file then puts the plugin's own code (`plugins/<id>/<version>/backend/src`) on the
   venv's path, so `python -I` still finds it.

Only the launcher, as the plugin's own UID, ever runs the venv's interpreter. A build that fails
leaves no venv behind.

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
_PROBE_TIMEOUT_SECONDS = 30
_OUTPUT_LINES_KEPT = 15
# Run by the plugin's interpreter before any plugin file exists: its version, the path it runs
# as (what pip writes into scripts), and the pip wheel its standard library ships.
_INTERPRETER_PROGRAM = """
import json, pathlib, sys, sysconfig
bundled = pathlib.Path(sysconfig.get_path("stdlib"), "ensurepip", "_bundled")
print(json.dumps({
    "version": f"{sys.version_info.major}.{sys.version_info.minor}",
    "executable": sys.executable,
    "pip_wheels": sorted(str(path) for path in bundled.glob("pip-*.whl")),
}))
"""
# What pip writes as a script's first line (distlib's rule on Linux): `#!<python>`, or, for a
# path with a space or longer than the kernel reads, a shell line that executes it.
_MAX_SHEBANG_BYTES = 127
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_COPY_CHUNK_BYTES = 1024 * 1024


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


@dataclass(frozen=True)
class _Interpreter:
    version: str
    executable: str
    pip_wheel: Path


async def build_venv(request: VenvRequest) -> Path:
    """Build (or reuse) the venv and return its Python.

    Raises:
        IncompatibleWheelError: A wheel does not fit the interpreter (checked before pip).
        VenvBuildError: The interpreter ships no pip wheel, `venv` or pip failed, or a wheel
            replaced the venv's interpreter.
    """
    lock = request.backend / "requirements.lock"
    marker = _marker_for(request)
    python = request.venv / "bin" / "python"
    if venv_is_current(request):
        return python
    await check_wheel_tags(request.interpreter, request.backend / "wheels")
    interpreter = await _describe_interpreter(request.interpreter)
    environment = {
        "LANG": "C.UTF-8",
        "HOME": str(request.temporary_directory),
        "TMPDIR": str(request.temporary_directory),
        # No pip configuration file at all, the image's included.
        "PIP_CONFIG_FILE": os.devnull,
    }
    # A fresh, empty directory: nothing of an earlier build is in it.
    if request.venv.exists():
        await _in_thread_to_the_end(shutil.rmtree, request.venv)
    try:
        await _run(
            [str(request.interpreter), "-I", "-m", "venv", "--without-pip", str(request.venv)],
            environment,
            _VENV_TIMEOUT_SECONDS,
            "creating the venv",
        )
        await _run(
            [
                str(request.interpreter),
                "-I",
                # pip's own way of running from its wheel: `<wheel>/pip` is its __main__.
                str(interpreter.pip_wheel / "pip"),
                "install",
                "--isolated",
                "--no-cache-dir",
                "--disable-pip-version-check",
                "--no-input",
                "--no-warn-script-location",
                "--root-user-action=ignore",
                "--prefix",
                str(request.venv),
                "--ignore-installed",
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
        _verify_interpreter_untouched(request.venv, request.interpreter, interpreter.version)
        site_packages = request.venv / "lib" / f"python{interpreter.version}" / "site-packages"
        if not site_packages.is_dir():
            raise VenvBuildError(f"the venv has no {site_packages.relative_to(request.venv)}")
        await _in_thread_to_the_end(
            _point_scripts_at_the_venv, request.venv, interpreter.executable
        )
        (site_packages / SOURCE_PATH_FILE_NAME).write_text(f"{request.source_path}\n")
        (request.venv / MARKER_FILE_NAME).write_text(json.dumps(marker))
    except BaseException:
        # A wheel may have written anything into the venv, a marker of this module's name too.
        await _in_thread_to_the_end(shutil.rmtree, request.venv, True)
        raise
    return python


def venv_is_current(request: VenvRequest) -> bool:
    """Whether `build_venv` would reuse the venv as it is, without installing anything."""
    python = request.venv / "bin" / "python"
    return _read_marker(request.venv) == _marker_for(request) and python.exists()


def script_first_line(python: bytes) -> bytes:
    """The first line pip gives a script that `python` runs (distlib's form on Linux)."""
    if b" " not in python and len(python) + 3 <= _MAX_SHEBANG_BYTES:
        return b"#!" + python + b"\n"
    return b"#!/bin/sh\n'''exec' " + python + b' "$0" "$@"\n' + b"' '''\n"


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
    file of the plugin's choosing; the plugin's UID would run that at every start.
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


def _point_scripts_at_the_venv(venv: Path, installer_python: str) -> None:
    """Give each script pip wrote into `bin/` the venv's python instead of the one pip ran on.

    pip writes the interpreter it runs on into a console script's first line, and into a
    `.data/scripts` file's that begins `#!python`; run from the venv's `bin/`, they must start
    the venv's python, as when pip ran inside the venv. Only a regular file whose first line is
    exactly what pip wrote is changed; links are never followed, and the rest is the script's
    as pip wrote it.
    """
    written = (
        script_first_line(os.fsencode(installer_python)),
        # The form pip's `#!python` rewrite gives a `.data/scripts` file, whatever the length.
        b"#!" + os.fsencode(installer_python) + b"\n",
    )
    replacement = script_first_line(os.fsencode(venv / "bin" / "python"))
    try:
        directory = os.open(venv / "bin", _DIRECTORY_FLAGS)
        try:
            with os.scandir(directory) as entries:
                names = [entry.name for entry in entries if entry.is_file(follow_symlinks=False)]
            for name in names:
                _replace_first_line(directory, name, written, replacement)
        finally:
            os.close(directory)
    except OSError as error:
        raise VenvBuildError(
            f"the scripts in bin/ could not be pointed at the venv: {error}"
        ) from None


def _replace_first_line(
    directory: int, name: str, written: tuple[bytes, ...], replacement: bytes
) -> None:
    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
    try:
        info = os.fstat(source)
        if not stat.S_ISREG(info.st_mode):
            return
        head = os.read(source, max(len(line) for line in written))
        first_line = next((line for line in written if head.startswith(line)), None)
        if first_line is None:
            return
        os.lseek(source, len(first_line), os.SEEK_SET)
        staged = f".{name}.rewritten"
        target = os.open(
            staged,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        try:
            os.write(target, replacement)
            while chunk := os.read(source, _COPY_CHUNK_BYTES):
                view = memoryview(chunk)
                while view:
                    view = view[os.write(target, view) :]
            os.fchmod(target, stat.S_IMODE(info.st_mode))
        finally:
            os.close(target)
        os.replace(staged, name, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        os.close(source)


async def _describe_interpreter(interpreter: Path) -> _Interpreter:
    """The trusted interpreter's version, its path as pip will see it, and its own pip wheel.

    Read before any plugin file exists: the venv's site-packages path is never derived by
    running the venv after an install.
    """
    output = await _run(
        [str(interpreter), "-I", "-c", _INTERPRETER_PROGRAM],
        {"LANG": "C.UTF-8"},
        _PROBE_TIMEOUT_SECONDS,
        "reading the interpreter",
    )
    try:
        described = json.loads(output)
        wheels = described["pip_wheels"]
        version, executable = described["version"], described["executable"]
    except (ValueError, KeyError, TypeError):
        raise VenvBuildError(f"{interpreter} did not describe itself: {output[-500:]}") from None
    if len(wheels) != 1:
        raise VenvBuildError(
            f"{interpreter} ships {len(wheels)} pip wheels for ensurepip, not one; the node "
            "installs with that pip"
        )
    return _Interpreter(version=version, executable=executable, pip_wheel=Path(wheels[0]))


async def _in_thread_to_the_end(function, *arguments):
    """Run `function` in a thread, and wait for it to finish even when cancelled meanwhile.

    A venv's files are removed or rewritten here: a later build of the same venv must never
    overlap that work. A cancellation is passed on once the thread is done.
    """
    work = asyncio.ensure_future(asyncio.to_thread(function, *arguments))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(work)
        except asyncio.CancelledError:
            if work.done():
                raise
            cancelled = True
            continue
        break
    if cancelled:
        raise asyncio.CancelledError
    return result


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
