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

# The wrapped source exits with this code when it can't write the result file, writing
# the run's write-failure marker and then the error to stderr. That failure is the
# server's, and the error names a server path, so the capture step logs it instead of
# showing it. The user's code can exit with this code too; only the marker tells the
# wrapper's exit apart.
RESULT_WRITE_FAILED_EXIT_CODE = 125

# The texts the user sees; the templates among them are filled in by the wrapped source.
_MISSING_ENTRYPOINT_MESSAGE = (
    'The code has no function named "{entrypoint}". Add one, or check its name.'
)
_MISSING_KEY_MESSAGE = "key {key!r} doesn't exist"
_UNSAVABLE_RESULT_MESSAGE = (
    "The function's return value can't be saved{reason}. "
    "Return text, numbers, lists or dictionaries."
)
_NETWORK_BLOCKED_MESSAGE = (
    "Network access denied: the sandbox network policy blocks all outbound network access."
)
_NETWORK_STORAGE_ONLY_MESSAGE = (
    "Network access denied: the sandbox network policy allows outbound "
    "network access only to the storage endpoint."
)

_PREAMBLE = r"""
import builtins as __sys_builtins
import errno as __sys_errno
import os as __sys_os
import socket as __sys_socket
import sys
import json
import linecache as __sys_linecache
import traceback as __sys_traceback

# User code has always been able to use these modules without importing them.
import errno
import os
import socket

__sys_json_dumps = json.dumps
__sys_json_dump = json.dump
__sys_stderr = sys.stderr
__sys_exit = sys.exit

__sys_network_block_mode = __sys_os.environ.get("SANDBOX_NETWORK_BLOCKED")
"""

# The user's code shares these globals and can rebind any name in them, builtins
# included (type = "pdf", str = 1), and the wrapper's own names too. So every function
# below takes what it uses as keyword-only defaults, bound when it is defined, and
# __sys_run deletes every __sys_* global before the user's code runs: nothing the
# wrapper does afterwards looks a name up in the globals.
_RUNNER = r"""

# Message-quality aid only, NOT a security control -- the real boundary is the
# kernel-enforced seccomp/Landlock filter launcher.py installs before this interpreter
# starts. SANDBOX_NETWORK_BLOCKED mirrors that real state ("all" / "storage_only"), set
# by the launch step.
def __sys_network_block_message(
    *,
    __sys_network_block_mode=__sys_network_block_mode,
    __sys_network_blocked_message=__sys_network_blocked_message,
    __sys_network_storage_only_message=__sys_network_storage_only_message,
):
    if __sys_network_block_mode == "storage_only":
        return __sys_network_storage_only_message
    return __sys_network_blocked_message


# Some in-sandbox tools catch socket.gaierror themselves and format it into
# their own returned string, e.g. f"could not resolve host {host}: {e}",
# so it never reaches __sys_is_network_denial() below. Monkeypatching
# getaddrinfo makes the exception itself carry the policy message, so every
# consumer that does str(e) gets it for free. Message-quality aid only, not a
# security control. Gated on "all" only: under storage_only, DNS genuinely
# still works over UDP, so a gaierror there is a real failure, not this.
if __sys_network_block_mode == "all":

    def __sys_getaddrinfo(
        *args,
        __sys_socket=__sys_socket,
        __sys_real_getaddrinfo=__sys_socket.getaddrinfo,
        __sys_network_block_message=__sys_network_block_message,
        **kwargs,
    ):
        try:
            return __sys_real_getaddrinfo(*args, **kwargs)
        except __sys_socket.gaierror as exc:
            raise __sys_socket.gaierror(exc.errno, __sys_network_block_message()) from None

    __sys_socket.getaddrinfo = __sys_getaddrinfo


def __sys_is_network_denial(
    exc,
    *,
    __sys_builtins=__sys_builtins,
    __sys_errno=__sys_errno,
    __sys_socket=__sys_socket,
    __sys_network_block_mode=__sys_network_block_mode,
):
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


def __sys_fail(message, exit_code=1, *, __sys_stderr=__sys_stderr, __sys_exit=__sys_exit):
    __sys_stderr.write(message + "\n")
    __sys_stderr.flush()
    __sys_exit(exit_code)


# Reads the user's own line from the traceback: the deepest frame in "<code>" is the
# line that raised, or the user's call into the library that did.
def __sys_user_line(
    exc, *, __sys_traceback=__sys_traceback, __sys_code_filename=__sys_code_filename
):
    line = None
    for frame, line_number in __sys_traceback.walk_tb(exc.__traceback__):
        if frame.f_code.co_filename == __sys_code_filename:
            line = line_number
    return line


def __sys_error_detail(
    exc, *, __sys_builtins=__sys_builtins, __sys_missing_key_message=__sys_missing_key_message
):
    if (
        __sys_builtins.isinstance(exc, __sys_builtins.KeyError)
        and __sys_builtins.len(exc.args) == 1
    ):
        return __sys_missing_key_message.format(key=exc.args[0])
    return __sys_builtins.str(exc)


def __sys_error_message(
    exc,
    *,
    __sys_builtins=__sys_builtins,
    __sys_code_filename=__sys_code_filename,
    __sys_user_line=__sys_user_line,
    __sys_error_detail=__sys_error_detail,
):
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


def __sys_failure_message(
    exc,
    *,
    __sys_builtins=__sys_builtins,
    __sys_network_block_mode=__sys_network_block_mode,
    __sys_is_network_denial=__sys_is_network_denial,
    __sys_network_block_message=__sys_network_block_message,
    __sys_error_message=__sys_error_message,
):
    if __sys_network_block_mode and __sys_builtins.isinstance(exc, __sys_builtins.OSError):
        try:
            denied = __sys_is_network_denial(__sys_builtins.getattr(exc, "reason", exc))
        except __sys_builtins.Exception:
            denied = False
        if denied:
            return __sys_network_block_message()
    return __sys_error_message(exc)


def __sys_run(
    *,
    __sys_globals=globals(),
    __sys_builtins=__sys_builtins,
    __sys_linecache=__sys_linecache,
    __sys_json_dumps=__sys_json_dumps,
    __sys_json_dump=__sys_json_dump,
    __sys_exit=__sys_exit,
    __sys_fail=__sys_fail,
    __sys_error_message=__sys_error_message,
    __sys_failure_message=__sys_failure_message,
    __sys_code_filename=__sys_code_filename,
    __sys_user_code=__sys_user_code,
    __sys_entrypoint=__sys_entrypoint,
    __sys_global_kwargs=__sys_global_kwargs,
    __sys_func_kwargs=__sys_func_kwargs,
    __sys_result_file_path=__sys_result_file_path,
    __sys_storage_mutations_path=__sys_storage_mutations_path,
    __sys_result_write_failed_exit_code=__sys_result_write_failed_exit_code,
    __sys_write_marker=__sys_write_marker,
    __sys_missing_entrypoint_message=__sys_missing_entrypoint_message,
    __sys_unsavable_result_message=__sys_unsavable_result_message,
):
    # The user's code reaches these by name, so they are imported into the globals.
    global DotDict, DotObject, DotList, get_secret

    for __sys_name in [name for name in __sys_globals if name.startswith("__sys_")]:
        del __sys_globals[__sys_name]

    # Lets tracebacks and inspect.getsource show the user's lines for "<code>".
    __sys_linecache.cache[__sys_code_filename] = (
        __sys_builtins.len(__sys_user_code),
        None,
        __sys_user_code.splitlines(True),
        __sys_code_filename,
    )

    try:
        from dotdict import DotDict, DotObject, DotList
        from epicstaff_secrets import get_secret
        __sys_dot_dict = DotDict
        for __sys_name, __sys_value in __sys_global_kwargs.items():
            __sys_globals[__sys_name] = __sys_value

        __sys_builtins.exec(
            __sys_builtins.compile(__sys_user_code, __sys_code_filename, "exec"), __sys_globals
        )

        __sys_entrypoint_function = __sys_globals.get(__sys_entrypoint)
        if not __sys_builtins.callable(__sys_entrypoint_function):
            __sys_fail(__sys_missing_entrypoint_message.format(entrypoint=__sys_entrypoint))

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
        __sys_fail(__sys_unsavable_result_message.format(reason=__sys_reason))

    try:
        with __sys_builtins.open(
            __sys_result_file_path, "w", encoding="utf-8"
        ) as __sys_result_file:
            __sys_result_file.write(__sys_result_json)
    except __sys_builtins.Exception as __sys_error:
        # Starts on its own line, so output the user's code left unfinished stays theirs.
        # The marker, never in the user's globals, is how the capture step tells this
        # exit from the user's code exiting with the same code.
        __sys_fail(
            "\n" + __sys_write_marker + __sys_error_message(__sys_error),
            __sys_result_write_failed_exit_code,
        )

    if __sys_storage_mutations_path is not None:
        try:
            from epicstaff_storage.storage import get_mutations as __sys_get_mutations
            __sys_mutations = __sys_get_mutations()
            if __sys_mutations:
                with __sys_builtins.open(
                    __sys_storage_mutations_path, "w"
                ) as __sys_mutations_file:
                    __sys_json_dump(__sys_mutations, __sys_mutations_file)
        except __sys_builtins.Exception:
            pass

    __sys_exit(0)


__sys_run()
"""


def wrap_code(
    *,
    code: str,
    result_file_path: Path,
    entrypoint: str,
    func_kwargs: dict[str, Any],
    result_write_marker: str,
    global_kwargs: dict[str, Any] | None = None,
    storage_mutations_path: Path | None = None,
) -> str:
    """Return the source the sandbox runs for one execution.

    Every value is embedded with ``repr``, a valid Python literal for any string and for
    the JSON-shaped kwargs, so nothing the user controls is ever parsed as wrapper code.
    On failure the source writes one line to stderr and exits 1: the user's error with
    their own line number, a missing entrypoint, a return value that isn't JSON, or a
    network denial. The wrapper binds every name it uses after the user's code before
    that code runs, and deletes its own ``__sys_*`` names from the globals the code
    shares, so rebinding a name (``type``, ``str``, ``__sys_exit``) can't make a
    traceback reach the user.

    A result file it can't write exits ``RESULT_WRITE_FAILED_EXIT_CODE`` instead, with
    ``result_write_marker`` followed by the error at the end of stderr. The marker is not
    in the user's globals, so code that exits with the same code doesn't carry it by
    accident. It is not a secret from code that deliberately
    looks for it: the user's code runs in the same process and can read the frames and
    the source file.

    Args:
        result_write_marker: A fresh unguessable string per execution; the capture step
            splits stderr at it.
    """
    values = {
        "__sys_code_filename": "<code>",
        "__sys_user_code": code,
        "__sys_entrypoint": entrypoint,
        "__sys_global_kwargs": global_kwargs or {},
        "__sys_func_kwargs": func_kwargs,
        "__sys_result_file_path": result_file_path.as_posix(),
        "__sys_storage_mutations_path": (
            storage_mutations_path.as_posix() if storage_mutations_path is not None else None
        ),
        "__sys_result_write_failed_exit_code": RESULT_WRITE_FAILED_EXIT_CODE,
        "__sys_write_marker": result_write_marker,
        # The texts the user sees.
        "__sys_missing_entrypoint_message": _MISSING_ENTRYPOINT_MESSAGE,
        "__sys_missing_key_message": _MISSING_KEY_MESSAGE,
        "__sys_unsavable_result_message": _UNSAVABLE_RESULT_MESSAGE,
        "__sys_network_blocked_message": _NETWORK_BLOCKED_MESSAGE,
        "__sys_network_storage_only_message": _NETWORK_STORAGE_ONLY_MESSAGE,
    }
    assignments = "".join(f"{name} = {value!r}\n" for name, value in values.items())
    return _PREAMBLE + assignments + _RUNNER
