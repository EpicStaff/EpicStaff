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
  fake-subprocess approach as test_execute_code_handler_network.py.
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


class TestNetworkDenialMessageUnderFullBlock:
    def test_eacces_with_no_filename_reports_network_denial(self, tmp_path):
        """A seccomp socket() denial: OSError(EACCES) with no filename, since
        socket() takes no path argument."""
        result = _run_wrapped(
            tmp_path,
            code="def main(**kwargs):\n    raise OSError(13, 'Permission denied')\n",
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "all"},
        )

        assert result.returncode == 1
        assert "sandbox network policy" in result.stderr
        assert "[Errno 13]" not in result.stderr

    def test_eacces_with_filename_is_not_reported_as_a_network_denial(self, tmp_path):
        """A Landlock filesystem denial: OSError(EACCES) WITH a filename. Must
        not be misattributed to the network even though the flag is set."""
        result = _run_wrapped(
            tmp_path,
            code=(
                "def main(**kwargs):\n"
                "    raise PermissionError(13, 'Permission denied', '/some/jailed/path')\n"
            ),
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "all"},
        )

        assert result.returncode == 1
        assert "sandbox network policy" not in result.stderr
        assert "/some/jailed/path" in result.stderr

    def test_eacces_with_no_filename_is_not_reported_when_flag_unset(self, tmp_path):
        """The message must only appear when the parent actually applied the
        block -- never speculatively."""
        result = _run_wrapped(
            tmp_path,
            code="def main(**kwargs):\n    raise OSError(13, 'Permission denied')\n",
            env_overrides={},
        )

        assert result.returncode == 1
        assert "sandbox network policy" not in result.stderr
        assert "[Errno 13]" in result.stderr

    def test_non_eacces_oserror_is_not_reported_as_network_denial(self, tmp_path):
        result = _run_wrapped(
            tmp_path,
            code="def main(**kwargs):\n    raise OSError(2, 'No such file or directory')\n",
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "all"},
        )

        assert result.returncode == 1
        assert "sandbox network policy" not in result.stderr
        assert "[Errno 2]" in result.stderr

    def test_message_does_not_mention_storage_under_full_block(self, tmp_path):
        result = _run_wrapped(
            tmp_path,
            code="def main(**kwargs):\n    raise OSError(13, 'Permission denied')\n",
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "all"},
        )

        assert result.returncode == 1
        assert "storage endpoint" not in result.stderr

    def test_dns_gaierror_reports_network_denial_under_full_block(self, tmp_path):
        """The most common real path: `requests.get("https://...")` hits DNS
        before any socket exists. Under a full block, seccomp denies the UDP
        socket outright, so DNS cannot succeed for any external name -- no
        false-positive risk in treating every gaierror as the block."""
        result = _run_wrapped(
            tmp_path,
            code=(
                "def main(**kwargs):\n"
                "    import socket\n"
                "    raise socket.gaierror(-3, 'Temporary failure in name resolution')\n"
            ),
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "all"},
        )

        assert result.returncode == 1
        assert "sandbox network policy" in result.stderr

    def test_urlerror_wrapping_eacces_reports_network_denial_under_full_block(self, tmp_path):
        """urllib wraps the underlying OSError in URLError.reason and drops
        errno on the outer exception -- must unwrap one level to catch it."""
        result = _run_wrapped(
            tmp_path,
            code=(
                "def main(**kwargs):\n"
                "    import urllib.error\n"
                "    raise urllib.error.URLError(OSError(13, 'Permission denied'))\n"
            ),
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "all"},
        )

        assert result.returncode == 1
        assert "sandbox network policy" in result.stderr

    def test_urlerror_wrapping_unrelated_oserror_is_not_reported(self, tmp_path):
        """The unwrap must apply the same discriminator to the inner
        exception, not treat every URLError as a network denial."""
        result = _run_wrapped(
            tmp_path,
            code=(
                "def main(**kwargs):\n"
                "    import urllib.error\n"
                "    raise urllib.error.URLError(OSError(2, 'No such file or directory'))\n"
            ),
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "all"},
        )

        assert result.returncode == 1
        assert "sandbox network policy" not in result.stderr


class TestNetworkDenialMessageUnderStorageOnlyBlock:
    def test_eacces_with_no_filename_reports_storage_only_message(self, tmp_path):
        """A Landlock ALLOW_PORTS denial when user code reaches a non-storage
        host: PermissionError(EACCES), no filename -- same shape as the full
        block, different wording."""
        result = _run_wrapped(
            tmp_path,
            code="def main(**kwargs):\n    raise OSError(13, 'Permission denied')\n",
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "storage_only"},
        )

        assert result.returncode == 1
        assert "sandbox network policy" in result.stderr
        assert "storage endpoint" in result.stderr

    def test_dns_gaierror_is_not_reported_as_network_denial(self, tmp_path):
        """Under storage_only, Landlock restricts TCP connect only -- DNS
        (UDP) stays reachable -- so a gaierror here is a genuine resolution
        failure, not our policy, and must not be misreported."""
        result = _run_wrapped(
            tmp_path,
            code=(
                "def main(**kwargs):\n"
                "    import socket\n"
                "    raise socket.gaierror(-3, 'Temporary failure in name resolution')\n"
            ),
            env_overrides={"SANDBOX_NETWORK_BLOCKED": "storage_only"},
        )

        assert result.returncode == 1
        assert "sandbox network policy" not in result.stderr


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


class TestSandboxNetworkBlockedEnvVarWiring:
    @pytest.mark.asyncio
    async def test_env_var_is_all_when_policy_is_block_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "BLOCK_NETWORK", True)
        monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: 4)

        recorded: dict = {}
        context = _make_execute_context(tmp_path, use_storage=False)
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        result = await ExecuteCodeHandler().handle(context)

        assert result.returncode == 0
        assert recorded["env"]["SANDBOX_NETWORK_BLOCKED"] == "all"

    @pytest.mark.asyncio
    async def test_env_var_absent_when_network_is_unrestricted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "BLOCK_NETWORK", False)
        monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: 4)

        recorded: dict = {}
        context = _make_execute_context(tmp_path)
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        result = await ExecuteCodeHandler().handle(context)

        assert result.returncode == 0
        assert "SANDBOX_NETWORK_BLOCKED" not in recorded["env"]

    @pytest.mark.asyncio
    async def test_env_var_is_storage_only_when_policy_is_allow_ports(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "BLOCK_NETWORK", True)
        monkeypatch.setattr(settings, "STORAGE_PORT", "9000")
        monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: 4)

        recorded: dict = {}
        context = _make_execute_context(
            tmp_path,
            use_storage=True,
            temp_storage_access_key="scoped-ak",
            temp_storage_secret_key="scoped-sk",
        )
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        result = await ExecuteCodeHandler().handle(context)

        assert result.returncode == 0
        assert recorded["env"]["SANDBOX_NETWORK_BLOCKED"] == "storage_only"
