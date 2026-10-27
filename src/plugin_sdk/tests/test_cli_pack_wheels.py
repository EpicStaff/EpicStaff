import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from epicstaff_plugin.cli import backend_wheels
from epicstaff_plugin.cli.main import main
from epicstaff_plugin.package_layout import read_package_file

def _wheel_file_name(name, version, platform):
    tag = "py3-none-any" if platform == "any" else f"cp313-cp313-{platform}"
    return f"{name.replace('-', '_')}-{version}-{tag}.whl"


def _wheel_bytes(name, version, requires=()):
    """A wheel holding only its metadata; the same bytes every time."""
    metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n" + "".join(
        f"Requires-Dist: {requirement}\n" for requirement in requires
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo(f"{name.replace('-', '_')}-{version}.dist-info/METADATA", (2026, 1, 1, 0, 0, 0)), metadata)
    return buffer.getvalue()


def _served(name, version, platforms=("any",), requires=()):
    return {platform: _wheel_bytes(name, version, requires) for platform in platforms}


# The wheels the fake index serves, by requirement and platform; "any" serves every platform.
INDEX = {
    ("uvicorn", "0.52.3"): _served("uvicorn", "0.52.3", requires=('colorama ; sys_platform == "win32"',)),
    ("pydantic-core", "2.46.4"): _served(
        "pydantic-core", "2.46.4", ("manylinux_2_28_x86_64", "manylinux_2_28_aarch64"), ('arm-helper ; platform_machine == "aarch64"',)
    ),
    ("colorama", "0.4.6"): _served("colorama", "0.4.6"),
    ("arm-helper", "1.0.0"): _served("arm-helper", "1.0.0"),
    ("pyjwt", "2.13.0"): _served("pyjwt", "2.13.0"),
}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _lock_text(index=INDEX, uvicorn="uvicorn"):
    """The lock of `index`; `uvicorn` is how its line names it (with extras, say)."""

    def hashes(name, version):
        return " ".join(f"--hash=sha256:{_sha256(data)}" for data in index[(name, version)].values())

    return (
        "# compiled by uv\n"
        f"{uvicorn}==0.52.3 \\\n    {hashes('uvicorn', '0.52.3')}\n"
        f"pydantic-core==2.46.4 \\\n    {hashes('pydantic-core', '2.46.4')}\n"
        f"colorama==0.4.6 ; sys_platform == 'win32' \\\n    {hashes('colorama', '0.4.6')}\n"
        f"arm-helper==1.0.0 ; platform_machine == 'aarch64' \\\n    {hashes('arm-helper', '1.0.0')}\n"
        f"pyjwt==2.13.0 {hashes('pyjwt', '2.13.0')}\n"
    )


class FakePip:
    """Stands in for `python -m pip download`: reads the requirement file, writes wheels."""

    def __init__(self, returncode=0, index=INDEX):
        self.commands = []
        self.requested = {}
        self.returncode = returncode
        self.index = index

    def __call__(self, command, check):
        assert check is False
        self.commands.append(command)
        platform = command[command.index("--platform") + 1]
        destination = Path(command[command.index("--dest") + 1])
        lines = Path(command[command.index("--requirement") + 1]).read_text().splitlines()
        self.requested[platform] = [line.split(" ")[0] for line in lines]
        if self.returncode == 0:
            for line in lines:
                name, _, version = line.split(" ")[0].partition("==")
                wheels = self.index[(name, version)]
                served = "any" if "any" in wheels else platform
                (destination / _wheel_file_name(name, version, served)).write_bytes(wheels[served])
        return subprocess.CompletedProcess(command, self.returncode)


@pytest.fixture
def fake_pip(monkeypatch):
    pip = FakePip()
    monkeypatch.setattr(backend_wheels.subprocess, "run", pip)
    return pip


def _sdk_wheel(directory: Path, requires=("pyjwt>=2.10,<3", 'pytest ; extra == "test"')) -> Path:
    path = directory / "epicstaff_plugin-0.2.0-py3-none-any.whl"
    metadata = "Metadata-Version: 2.4\nName: epicstaff-plugin\nVersion: 0.2.0\n" + "".join(
        f"Requires-Dist: {requirement}\n" for requirement in requires
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("epicstaff_plugin/__init__.py", "")
        archive.writestr("epicstaff_plugin-0.2.0.dist-info/METADATA", metadata)
    return path


@pytest.fixture
def backend_source(plugin_source, tmp_path):
    """The Weather source with a backend whose lock does not pin the SDK yet."""
    source, spa = plugin_source
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["backend"] = {"python": "3.13", "entrypoint": "weather_plugin.app:app"}
    (source / "manifest.json").write_text(json.dumps(manifest))
    (source / "backend" / "src" / "weather_plugin").mkdir(parents=True)
    (source / "backend" / "src" / "weather_plugin" / "app.py").write_text("app = None\n")
    (source / "backend" / "requirements.lock").write_text(_lock_text())
    wheels = tmp_path / "local-wheels"
    wheels.mkdir()
    return source, spa, _sdk_wheel(wheels)


def _pack(source, spa, output, *options):
    return main(["pack", str(source), "--spa-dir", str(spa), "--out", str(output), *options])


def test_packing_with_wheels_adds_them_and_pins_the_local_one(backend_source, fake_pip, tmp_path):
    source, spa, sdk_wheel = backend_source
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output, "--download-wheels", "--local-wheel", str(sdk_wheel)) == 0

    package = read_package_file(output)
    wheels = sorted(file.path for file in package.files if file.path.startswith("backend/wheels/"))
    assert wheels == [
        "backend/wheels/arm_helper-1.0.0-py3-none-any.whl",
        "backend/wheels/epicstaff_plugin-0.2.0-py3-none-any.whl",
        "backend/wheels/pydantic_core-2.46.4-cp313-cp313-manylinux_2_28_aarch64.whl",
        "backend/wheels/pydantic_core-2.46.4-cp313-cp313-manylinux_2_28_x86_64.whl",
        "backend/wheels/pyjwt-2.13.0-py3-none-any.whl",
        "backend/wheels/uvicorn-0.52.3-py3-none-any.whl",
    ]
    with zipfile.ZipFile(output) as archive:
        packaged_lock = archive.read("backend/requirements.lock").decode()
    assert packaged_lock == (
        _lock_text()
        + "# Added by epicstaff-plugin pack --local-wheel.\n"
        + f"epicstaff-plugin==0.2.0 --hash=sha256:{_sha256(sdk_wheel.read_bytes())}\n"
    )


def test_packing_never_writes_into_the_source_directory(backend_source, fake_pip, tmp_path):
    source, spa, sdk_wheel = backend_source

    _pack(source, spa, tmp_path / "weather.esplugin", "--download-wheels", "--local-wheel", str(sdk_wheel))

    assert not (source / "backend" / "wheels").exists()
    assert (source / "backend" / "requirements.lock").read_text() == _lock_text()


def test_pip_downloads_binary_wheels_for_each_default_platform_with_markers_of_the_node(backend_source, fake_pip, tmp_path):
    source, spa, sdk_wheel = backend_source

    _pack(source, spa, tmp_path / "weather.esplugin", "--download-wheels", "--local-wheel", str(sdk_wheel))

    platforms = [command[command.index("--platform") + 1] for command in fake_pip.commands]
    assert platforms == ["manylinux_2_28_x86_64", "manylinux_2_28_aarch64"]
    for command in fake_pip.commands:
        assert command[1:4] == ["-m", "pip", "download"]
        for option in ("--no-deps", "--only-binary=:all:", "--require-hashes"):
            assert option in command
        assert command[command.index("--python-version") + 1] == "3.13"
        assert command[command.index("--implementation") + 1] == "cp"
        assert command[command.index("--abi") + 1] == "cp313"
    # Markers are evaluated for the node, not for this machine: no Windows-only colorama,
    # and the aarch64-only helper only for aarch64.
    assert fake_pip.requested == {
        "manylinux_2_28_x86_64": ["uvicorn==0.52.3", "pydantic-core==2.46.4", "pyjwt==2.13.0"],
        "manylinux_2_28_aarch64": ["uvicorn==0.52.3", "pydantic-core==2.46.4", "arm-helper==1.0.0", "pyjwt==2.13.0"],
    }


def test_the_platforms_can_be_chosen(backend_source, fake_pip, tmp_path):
    source, spa, sdk_wheel = backend_source

    _pack(
        source,
        spa,
        tmp_path / "weather.esplugin",
        "--download-wheels",
        "--platform",
        "manylinux_2_28_x86_64",
        "--local-wheel",
        str(sdk_wheel),
    )

    assert list(fake_pip.requested) == ["manylinux_2_28_x86_64"]


def test_packing_with_wheels_twice_gives_identical_bytes(backend_source, fake_pip, tmp_path):
    source, spa, sdk_wheel = backend_source
    first, second = tmp_path / "first.esplugin", tmp_path / "second.esplugin"

    assert _pack(source, spa, first, "--download-wheels", "--local-wheel", str(sdk_wheel)) == 0
    assert _pack(source, spa, second, "--download-wheels", "--local-wheel", str(sdk_wheel)) == 0

    assert first.read_bytes() == second.read_bytes()


def test_a_local_wheel_alone_is_added_without_downloading(backend_source, fake_pip, tmp_path):
    source, spa, sdk_wheel = backend_source
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output, "--local-wheel", str(sdk_wheel)) == 0

    assert fake_pip.commands == []
    assert [file.path for file in read_package_file(output).files if "wheels/" in file.path] == [
        "backend/wheels/epicstaff_plugin-0.2.0-py3-none-any.whl"
    ]


def test_a_lock_without_the_sdk_cannot_be_packed_without_its_wheel(backend_source, fake_pip, tmp_path, capsys):
    source, spa, _ = backend_source
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output, "--download-wheels") == 1
    assert "does not pin epicstaff-plugin, which every plugin backend needs" in capsys.readouterr().out
    assert not output.exists()


def test_a_local_wheel_the_lock_already_pins_is_refused(backend_source, fake_pip, tmp_path, capsys):
    source, spa, _ = backend_source
    wheels = tmp_path / "uvicorn-build"
    wheels.mkdir()
    local = wheels / "uvicorn-0.52.3-py3-none-any.whl"
    with zipfile.ZipFile(local, "w") as archive:
        archive.writestr("uvicorn-0.52.3.dist-info/METADATA", "Name: uvicorn\nVersion: 0.52.3\n")

    assert _pack(source, spa, tmp_path / "weather.esplugin", "--local-wheel", str(local)) == 1
    assert "already pins uvicorn" in capsys.readouterr().out


def test_a_local_wheel_whose_requirements_the_lock_misses_is_refused(backend_source, fake_pip, tmp_path, capsys):
    source, spa, _ = backend_source
    directory = tmp_path / "newer-sdk"
    directory.mkdir()
    sdk_wheel = _sdk_wheel(directory, requires=("pyjwt>=3", "cryptography>=50", 'pywin32 ; sys_platform == "win32"'))

    assert _pack(source, spa, tmp_path / "weather.esplugin", "--download-wheels", "--local-wheel", str(sdk_wheel)) == 1

    out = capsys.readouterr().out
    assert "does not pin pyjwt>=3, which epicstaff_plugin-0.2.0-py3-none-any.whl requires" in out
    assert "does not pin cryptography>=50" in out
    assert "pywin32" not in out
    assert fake_pip.commands == []


def _with_index(monkeypatch, source, index, uvicorn="uvicorn"):
    """Serve `index` from the fake pip, and give the source the lock compiled for it."""
    pip = FakePip(index=index)
    monkeypatch.setattr(backend_wheels.subprocess, "run", pip)
    (source / "backend" / "requirements.lock").write_text(_lock_text(index, uvicorn))
    return pip


def test_a_downloaded_wheel_whose_requirement_the_lock_misses_is_refused(backend_source, monkeypatch, tmp_path, capsys):
    source, spa, sdk_wheel = backend_source
    _with_index(monkeypatch, source, {**INDEX, ("uvicorn", "0.52.3"): _served("uvicorn", "0.52.3", requires=("h11>=0.8",))})
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output, "--download-wheels", "--local-wheel", str(sdk_wheel)) == 1

    assert (
        "does not pin h11>=0.8, which uvicorn-0.52.3-py3-none-any.whl requires on "
        "manylinux_2_28_x86_64, manylinux_2_28_aarch64; add it to the requirements the lock is compiled from"
    ) in capsys.readouterr().out
    assert not output.exists()


def test_a_requirement_only_one_platform_installs_names_that_platform(backend_source, monkeypatch, tmp_path, capsys):
    source, spa, sdk_wheel = backend_source
    platforms = ("manylinux_2_28_x86_64", "manylinux_2_28_aarch64")
    requires = ('arm-only ; platform_machine == "aarch64"',)
    _with_index(monkeypatch, source, {**INDEX, ("pydantic-core", "2.46.4"): _served("pydantic-core", "2.46.4", platforms, requires)})

    assert _pack(source, spa, tmp_path / "weather.esplugin", "--download-wheels", "--local-wheel", str(sdk_wheel)) == 1

    out = capsys.readouterr().out
    assert (
        "does not pin arm-only; platform_machine == \"aarch64\", which "
        "pydantic_core-2.46.4-cp313-cp313-manylinux_2_28_aarch64.whl requires on manylinux_2_28_aarch64;"
    ) in out
    assert "x86_64.whl requires" not in out


@pytest.mark.parametrize(("lock_line", "packed"), [("uvicorn[standard]", False), ("uvicorn", True)], ids=["asked", "not_asked"])
def test_what_an_extra_requires_counts_only_when_the_lock_asks_for_the_extra(
    backend_source, monkeypatch, tmp_path, capsys, lock_line, packed
):
    source, spa, sdk_wheel = backend_source
    requires = ('watchfiles>=0.13 ; extra == "standard"',)
    _with_index(monkeypatch, source, {**INDEX, ("uvicorn", "0.52.3"): _served("uvicorn", "0.52.3", requires=requires)}, lock_line)

    status = _pack(source, spa, tmp_path / "weather.esplugin", "--download-wheels", "--local-wheel", str(sdk_wheel))

    assert status == (0 if packed else 1)
    assert ("does not pin watchfiles>=0.13" in capsys.readouterr().out) is not packed


def test_an_extra_a_requirement_asks_for_counts_too(backend_source, monkeypatch, tmp_path, capsys):
    source, spa, sdk_wheel = backend_source
    index = {
        **INDEX,
        ("pyjwt", "2.13.0"): _served("pyjwt", "2.13.0", requires=('cryptography>=3.4 ; extra == "crypto"',)),
    }
    _with_index(monkeypatch, source, index)
    directory = tmp_path / "crypto-sdk"
    directory.mkdir()
    crypto_sdk = _sdk_wheel(directory, requires=("pyjwt[crypto]>=2.10,<3",))

    assert _pack(source, spa, tmp_path / "weather.esplugin", "--download-wheels", "--local-wheel", str(crypto_sdk)) == 1

    assert "does not pin cryptography>=3.4; extra == \"crypto\", which pyjwt-2.13.0-py3-none-any.whl requires" in capsys.readouterr().out


def test_wheels_the_source_ships_are_checked_too(backend_source, fake_pip, tmp_path, capsys):
    source, spa, _ = backend_source
    (source / "backend" / "wheels").mkdir()
    (source / "backend" / "wheels" / "uvicorn-0.52.3-py3-none-any.whl").write_bytes(
        _wheel_bytes("uvicorn", "0.52.3", requires=("h11>=0.8",))
    )
    (source / "backend" / "wheels" / "pyjwt-2.13.0-py3-none-any.whl").write_bytes(b"not a zip")

    assert _pack(source, spa, tmp_path / "weather.esplugin") == 1

    out = capsys.readouterr().out
    assert "does not pin h11>=0.8, which uvicorn-0.52.3-py3-none-any.whl requires" in out
    assert "package.backend/wheels/pyjwt-2.13.0-py3-none-any.whl: cannot be read: File is not a zip file" in out


def test_a_failed_download_writes_no_package(backend_source, monkeypatch, tmp_path, capsys):
    source, spa, sdk_wheel = backend_source
    monkeypatch.setattr(backend_wheels.subprocess, "run", FakePip(returncode=1))
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output, "--download-wheels", "--local-wheel", str(sdk_wheel)) == 1
    assert "pip could not download every wheel for manylinux_2_28_x86_64" in capsys.readouterr().out
    assert not output.exists()


def test_downloading_needs_pip(backend_source, fake_pip, monkeypatch, tmp_path, capsys):
    source, spa, sdk_wheel = backend_source
    monkeypatch.setattr(backend_wheels.importlib.util, "find_spec", lambda name: None)

    assert _pack(source, spa, tmp_path / "weather.esplugin", "--download-wheels", "--local-wheel", str(sdk_wheel)) == 2
    assert "--download-wheels runs pip, which is not installed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--platform", "manylinux_2_28_x86_64"], "--platform applies only with --download-wheels"),
        (["--download-wheels", "--platform", "macosx_14_0_arm64"], "is not a Linux wheel platform"),
        (["--local-wheel", "missing-1.0.0-py3-none-any.whl"], "cannot read --local-wheel"),
        (["--local-wheel", "not-a-wheel.zip"], "is not named like a wheel"),
    ],
)
def test_wrong_wheel_options_are_usage_errors(backend_source, fake_pip, tmp_path, capsys, options, message):
    source, spa, _ = backend_source

    assert _pack(source, spa, tmp_path / "weather.esplugin", *options) == 2
    assert message in capsys.readouterr().err


def test_downloading_into_a_source_that_ships_wheels_is_a_usage_error(backend_source, fake_pip, tmp_path, capsys):
    source, spa, sdk_wheel = backend_source
    (source / "backend" / "wheels").mkdir()
    (source / "backend" / "wheels" / "uvicorn-0.52.3-py3-none-any.whl").write_bytes(b"uvicorn-wheel")

    assert _pack(source, spa, tmp_path / "weather.esplugin", "--download-wheels", "--local-wheel", str(sdk_wheel)) == 2
    assert "the source already has backend/wheels/" in capsys.readouterr().err


def test_wheels_need_a_backend(plugin_source, tmp_path, capsys):
    source, spa = plugin_source
    sdk_directory = tmp_path / "sdk"
    sdk_directory.mkdir()

    assert _pack(source, spa, tmp_path / "weather.esplugin", "--local-wheel", str(_sdk_wheel(sdk_directory))) == 1
    assert "manifest.backend: is missing, but wheels were asked for" in capsys.readouterr().out


def test_the_requirements_the_lock_is_compiled_from_stay_in_the_source(backend_source, tmp_path):
    source, spa, sdk_wheel = backend_source
    (source / "backend" / "requirements.in").write_text("uvicorn\n")
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output, "--local-wheel", str(sdk_wheel)) == 0

    with zipfile.ZipFile(output) as archive:
        assert "backend/requirements.in" not in archive.namelist()


def test_pip_is_given_every_older_manylinux_tag_the_node_runs(backend_source, fake_pip, tmp_path):
    source, spa, sdk_wheel = backend_source

    _pack(source, spa, tmp_path / "weather.esplugin", "--download-wheels", "--local-wheel", str(sdk_wheel))

    x86_64, aarch64 = (
        [command[index + 1] for index, option in enumerate(command) if option == "--platform"]
        for command in fake_pip.commands
    )
    assert x86_64[:3] == ["manylinux_2_28_x86_64", "manylinux_2_27_x86_64", "manylinux_2_26_x86_64"]
    assert {"manylinux_2_17_x86_64", "manylinux2014_x86_64", "manylinux2010_x86_64", "manylinux1_x86_64"} <= set(x86_64)
    assert x86_64[-2:] == ["manylinux_2_5_x86_64", "manylinux1_x86_64"]
    assert aarch64[-2:] == ["manylinux_2_17_aarch64", "manylinux2014_aarch64"]


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("manylinux2014_aarch64", ["manylinux_2_17_aarch64", "manylinux2014_aarch64"]),
        ("musllinux_1_2_x86_64", ["musllinux_1_2_x86_64", "musllinux_1_1_x86_64"]),
    ],
)
def test_compatible_platforms(platform, expected):
    assert backend_wheels.compatible_platforms(platform) == expected
