"""Builds the browser's side of a plugin login: PKCE, the authorize request, the code exchange."""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

from rbac.identity.refresh_cookie import refresh_cookie_name
from rest_framework_simplejwt.tokens import RefreshToken

AUTHORIZE_URL = "/api/auth/plugin-authorize/"
TOKEN_URL = "/api/auth/plugin-token/"
EPICSTAFF_ORIGIN = "http://epicstaff.localhost"
WEATHER_ORIGIN = "http://weather.plugins.epicstaff.localhost"
CALLBACK_URL = f"{WEATHER_ORIGIN}/.well-known/epicstaff/callback.html"
SILENT_CALLBACK_URL = f"{WEATHER_ORIGIN}/.well-known/epicstaff/silent-callback.html"
STATE = "state-" + "s" * 40


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    """A fresh `(code_verifier, code_challenge)`, as the JS SDK makes them."""
    verifier = secrets.token_urlsafe(32)
    return verifier, challenge_for(verifier)


def session_cookie(user) -> str:
    """A `Cookie` header carrying a fresh EpicStaff session (refresh token) of `user`."""
    return f"{refresh_cookie_name()}={RefreshToken.for_user(user)}"


def authorize(client, *, cookie: str | None = None, challenge: str | None = None, **parameters):
    """GET the authorize endpoint with the pinned parameters; `None` leaves a parameter out."""
    query = {
        "plugin": "weather",
        "state": STATE,
        "code_challenge": challenge or pkce_pair()[1],
        "code_challenge_method": "S256",
        **parameters,
    }
    query = {name: value for name, value in query.items() if value is not None}
    extra = {"HTTP_COOKIE": cookie} if cookie is not None else {}
    return client.get(AUTHORIZE_URL, query, **extra)


def redirect_parts(response) -> tuple[str, dict[str, str]]:
    """The redirect target without its fragment, and the fragment's parameters."""
    location = response["Location"]
    target, _, fragment = location.partition("#")
    return target, {name: values[0] for name, values in parse_qs(fragment).items()}


def query_of(location: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(location).query)


def code_for(client, user, *, challenge: str, **parameters) -> str:
    """Run the authorize step for `user` and return the code it hands the plugin's callback."""
    response = authorize(client, cookie=session_cookie(user), challenge=challenge, **parameters)
    assert response.status_code == 302, response.content
    target, result = redirect_parts(response)
    assert "code" in result, response["Location"]
    return result["code"]


def exchange(client, code: str, verifier: str, *, origin: str | None = WEATHER_ORIGIN, **extra):
    """POST the token exchange as the plugin page does: JSON, from the plugin's origin."""
    headers = {"HTTP_ORIGIN": origin} if origin is not None else {}
    return client.post(
        TOKEN_URL, {"code": code, "code_verifier": verifier}, format="json", **headers, **extra
    )
