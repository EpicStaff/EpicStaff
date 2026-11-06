"""The error a code node shows when its code ran and failed, or couldn't run at all."""

from foundation.utils.error_reference import log_with_reference
from services.graph.exceptions import (
    CodeExecutionUnavailableError,
    PublicNodeError,
    ReturnCodeError,
)
from src.shared.models import CodeFailureCode, CodeResultData

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
# The failures a server log line explains, under the result's reference; their detail
# names neither the node nor the code, so the node says which code couldn't run.
_SERVER_FAILURE_TEXTS = {
    CodeFailureCode.SANDBOX_ERROR: _COULDNT_RUN_TEXT,
    CodeFailureCode.DISPATCH_FAILED: _COULDNT_RUN_TEXT,
    CodeFailureCode.UNSAFE_TO_RUN: _UNSAFE_TO_RUN_TEXT,
}


def code_failure_error(
    result: CodeResultData,
    *,
    kind_name: str,
    node_label: str,
    entrypoint: str | None,
) -> PublicNodeError | None:
    """Return the error a code node fails with for this `run_code` result, or None if it ran.

    A failure only a server log explains names the node and cites the result's
    reference. An input the entrypoint has no parameter for is told in words, when the
    node has an input map. Every other failure shows its `detail`.

    Args:
        kind_name: Names the node's kind in the message, e.g. "Python".
        entrypoint: The function the node's input map passes its inputs to. None for a
            node without an input map, whose inputs the user doesn't choose.
    """
    failure = result.failure
    if failure is None:
        if result.returncode == 0:
            return None
        reference = log_missing_failure(result)
        return CodeExecutionUnavailableError(
            _COULDNT_RUN_TEXT.format(
                kind_name=kind_name, node_label=node_label, reference=reference
            ),
            reference=reference,
        )
    server_failure_text = _SERVER_FAILURE_TEXTS.get(failure.code)
    if server_failure_text is not None:
        return CodeExecutionUnavailableError(
            server_failure_text.format(
                kind_name=kind_name, node_label=node_label, reference=result.reference
            ),
            reference=result.reference,
        )
    if failure.code is CodeFailureCode.UNEXPECTED_ARGUMENT and entrypoint is not None:
        return ReturnCodeError(
            _UNEXPECTED_ARGUMENT_TEXT.format(argument=failure.attr, entrypoint=entrypoint)
        )
    return ReturnCodeError(failure.detail)


def log_missing_failure(result: CodeResultData) -> str:
    """Log a failed result that doesn't say why, and return the reference it is logged under.

    Every failed result from the sandbox or crew carries its failure, so one without it
    breaks their contract; only its return code is logged, since its output is the
    user's.
    """
    return log_with_reference(
        "Code execution {execution_id} failed with return code {returncode} but reported "
        "no failure",
        execution_id=result.execution_id,
        returncode=result.returncode,
    )
