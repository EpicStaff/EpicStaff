"""Code results as the sandbox sends them to crew, for tests of the nodes that read them.

A failed result holds the contract every sandbox result holds: a non-zero return code, the
failure, and the failure's detail as the last line of stderr.
"""

import json
from typing import Any

from src.shared.models import (
    CodeFailure,
    CodeFailureCode,
    CodeResultData,
    UserCodeError,
    describe_user_code_error,
)


def succeeded(value: Any) -> CodeResultData:
    """Return the result of code whose entrypoint returned `value`."""
    return CodeResultData(
        execution_id="test", returncode=0, stdout="", stderr="", result_data=json.dumps(value)
    )


def failed(
    failure: CodeFailure, *, reference: str | None = None, printed: str = ""
) -> CodeResultData:
    """Return the result of a failed execution; `printed` is what the code wrote to stderr first."""
    return CodeResultData(
        execution_id="test",
        returncode=1,
        stdout="",
        stderr=f"{printed}{failure.detail}",
        result_data=None,
        failure=failure,
        reference=reference,
    )


def user_code_failure(exception_type: str, line: int | None, message: str) -> CodeFailure:
    """Return the failure the sandbox reports for an exception the user's code raised."""
    return CodeFailure(
        code=CodeFailureCode.USER_CODE_ERROR,
        detail=describe_user_code_error(exception_type, line, message),
        user_error=UserCodeError(exception_type=exception_type, line=line, message=message),
    )


def raised_on(
    code: str, line_text: str, exception_type: str, message: str, *, printed: str = ""
) -> CodeResultData:
    """Return the result the sandbox reports when the line of `code` holding `line_text` raised.

    The sandbox names the line of the code it was sent, so a node that wraps the user's
    code in its own is told a line of the whole code.
    """
    line = next(
        number for number, text in enumerate(code.splitlines(), start=1) if line_text in text
    )
    return failed(user_code_failure(exception_type, line, message), printed=printed)


class CannedRunCodeService:
    """Stands in for RunPythonCodeService, answering each run with the next canned result.

    The last result answers every run after it.
    """

    def __init__(self, *results: CodeResultData) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    async def run_code(self, python_code_data, inputs, **kwargs) -> CodeResultData:
        self.calls.append({"python_code_data": python_code_data, "inputs": inputs})
        if len(self._results) > 1:
            return self._results.pop(0)
        return self._results[0]
