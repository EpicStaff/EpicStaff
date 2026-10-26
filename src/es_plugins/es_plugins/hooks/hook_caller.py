"""Make one hook call to a plugin process on the node's loopback, and read what came of it.

The call is exactly the claimed invocation: `POST http://127.0.0.1:<port><HOOK_PATHS[kind]>`
with the assertion in `X-EpicStaff-Hook` and the body's bytes as django_app sent them (the
assertion is bound to their sha256). Like the health check, it never goes through a proxy and
never follows a redirect. The plugin's answer is read up to 64 KiB, undecoded: the node needs
only `{"status": "done"}` or the error message, and a plugin cannot make it hold more.
"""

import asyncio
import json
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from epicstaff_plugin.contracts.hook_api import (
    HOOK_HEADER,
    HOOK_PATHS,
    MAX_HOOK_ERROR_MESSAGE_LENGTH,
)
from src.shared.models.plugin_nodes import HookInvocation

MAX_HOOK_RESPONSE_BYTES = 64 * 1024
# The Unicode categories an error does not keep: control characters, and surrogates.
_UNSENDABLE = ("Cc", "Cs")


@dataclass(frozen=True)
class HookOutcome:
    """What came of one hook call, as the node reports it to django_app."""

    succeeded: bool
    error: str | None
    """Why it failed, for the SuperAdmin: the plugin's own message when it sent one."""

    http_status: int | None
    """The plugin's status code; None when no answer came."""

    duration_ms: int


class PluginHookCaller:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        # No timeout of httpx's own: the hook's timeout covers the whole exchange (below).
        self._client = httpx.AsyncClient(
            timeout=None,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
        self._clock = clock

    async def call(self, port: int, invocation: HookInvocation) -> HookOutcome:
        """Make the call and wait for the answer, for at most `invocation.timeout_seconds`.

        Never raises for what the plugin does: a refused connection, one lost before the answer
        came, or a timeout is a failed outcome.
        """
        started = self._clock()
        status: int | None = None
        try:
            async with asyncio.timeout(invocation.timeout_seconds):
                status, content = await self._post(port, invocation)
        except (TimeoutError, httpx.TimeoutException):
            succeeded, error = False, f"timed out after {invocation.timeout_seconds} s"
        except httpx.ConnectError as connection_error:
            succeeded, error = False, f"could not connect: {_reason(connection_error)}"
        except httpx.HTTPError as connection_error:
            # Connected, then the exchange broke: the plugin closed the connection, or sent no
            # valid HTTP.
            succeeded, error = False, f"the connection was lost: {_reason(connection_error)}"
        else:
            succeeded, error = outcome_of_answer(status, content)
        return HookOutcome(
            succeeded=succeeded,
            error=None if error is None else clean_error(error),
            http_status=status,
            duration_ms=round((self._clock() - started) * 1000),
        )

    async def _post(self, port: int, invocation: HookInvocation) -> tuple[int, bytes]:
        url = f"http://127.0.0.1:{port}{HOOK_PATHS[invocation.kind]}"
        headers = {
            HOOK_HEADER: invocation.assertion,
            "Content-Type": "application/json",
            # Undecoded bytes are what the cap counts; a compressed answer could not be capped.
            "Accept-Encoding": "identity",
        }
        async with self._client.stream(
            "POST", url, content=invocation.body.encode("utf-8"), headers=headers
        ) as response:
            content = bytearray()
            async for chunk in response.aiter_raw():
                content += chunk
                if len(content) >= MAX_HOOK_RESPONSE_BYTES:
                    break
            return response.status_code, bytes(content[:MAX_HOOK_RESPONSE_BYTES])

    async def aclose(self) -> None:
        await self._client.aclose()


def outcome_of_answer(status: int, content: bytes) -> tuple[bool, str | None]:
    """Succeeded for `200 {"status": "done"}`; otherwise failed with the plugin's message or the status."""
    try:
        document = json.loads(content)
    except (ValueError, RecursionError):
        # RecursionError: JSON nested deeper than the parser goes, which a plugin can send.
        document = None
    if not isinstance(document, dict):
        document = {}
    if status == 200 and document.get("status") == "done":
        return True, None
    error = document.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    if isinstance(message, str) and clean_error(message):
        return False, message
    return False, f"HTTP {status}"


def clean_error(error: str) -> str:
    """Make an error one line of at most what django_app stores.

    Control characters become spaces and runs of spaces one, so "line one\\nline two" reads
    "line one line two". Lone surrogates go the same way: JSON can carry them (`"\\ud800"`),
    and they have no UTF-8 form, so the result could not be sent.
    """
    spaced = "".join(
        " " if unicodedata.category(character) in _UNSENDABLE else character for character in error
    )
    one_line = " ".join(word for word in spaced.split(" ") if word)
    return one_line[:MAX_HOOK_ERROR_MESSAGE_LENGTH].rstrip()


def _reason(error: httpx.HTTPError) -> str:
    return str(error) or type(error).__name__
