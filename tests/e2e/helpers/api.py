"""HTTP client for the e2e suite.

One `ApiClient` per identity: anonymous, a JWT (`Authorization: Bearer`) or an API key
(`X-Api-Key` + `X-Organization-Id`). The identity is fixed at construction: per-request
credential headers, `auth=` and `cookies=` are rejected, no client stores cookies (so no
refresh cookie ever rides along), and environment proxies are ignored. A request can
therefore never carry a JWT and an API key at once.

Every request is logged (method, URL, status, duration) through the `e2e.api` logger; pytest
shows those lines with a failing test. A status other than the expected one raises an
AssertionError with method, URL, status and the response body. Everything logged or raised
goes through `helpers.redaction`.
"""

import json
import logging
import os
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx

from helpers.redaction import REDACTED, redact, redact_url, scrub

logger = logging.getLogger("e2e.api")

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost").rstrip("/")

REQUEST_TIMEOUT_SECONDS = 30
BODY_EXCERPT_LENGTH = 2000
CREDENTIAL_HEADERS = frozenset({"authorization", "x-api-key", "cookie"})
FORBIDDEN_REQUEST_ARGUMENTS = frozenset({"auth", "cookies"})

__all__ = [
    "BASE_URL",
    "REDACTED",
    "ApiClient",
    "assert_error",
    "body_excerpt",
    "describe_response",
    "page_results",
]


def body_excerpt(response: httpx.Response) -> str:
    """Response body for failure output: redacted JSON, or the start of the scrubbed text."""
    try:
        text = json.dumps(redact(response.json()), ensure_ascii=False)
    except ValueError:
        text = scrub(response.text)
    if len(text) > BODY_EXCERPT_LENGTH:
        return f"{text[:BODY_EXCERPT_LENGTH]}... ({len(text)} chars)"
    return text


def describe_response(response: httpx.Response) -> str:
    request = response.request
    return (
        f"{request.method} {redact_url(str(request.url))} -> {response.status_code}\n"
        f"body: {body_excerpt(response)}"
    )


def status_is_expected(status_code: int, expect: int | Iterable[int] | None) -> bool:
    if expect is None:
        return True
    return status_code in ({expect} if isinstance(expect, int) else set(expect))


def check_status(response: httpx.Response, expect: int | Iterable[int] | None) -> None:
    if not status_is_expected(response.status_code, expect):
        allowed = {expect} if isinstance(expect, int) else set(expect)
        raise AssertionError(
            f"Expected status {sorted(allowed)}, got {response.status_code}: "
            f"{describe_response(response)}"
        )


def cookie_refusing_jar() -> CookieJar:
    return CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))


class ApiClient:
    """Synchronous client bound to one identity. Build it with a classmethod constructor."""

    def __init__(self, base_url: str, identity_headers: dict[str, str], label: str) -> None:
        self.label = label
        self._http = httpx.Client(
            base_url=base_url,
            headers=identity_headers,
            cookies=cookie_refusing_jar(),
            timeout=REQUEST_TIMEOUT_SECONDS,
            trust_env=False,
        )

    @classmethod
    def anonymous(cls, base_url: str) -> "ApiClient":
        return cls(base_url, {}, "anonymous")

    @classmethod
    def with_jwt(cls, base_url: str, access_token: str, org_id: int | None = None) -> "ApiClient":
        headers = {"Authorization": f"Bearer {access_token}"}
        if org_id is not None:
            headers["X-Organization-Id"] = str(org_id)
        return cls(base_url, headers, "jwt")

    @classmethod
    def with_api_key(cls, base_url: str, api_key: str, org_id: int | None) -> "ApiClient":
        """API-key client; `org_id=None` leaves out `X-Organization-Id` (negative tests)."""
        headers = {"X-Api-Key": api_key}
        if org_id is not None:
            headers["X-Organization-Id"] = str(org_id)
        return cls(base_url, headers, "api-key")

    def close(self) -> None:
        self._http.close()

    @staticmethod
    def _reject_credentials(headers: dict[str, str] | None, arguments: dict) -> None:
        if headers and CREDENTIAL_HEADERS & {name.lower() for name in headers}:
            raise ValueError("Credentials are fixed per client; build another ApiClient.")
        if FORBIDDEN_REQUEST_ARGUMENTS & arguments.keys():
            raise ValueError("`auth` and `cookies` are not accepted; build another ApiClient.")

    def _log(self, method: str, url: httpx.URL, status: int, duration: float, note: str = "") -> None:
        logger.info(
            "[%s] %s %s -> %s (%.2fs)%s",
            self.label,
            method,
            redact_url(str(url)),
            status,
            duration,
            note,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        expect: int | Iterable[int] | None = 200,
        headers: dict[str, str] | None = None,
        **arguments: object,
    ) -> httpx.Response:
        """Send a request and check its status.

        Args:
            expect: Allowed status code(s); None skips the check.
            headers: Extra headers. Credentials are rejected: they belong to the identity.
            arguments: Passed to httpx (`json`, `params`, `content`, `files`, ...).
        """
        self._reject_credentials(headers, arguments)
        started = time.monotonic()
        response = self._http.request(method, path, headers=headers, **arguments)
        self._log(method, response.request.url, response.status_code, time.monotonic() - started)
        check_status(response, expect)
        return response

    @contextmanager
    def stream(
        self,
        method: str,
        path: str,
        *,
        timeout: httpx.Timeout,
        expect: int | Iterable[int] | None = 200,
        headers: dict[str, str] | None = None,
        **arguments: object,
    ) -> Iterator[httpx.Response]:
        """Open a streaming response (SSE) with its own connect/read timeouts.

        The status is checked once the headers arrive; on a mismatch the body is read for
        the error message. The logged duration is time to headers.
        """
        self._reject_credentials(headers, arguments)
        started = time.monotonic()
        with self._http.stream(
            method, path, headers=headers, timeout=timeout, **arguments
        ) as response:
            self._log(
                method,
                response.request.url,
                response.status_code,
                time.monotonic() - started,
                " (stream opened)",
            )
            if not status_is_expected(response.status_code, expect):
                response.read()
                check_status(response, expect)
            yield response

    def get(self, path: str, **arguments: object) -> httpx.Response:
        return self.request("GET", path, **arguments)

    def post(self, path: str, **arguments: object) -> httpx.Response:
        return self.request("POST", path, **arguments)

    def put(self, path: str, **arguments: object) -> httpx.Response:
        return self.request("PUT", path, **arguments)

    def patch(self, path: str, **arguments: object) -> httpx.Response:
        return self.request("PATCH", path, **arguments)

    def delete(self, path: str, **arguments: object) -> httpx.Response:
        return self.request("DELETE", path, **arguments)


def page_results(body: object) -> list:
    """Items of a list endpoint, paginated (`{"count", "results"}`) or not."""
    if isinstance(body, dict) and "results" in body:
        return body["results"]
    assert isinstance(body, list), f"Expected a list or a page, got {type(body).__name__}"
    return body


def assert_error(response: httpx.Response, status_code: int, code: str) -> dict:
    """Assert the project's error envelope `{status_code, code, message, errors?}`.

    Asserts on `code`, never on the human-readable `message`.
    """
    assert response.status_code == status_code, (
        f"Expected status {status_code}, got {response.status_code}: "
        f"{describe_response(response)}"
    )
    envelope = response.json()
    assert envelope.get("code") == code, (
        f"Expected error code {code!r}, got {envelope.get('code')!r}: "
        f"{describe_response(response)}"
    )
    assert envelope.get("status_code") == status_code, describe_response(response)
    assert isinstance(envelope.get("message"), str), describe_response(response)
    return envelope
