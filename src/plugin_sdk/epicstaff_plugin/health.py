"""The health endpoint the EpicStaff node polls on every plugin process."""

import json

from epicstaff_plugin.asgi import ASGIApp, Receive, Scope, Send

HEALTH_PATH = "/_epicstaff/health"
_HEALTH_BODY = json.dumps({"status": "ok"}, separators=(",", ":")).encode("utf-8")
_HEALTH_HEADERS = [
    (b"content-type", b"application/json"),
    (b"content-length", str(len(_HEALTH_BODY)).encode("latin-1")),
]


class HealthCheckMiddleware:
    """Answer `GET /_epicstaff/health` with `200 {"status": "ok"}`; pass everything else on.

    It sits in front of the context check: the node calls it over loopback without a
    context, and nginx never forwards `/_epicstaff/` from outside.
    """

    def __init__(self, app: ASGIApp):
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "GET" and scope["path"] == HEALTH_PATH:
            await send({"type": "http.response.start", "status": 200, "headers": _HEALTH_HEADERS})
            await send({"type": "http.response.body", "body": _HEALTH_BODY})
            return
        await self._app(scope, receive, send)
