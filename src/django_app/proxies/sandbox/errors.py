"""Errors the sandbox gateway answers with.

Failures of the proxied resource itself, as opposed to the transport errors
`foundation.transport.http` raises for the upstream call. Each one carries the
status the gateway renders it as.
"""

from utils.exceptions import CustomAPIExeption

__all__ = ["VenvInUseError"]


class VenvInUseError(CustomAPIExeption):
    """Raised when a virtual environment still has Python code pointing at it.

    409, not 400: the request is well formed, the resource is just not in a state
    that allows deleting it.
    """

    status_code = 409
    default_detail = "This virtual environment is still in use."
    default_code = "venv_in_use"
