"""Errors the sandbox gateway answers with.

Failures of the proxied resource itself, as opposed to the transport errors
`foundation.transport.http` raises for the upstream call. Each one carries the
status the gateway renders it as.
"""

from utils.exceptions import CustomAPIExeption

__all__ = ["UnknownCustomLibraryError", "VenvInUseError"]


class UnknownCustomLibraryError(CustomAPIExeption):
    """Raised when a venv names a stored library the organization does not have.

    Worded as unknown rather than forbidden on purpose: a library of another
    organization and a library that was never created have to read the same, or
    the refusal says which private package names exist.
    """

    status_code = 400
    default_detail = "This organization has no custom library by that name."
    default_code = "unknown_custom_library"


class VenvInUseError(CustomAPIExeption):
    """Raised when a virtual environment still has Python code pointing at it.

    409, not 400: the request is well formed, the resource is just not in a state
    that allows deleting it.
    """

    status_code = 409
    default_detail = "This virtual environment is still in use."
    default_code = "venv_in_use"
