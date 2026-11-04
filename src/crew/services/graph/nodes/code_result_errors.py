"""The error a code node shows when its code ran and failed, or its result never arrived."""

import re
from typing import Any

from services.graph.exceptions import ReturnCodeError
from services.run_python_code_service import is_result_timeout

RESULT_TIMEOUT_TEXT = (
    "The code's result didn't arrive in time. Try again or contact your administrator."
)
_UNEXPECTED_ARGUMENT_TEXT = (
    'Input "{argument}" isn\'t a parameter of {entrypoint}(). '
    "Add it to {entrypoint}, or remove it from the input map."
)


def code_failure_error(result: dict[str, Any], entrypoint: str | None = None) -> ReturnCodeError:
    """Return the error for a `run_code` result with a non-zero return code.

    Code whose stderr is the user's own error is shown that stderr. A result crew gave up
    waiting for, and, when `entrypoint` is given, an input the entrypoint has no parameter
    for, are told in words instead.

    Args:
        result: What `RunPythonCodeService.run_code` returned; the sandbox didn't fail.
        entrypoint: The function the node's input map passes its inputs to. None for a
            node without an input map, whose inputs the user doesn't choose.
    """
    if is_result_timeout(result):
        return ReturnCodeError(RESULT_TIMEOUT_TEXT)
    stderr = result["stderr"]
    if entrypoint is not None:
        argument = _unexpected_argument(stderr, entrypoint)
        if argument is not None:
            return ReturnCodeError(
                _UNEXPECTED_ARGUMENT_TEXT.format(argument=argument, entrypoint=entrypoint)
            )
    return ReturnCodeError(stderr)


def _unexpected_argument(stderr: str, entrypoint: str) -> str | None:
    """Return the input the entrypoint was called with but has no parameter for, if that failed.

    The sandbox reports an error as "<Type> on line <N>: <detail>", its last stderr line,
    and leaves out "on line" only when no line of the user's code raised it. Python raises
    this TypeError while binding the call, before the entrypoint's first line runs, so a
    report without a line is the sandbox's own call, and one with a line is a call the
    user's code made.
    """
    lines = stderr.strip().splitlines()
    if not lines:
        return None
    match = re.fullmatch(
        rf"TypeError: {re.escape(entrypoint)}\(\) got an unexpected keyword argument "
        r"'(?P<argument>[^']+)'.*",
        lines[-1],
    )
    return match["argument"] if match else None
