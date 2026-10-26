"""What the EpicStaff client raises when a call cannot be made or EpicStaff refuses it."""

import json
from typing import Any

import httpx

MAX_ERROR_MESSAGE_LENGTH = 2000


class ServiceAccountUnavailable(Exception):  # noqa: N818 (the platform contract names it so)
    """The runtime file holds no service account for the organization.

    The plugin is not granted to it, its grant holds no key (the install hook failed, for
    example), or the node has not written the new runtime file yet.
    """

    def __init__(self, org_id: int):
        self.org_id = org_id
        super().__init__(f"this plugin holds no service account for organization {org_id}")


class EpicStaffApiError(Exception):
    """EpicStaff answered a call with a status of 400 or more.

    `code` and `message` come from EpicStaff's error envelope
    (`{"status_code", "code", "message", "errors"?}`); an answer in another shape has no
    `code`, and its body, cut short, is the `message`. `errors` lists field errors when
    EpicStaff gives them.
    """

    def __init__(
        self,
        status: int,
        code: str | None,
        message: str,
        errors: list[Any] | None = None,
        *,
        method: str = "",
        path: str = "",
    ):
        self.status = status
        self.code = code
        self.message = message
        self.errors = errors
        self.method = method
        self.path = path
        reason = f"{status} {code}" if code else str(status)
        request = f"{method} {path}: " if method else ""
        super().__init__(f"EpicStaff refused {request}{reason}: {message}")

    @classmethod
    def from_response(
        cls, response: httpx.Response, *, method: str = "", path: str = ""
    ) -> "EpicStaffApiError":
        """Build the error from a refused response, reading EpicStaff's error envelope."""
        try:
            document = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            document = None
        if isinstance(document, dict) and isinstance(document.get("message"), str):
            code = document.get("code")
            errors = document.get("errors")
            return cls(
                response.status_code,
                code if isinstance(code, str) else None,
                document["message"][:MAX_ERROR_MESSAGE_LENGTH],
                errors if isinstance(errors, list) else None,
                method=method,
                path=path,
            )
        text = response.text.strip() or response.reason_phrase
        return cls(
            response.status_code,
            None,
            text[:MAX_ERROR_MESSAGE_LENGTH],
            method=method,
            path=path,
        )
