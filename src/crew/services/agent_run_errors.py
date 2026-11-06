"""Turn a failed agent-service run into the error an Agent or Task node shows the user.

The agent service reports why a run failed as a ``stop_reason`` and an ``error_kind``; its
``error`` field is the provider's raw text, which can quote part of an API key or the
provider's response, so it is never shown and never logged as it is: the log gets only
the error class and the text's length.
"""

import re

from foundation.utils.error_reference import log_with_reference
from loguru import logger
from services.graph.exceptions import PublicNodeError
from src.shared.models import AgentDefinitionData, LLMData
from src.shared.models.agent_service import FailedLLM, LLMErrorKind, StopReason
from src.shared.public_error import PublicErrorMessage, build_public_error_message


class AgentTaskError(PublicNodeError):
    """An Agent or Task node's run failed in the agent service; the message is for the user."""


class AgentTaskTimeoutError(AgentTaskError):
    """The agent ran out of its own time limit, or the agent service didn't answer in time."""


_LLM_ERROR_TEXTS: dict[LLMErrorKind, str] = {
    LLMErrorKind.AUTHENTICATION: (
        'The provider rejected the API key for model "{model}". Check the key in the LLM settings.'
    ),
    LLMErrorKind.RATE_LIMIT: (
        'The provider\'s rate limit for model "{model}" was reached. '
        "Wait a minute and run the flow again, or lower the agent's requests per minute."
    ),
    LLMErrorKind.QUOTA_EXCEEDED: (
        'The provider account for model "{model}" has run out of credit. '
        "Top it up, or choose another LLM."
    ),
    LLMErrorKind.CONTEXT_TOO_LONG: (
        'The prompt is too long for model "{model}". '
        "Shorten the task or its inputs, or choose a model with a bigger context window."
    ),
    LLMErrorKind.MODEL_NOT_FOUND: (
        'The provider has no model "{model}". Check the model name in the LLM settings.'
    ),
    LLMErrorKind.PROVIDER_UNAVAILABLE: (
        'The provider of model "{model}" isn\'t responding. Try again in a few minutes.'
    ),
    LLMErrorKind.CONTENT_REFUSED: (
        'The provider of model "{model}" refused the request because of its content policy. '
        "Change the task or its inputs."
    ),
    LLMErrorKind.PROVIDER_TIMEOUT: (
        'The provider of model "{model}" took too long to answer. Try again.'
    ),
    LLMErrorKind.UNKNOWN: (
        'The LLM request for model "{model}" failed. '
        "Try again or contact your administrator (reference: {reference})."
    ),
}

# With a custom base URL the URL itself is as likely to be wrong as the model name.
_MODEL_NOT_FOUND_AT_CUSTOM_BASE_URL_TEXT = (
    'The provider has no model "{model}". Check the model name and base URL in the LLM settings.'
)

_AGENT_SERVICE_NO_ANSWER_TEXT = (
    "The agent service didn't answer in time. "
    "Try again or contact your administrator (reference: {reference})."
)

# The agent service writes str() of a litellm exception, which starts with its class.
_LITELLM_ERROR_CLASS = re.compile(r"\blitellm\.\w+")


def agent_service_no_answer_error(
    timeout_s: float, run_correlation_id: str
) -> AgentTaskTimeoutError:
    """Build the error for a run whose result crew stopped waiting for after ``timeout_s``.

    Logs the wait under a new reference, which the message cites and the failed session
    repeats.
    """
    reference = log_with_reference(
        "Agent service didn't answer within {timeout_s}s "
        "(agent_correlation_id={agent_correlation_id})",
        timeout_s=timeout_s,
        agent_correlation_id=run_correlation_id,
    )
    return AgentTaskTimeoutError(
        _AGENT_SERVICE_NO_ANSWER_TEXT.format(reference=reference), correlation_id=reference
    )


def agent_run_error(
    payload: dict, agent_definition: AgentDefinitionData, llm: LLMData, run_correlation_id: str
) -> AgentTaskError:
    """Build the error for a failed run from its ``agent.result`` or ``agent.error`` payload.

    Logs the failure under ``run_correlation_id``, the id the agent service logged the run
    under. A failure the user can't fix from the message alone also gets a reference,
    logged with it, that the message cites and the failed session repeats.

    Args:
        payload: The envelope payload. ``stop_reason``, ``error_kind`` and ``failed_llm``
            are optional, so an agent service that doesn't send them still fails readably.
        agent_definition: The node's agent; its fallback LLM is named when ``failed_llm``
            says the fallback failed.
        llm: The agent's LLM, already checked to be set by the node.
        run_correlation_id: The id crew dispatched the run under.
    """
    raw_error = payload.get("error")
    stop_reason = payload.get("stop_reason")
    error_kind = payload.get("error_kind")

    if stop_reason == StopReason.TIMEOUT:
        limit_s = agent_definition.max_execution_time
        if limit_s is None:
            # Only crew's own wait limits an agent without a time limit, so the agent
            # service reporting a timeout is something the user can't act on.
            reference = _log_unexplained_failure(raw_error, run_correlation_id)
            return AgentTaskError(
                build_public_error_message(PublicErrorMessage.NODE_EXECUTION_FAILED, reference),
                correlation_id=reference,
            )
        _log_explained_failure(StopReason.TIMEOUT.value, run_correlation_id)
        return _agent_time_limit_error(agent_definition.name, limit_s)

    if stop_reason != StopReason.LLM_ERROR and error_kind is None:
        # Not an LLM failure (internal_error, a broken output schema, an unknown tool
        # reference, a crash), so nothing more specific than the generic message can be said.
        reference = _log_unexplained_failure(raw_error, run_correlation_id)
        return AgentTaskError(
            build_public_error_message(PublicErrorMessage.NODE_EXECUTION_FAILED, reference),
            correlation_id=reference,
        )

    # An llm_error without a kind comes from an agent service older than error_kind.
    kind = _known_kind(error_kind)
    llm_that_failed = _llm_that_failed(payload.get("failed_llm"), agent_definition, llm)
    if kind is LLMErrorKind.UNKNOWN:
        reference = _log_unexplained_failure(raw_error, run_correlation_id)
        return AgentTaskError(
            llm_error_text(kind, llm_that_failed, reference), correlation_id=reference
        )

    _log_explained_failure(kind.value, run_correlation_id)
    return AgentTaskError(llm_error_text(kind, llm_that_failed))


def llm_error_text(kind: LLMErrorKind, llm: LLMData, reference: str | None = None) -> str:
    """Return the text that tells the user why a call to ``llm`` failed.

    Args:
        reference: The log line's reference; required for ``UNKNOWN``, whose text cites it.
    """
    model = llm.config.model
    if kind is LLMErrorKind.MODEL_NOT_FOUND and llm.config.base_url:
        return _MODEL_NOT_FOUND_AT_CUSTOM_BASE_URL_TEXT.format(model=model)
    return _LLM_ERROR_TEXTS[kind].format(model=model, reference=reference)


def _agent_time_limit_error(agent_name: str, limit_s: float) -> AgentTaskTimeoutError:
    unit = "second" if limit_s == 1 else "seconds"
    return AgentTaskTimeoutError(
        f'Agent "{agent_name}" didn\'t finish within {_format_seconds(limit_s)} {unit}. '
        "Raise its max execution time, or make the task simpler."
    )


def _format_seconds(seconds: float) -> str:
    # Whole numbers print as ints, so a large limit never reads as 1e+06.
    return str(int(seconds)) if float(seconds).is_integer() else str(seconds)


def _llm_that_failed(
    failed_llm: object, agent_definition: AgentDefinitionData, primary_llm: LLMData
) -> LLMData:
    # A payload without failed_llm comes from an agent service older than the field, which
    # only ever reported the primary.
    if failed_llm == FailedLLM.FALLBACK and agent_definition.fallback_llm is not None:
        return agent_definition.fallback_llm
    return primary_llm


def _known_kind(error_kind: object) -> LLMErrorKind:
    # A kind crew doesn't know yet (a newer agent service) or none at all (an older one).
    try:
        return LLMErrorKind(error_kind)
    except ValueError:
        return LLMErrorKind.UNKNOWN


def _log_explained_failure(reason: str, run_correlation_id: str) -> None:
    # The message already says what happened, so the raw text adds nothing worth logging.
    logger.warning(
        "Agent run failed: {reason} (agent_correlation_id={agent_correlation_id})",
        reason=reason,
        agent_correlation_id=run_correlation_id,
    )


def _log_unexplained_failure(raw_error: object, run_correlation_id: str) -> str:
    return log_with_reference(
        "Agent run failed: {error} (agent_correlation_id={agent_correlation_id})",
        error=_describe_for_log(raw_error),
        agent_correlation_id=run_correlation_id,
    )


def _describe_for_log(raw_error: object) -> str:
    # The class says what went wrong; the agent service's own log line for the run, found
    # by agent_correlation_id, has the digest. Crew only has the text, so the class is the
    # litellm prefix when there is one.
    if raw_error is None:
        return "<none>"
    text = str(raw_error)
    match = _LITELLM_ERROR_CLASS.search(text)
    error_class = match.group(0) if match else "<unknown class>"
    return f"{error_class}: <redacted len={len(text)}>"
