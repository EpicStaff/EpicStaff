"""The uv command lines the provider builds, with uv itself never run.

Asserted here rather than left to an end-to-end run because the flag that matters has
to reach two commands, not one, and dropping it from the second is invisible until a
venv declaring a custom library fails to install something it had already resolved.
"""

from pathlib import Path

import pytest

from manager.infrastructure.providers import UVProvider


@pytest.fixture
def commands(monkeypatch) -> list[tuple[str, ...]]:
    """Every uv invocation `apply` makes, in order, with the process never started."""
    recorded: list[tuple[str, ...]] = []

    async def record(*args: str, **kwargs):
        recorded.append(args)

    monkeypatch.setattr(UVProvider, "run", record)
    return recorded


@pytest.fixture
def venv_path(tmp_path) -> Path:
    path = tmp_path / "venv"
    path.mkdir()
    return path


async def test_both_commands_are_told_about_the_wheelhouse(commands, venv_path, tmp_path):
    """The lock pins a version no package index has, so the sync that installs from
    that lock has to be able to find it too."""
    wheelhouse = tmp_path / "wheels"

    await UVProvider.apply(venv_path, "acme-core>=1", wheelhouse=wheelhouse)

    assert [command[:2] for command in commands] == [("pip", "compile"), ("pip", "sync")]
    for command in commands:
        assert "--find-links" in command
        assert command[command.index("--find-links") + 1] == str(wheelhouse)


async def test_neither_command_mentions_a_wheelhouse_when_there_is_none(commands, venv_path):
    """A venv of ordinary packages resolves exactly as it did before this existed."""
    await UVProvider.apply(venv_path, "requests>=2")

    assert commands
    assert all("--find-links" not in command for command in commands)
    assert all("--offline" not in command and "--no-index" not in command for command in commands)


async def test_an_offline_build_keeps_both_commands_off_the_index(commands, venv_path, tmp_path):
    """A system venv is built at startup with no internet: the resolve and the install
    both read the image's wheelhouse alone."""
    wheelhouse = tmp_path / "system_wheelhouse"

    await UVProvider.apply(venv_path, "pdfplumber==0.11.10", wheelhouse=wheelhouse, offline=True)

    assert [command[:2] for command in commands] == [("pip", "compile"), ("pip", "sync")]
    for command in commands:
        assert {"--offline", "--no-index"} <= set(command)
        assert command[command.index("--find-links") + 1] == str(wheelhouse)


async def test_the_requirements_still_reach_the_resolver_unchanged(monkeypatch, venv_path, tmp_path):
    """The wheelhouse says where to look, not what to install: the requirements go in
    on stdin as before, one per line."""
    sent: list[str | None] = []

    async def record(*args: str, input=None, **kwargs):
        sent.append(input)

    monkeypatch.setattr(UVProvider, "run", record)

    await UVProvider.apply(venv_path, "acme-core>=1", "requests", wheelhouse=tmp_path)

    assert sent[0] == "acme-core>=1\nrequests"


async def test_a_venv_that_was_never_initialised_is_refused(venv_path, tmp_path):
    with pytest.raises(ValueError):
        await UVProvider.apply(venv_path / "missing", "requests", wheelhouse=tmp_path)


async def test_predefined_packages_install_from_the_wheelhouse_alone(commands, venv_path, tmp_path):
    """A venv build at runtime must not reach a package index or run a build backend."""
    await UVProvider.install_local(venv_path, "dotdict", "epicstaff-storage", wheelhouse=tmp_path)

    [command] = commands
    assert command[:2] == ("pip", "install")
    assert {"--offline", "--no-index", "--no-build"} <= set(command)
    assert command[command.index("--find-links") + 1] == str(tmp_path)
    assert command[-2:] == ("dotdict", "epicstaff-storage")


async def test_every_predefined_package_is_reinstalled(commands, venv_path, tmp_path):
    """Our packages keep one version across images, so a venv that already holds one
    would otherwise keep the copy from an older image."""
    await UVProvider.install_local(venv_path, "dotdict", "epicstaff-storage", wheelhouse=tmp_path)

    [command] = commands
    reinstalled = {
        command[index + 1] for index, option in enumerate(command) if option == "--reinstall-package"
    }
    assert reinstalled == {"dotdict", "epicstaff-storage"}


async def test_a_library_with_extras_reaches_the_resolver_as_written(monkeypatch, venv_path):
    sent: list[str | None] = []

    async def record(*args: str, input=None, **kwargs):
        sent.append(input)

    monkeypatch.setattr(UVProvider, "run", record)

    await UVProvider.apply(venv_path, "requests[socks,security]>=2.0, <3")

    assert sent[0] == "requests[socks,security]>=2.0, <3"
