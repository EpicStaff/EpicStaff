"""Real `python -m venv` and offline pip installs, from wheels built in the test."""

import subprocess
import sys
from pathlib import Path

import pytest

from es_plugins.packages.venv_builder import (
    MARKER_FILE_NAME,
    VenvBuildError,
    VenvRequest,
    build_venv,
)
from es_plugins.packages.wheel_tag_check import IncompatibleWheelError
from tests.helpers import FOREIGN_WHEEL_TAG, lock_for, make_wheel


def backend(tmp_path: Path, wheels: list[Path], lock: str | None = None) -> Path:
    directory = tmp_path / "backend"
    (directory / "wheels").mkdir(parents=True, exist_ok=True)
    for wheel in wheels:
        target = directory / "wheels" / wheel.name
        if wheel != target:
            target.write_bytes(wheel.read_bytes())
    (directory / "requirements.lock").write_text(lock if lock is not None else lock_for(wheels))
    return directory


def request_for(tmp_path: Path, backend_directory: Path) -> VenvRequest:
    source = tmp_path / "code" / "backend" / "src"
    (source / "weather_plugin").mkdir(parents=True)
    (source / "weather_plugin" / "__init__.py").write_text("NAME = 'weather'\n")
    (tmp_path / "tmp").mkdir()
    return VenvRequest(
        interpreter=Path(sys.executable),
        venv=tmp_path / "venvs" / "weather" / "0.2.0",
        backend=backend_directory,
        source_path=source,
        temporary_directory=tmp_path / "tmp",
    )


def run_isolated(python: Path, code: str) -> str:
    return subprocess.run(
        [str(python), "-I", "-c", code], check=True, capture_output=True, text=True
    ).stdout.strip()


async def test_the_venv_holds_the_locked_wheels_and_finds_the_plugin_code_under_isolation(tmp_path):
    wheels = [make_wheel(tmp_path / "built", "uvicorn", "0.52.3")]
    request = request_for(tmp_path, backend(tmp_path, wheels))

    python = await build_venv(request)

    assert python == request.venv / "bin" / "python"
    assert run_isolated(python, "import uvicorn; print(uvicorn.VERSION)") == "0.52.3"
    assert run_isolated(python, "import weather_plugin; print(weather_plugin.NAME)") == "weather"


async def test_building_the_same_venv_again_reuses_it(tmp_path):
    wheels = [make_wheel(tmp_path / "built", "uvicorn", "0.52.3")]
    request = request_for(tmp_path, backend(tmp_path, wheels))
    await build_venv(request)
    sentinel = request.venv / "kept"
    sentinel.write_text("built once")

    await build_venv(request)

    assert sentinel.read_text() == "built once"


async def test_a_changed_lock_rebuilds_the_venv(tmp_path):
    first = [make_wheel(tmp_path / "first", "uvicorn", "0.52.3")]
    request = request_for(tmp_path, backend(tmp_path, first))
    await build_venv(request)
    (request.venv / "kept").write_text("old")
    for wheel in (request.backend / "wheels").iterdir():
        wheel.unlink()
    second = [make_wheel(tmp_path / "second", "uvicorn", "0.53.0")]
    backend(tmp_path, second)

    python = await build_venv(request)

    assert not (request.venv / "kept").exists()
    assert run_isolated(python, "import uvicorn; print(uvicorn.VERSION)") == "0.53.0"


async def test_a_hash_mismatch_fails_the_offline_install(tmp_path):
    wheels = [make_wheel(tmp_path / "built", "uvicorn", "0.52.3")]
    lock = f"uvicorn==0.52.3 --hash=sha256:{'0' * 64}\n"
    request = request_for(tmp_path, backend(tmp_path, wheels, lock))

    with pytest.raises(VenvBuildError, match="DO NOT MATCH THE HASHES"):
        await build_venv(request)

    assert not (request.venv / MARKER_FILE_NAME).exists()


async def test_a_wrong_platform_wheel_is_refused_before_pip_runs(tmp_path):
    wheels = [
        make_wheel(tmp_path / "built", "uvicorn", "0.52.3"),
        make_wheel(tmp_path / "built", "pydantic-core", "2.46.4", tag=FOREIGN_WHEEL_TAG),
    ]
    request = request_for(tmp_path, backend(tmp_path, wheels))

    with pytest.raises(IncompatibleWheelError, match="pydantic-core 2.46.4 has no wheel for this node"):
        await build_venv(request)

    assert not request.venv.exists()


def wheel_running_code_as_whoever_starts_the_venv(directory: Path, marker: Path, **extra) -> Path:
    """A wheel whose root `.pth` runs on every start of the venv's interpreter."""
    pth = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('ran')\n"
    return make_wheel(directory, "evil", "1.0", extra_files={"evil.pth": pth, **extra})


async def test_a_wheels_pth_file_never_runs_while_the_venv_is_built(tmp_path):
    marker = tmp_path / "ran-as-the-agent"
    wheels = [
        make_wheel(tmp_path / "built", "uvicorn", "0.52.3"),
        wheel_running_code_as_whoever_starts_the_venv(tmp_path / "built", marker),
    ]
    request = request_for(tmp_path, backend(tmp_path, wheels))

    python = await build_venv(request)

    # The build never started the venv's interpreter after the install; only the plugin's
    # own UID will, when the launcher starts it.
    assert not marker.exists()
    run_isolated(python, "pass")
    assert marker.read_text() == "ran"


async def test_a_wheel_that_replaces_the_venvs_python_fails_the_build_unrun(tmp_path):
    marker = tmp_path / "ran-as-the-agent"
    replaced = tmp_path / "replaced-python-ran"
    script = f"#!/bin/sh\necho ran > {replaced}\n"
    wheels = [
        make_wheel(tmp_path / "built", "uvicorn", "0.52.3"),
        wheel_running_code_as_whoever_starts_the_venv(
            tmp_path / "built",
            marker,
            **{"evil-1.0.data/scripts/python": script, "evil-1.0.data/scripts/python3": script},
        ),
    ]
    request = request_for(tmp_path, backend(tmp_path, wheels))

    with pytest.raises(VenvBuildError, match="is not a symlink; a wheel may have replaced it"):
        await build_venv(request)

    assert not marker.exists()
    assert not replaced.exists()
    assert not (request.venv / MARKER_FILE_NAME).exists()
