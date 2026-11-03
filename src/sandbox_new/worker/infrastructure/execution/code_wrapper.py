"""Wraps user code into the source actually run inside the sandbox subprocess.

Builds the preamble that injects globals and secrets, runs the user's code, calls the
entrypoint, writes its return value to the result file, and turns a failure into one
readable line on stderr. This is mechanism, not policy: the real network/filesystem
boundary is the kernel-enforced seccomp/Landlock filter the launcher installs before
this source runs. Pure -- it only formats a string.

The user's code is embedded as a string literal and run with ``exec(compile(...))``
under the file name ``<code>``, never pasted into the wrapper's own source. So a
traceback's line numbers are the user's own, a syntax error is raised where the wrapper
can catch it, and a multi-line string in the code keeps its exact content.
"""

from pathlib import Path
from typing import Any

__all__ = ["RESULT_WRITE_FAILED_EXIT_CODE", "wrap_code"]

# The wrapped source exits with this code when it can't write the result file, with
# the error as its last stderr line. That failure is the server's, and the error
# names a server path, so the capture step logs it instead of showing it.
RESULT_WRITE_FAILED_EXIT_CODE = 125

_MISSING_ENTRYPOINT_MESSAGE = (
    'The code has no function named "{entrypoint}". Add one, or check its name.'
)

# Message-quality aid only, NOT a security control -- the real boundary is the
# kernel-enforced seccomp/Landlock filter launcher.py installs before this interpreter
# starts. SANDBOX_NETWORK_BLOCKED mirrors that real state ("all" / "storage_only"), set
# by the launch step.
_PREAMBLE = r"""
import builtins as __sys_builtins
import errno as __sys_errno
import os as __sys_os
import socket as __sys_socket
import sys
import json
import linecache as __sys_linecache
import traceback as __sys_traceback

# The user's code shares these globals and can rebind any name in them, builtins
# included (type = "pdf", str = 1). Everything that runs after it reaches modules,
# builtins and functions only through these private aliases, never by a public name.
__sys_json_dumps = json.dumps
__sys_json_dump = json.dump
__sys_stderr = sys.stderr
__sys_exit = sys.exit

__sys_network_block_mode = __sys_os.environ.get("SANDBOX_NETWORK_BLOCKED")


def __sys_network_block_message():
    if __sys_network_block_mode == "storage_only":
        return (
            "Network access denied: the sandbox network policy allows outbound "
            "network access only to the storage endpoint."
        )
    return "Network access denied: the sandbox network policy blocks all outbound network access."


# Some in-sandbox tools catch socket.gaierror themselves and format it into
# their own returned string, e.g. f"could not resolve host {host}: {e}",
# so it never reaches __sys_is_network_denial() below. Monkeypatching
# getaddrinfo makes the exception itself carry the policy message, so every
# consumer that does str(e) gets it for free. Message-quality aid only, not a
# security control. Gated on "all" only: under storage_only, DNS genuinely
# still works over UDP, so a gaierror there is a real failure, not this.
if __sys_network_block_mode == "all":
    __sys_real_getaddrinfo = __sys_socket.getaddrinfo

    def __sys_getaddrinfo(*args, **kwargs):
        try:
            return __sys_real_getaddrinfo(*args, **kwargs)
        except __sys_socket.gaierror as exc:
            raise __sys_socket.gaierror(exc.errno, __sys_network_block_message()) from None

    __sys_socket.getaddrinfo = __sys_getaddrinfo


def __sys_is_network_denial(exc):
    # Partial coverage, deliberately: the raw OSError/PermissionError from
    # seccomp/Landlock, socket.gaierror (DNS), and one level of unwrap for
    # urllib's URLError (.reason). Other wrapper exceptions (requests, httpx,
    # botocore, ...) fall through to the readable error message below.
    if __sys_builtins.isinstance(exc, __sys_socket.gaierror):
        # Only a full block guarantees DNS itself fails; under storage_only,
        # Landlock leaves DNS reachable, so a gaierror there is real and must
        # not be misreported as a policy denial.
        return __sys_network_block_mode == "all"
    return (
        __sys_builtins.isinstance(exc, __sys_builtins.OSError)
        and exc.errno == __sys_errno.EACCES
        and exc.filename is None
    )
"""

# Reads the user's own line from the traceback: the deepest frame in "<code>" is the
# line that raised, or the user's call into the library that did.
_RUNNER = r"""

def __sys_fail(message, exit_code=1):
    __sys_stderr.write(message + "\n")
    __sys_stderr.flush()
    __sys_exit(exit_code)


def __sys_user_line(exc):
    line = None
    for frame, line_number in __sys_traceback.walk_tb(exc.__traceback__):
        if frame.f_code.co_filename == __sys_code_filename:
            line = line_number
    return line


def __sys_error_detail(exc):
    if (
        __sys_builtins.isinstance(exc, __sys_builtins.KeyError)
        and __sys_builtins.len(exc.args) == 1
    ):
        return f"key {exc.args[0]!r} doesn't exist"
    return __sys_builtins.str(exc)


def __sys_error_message(exc):
    # The location stands on its own: the detail runs the exception's own code
    # (its __str__, a key's __repr__), which can raise too.
    is_own_syntax_error = (
        __sys_builtins.isinstance(exc, __sys_builtins.SyntaxError)
        and exc.filename == __sys_code_filename
        and exc.lineno is not None
    )
    line = exc.lineno if is_own_syntax_error else __sys_user_line(exc)
    name = __sys_builtins.type(exc).__name__
    location = name if line is None else f"{name} on line {line}"
    try:
        detail = exc.msg if is_own_syntax_error else __sys_error_detail(exc)
        return f"{location}: {detail}" if detail else location
    except __sys_builtins.Exception:
        return location


def __sys_failure_message(exc):
    if __sys_network_block_mode and __sys_builtins.isinstance(exc, __sys_builtins.OSError):
        try:
            denied = __sys_is_network_denial(__sys_builtins.getattr(exc, "reason", exc))
        except __sys_builtins.Exception:
            denied = False
        if denied:
            return __sys_network_block_message()
    return __sys_error_message(exc)


# Lets tracebacks and inspect.getsource show the user's lines for "<code>".
__sys_linecache.cache[__sys_code_filename] = (
    len(__sys_user_code),
    None,
    __sys_user_code.splitlines(True),
    __sys_code_filename,
)

try:
    from dotdict import DotDict, DotObject, DotList
    from epicstaff_secrets import get_secret
    __sys_dot_dict = DotDict
    for __sys_name, __sys_value in __sys_global_kwargs.items():
        globals()[__sys_name] = __sys_value

    exec(compile(__sys_user_code, __sys_code_filename, "exec"), globals())

    __sys_entrypoint_function = __sys_builtins.globals().get(__sys_entrypoint)
    if not __sys_builtins.callable(__sys_entrypoint_function):
        __sys_fail(__sys_missing_entrypoint_message)

    __sys_result_value = __sys_entrypoint_function(**__sys_dot_dict(__sys_func_kwargs))
except __sys_builtins.SystemExit:
    raise
# BaseException, not Exception: asyncio.CancelledError or KeyboardInterrupt from the
# user's code would otherwise print this wrapper's traceback.
except __sys_builtins.BaseException as __sys_error:
    __sys_fail(__sys_failure_message(__sys_error))

try:
    __sys_result_json = __sys_json_dumps(__sys_result_value)
except __sys_builtins.Exception as __sys_error:
    try:
        __sys_reason = f": {__sys_error}"
    except __sys_builtins.Exception:
        __sys_reason = ""
    __sys_fail(
        f"The function's return value can't be saved{__sys_reason}. "
        "Return text, numbers, lists or dictionaries."
    )

try:
    with __sys_builtins.open(__sys_result_file_path, "w", encoding="utf-8") as __sys_result_file:
        __sys_result_file.write(__sys_result_json)
except __sys_builtins.Exception as __sys_error:
    # Starts on its own line, so output the user's code left unfinished stays theirs.
    __sys_fail("\n" + __sys_error_message(__sys_error), __sys_result_write_failed_exit_code)
"""

_STORAGE_MUTATIONS_TAIL = r"""
try:
    from epicstaff_storage.storage import get_mutations as __es_get_muts
    __es_muts = __es_get_muts()
    if __es_muts:
        with __sys_builtins.open(__sys_storage_mutations_path, "w") as __es_mf:
            __sys_json_dump(__es_muts, __es_mf)
except __sys_builtins.Exception:
    pass
"""


def wrap_code(
    *,
    code: str,
    result_file_path: Path,
    entrypoint: str,
    func_kwargs: dict[str, Any],
    global_kwargs: dict[str, Any] | None = None,
    storage_mutations_path: Path | None = None,
) -> str:
    """Return the source the sandbox runs for one execution.

    Every value is embedded with ``repr``, a valid Python literal for any string and for
    the JSON-shaped kwargs, so nothing the user controls is ever parsed as wrapper code.
    On failure the source writes one line to stderr and exits 1: the user's error with
    their own line number, a missing entrypoint, a return value that isn't JSON, or a
    network denial. No traceback reaches the user, whatever names the user's code
    rebinds. A result file it can't write exits ``RESULT_WRITE_FAILED_EXIT_CODE``
    instead, with the error as the last stderr line.
    """
    global_kwargs = global_kwargs or {}
    values = (
        '__sys_code_filename = "<code>"\n'
        f"__sys_user_code = {code!r}\n"
        f"__sys_entrypoint = {entrypoint!r}\n"
        f"__sys_missing_entrypoint_message = "
        f"{_MISSING_ENTRYPOINT_MESSAGE.format(entrypoint=entrypoint)!r}\n"
        f"__sys_global_kwargs = {global_kwargs!r}\n"
        f"__sys_func_kwargs = {func_kwargs!r}\n"
        f"__sys_result_file_path = {result_file_path.as_posix()!r}\n"
        f"__sys_result_write_failed_exit_code = {RESULT_WRITE_FAILED_EXIT_CODE!r}\n"
    )
    wrapped_code = _PREAMBLE + values + _RUNNER

    if storage_mutations_path:
        wrapped_code += (
            f"\n__sys_storage_mutations_path = {storage_mutations_path.as_posix()!r}\n"
            + _STORAGE_MUTATIONS_TAIL
        )

    wrapped_code += "__sys_exit(0)\n"

    return wrapped_code
