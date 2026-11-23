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

    Read from EpicStaff's error envelope, `{"type", "errors": [{"code", "detail", "attr",
    "context"}]}`: `errors` is that list as it came, `code` is the first item's code and
    `message` joins every item's `detail` with `; `, each led by its `attr` when it names a
    field. An answer in another shape has no `code`, and its body, cut short, is the
    `message`.
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
        envelope = _read_envelope(document)
        if envelope is None:
            # shortcut: reads the pre-envelope body of older EpicStaff servers
            envelope = _read_pre_envelope_body(document)
        if envelope is not None:
            code, message, errors = envelope
            return cls(
                response.status_code,
                code,
                message[:MAX_ERROR_MESSAGE_LENGTH],
                errors,
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


def _read_envelope(document: Any) -> tuple[str | None, str, list[Any]] | None:
    """Read `{"type", "errors": [{"code", "detail", ...}]}` into code, message and items."""
    if not isinstance(document, dict):
        return None
    items = document.get("errors")
    if not isinstance(items, list) or not items:
        return None
    details = [
        _item_text(item)
        for item in items
        if isinstance(item, dict) and isinstance(item.get("detail"), str)
    ]
    if not details:
        return None
    first_code = items[0].get("code") if isinstance(items[0], dict) else None
    return (first_code if isinstance(first_code, str) else None), "; ".join(details), items


def _item_text(item: dict) -> str:
    """Render an item as EpicStaff's old `message` did: `attr: detail`, or the detail alone."""
    attr = item.get("attr")
    return f"{attr}: {item['detail']}" if isinstance(attr, str) and attr else item["detail"]


def _read_pre_envelope_body(document: Any) -> tuple[str | None, str, list[Any] | None] | None:
    """Read `{"status_code", "code", "message", "errors"?}`, which EpicStaff answered before."""
    if not isinstance(document, dict) or not isinstance(document.get("message"), str):
        return None
    code = document.get("code")
    errors = document.get("errors")
    return (
        (code if isinstance(code, str) else None),
        document["message"],
        (errors if isinstance(errors, list) else None),
    )
