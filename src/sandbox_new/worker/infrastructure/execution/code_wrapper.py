"""Wraps user code into the source actually run inside the sandbox subprocess.

Builds the preamble that injects globals and secrets, runs the user's code, calls the
entrypoint, writes its return value to the result file, and turns a failure into a
structured failure in the failure file plus one readable line on stderr. This is
mechanism, not policy: the real network/filesystem boundary is the kernel-enforced
seccomp/Landlock filter the launcher installs before this source runs. Pure -- it only
formats a string.

The user's code is embedded as a string literal and run with ``exec(compile(...))``
under the file name ``<code>``, never pasted into the wrapper's own source. So a
traceback's line numbers are the user's own, a syntax error is raised where the wrapper
can catch it, and a multi-line string in the code keeps its exact content.
"""

from pathlib import Path
from typing import Any

from src.shared.models.code_failure import USER_CODE_LOCATION_TEMPLATE, CodeFailureCode

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

# Bounds on the text the user's code controls (an exception's message, its class name,
# an argument name) in the failure file, only so the file fits the 128 KiB the capture
# step reads: the message and a name are each in the file twice, at up to 6 bytes a
# character (JSON writes a control character as a 6-character escape). They are no
# display limit, and stderr gets the line uncut. The worker shortens the texts it shows
# only after it masks the job's secrets: cut before that, a secret straddling the cut
# would leave a prefix the mask no longer matches.
_MAX_RAW_MESSAGE_LENGTH = 9_000
_MAX_RAW_NAME_LENGTH = 500

_PREAMBLE = r"""
import builtins as __sys_builtins
import errno as __sys_errno
import inspect as __sys_inspect
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


def __sys_exit_with_line(line, exit_code, *, __sys_stderr=__sys_stderr, __sys_exit=__sys_exit):
    __sys_stderr.write(line + "\n")
    __sys_stderr.flush()
    __sys_exit(exit_code)


# The worker reads the failure from the file; stderr gets the line for whoever reads
# only the streams: `line` when the file's texts were bounded, else the detail. The file
# is best effort: without it the worker still sees the exit code, and stderr still has
# the line.
def __sys_fail(
    failure,
    line=None,
    *,
    __sys_builtins=__sys_builtins,
    __sys_json_dumps=__sys_json_dumps,
    __sys_failure_file_path=__sys_failure_file_path,
    __sys_exit_with_line=__sys_exit_with_line,
):
    try:
        failure_json = __sys_json_dumps(failure, ensure_ascii=False)
        with __sys_builtins.open(__sys_failure_file_path, "w", encoding="utf-8") as file:
            file.write(failure_json)
    except __sys_builtins.Exception:
        pass
    __sys_exit_with_line(failure["detail"] if line is None else line, 1)


# A plain str: the text can come from the user's code, as a str subclass whose methods
# run their code.
def __sys_plain(text, *, __sys_builtins=__sys_builtins):
    return __sys_builtins.str.__str__(text)


# At most `limit` characters of a plain str, for the failure file.
def __sys_capped(text, limit, *, __sys_builtins=__sys_builtins):
    if __sys_builtins.len(text) <= limit:
        return text
    return text[:limit] + "..."


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


# The exception's type, the user's line and its message, uncut: the parts of the line a
# user sees for it.
def __sys_error_parts(
    exc,
    *,
    __sys_builtins=__sys_builtins,
    __sys_code_filename=__sys_code_filename,
    __sys_user_line=__sys_user_line,
    __sys_error_detail=__sys_error_detail,
    __sys_plain=__sys_plain,
):
    is_own_syntax_error = (
        __sys_builtins.isinstance(exc, __sys_builtins.SyntaxError)
        and exc.filename == __sys_code_filename
        and __sys_builtins.isinstance(exc.lineno, __sys_builtins.int)
    )
    line = exc.lineno if is_own_syntax_error else __sys_user_line(exc)
    exception_type = __sys_plain(__sys_builtins.type(exc).__name__)
    # The type and line stand on their own: the message runs the exception's own code
    # (its __str__, a key's __repr__), which can raise too.
    try:
        message = __sys_plain(exc.msg if is_own_syntax_error else __sys_error_detail(exc))
    except __sys_builtins.Exception:
        message = ""
    return exception_type, line, message


def __sys_describe_error(
    exception_type,
    line,
    message,
    *,
    __sys_user_code_location_template=__sys_user_code_location_template,
):
    location = (
        exception_type
        if line is None
        else __sys_user_code_location_template.format(exception_type=exception_type, line=line)
    )
    return f"{location}: {message}" if message else location


def __sys_error_message(
    exc, *, __sys_error_parts=__sys_error_parts, __sys_describe_error=__sys_describe_error
):
    return __sys_describe_error(*__sys_error_parts(exc))


# A call that can't bind its arguments raises TypeError before the entrypoint's first
# line runs, so its traceback has no frame in "<code>". The signature then names the
# argument at fault, the way Python checks them: an argument it doesn't take first, then
# one it requires and didn't get. None when the signature can't be read or names neither.
def __sys_argument_at_fault(
    function,
    arguments,
    *,
    __sys_builtins=__sys_builtins,
    __sys_inspect=__sys_inspect,
    __sys_unexpected_argument_code=__sys_unexpected_argument_code,
    __sys_missing_argument_code=__sys_missing_argument_code,
):
    # All of it, not only the signature call: the user's code can rebind what inspect
    # hands back (inspect.Parameter = None), and a raise here would print this wrapper's
    # traceback.
    try:
        parameters = __sys_inspect.signature(function).parameters
        kinds = __sys_inspect.Parameter
        takes_any_keyword = __sys_builtins.any(
            parameter.kind is kinds.VAR_KEYWORD for parameter in parameters.values()
        )
        if not takes_any_keyword:
            for name in arguments:
                parameter = parameters.get(name)
                if parameter is None or parameter.kind in (
                    kinds.POSITIONAL_ONLY,
                    kinds.VAR_POSITIONAL,
                ):
                    return __sys_unexpected_argument_code, name
        for name, parameter in parameters.items():
            if parameter.default is not parameter.empty:
                continue
            # Arguments are passed by name only, so a positional-only one is never given.
            if parameter.kind is kinds.POSITIONAL_ONLY or (
                parameter.kind in (kinds.POSITIONAL_OR_KEYWORD, kinds.KEYWORD_ONLY)
                and name not in arguments
            ):
                return __sys_missing_argument_code, name
    except __sys_builtins.Exception:
        return None
    return None


# The failure for an exception the user's code, or the call into it, raised, with its
# texts bounded for the file, and the uncut line for stderr. `entrypoint_function` is
# None until the entrypoint has been found.
def __sys_failure(
    exc,
    entrypoint_function,
    *,
    __sys_builtins=__sys_builtins,
    __sys_network_block_mode=__sys_network_block_mode,
    __sys_is_network_denial=__sys_is_network_denial,
    __sys_network_block_message=__sys_network_block_message,
    __sys_error_parts=__sys_error_parts,
    __sys_describe_error=__sys_describe_error,
    __sys_argument_at_fault=__sys_argument_at_fault,
    __sys_capped=__sys_capped,
    __sys_plain=__sys_plain,
    __sys_func_kwargs=__sys_func_kwargs,
    __sys_max_raw_message_length=__sys_max_raw_message_length,
    __sys_max_raw_name_length=__sys_max_raw_name_length,
    __sys_network_denied_code=__sys_network_denied_code,
    __sys_user_code_error_code=__sys_user_code_error_code,
):
    if __sys_network_block_mode and __sys_builtins.isinstance(exc, __sys_builtins.OSError):
        try:
            denied = __sys_is_network_denial(__sys_builtins.getattr(exc, "reason", exc))
        except __sys_builtins.Exception:
            denied = False
        if denied:
            message = __sys_network_block_message()
            return {"code": __sys_network_denied_code, "detail": message}, message

    exception_type, line, message = __sys_error_parts(exc)
    stderr_line = __sys_describe_error(exception_type, line, message)
    exception_type = __sys_capped(exception_type, __sys_max_raw_name_length)
    message = __sys_capped(message, __sys_max_raw_message_length)
    detail = __sys_describe_error(exception_type, line, message)
    if (
        entrypoint_function is not None
        and __sys_builtins.isinstance(exc, __sys_builtins.TypeError)
        and line is None
    ):
        fault = __sys_argument_at_fault(entrypoint_function, __sys_func_kwargs)
        if fault is not None:
            code, name = fault
            failure = {
                "code": code,
                "detail": detail,
                "attr": __sys_capped(__sys_plain(name), __sys_max_raw_name_length),
            }
            return failure, stderr_line
    failure = {
        "code": __sys_user_code_error_code,
        "detail": detail,
        "user_error": {"exception_type": exception_type, "line": line, "message": message},
    }
    return failure, stderr_line


def __sys_run(
    *,
    __sys_globals=globals(),
    __sys_builtins=__sys_builtins,
    __sys_linecache=__sys_linecache,
    __sys_json_dumps=__sys_json_dumps,
    __sys_json_dump=__sys_json_dump,
    __sys_exit=__sys_exit,
    __sys_fail=__sys_fail,
    __sys_exit_with_line=__sys_exit_with_line,
    __sys_capped=__sys_capped,
    __sys_plain=__sys_plain,
    __sys_error_message=__sys_error_message,
    __sys_failure=__sys_failure,
    __sys_code_filename=__sys_code_filename,
    __sys_user_code=__sys_user_code,
    __sys_entrypoint=__sys_entrypoint,
    __sys_global_kwargs=__sys_global_kwargs,
    __sys_func_kwargs=__sys_func_kwargs,
    __sys_result_file_path=__sys_result_file_path,
    __sys_storage_mutations_path=__sys_storage_mutations_path,
    __sys_result_write_failed_exit_code=__sys_result_write_failed_exit_code,
    __sys_write_marker=__sys_write_marker,
    __sys_max_raw_message_length=__sys_max_raw_message_length,
    __sys_missing_entrypoint_message=__sys_missing_entrypoint_message,
    __sys_unsavable_result_message=__sys_unsavable_result_message,
    __sys_missing_entrypoint_code=__sys_missing_entrypoint_code,
    __sys_bad_return_value_code=__sys_bad_return_value_code,
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

    __sys_entrypoint_function = None
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
            __sys_fail(
                {
                    "code": __sys_missing_entrypoint_code,
                    "detail": __sys_missing_entrypoint_message.format(
                        entrypoint=__sys_entrypoint
                    ),
                }
            )

        __sys_result_value = __sys_entrypoint_function(**__sys_dot_dict(__sys_func_kwargs))
    except __sys_builtins.SystemExit as __sys_exit_request:
        # sys.exit(3) is the code's own exit status; sys.exit("Missing API key") is an
        # error it meant the user to read. The wrapper's own exits carry an int too.
        __sys_exit_status = __sys_exit_request.code
        if __sys_exit_status is None or __sys_builtins.isinstance(
            __sys_exit_status, __sys_builtins.int
        ):
            raise
        __sys_fail(*__sys_failure(__sys_exit_request, __sys_entrypoint_function))
    # BaseException, not Exception: asyncio.CancelledError or KeyboardInterrupt from the
    # user's code would otherwise print this wrapper's traceback.
    except __sys_builtins.BaseException as __sys_error:
        __sys_fail(*__sys_failure(__sys_error, __sys_entrypoint_function))

    try:
        __sys_result_json = __sys_json_dumps(__sys_result_value)
    except __sys_builtins.Exception as __sys_error:
        try:
            __sys_reason = ": " + __sys_plain(__sys_builtins.str(__sys_error))
        except __sys_builtins.Exception:
            __sys_reason = ""
        __sys_fail(
            {
                "code": __sys_bad_return_value_code,
                "detail": __sys_unsavable_result_message.format(
                    reason=__sys_capped(__sys_reason, __sys_max_raw_message_length)
                ),
            },
            __sys_unsavable_result_message.format(reason=__sys_reason),
        )

    try:
        with __sys_builtins.open(
            __sys_result_file_path, "w", encoding="utf-8"
        ) as __sys_result_file:
            __sys_result_file.write(__sys_result_json)
    except __sys_builtins.Exception as __sys_error:
        # Starts on its own line, so output the user's code left unfinished stays theirs.
        # The marker, never in the user's globals, is how the capture step tells this
        # exit from the user's code exiting with the same code. It is the server's
        # failure, not the user's, so it writes no failure file.
        __sys_exit_with_line(
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
    failure_file_path: Path,
    entrypoint: str,
    func_kwargs: dict[str, Any],
    result_write_marker: str,
    global_kwargs: dict[str, Any] | None = None,
    storage_mutations_path: Path | None = None,
) -> str:
    """Return the source the sandbox runs for one execution.

    Every value is embedded with ``repr``, a valid Python literal for any string and for
    the JSON-shaped kwargs, so nothing the user controls is ever parsed as wrapper code.
    On failure the source writes a ``CodeFailure`` as JSON to ``failure_file_path``,
    then its detail as one line to stderr, and exits 1. The failure is one the wrapper
    can report (``WRAPPER_FAILURE_CODES``): the user's error with their own line number,
    an argument the entrypoint doesn't take or misses, a missing entrypoint, a return
    value that isn't JSON, or a network denial. The wrapper binds every name it uses
    after the user's code before that code runs, and deletes its own ``__sys_*`` names
    from the globals the code shares, so rebinding a name (``type``, ``str``,
    ``__sys_exit``) can't make a traceback reach the user.

    A result file it can't write exits ``RESULT_WRITE_FAILED_EXIT_CODE`` instead, with
    ``result_write_marker`` followed by the error at the end of stderr, and no failure
    file. The marker is not in the user's globals, so code that exits with the same code
    doesn't carry it by accident. It is not a secret from code that deliberately
    looks for it: the user's code runs in the same process and can read the frames and
    the source file.

    Args:
        failure_file_path: Where the failure goes; the user's code can write there too,
            so the capture step trusts only the codes the wrapper can report.
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
        "__sys_failure_file_path": failure_file_path.as_posix(),
        "__sys_storage_mutations_path": (
            storage_mutations_path.as_posix() if storage_mutations_path is not None else None
        ),
        "__sys_result_write_failed_exit_code": RESULT_WRITE_FAILED_EXIT_CODE,
        "__sys_write_marker": result_write_marker,
        "__sys_max_raw_message_length": _MAX_RAW_MESSAGE_LENGTH,
        "__sys_max_raw_name_length": _MAX_RAW_NAME_LENGTH,
        # The texts the user sees.
        "__sys_missing_entrypoint_message": _MISSING_ENTRYPOINT_MESSAGE,
        "__sys_missing_key_message": _MISSING_KEY_MESSAGE,
        "__sys_unsavable_result_message": _UNSAVABLE_RESULT_MESSAGE,
        "__sys_network_blocked_message": _NETWORK_BLOCKED_MESSAGE,
        "__sys_network_storage_only_message": _NETWORK_STORAGE_ONLY_MESSAGE,
        "__sys_user_code_location_template": USER_CODE_LOCATION_TEMPLATE,
        # The codes of the failures it reports, plain strings in the failure file.
        "__sys_user_code_error_code": CodeFailureCode.USER_CODE_ERROR.value,
        "__sys_missing_entrypoint_code": CodeFailureCode.MISSING_ENTRYPOINT.value,
        "__sys_unexpected_argument_code": CodeFailureCode.UNEXPECTED_ARGUMENT.value,
        "__sys_missing_argument_code": CodeFailureCode.MISSING_ARGUMENT.value,
        "__sys_bad_return_value_code": CodeFailureCode.BAD_RETURN_VALUE.value,
        "__sys_network_denied_code": CodeFailureCode.NETWORK_DENIED.value,
    }
    assignments = "".join(f"{name} = {value!r}\n" for name, value in values.items())
    return _PREAMBLE + assignments + _RUNNER
