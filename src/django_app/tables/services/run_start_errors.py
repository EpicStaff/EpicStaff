from rest_framework.exceptions import APIException
from utils.exception_handler import flatten_error_detail

FLOW_START_FAILED_MESSAGE = (
    "Something went wrong on the server. Try again or contact your administrator."
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
