"""The error a code node shows when its code ran and failed, or couldn't run at all."""

from foundation.utils.error_reference import log_with_reference, trusted_reference
from loguru import logger
from services.graph.exceptions import (
    CodeExecutionUnavailableError,
    PublicNodeError,
    ReturnCodeError,
)
from src.shared.models import SERVER_FAILURE_CODES, CodeFailureCode, CodeResultData

_COULDNT_RUN_TEXT = (
    '{kind_name} node "{node_label}" couldn\'t run its code. '
    "Try again or contact your administrator (reference: {reference})."
)
_UNSAFE_TO_RUN_TEXT = (
    "{kind_name} node \"{node_label}\" couldn't run its code: this server can't run code "
    "safely right now. Contact your administrator (reference: {reference})."
)
_UNEXPECTED_ARGUMENT_TEXT = (
    'Input "{argument}" isn\'t a parameter of {entrypoint}(). '
    "Add it to {entrypoint}, or remove it from the input map."
)
_FAILED_WITHOUT_OUTPUT_TEXT = "The code failed with exit code {returncode}."


def code_failure_error(
    result: CodeResultData,
    *,
    kind_name: str,
    node_label: str,
    entrypoint: str | None,
    session_id: int,
) -> PublicNodeError | None:
    """Return the error a code node fails with for this `run_code` result, or None if it ran.

    A failure only a server log explains names the node and cites the result's
    reference, or a new one when it isn't well-formed. An input the entrypoint has no
    parameter for is told in words, when the node has an input map. Every other failure,
    a code this version doesn't know included, shows its `detail`. A failed result
    without a failure comes from a sandbox older than the failure field, and shows the
    end of the user's stderr, as it did then.

    Args:
        kind_name: Names the node's kind in the message, e.g. "Python".
        entrypoint: The function the node's input map passes its inputs to. None for a
            node without an input map, whose inputs the user doesn't choose.
        session_id: Logged with a server failure's reference, so the reference the user
            quotes leads to the run.
    """
    failure = result.failure
    if failure is None:
        if result.returncode == 0:
            return None
        return ReturnCodeError(failure_text_without_failure(result))
    if failure.code in SERVER_FAILURE_CODES:
        subject = f'{kind_name} node "{node_label}"'
        reference = server_failure_reference(result, subject=subject, session_id=session_id)
        text = (
            _UNSAFE_TO_RUN_TEXT
            if failure.code is CodeFailureCode.UNSAFE_TO_RUN
            else _COULDNT_RUN_TEXT
        )
        return CodeExecutionUnavailableError(
            text.format(kind_name=kind_name, node_label=node_label, reference=reference),
            reference=reference,
        )
    if failure.code is CodeFailureCode.UNEXPECTED_ARGUMENT and entrypoint is not None:
        return ReturnCodeError(
            _UNEXPECTED_ARGUMENT_TEXT.format(argument=failure.attr, entrypoint=entrypoint)
        )
    return ReturnCodeError(failure.detail)


def server_failure_reference(result: CodeResultData, *, subject: str, session_id: int) -> str:
    """Return the reference a failure of the sandbox or of dispatch cites to the user.

    That is the result's own reference, under which its producer logged the failure at
    ERROR, when it is well-formed. Crew logs its own context under the same reference at
    WARNING, so the reference the user quotes leads from the sandbox's log line to the
    session and node, and one failure raises one alert. A missing or malformed reference
    is never shown: the failure is logged here instead, by its execution id, under a new
    reference.

    Args:
        subject: Names the code that couldn't run, e.g. 'Python node "Parse #1"'.
    """
    reference = trusted_reference(result.reference)
    if reference is not None:
        return log_with_reference(
            "{subject} of session {session_id}: execution {execution_id} failed on the "
            "server ({code})",
            subject=subject,
            session_id=session_id,
            execution_id=result.execution_id,
            code=result.failure.code.value,
            reference=reference,
            level="WARNING",
        )
    return log_with_reference(
        "{subject} of session {session_id}: execution {execution_id} failed on the server "
        "without a usable reference",
        subject=subject,
        session_id=session_id,
        execution_id=result.execution_id,
    )


def failure_text_without_failure(result: CodeResultData) -> str:
    """Return what a failed result without a failure shows: the last line of its stderr.

    Every failed result from this version of the sandbox carries its failure, so one
    without it comes from an older sandbox during a deploy, whose stderr ends with the
    failure line, as it did before the failure field. That line is usually the user's
    own error, masked by the sandbox, but an older sandbox also wrote its own failures
    there, and crew can't tell them apart without the failure: for that deploy window,
    such a failure shows the older sandbox's text, as it did then. Only the return code
    is logged, at WARNING.
    """
    logger.warning(
        "Code execution {execution_id} failed with return code {returncode} but reported "
        "no failure; showing its stderr",
        execution_id=result.execution_id,
        returncode=result.returncode,
    )
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    if lines:
        return lines[-1].strip()
    return _FAILED_WITHOUT_OUTPUT_TEXT.format(returncode=result.returncode)
