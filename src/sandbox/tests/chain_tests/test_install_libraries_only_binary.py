"""`InstallLibrariesHandler` installs caller-supplied libraries wheels-only.

A caller-supplied source package's setup.py / PEP 517 build hook runs as root at
install time, where the per-uid egress firewall does not filter it, so those
installs must carry ``--only-binary=:all:`` (no install-time code runs). The pip
self-upgrade, pip freeze and the first-party ``/app/src/shared/*`` local-path
installs must NOT -- the shared packages are source dirs with no wheels.

No real pip: asyncio.create_subprocess_exec is faked, so the test records the
argv of every subprocess the handler fires.
"""

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain
from dynamic_venv_executor_chain import InstallLibrariesHandler

ONLY_BINARY = "--only-binary=:all:"
INTERNAL_LIBRARY = "/app/src/shared/dotdict"
CALLER_LIBRARY = "requests==2.31.0"


class _FakeProcess:
    returncode = 0

    async def communicate(self):
        # Empty pip-freeze output -> no uninstall calls, keeping the trace to
        # upgrade + freeze + the install loop.
        return (b"", b"")


def _argv_for(recorded_calls: list[tuple], token: str) -> tuple | None:
    """Return the first recorded argv containing an argument ending with token."""
    for argv in recorded_calls:
        if any(str(arg).endswith(token) for arg in argv):
            return argv
    return None


@pytest.mark.asyncio
async def test_only_caller_libraries_are_installed_binary_only(tmp_path, monkeypatch):
    recorded_calls: list[tuple] = []

    async def _fake_exec(*args, **kwargs):
        recorded_calls.append(args)
        return _FakeProcess()

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio, "create_subprocess_exec", _fake_exec
    )

    hash_file = tmp_path / "libhash"  # absent -> hash_changed -> installs run
    context = {
        "python_executable": tmp_path / "bin" / "python",
        "lib_hash": "deadbeef",
        "hash_file": hash_file,
        "execution_id": "exec-only-binary-001",
        "libraries": [INTERNAL_LIBRARY, CALLER_LIBRARY],
    }

    result = await InstallLibrariesHandler().handle(context)

    assert result == "Libraries installed."

    caller_install = _argv_for(recorded_calls, CALLER_LIBRARY)
    assert caller_install is not None, "caller library was never installed"
    assert ONLY_BINARY in caller_install

    internal_install = _argv_for(recorded_calls, INTERNAL_LIBRARY)
    assert internal_install is not None, "internal library was never installed"
    assert ONLY_BINARY not in internal_install

    pip_upgrade = _argv_for(recorded_calls, "pip")  # the "--upgrade" / "freeze" calls
    assert pip_upgrade is not None
    for argv in recorded_calls:
        if "--upgrade" in argv or "freeze" in argv:
            assert ONLY_BINARY not in argv
