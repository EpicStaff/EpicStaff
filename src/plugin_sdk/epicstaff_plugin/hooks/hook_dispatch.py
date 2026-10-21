"""ASGI middleware that answers EpicStaff's hook calls before any other check sees them."""

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from epicstaff_plugin.asgi import ASGIApp, Receive, Scope, Send
from epicstaff_plugin.client.epicstaff_client import EpicStaffClient
from epicstaff_plugin.contracts.hook_api import (
    HOOK_HEADER,
    HOOK_PATHS,
    MAX_HOOK_BODY_BYTES,
    MAX_HOOK_ERROR_MESSAGE_LENGTH,
)
from epicstaff_plugin.hooks.assertion_verifier import HookAssertionRejected, HookAssertionVerifier
from epicstaff_plugin.hooks.hook_registry import HookRegistry

logger = logging.getLogger(__name__)

_KIND_BY_PATH = {path: kind for kind, path in HOOK_PATHS.items()}
_HOOK_HEADER_NAME = HOOK_HEADER.lower().encode("latin-1")


class _BodyTooLargeError(Exception):
    pass


class HookDispatchMiddleware:
    """Answer `POST` on the hook paths with the registered handler; pass everything else on.

    A hook call carries no gateway context, so this sits in front of the context check:
    a call to a hook path never reaches it or the plugin's app. Instead every call must
    carry a hook assertion that verifies (401 otherwise); then the handler for the kind runs
    (501 when there is none) and its outcome is the answer: 200 `done`, or 500 `failed` with
    the first line of the exception. Any other method on a hook path gets 405.

    Handlers for one organization run one at a time, so a retried job never overlaps a slow
    earlier attempt still running in this process.
    """

    def __init__(
        self,
        app: ASGIApp,
        verifier: HookAssertionVerifier,
        registry: HookRegistry,
        epicstaff: EpicStaffClient,
    ):
        self._app = app
        self._verifier = verifier
        self._registry = registry
        self._epicstaff = epicstaff
        self._org_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = _KIND_BY_PATH.get(scope.get("path", "")) if scope["type"] == "http" else None
        if kind is None:
            await self._app(scope, receive, send)
            return
        if scope["method"] != "POST":
            await _answer(
                send,
                405,
                {"status": "failed", "error": {"message": "use POST"}},
                extra_headers=[(b"allow", b"POST")],
            )
            return
        try:
            assertion = _assertion(scope["headers"])
            body = await _read_body(receive)
            hook = await self._verifier.verify_async(assertion, body, kind)
        except _BodyTooLargeError:
            await _failed(send, 401, "hook assertion rejected: body_too_large")
            return
        except HookAssertionRejected as rejection:
            logger.warning(
                "Refused a call to the %s hook: hook assertion %s", kind, rejection.reason
            )
            await _failed(send, 401, f"hook assertion rejected: {rejection.reason}")
            return
        handler = self._registry.handler(kind)
        if handler is None:
            await _failed(send, 501, f"this plugin has no {kind} hook")
            return
        request = hook.request
        async with self._org_locks[request.org.id]:
            try:
                await handler(request, self._epicstaff.for_org(request.org.id))
            # Whatever the handler raises fails the hook, and its message is what the
            # SuperAdmin sees next to the grant.
            except Exception as error:
                logger.exception(
                    "The %s hook failed (job %s, attempt %s, organization %s)",
                    kind,
                    request.job_id,
                    request.attempt,
                    request.org.id,
                )
                await _failed(send, 500, _first_line(error))
                return
        await _answer(send, 200, {"status": "done"})


def _assertion(headers: list[tuple[bytes, bytes]]) -> str:
    values = [value for name, value in headers if name.lower() == _HOOK_HEADER_NAME]
    if not values:
        raise HookAssertionRejected("missing")
    if len(values) > 1:
        raise HookAssertionRejected("ambiguous")
    return values[0].decode("latin-1")


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_HOOK_BODY_BYTES:
            raise _BodyTooLargeError
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _first_line(error: Exception) -> str:
    lines = str(error).strip().splitlines()
    message = lines[0] if lines else type(error).__name__
    return message[:MAX_HOOK_ERROR_MESSAGE_LENGTH]


async def _failed(send: Send, status: int, message: str) -> None:
    await _answer(send, status, {"status": "failed", "error": {"message": message}})


async def _answer(
    send: Send,
    status: int,
    document: dict[str, Any],
    *,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(document, separators=(",", ":")).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("latin-1")),
        (b"cache-control", b"no-store"),
        *(extra_headers or []),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
