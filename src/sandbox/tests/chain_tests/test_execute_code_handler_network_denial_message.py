"""wrap_code's network-denial message: turning a bare EACCES PermissionError
(or a DNS gaierror, or a wrapped URLError) into a plain-English "the sandbox
network policy blocked this" explanation, without misattributing an
unrelated Landlock filesystem denial to the network.

Two layers are covered:

Layer A — the generated preamble (real subprocess, no real seccomp filter):
  wrap_code()'s output is executed directly with sys.executable, exactly the
  way test_execute_code_handler_env.py drives get_secret end-to-end. The
  child code raises the exception itself (with the errno/filename/type shape
  a real seccomp or Landlock denial -- or DNS failure -- would have) to
  exercise the except clause without needing a real kernel filter in this
  environment. The real, kernel-enforced shapes are additionally pinned by
  test_seccomp.py and by an in-image probe (not part of this suite).

Layer B — wiring in ExecuteCodeHandler.handle():
  SANDBOX_NETWORK_BLOCKED must reach the child's environment as "all" for
  BLOCK_ALL, "storage_only" for ALLOW_PORTS, and be absent otherwise. Same
  fake-subprocess approach as test_execute_code_handler_isolation.py.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain
import settings
from dynamic_venv_executor_chain import ExecuteCodeHandler

from conftest import make_execute_context

SHARED_PATH = Path(__file__).resolve().parents[3] / "shared"


def _run_wrapped(tmp_path: Path, code: str, env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    import os

    result_path = tmp_path / "output.txt"
    wrapped = ExecuteCodeHandler().wrap_code(
        code=code,
        result_file_path=result_path,
        entrypoint="main",
        func_kwargs={},
        global_kwargs={},
    )
    code_path = tmp_path / "code.py"
    code_path.write_text(wrapped)

    return subprocess.run(
        [sys.executable, str(code_path)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SHARED_PATH), **env_overrides},
    )


_EACCES = "    raise OSError(13, 'Permission denied')\n"
_EACCES_ON_A_PATH = "    raise PermissionError(13, 'Permission denied', '/some/jailed/path')\n"
_ENOENT = "    raise OSError(2, 'No such file or directory')\n"
_DNS_FAILURE = (
    "    import socket\n"
    "    raise socket.gaierror(-3, 'Temporary failure in name resolution')\n"
)
_URLERROR_EACCES = (
    "    import urllib.error\n"
    "    raise urllib.error.URLError(OSError(13, 'Permission denied'))\n"
)
_URLERROR_ENOENT = (
    "    import urllib.error\n"
    "    raise urllib.error.URLError(OSError(2, 'No such file or directory'))\n"
)

ALL = {"SANDBOX_NETWORK_BLOCKED": "all"}
STORAGE_ONLY = {"SANDBOX_NETWORK_BLOCKED": "storage_only"}


@pytest.mark.parametrize(
    ("env", "raises", "expected_wording", "must_keep"),
    [
        # A seccomp socket() denial: EACCES with no filename (socket() takes no path).
        (ALL, _EACCES, "blocks all outbound network access", None),
        # A Landlock filesystem denial carries a filename: never blamed on the network.
        (ALL, _EACCES_ON_A_PATH, None, "/some/jailed/path"),
        # Only when the parent actually applied the block, never speculatively.
        ({}, _EACCES, None, "[Errno 13]"),
        (ALL, _ENOENT, None, "[Errno 2]"),
        # requests hits DNS before any socket exists; under a full block DNS cannot succeed.
        (ALL, _DNS_FAILURE, "blocks all outbound network access", None),
        # urllib hides the errno inside URLError.reason.
        (ALL, _URLERROR_EACCES, "blocks all outbound network access", None),
        (ALL, _URLERROR_ENOENT, None, None),
        # A Landlock port denial outside the storage endpoint.
        (STORAGE_ONLY, _EACCES, "storage endpoint", None),
        # Under storage_only DNS stays open, so a resolution failure is genuine.
        (STORAGE_ONLY, _DNS_FAILURE, None, None),
    ],
    ids=[
        "full-block-socket-denial",
        "filesystem-denial-under-full-block",
        "socket-denial-without-a-block",
        "unrelated-oserror",
        "full-block-dns-failure",
        "full-block-urlerror",
        "unrelated-urlerror",
        "storage-only-socket-denial",
        "storage-only-dns-failure",
    ],
)
def test_network_denial_is_explained_only_when_the_policy_caused_it(
    tmp_path, env, raises, expected_wording, must_keep
):
    result = _run_wrapped(tmp_path, code="def main(**kwargs):\n" + raises, env_overrides=env)

    assert result.returncode == 1
    if expected_wording:
        assert "sandbox network policy" in result.stderr
        assert expected_wording in result.stderr
        assert "[Errno 13]" not in result.stderr
    else:
        assert "sandbox network policy" not in result.stderr
    if must_keep:
        assert must_keep in result.stderr


class TestGetaddrinfoMonkeypatch:
    """The wrap_code() preamble replaces socket.getaddrinfo so that any
    consumer's own `except socket.gaierror as e: ...{e}...` -- not just the
    `except OSError` clause above -- gets the truthful policy wording. This
    is what actually fixes the six shared tools (web_fetch_tool and co.) that
    catch gaierror themselves inside their own _ssrf_guard() and format it
    into their own returned string, never letting it reach wrap_code's own
    except clause.

    __sys_real_getaddrinfo is swapped out (rather than hitting real DNS) so
    these tests are deterministic regardless of the machine's network/DNS
    state.
    """

    # Indented at 4 spaces to sit directly inside `def main(**kwargs):`.
    # Swaps out __sys_real_getaddrinfo (the saved original the wrapper
    # calls through) so the wrapper's own gaierror-catching logic is
    # exercised deterministically, without touching real DNS.
    _FAKE_REAL_GETADDRINFO_RAISES = (
        "    import socket\n"
        "    def _fake_real(*a, **kw):\n"
        "        raise socket.gaierror(-3, 'Temporary failure in name resolution')\n"
        "    globals()['__sys_real_getaddrinfo'] = _fake_real\n"
    )

    def test_patch_installed_under_full_block_and_errno_preserved(self, tmp_path):
        result = _run_wrapped(
            tmp_path,
            code=(
                "def main(**kwargs):\n"
                + self._FAKE_REAL_GETADDRINFO_RAISES
                + "    try:\n"
                "        socket.getaddrinfo('github.com', 443)\n"
                "    except socket.gaierror as e:\n"
                "        print(f'ERRNO={e.errno}')\n"
                "        raise\n"
            ),
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "all"},
        )

        assert result.returncode == 1
        assert "sandbox network policy" in result.stderr
        assert "ERRNO=-3" in result.stdout

    def test_tool_shaped_gaierror_consumer_gets_policy_wording(self, tmp_path):
        """Reproduces the exact pattern used by web_fetch_tool's
        _ssrf_guard(): catch gaierror locally and format it into a returned
        string, never letting it propagate to wrap_code's except clause."""
        result = _run_wrapped(
            tmp_path,
            code=(
                "def main(**kwargs):\n"
                + self._FAKE_REAL_GETADDRINFO_RAISES
                + "    try:\n"
                "        socket.getaddrinfo('github.com', 443)\n"
                "        return 'unreachable'\n"
                "    except socket.gaierror as e:\n"
                "        return f\"Error: could not resolve host 'github.com': {e}\"\n"
            ),
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "all"},
        )

        assert result.returncode == 0
        output = json.loads((tmp_path / "output.txt").read_text())
        assert output == (
            "Error: could not resolve host 'github.com': [Errno -3] "
            "Network access denied: the sandbox network policy blocks all "
            "outbound network access."
        )

    def test_patch_not_installed_under_storage_only(self, tmp_path):
        """Under storage_only the preamble must leave socket.getaddrinfo as
        the stdlib original. Asserted on the observable function -- its
        defining module and qualname -- rather than on the presence of a
        wrapper name, so renaming the wrapper cannot make this pass while the
        patch is installed (the preamble's wrapper is defined in the generated
        script, so its __module__ is "__main__", never "socket")."""
        result = _run_wrapped(
            tmp_path,
            code=(
                "def main(**kwargs):\n"
                "    import socket\n"
                "    if socket.getaddrinfo.__module__ != 'socket':\n"
                "        return 'PATCHED'\n"
                "    if socket.getaddrinfo.__qualname__ != 'getaddrinfo':\n"
                "        return 'PATCHED'\n"
                "    return 'NOT_PATCHED'\n"
            ),
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "storage_only"},
        )

        assert result.returncode == 0
        output = json.loads((tmp_path / "output.txt").read_text())
        assert output == "NOT_PATCHED"


def _make_execute_context(tmp_path: Path, **overrides):
    return make_execute_context(tmp_path, execution_id="test-exec-network-message", **overrides)


def _patch_subprocess(monkeypatch, recorded: dict, result_file_path: Path) -> None:
    class _FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def _fake_create(*args, **kwargs):
        recorded["argv"] = args
        recorded.update(kwargs)
        result_file_path.write_text('"ok"')
        return _FakeProcess()

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio,
        "create_subprocess_exec",
        _fake_create,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("block_network", "use_storage", "expected"),
    [(True, False, "all"), (False, False, None), (True, True, "storage_only")],
    ids=["block-all", "unrestricted", "allow-storage-port"],
)
async def test_child_is_told_which_network_block_applies(
    tmp_path, monkeypatch, block_network, use_storage, expected
):
    monkeypatch.setattr(settings, "BLOCK_NETWORK", block_network)
    monkeypatch.setattr(settings, "STORAGE_PORT", "9000")
    monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: 4)
    recorded: dict = {}
    context = _make_execute_context(
        tmp_path,
        use_storage=use_storage,
        temp_storage_access_key="scoped-ak",
        temp_storage_secret_key="scoped-sk",
    )
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    result = await ExecuteCodeHandler().handle(context)

    assert result.returncode == 0
    assert recorded["env"].get("SANDBOX_NETWORK_BLOCKED") == expected
