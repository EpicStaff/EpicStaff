"""Real `python -m venv` and offline pip installs, from wheels built in the test.

The interpreter is the tests' own; the pip that installs is the wheel its standard library ships
for ensurepip, as on the node.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from es_plugins.packages import venv_builder
from es_plugins.packages.venv_builder import (
    VenvBuildError,
    VenvRequest,
    build_venv,
    script_first_line,
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

    assert not request.venv.exists()


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
    assert not request.venv.exists()


def marker_writer(directory: Path, label: str) -> str:
    return f"import pathlib; pathlib.Path({str(directory)!r}, {label!r}).write_text('ran')\n"


async def test_the_venv_has_no_pip_of_its_own(tmp_path):
    request = request_for(tmp_path, backend(tmp_path, [make_wheel(tmp_path / "built", "uvicorn", "0.52.3")]))

    python = await build_venv(request)

    assert run_isolated(python, "import importlib.util; print(importlib.util.find_spec('pip'))") == "None"


async def test_a_wheel_that_overwrites_pips_files_never_runs_while_the_venv_is_built(tmp_path):
    ran = tmp_path / "ran"
    ran.mkdir()
    # pip's entry point and modules it imports while it installs: a pip that ran from the venv's
    # site-packages would have run them as the agent.
    overwritten = {
        path: marker_writer(ran, path.replace("/", "."))
        for path in (
            "pip/__init__.py",
            "pip/__main__.py",
            "pip/_internal/__init__.py",
            "pip/_internal/cli/main.py",
            "pip/_internal/operations/install/wheel.py",
            "pip/_internal/utils/misc.py",
        )
    }
    wheels = [
        make_wheel(tmp_path / "built", "uvicorn", "0.52.3"),
        make_wheel(tmp_path / "built", "evil", "1.0", extra_files=overwritten),
    ]
    request = request_for(tmp_path, backend(tmp_path, wheels))

    python = await build_venv(request)

    assert list(ran.iterdir()) == []
    # The files are in the plugin's venv: its own interpreter runs them once it imports pip.
    run_isolated(python, "import pip")
    assert "pip.__init__.py" in {path.name for path in ran.iterdir()}


async def test_scripts_pip_writes_run_the_venvs_python(tmp_path):
    wheels = [
        make_wheel(
            tmp_path / "built",
            "uvicorn",
            "0.52.3",
            body="VERSION = '0.52.3'\n\ndef main():\n    import sys\n    print(VERSION, sys.prefix)\n",
            extra_files={
                "uvicorn-0.52.3.dist-info/entry_points.txt": "[console_scripts]\nserve-weather = uvicorn:main\n",
                "uvicorn-0.52.3.data/scripts/weather-script": "#!python\nimport sys, uvicorn\nprint(uvicorn.VERSION, sys.prefix)\n",
            },
        )
    ]
    request = request_for(tmp_path, backend(tmp_path, wheels))

    python = await build_venv(request)

    # The test's wheel carries no file modes: its data script is not executable as installed.
    (request.venv / "bin" / "weather-script").chmod(0o755)
    for script in ("serve-weather", "weather-script"):
        path = request.venv / "bin" / script
        assert path.read_bytes().startswith(script_first_line(bytes(python)))
        output = subprocess.run([str(path)], check=True, capture_output=True, text=True).stdout.strip()
        assert output == f"0.52.3 {request.venv}"


def test_a_scripts_first_line_runs_a_long_python_path_through_the_shell():
    assert script_first_line(b"/venv/bin/python") == b"#!/venv/bin/python\n"
    long_path = b"/var/lib/es_plugins/venvs/" + b"p" * 100 + b"/bin/python"
    assert script_first_line(long_path) == (
        b"#!/bin/sh\n" + b"'''exec' " + long_path + b' "$0" "$@"\n' + b"' '''\n"
    )


async def test_an_interpreter_without_a_pip_wheel_of_its_own_is_refused(tmp_path):
    interpreter = tmp_path / "python"
    interpreter.write_text("#!/bin/sh\necho '{\"version\": \"3.13\", \"executable\": \"/x\", \"pip_wheels\": []}'\n")
    interpreter.chmod(0o755)

    with pytest.raises(VenvBuildError, match="ships 0 pip wheels for ensurepip, not one"):
        await venv_builder._describe_interpreter(interpreter)
