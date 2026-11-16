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
