from rest_framework.exceptions import APIException
from utils.exception_handler import flatten_error_detail

# Cites the reference the failure's traceback is logged under.
FLOW_START_FAILED_MESSAGE = (
    "Something went wrong on the server. "
    "Try again or contact your administrator (reference: {reference})."
)
# Shown when no crew instance listens for the run.
FLOW_SERVICE_NOT_RUNNING_MESSAGE = (
    "The flow couldn't start: the flow service isn't running. "
    "Try again or contact your administrator."
)
# Shown when no crew instance listens for the run's stop command.
FLOW_SERVICE_NOT_RUNNING_ON_STOP_MESSAGE = (
    "The flow couldn't be stopped: the flow service isn't running. "
    "Try again or contact your administrator."
)


def user_facing_run_error(error: APIException) -> str:
    """Return the text of an error raised on purpose to refuse a run; it is written for the user."""
    return flatten_error_detail(error.detail)


def run_start_failure_reason(error: Exception, reference: str) -> str:
    """Return the reason stored on a session whose run failed to start.

    `GET /sessions/<id>/` returns it and fanout_tool hands it to an agent. An
    `APIException` keeps its own text. Anything else is a bug or an outage whose
    text can carry internals (hosts, SQL, file paths), so it gets the generic
    message, citing `reference`.

    Args:
        reference: The id the caller logs the failure's traceback under.
    """
    if isinstance(error, APIException):
        return user_facing_run_error(error)
    return FLOW_START_FAILED_MESSAGE.format(reference=reference)
