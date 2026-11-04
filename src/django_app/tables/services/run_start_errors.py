from rest_framework.exceptions import APIException
from utils.exception_handler import UPSTREAM_FAILURE_MESSAGE, flatten_error_detail

FLOW_START_FAILED_MESSAGE = UPSTREAM_FAILURE_MESSAGE
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


def user_facing_run_error(error: Exception) -> str:
    """Return the text a user may see for a run that failed to start.

    An `APIException` is raised on purpose to refuse the run, and its text is
    written for the user. Anything else is a bug or an outage whose text can
    carry internals (hosts, SQL, file paths), so it gets the generic message.
    The same text goes to the run-session response and to the session's stored
    reason, which `GET /sessions/<id>/` returns and fanout_tool hands to an agent.
    """
    if isinstance(error, APIException):
        return flatten_error_detail(error.detail)
    return FLOW_START_FAILED_MESSAGE
