"""The errors a Decision Table or Classification Decision Table node shows the user.

Both nodes run the user's code in the sandbox: condition expressions, manipulation code,
and the classification table's pre- and post-computation. Crew wraps conditions and
manipulations in code it generates, so a failure is reported against the part of the node
the user wrote, with the user's own line numbers rather than the generated code's. A
sandbox that couldn't run the code, or a result crew can't read, is logged and cited by a
reference.
"""

from dataclasses import dataclass
from typing import Any

from foundation.utils.error_reference import log_with_reference
from loguru import logger
from services.agent_run_errors import llm_error_text
from services.graph.exceptions import PublicNodeError
from services.graph.nodes.code_result_errors import (
    failure_text_without_failure,
    server_failure_reference,
)
from src.shared.llm_error_kind import classify_llm_error
from src.shared.models import (
    SERVER_FAILURE_CODES,
    CodeFailure,
    CodeFailureCode,
    CodeResultData,
    LLMData,
    describe_user_code_error,
)
from src.shared.models.agent_service import LLMErrorKind

PRE_COMPUTATION_SUBJECT = "Pre-computation code"
POST_COMPUTATION_SUBJECT = "Post-computation code"

_SERVER_ERROR_TEXT = (
    "{subject}: the code couldn't run because of a server error. "
    "Try again or contact your administrator (reference: {reference})."
)
_UNSAFE_TO_RUN_TEXT = (
    "{subject}: this server can't run code safely right now, so the code wasn't run. "
    "Contact your administrator (reference: {reference})."
)
_RESULT_TIMEOUT_TEXT = (
    "{subject}: the code's result didn't arrive in time. Try again or contact your administrator."
)

# Where the agent's text tells the user to change the task or the agent, a prompt's says
# what to change about the prompt. Every other kind keeps the agent's text after the
# prompt's name.
_PROMPT_LLM_ERROR_TEXTS: dict[LLMErrorKind, str] = {
    LLMErrorKind.RATE_LIMIT: (
        '{subject}: The provider\'s rate limit for model "{model}" was reached. '
        "Wait a minute and run the flow again."
    ),
    LLMErrorKind.CONTEXT_TOO_LONG: (
        '{subject} is too long for model "{model}". '
        "Shorten the prompt or its inputs, or choose a model with a bigger context window."
    ),
    LLMErrorKind.CONTENT_REFUSED: (
        '{subject}: The provider of model "{model}" refused the request because of its '
        "content policy. Change the prompt or its inputs."
    ),
}

# Runs in the sandbox inside the generated condition code: turns an exception raised by a
# condition expression into the failure crew reads with `ConditionFailure.from_result`.
# Like the sandbox's own messages, the message has no exception type for an ordinary
# error, and no line number, since an expression is one line inside the generated code.
CONDITION_FAILURE_SOURCE = """
_NOT_BOOLEAN_FAILURE = {"message": None, "not_boolean": True, "exited": False}


def _describe_condition_error(error):
    name = type(error).__name__
    try:
        if isinstance(error, SyntaxError):
            detail = error.msg
        elif isinstance(error, KeyError) and len(error.args) == 1:
            detail = f"key {error.args[0]!r} doesn't exist"
        else:
            detail = str(error)
    except Exception:
        return name
    # KeyboardInterrupt and the like say nothing without their type.
    if not detail or not isinstance(error, Exception):
        return f"{name}: {detail}" if detail else name
    return detail


def _condition_failure(error):
    if isinstance(error, SystemExit):
        return {"message": None, "not_boolean": False, "exited": True}
    return {"message": _describe_condition_error(error), "not_boolean": False, "exited": False}
"""


class DecisionTableError(PublicNodeError):
    """A Decision Table or Classification Decision Table node failed; the message is for the user."""


@dataclass(frozen=True)
class ConditionFailure:
    """Why a condition expression gave no result, as the generated condition code reports it.

    The code reports ``{"message": <text>, "not_boolean": false, "exited": false}`` for an
    expression that raised, ``{"message": null, "not_boolean": false, "exited": true}`` for
    one that called exit(), and ``{"message": null, "not_boolean": true, "exited": false}``
    for one whose value isn't a bool.
    """

    message: str | None
    not_boolean: bool
    exited: bool

    @classmethod
    def from_result(cls, error: Any) -> "ConditionFailure | None":
        """Read the ``error`` of a condition result; None when the condition gave a result.

        Raises:
            TypeError: ``error`` isn't in the shape the generated code reports.
        """
        if error is None:
            return None
        if not isinstance(error, dict):
            raise TypeError("condition error is not an object")
        message = error.get("message")
        not_boolean = error.get("not_boolean")
        exited = error.get("exited")
        if not isinstance(not_boolean, bool) or not isinstance(exited, bool):
            raise TypeError("condition error has no kind")
        if not not_boolean and not exited and not isinstance(message, str):
            raise TypeError("condition error has no message")
        return cls(message=message, not_boolean=not_boolean, exited=exited)


@dataclass(frozen=True)
class UserCodePart:
    """Where a piece of the user's code sits in the source crew generates around it.

    Args:
        label: Names the piece after the condition, e.g. "manipulation code".
        first_line: The source line the piece starts on, counting from 1.
        line_count: How many source lines the piece takes.
        shows_line_numbers: Whether a failure in it cites a line. A piece the user wrote
            as a single expression doesn't.
    """

    label: str
    first_line: int
    line_count: int
    shows_line_numbers: bool


def condition_subject(condition_name: str) -> str:
    """Return how a message names the condition (a row of the table) it is about."""
    return f'Condition "{condition_name}"'


def conditions_subject(first_condition_name: str, last_condition_name: str) -> str:
    """Return how a message names a run of conditions evaluated together."""
    return f'Conditions "{first_condition_name}" to "{last_condition_name}"'


def condition_error(condition_name: str, failure: ConditionFailure) -> DecisionTableError:
    """Return the error for a condition expression that raised or isn't true or false."""
    if failure.exited:
        return DecisionTableError(
            f"{condition_subject(condition_name)} stopped the code with exit()."
        )
    if failure.not_boolean:
        return DecisionTableError(f"{condition_subject(condition_name)} must give true or false.")
    return DecisionTableError(f"{condition_subject(condition_name)}: {failure.message}")


def check_code_ran(
    result: CodeResultData, subject: str, *, session_id: int, node_name: str
) -> None:
    """Raise if the sandbox couldn't run the code, or its result didn't reach crew in time.

    Both are failures of the server, not of the user's code. The sandbox's own failure was
    logged under the result's reference, which the message cites when it is well-formed
    (see `server_failure_reference`). A failed result that doesn't say why comes from an
    older sandbox, and fails with the end of its stderr (see
    `failure_text_without_failure`). Once this returns, the code ran, and `result.failure`
    is set exactly when it failed.

    Args:
        result: What `RunPythonCodeService.run_code` returned.
        subject: Names the code in the message, e.g. 'Condition "High score"'.
        session_id: Logged with a server failure's reference.
        node_name: Logged with it too, so the reference leads to the node.

    Raises:
        DecisionTableError: The code didn't run, or its result didn't arrive, or an older
            sandbox reported a failed result without a failure.
    """
    failure = result.failure
    if failure is None:
        if result.returncode == 0:
            return
        raise DecisionTableError(f"{subject}: {failure_text_without_failure(result)}")
    if failure.code in SERVER_FAILURE_CODES:
        reference = server_failure_reference(
            result, subject=f"{subject} of node {node_name}", session_id=session_id
        )
        text = (
            _UNSAFE_TO_RUN_TEXT
            if failure.code is CodeFailureCode.UNSAFE_TO_RUN
            else _SERVER_ERROR_TEXT
        )
        raise DecisionTableError(
            text.format(subject=subject, reference=reference), reference=reference
        )
    if failure.code is CodeFailureCode.RESULT_TIMEOUT:
        raise DecisionTableError(_RESULT_TIMEOUT_TEXT.format(subject=subject))


def unreadable_result_error(subject: str, result_data: Any) -> DecisionTableError:
    """Log a result crew can't read under a new reference, and return the error citing it.

    The raw result can hold the flow's variables, so it goes only to the log.
    """
    reference = log_with_reference(
        "{subject}: unreadable code result {result_data!r}",
        subject=subject,
        result_data=result_data,
    )
    return DecisionTableError(
        _SERVER_ERROR_TEXT.format(subject=subject, reference=reference),
        reference=reference,
    )


def user_code_error(subject: str, failure: CodeFailure) -> DecisionTableError:
    """Return the error for code the user wrote whole, whose line numbers are already theirs."""
    return DecisionTableError(f"{subject}: {failure.detail}")


def manipulation_error(
    condition_name: str, failure: CodeFailure, parts: list[UserCodePart]
) -> DecisionTableError:
    """Return the error for a condition's manipulation code that failed in the sandbox.

    The line of an error in the code, which counts lines of the source crew generated, is
    turned into a line of the part of the code it falls in. An error on a line of the
    generated code is shown without a line number, and any other failure by its detail.
    """
    subject = condition_subject(condition_name)
    user_error = failure.user_error
    if user_error is None:
        return DecisionTableError(f"{subject}, manipulation code: {failure.detail}")

    if user_error.line is not None:
        for part in parts:
            line = user_error.line - part.first_line + 1
            if 1 <= line <= part.line_count:
                if part.shows_line_numbers:
                    message = describe_user_code_error(
                        user_error.exception_type, line, user_error.message
                    )
                else:
                    message = user_error.message or user_error.exception_type
                return DecisionTableError(f"{subject}, {part.label}: {message}")
    message = describe_user_code_error(user_error.exception_type, None, user_error.message)
    return DecisionTableError(f"{subject}, manipulation code: {message}")


def prompt_llm_error(prompt_id: str, llm: LLMData, error: Exception) -> DecisionTableError:
    """Log a prompt's failed LLM call and return the error that tells the user why.

    The provider's text can quote part of the API key or the provider's response, so the
    log gets only the error's class and the text's length; an exception that isn't an LLM
    failure at all is crew's own, and is logged in full.
    """
    subject = f'Prompt "{prompt_id}"'
    kind = classify_llm_error(error)
    if kind is not None and kind is not LLMErrorKind.UNKNOWN:
        logger.warning("{subject}: LLM call failed: {kind}", subject=subject, kind=kind.value)
        prompt_text = _PROMPT_LLM_ERROR_TEXTS.get(kind)
        if prompt_text is not None:
            return DecisionTableError(prompt_text.format(subject=subject, model=llm.config.model))
        return DecisionTableError(f"{subject}: {llm_error_text(kind, llm)}")

    if kind is None:
        reference = log_with_reference(
            "{subject}: LLM call failed", subject=subject, exception=error
        )
    else:
        reference = log_with_reference(
            "{subject}: LLM call failed: {error_class}: <redacted len={length}>",
            subject=subject,
            error_class=type(error).__name__,
            length=len(str(error)),
        )
    return DecisionTableError(
        f"{subject}: {llm_error_text(LLMErrorKind.UNKNOWN, llm, reference)}",
        reference=reference,
    )
