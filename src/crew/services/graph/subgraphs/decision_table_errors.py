"""The errors a Decision Table or Classification Decision Table node shows the user.

Both nodes run the user's code in the sandbox: condition expressions, manipulation code,
and the classification table's pre- and post-computation. Crew wraps conditions and
manipulations in code it generates, so a failure is reported against the part of the node
the user wrote, with the user's own line numbers rather than the generated code's. A
sandbox that couldn't run the code, or a result crew can't read, is logged and cited by a
reference.
"""

import re
from dataclasses import dataclass
from typing import Any

from loguru import logger
from services.agent_run_errors import llm_error_text
from services.graph.exceptions import PublicNodeError
from services.run_python_code_service import CORRELATION_ID_KEY, is_result_timeout
from src.shared.llm_error_kind import classify_llm_error
from src.shared.models import LLMData
from src.shared.models.agent_service import LLMErrorKind
from src.shared.public_error import new_error_correlation_id

PRE_COMPUTATION_SUBJECT = "Pre-computation code"
POST_COMPUTATION_SUBJECT = "Post-computation code"

_SERVER_ERROR_TEXT = (
    "{subject}: the code couldn't run because of a server error. "
    "Try again or contact your administrator (reference: {reference})."
)
_RESULT_TIMEOUT_TEXT = (
    "{subject}: the code's result didn't arrive in time. Try again or contact your administrator."
)
_STRAY_BRACE_TEXT = (
    'Prompt "{prompt_id}" has a "{brace}" without a matching "{match}". '
    "To write a brace, double it: {{{{ or }}}}."
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

# str.format's messages for a brace that opens or closes no placeholder. Any other
# ValueError of str.format is not about a stray brace and is left to the caller.
_STRAY_OPENING_BRACE_MESSAGES = (
    "Single '{' encountered in format string",
    "expected '}' before end of string",
    "unmatched '{' in format spec",
)
_STRAY_CLOSING_BRACE_MESSAGES = ("Single '}' encountered in format string",)

# The sandbox reports a failure of the code as "<Type> on line <N>: <detail>", last in
# stderr, where N counts lines of the source crew sent: the generated wrapper's, not the
# user's. The detail is the exception's message, which can span lines, and whatever the
# user's code wrote to stderr comes before it.
_LOCATION_LINE = re.compile(r"\w+ on line \d+(?::|$)")
_LOCATED_FAILURE = re.compile(
    r"(?P<type>\w+) on line (?P<line>\d+)(?:: (?P<detail>.*))?", re.DOTALL
)

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


def check_code_ran(result: dict[str, Any], subject: str) -> None:
    """Raise if the sandbox couldn't run the code, or its result didn't reach crew in time.

    Both are failures of the server, not of the user's code. The sandbox's own failure was
    logged by `RunPythonCodeService` under the result's correlation id, which the message
    cites.

    Args:
        result: What `RunPythonCodeService.run_code` returned.
        subject: Names the code in the message, e.g. 'Condition "High score"'.

    Raises:
        DecisionTableError: The code didn't run, or its result didn't arrive.
    """
    correlation_id = result.get(CORRELATION_ID_KEY)
    if correlation_id is not None:
        raise DecisionTableError(
            _SERVER_ERROR_TEXT.format(subject=subject, reference=correlation_id),
            correlation_id=correlation_id,
        )
    if is_result_timeout(result):
        raise DecisionTableError(_RESULT_TIMEOUT_TEXT.format(subject=subject))


def unreadable_result_error(subject: str, result_data: Any) -> DecisionTableError:
    """Log a result crew can't read under a new reference, and return the error citing it.

    The raw result can hold the flow's variables, so it goes only to the log.
    """
    reference = new_error_correlation_id()
    logger.error(
        "{subject}: unreadable code result {result_data!r} (correlation_id={correlation_id})",
        subject=subject,
        result_data=result_data,
        correlation_id=reference,
    )
    return DecisionTableError(
        _SERVER_ERROR_TEXT.format(subject=subject, reference=reference),
        correlation_id=reference,
    )


def user_code_error(subject: str, stderr: str) -> DecisionTableError:
    """Return the error for code the user wrote whole, whose line numbers are already theirs."""
    return DecisionTableError(f"{subject}: {stderr.strip()}")


def manipulation_error(
    condition_name: str, stderr: str, parts: list[UserCodePart]
) -> DecisionTableError:
    """Return the error for a condition's manipulation code that failed in the sandbox.

    The line the sandbox names is turned into a line of the part of the code it falls in.
    A failure on a line of the generated code keeps the sandbox's text without the line
    number. Only the sandbox's message is shown, not what the code printed before it; a
    stderr without a located message is shown whole.
    """
    subject = condition_subject(condition_name)
    text = stderr.strip()
    located = _last_located_failure(text)
    if located is None:
        return DecisionTableError(f"{subject}, manipulation code: {text}")

    error_type = located["type"]
    detail = located["detail"]
    source_line = int(located["line"])
    for part in parts:
        line = source_line - part.first_line + 1
        if 1 <= line <= part.line_count:
            if part.shows_line_numbers:
                location = f"{error_type} on line {line}"
                message = f"{location}: {detail}" if detail else location
            else:
                message = detail or error_type
            return DecisionTableError(f"{subject}, {part.label}: {message}")
    message = f"{error_type}: {detail}" if detail else error_type
    return DecisionTableError(f"{subject}, manipulation code: {message}")


def _last_located_failure(stderr: str) -> re.Match[str] | None:
    # Searched from the end: a line the user printed earlier can look like a location too.
    lines = stderr.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if _LOCATION_LINE.match(lines[index]):
            return _LOCATED_FAILURE.fullmatch("\n".join(lines[index:]))
    return None


def stray_brace_error(prompt_id: str, format_error: ValueError) -> DecisionTableError | None:
    """Return the error for a prompt with a single brace, or None for another format error."""
    message = str(format_error)
    if message in _STRAY_OPENING_BRACE_MESSAGES:
        brace, match = "{", "}"
    elif message in _STRAY_CLOSING_BRACE_MESSAGES:
        brace, match = "}", "{"
    else:
        return None
    return DecisionTableError(
        _STRAY_BRACE_TEXT.format(prompt_id=prompt_id, brace=brace, match=match)
    )


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

    reference = new_error_correlation_id()
    if kind is None:
        logger.opt(exception=error).error(
            "{subject}: LLM call failed (correlation_id={correlation_id})",
            subject=subject,
            correlation_id=reference,
        )
    else:
        logger.error(
            "{subject}: LLM call failed: {error_class}: <redacted len={length}> "
            "(correlation_id={correlation_id})",
            subject=subject,
            error_class=type(error).__name__,
            length=len(str(error)),
            correlation_id=reference,
        )
    return DecisionTableError(
        f"{subject}: {llm_error_text(LLMErrorKind.UNKNOWN, llm, reference)}",
        correlation_id=reference,
    )
