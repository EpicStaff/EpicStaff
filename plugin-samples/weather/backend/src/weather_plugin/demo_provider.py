"""A stand-in for an external OAuth provider, so the sample can show the popup hand-off.

A real provider shows its consent page and redirects back to the plugin's callback page with a
code and the `state` it was given. This one redirects at once. With `coop=1` it also sends
`Cross-Origin-Opener-Policy: same-origin`, as some providers do, which severs the popup from
the page that opened it, so the hand-off has to go through the relay.
"""

import html
import secrets
from collections.abc import Sequence
from typing import Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict

from weather_plugin.popup_relay import PopupState

CALLBACK_PATH = "/oauth-demo/callback"


class AuthorizationRequest(BaseModel):
    """The query of `GET /api/demo-provider`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: PopupState
    coop: Literal["0", "1"]

    @property
    def severs_opener(self) -> bool:
        return self.coop == "1"


def parse_authorization_request(query: Sequence[tuple[str, str]]) -> AuthorizationRequest:
    """Read the query's `state` and `coop`, each given exactly once and nothing else.

    Raises:
        ValueError: A parameter is missing, repeated, unknown or malformed.
    """
    names = [name for name, _ in query]
    if len(set(names)) != len(names):
        raise ValueError("a query parameter is repeated")
    return AuthorizationRequest.model_validate(dict(query))


def redirect_page(state: PopupState) -> str:
    """Return the page that sends the popup on to the callback with a new demo code."""
    code = f"demo-{secrets.token_hex(8)}"
    target = f"{CALLBACK_PATH}?{urlencode({'code': code, 'state': state})}"
    return f'<!doctype html><meta http-equiv="refresh" content="0;url={html.escape(target)}">'
