"""seccomp is irreversible once installed in a process: there is no way to
undo block_network() and keep testing normal socket behaviour afterwards in the
same interpreter. Every behavioural assertion here therefore runs inside a
real subprocess that imports seccomp fresh, rather than calling block_network()
in the pytest process itself.
"""

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: seccomp/socket-family behaviour asserted here is Linux-specific; runs in the Linux image",
)

_SANDBOX_DIR = Path(__file__).resolve().parents[2]


def _run(snippet: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(_SANDBOX_DIR)},
    )


class TestBlockNetwork:
    def test_af_inet_socket_raises_permission_error_after_block_network(self):
        snippet = (
            "import socket\n"
            "import seccomp\n"
            "seccomp.block_network()\n"
            "try:\n"
            "    socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "except PermissionError:\n"
            "    pass\n"
            "else:\n"
            "    raise SystemExit('expected PermissionError for AF_INET')\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_af_inet6_socket_raises_permission_error_after_block_network(self):
        snippet = (
            "import socket\n"
            "import seccomp\n"
            "seccomp.block_network()\n"
            "try:\n"
            "    socket.socket(socket.AF_INET6, socket.SOCK_STREAM)\n"
            "except PermissionError:\n"
            "    pass\n"
            "else:\n"
            "    raise SystemExit('expected PermissionError for AF_INET6')\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_af_unix_socket_still_succeeds_after_block_network(self):
        """AF_UNIX is not an egress path and must stay usable -- multiprocessing,
        some logging handlers, and local IPC all depend on it."""
        snippet = (
            "import socket\n"
            "import seccomp\n"
            "seccomp.block_network()\n"
            "sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "sock.close()\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_ordinary_file_syscalls_still_work_after_block_network(self):
        """The filter must only affect socket(2), not syscalls in general."""
        snippet = (
            "import tempfile\n"
            "import seccomp\n"
            "seccomp.block_network()\n"
            "with tempfile.NamedTemporaryFile(mode='w+', delete=False) as handle:\n"
            "    handle.write('hello')\n"
            "    path = handle.name\n"
            "with open(path) as handle:\n"
            "    assert handle.read() == 'hello'\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_af_inet_socket_succeeds_without_block_network(self):
        """Proves the harness itself isn't what makes AF_INET fail above --
        without installing the filter, a plain AF_INET socket works fine."""
        snippet = (
            "import socket\n"
            "sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "sock.close()\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_af_netlink_socket_raises_permission_error_after_block_network(self):
        """Only AF_UNIX is permitted by the filter -- AF_NETLINK is denied like
        every other non-AF_UNIX family. (A stale comment in seccomp.py used to
        claim the opposite; this pins the actual behaviour.)"""
        snippet = (
            "import socket\n"
            "import seccomp\n"
            "seccomp.block_network()\n"
            "try:\n"
            "    socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 0)\n"
            "except PermissionError:\n"
            "    pass\n"
            "else:\n"
            "    raise SystemExit('expected PermissionError for AF_NETLINK')\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_local_name_resolution_still_works_after_block_network(self):
        """getaddrinfo("localhost", ...) is answered from /etc/hosts and never
        touches netlink, so it must keep working even though AF_NETLINK is
        denied above."""
        snippet = (
            "import socket\n"
            "import seccomp\n"
            "seccomp.block_network()\n"
            "socket.getaddrinfo('localhost', 80)\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_block_survives_execve_into_a_fresh_interpreter(self):
        """The filter must be inherited across execve, not reset by it --
        that's the whole point of enforcing it in the kernel rather than in
        this process's Python state."""
        snippet = (
            "import os, sys\n"
            "import seccomp\n"
            "seccomp.block_network()\n"
            "os.execv(sys.executable, [sys.executable, '-c',\n"
            "    'import socket\\n'\n"
            "    'try:\\n'\n"
            "    '    socket.socket(socket.AF_INET, socket.SOCK_STREAM)\\n'\n"
            "    'except PermissionError:\\n'\n"
            "    '    pass\\n'\n"
            "    'else:\\n'\n"
            "    '    raise SystemExit(\"expected PermissionError after execve\")\\n'\n"
            "])\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_no_new_privs_is_set_after_block_network(self):
        snippet = (
            "import ctypes\n"
            "import seccomp\n"
            "seccomp.block_network()\n"
            "_PR_GET_NO_NEW_PRIVS = 39\n"
            "nnp = ctypes.CDLL(None).prctl(_PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0)\n"
            "assert nnp == 1, f'expected NO_NEW_PRIVS=1, got {nnp}'\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_io_uring_setup_is_denied_after_block_network(self):
        """io_uring can create and drive sockets through its submission queue
        without ever issuing socket(2), so the socket(2) rule alone is
        bypassable -- io_uring_setup must be denied outright. There is no libc
        wrapper for it, so it is issued through syscall(2); the syscall number
        is resolved by libseccomp rather than hardcoded per architecture.

        EACCES specifically: a kernel built without io_uring answers ENOSYS,
        which must not be mistaken for the filter doing its job."""
        snippet = (
            "import ctypes\n"
            "import errno\n"
            "import seccomp\n"
            "libseccomp = ctypes.CDLL('libseccomp.so.2')\n"
            "libseccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]\n"
            "libseccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int\n"
            "io_uring_setup_number = libseccomp.seccomp_syscall_resolve_name(b'io_uring_setup')\n"
            "assert io_uring_setup_number >= 0, 'io_uring_setup unknown on this architecture'\n"
            "libc = ctypes.CDLL(None, use_errno=True)\n"
            "libc.syscall.restype = ctypes.c_long\n"
            "libc.syscall.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p]\n"
            "params = ctypes.create_string_buffer(256)\n"
            "seccomp.block_network()\n"
            "ctypes.set_errno(0)\n"
            "result = libc.syscall(io_uring_setup_number, 1, params)\n"
            "call_errno = ctypes.get_errno()\n"
            "if result != -1 or call_errno != errno.EACCES:\n"
            "    raise SystemExit(\n"
            "        f'expected io_uring_setup to be denied with EACCES, '\n"
            "        f'got result={result} errno={call_errno}'\n"
            "    )\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_filter_covers_a_thread_that_existed_before_block_network(self):
        """TSYNC applies the filter to the whole thread group. Without it the
        filter lands on the calling thread only, and any thread that was
        already running keeps unrestricted network access -- a silent hole the
        moment this runs anywhere threaded."""
        snippet = (
            "import socket\n"
            "import threading\n"
            "import seccomp\n"
            "thread_started = threading.Event()\n"
            "filter_installed = threading.Event()\n"
            "outcome = {}\n"
            "def probe_from_thread():\n"
            "    thread_started.set()\n"
            "    filter_installed.wait(30)\n"
            "    try:\n"
            "        socket.socket(socket.AF_INET, socket.SOCK_STREAM).close()\n"
            "    except PermissionError:\n"
            "        outcome['result'] = 'denied'\n"
            "    else:\n"
            "        outcome['result'] = 'allowed'\n"
            "thread = threading.Thread(target=probe_from_thread)\n"
            "thread.start()\n"
            "assert thread_started.wait(30), 'probe thread never started'\n"
            "seccomp.block_network()\n"
            "filter_installed.set()\n"
            "thread.join(30)\n"
            "if outcome.get('result') != 'denied':\n"
            "    raise SystemExit(\n"
            "        f'pre-existing thread was not covered by the filter: {outcome}'\n"
            "    )\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_denied_socket_error_has_the_shape_the_chain_discriminates_on(self):
        """dynamic_venv_executor_chain separates a network denial from a
        Landlock filesystem denial by `errno == EACCES and filename is None`.
        Every other test of that discriminator feeds hand-authored exceptions;
        this one pins the shape a real kernel seccomp denial actually has."""
        snippet = (
            "import socket\n"
            "import seccomp\n"
            "seccomp.block_network()\n"
            "try:\n"
            "    socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "except PermissionError as exc:\n"
            "    assert exc.errno == 13, f'expected EACCES, got {exc.errno}'\n"
            "    assert exc.filename is None, f'expected filename None, got {exc.filename!r}'\n"
            "else:\n"
            "    raise SystemExit('expected PermissionError for AF_INET')\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr
