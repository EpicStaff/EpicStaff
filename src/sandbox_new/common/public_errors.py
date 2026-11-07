"""What a user sees when the sandbox itself fails, rather than their code.

The detail of such a failure can name server settings and paths, or quote an exception
whose text carries the job's code or secrets. It goes to the log under a fresh
reference; the user sees a fixed text that cites the reference, so an administrator can
find the log line without the user ever seeing its content.
"""

from typing import Literal

from foundation.utils.error_reference import log_with_reference
from src.shared.models.code_failure import CodeFailure, CodeFailureCode

__all__ = ["log_sandbox_failure", "sandbox_failure"]

_SERVER_ERROR_TEXT = (
    "The code couldn't run because of a server error. Try again or contact your "
    "administrator (reference: {reference})."
)
# The texts shown in place of a sandbox failure, by the code reported for it.
_PUBLIC_TEXTS = {
    CodeFailureCode.SANDBOX_ERROR: _SERVER_ERROR_TEXT,
    CodeFailureCode.DISPATCH_FAILED: _SERVER_ERROR_TEXT,
    CodeFailureCode.UNSAFE_TO_RUN: (
        "This server can't run code safely right now, so the code wasn't run. Contact "
        "your administrator (reference: {reference})."
    ),
}


def sandbox_failure(code: CodeFailureCode, reference: str) -> CodeFailure:
    """Return the failure the user sees for a sandbox failure logged under ``reference``.

    Args:
        code: ``sandbox_error``, ``dispatch_failed`` or ``unsafe_to_run``, the codes of a
            failure only a server log line explains.
    """
    return CodeFailure(code=code, detail=_PUBLIC_TEXTS[code].format(reference=reference))


def log_sandbox_failure(
    detail: str,
    *,
    execution_id: str | None,
    session_id: int | None,
    level: Literal["ERROR", "WARNING"] = "ERROR",
) -> str:
    """Log ``detail`` under a fresh reference and return the reference.

    Args:
        detail: Logged as it is. Mask the job's secrets in it first; where the secrets
            aren't at hand, pass only an exception's type name when its text may quote
            them.
        execution_id: Names the execution in the log line; None when it is unknown.
        session_id: The flow session the job ran for, so a reference the user quotes
            leads to the run; None for a job sent outside a session.
        level: ERROR by default; WARNING for a failure the user's code can cause on
            purpose, which mustn't raise an alert.
    """
    return log_with_reference(
        "Execution {execution_id} of session {session_id} failed in the sandbox: {detail}",
        execution_id=execution_id,
        session_id=session_id,
        detail=detail,
        level=level,
    )
