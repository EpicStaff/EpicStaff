"""What a user sees when the sandbox itself fails, rather than their code.

The detail of such a failure can name server settings and paths, or quote an exception
whose text carries the job's code or secrets. It goes to the log under a fresh
reference; the user sees a fixed text that cites the reference, so an administrator can
find the log line without the user ever seeing its content.
"""

from enum import StrEnum

from foundation.utils.error_reference import log_with_reference

__all__ = ["SandboxFailureMessage", "log_sandbox_failure", "public_failure_text"]


class SandboxFailureMessage(StrEnum):
    """Texts shown in place of a sandbox failure; each takes a ``reference``."""

    SERVER_ERROR = (
        "The code couldn't run because of a server error. Try again or contact your "
        "administrator (reference: {reference})."
    )
    UNSAFE_TO_RUN = (
        "This server can't run code safely right now, so the code wasn't run. Contact "
        "your administrator (reference: {reference})."
    )


def public_failure_text(message: SandboxFailureMessage, reference: str) -> str:
    """Return ``message`` citing ``reference``, the text the user sees."""
    return message.format(reference=reference)


def log_sandbox_failure(detail: str, *, execution_id: str | None) -> str:
    """Log ``detail`` at ERROR under a fresh reference and return the reference.

    Args:
        detail: Logged as it is. Mask the job's secrets in it first; where the secrets
            aren't at hand, pass only an exception's type name when its text may quote
            them.
        execution_id: Names the execution in the log line; None when it is unknown.
    """
    return log_with_reference(
        "Execution {execution_id} failed in the sandbox: {detail}",
        execution_id=execution_id,
        detail=detail,
    )
