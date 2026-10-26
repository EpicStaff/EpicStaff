"""Stand-in for django_app in the gateway lab: the gateway check and an echo of the API.

`GET /api/plugin-gateway/check/` answers as the plugin gateway check does: 404 without the
shared secret, then 200 with X-Plugin-Upstream, X-Plugin-Context and
X-Plugin-Forward-Authorization, or 401/403 with X-Plugin-Deny, in the check's order (plugin,
canonical path, availability, public path, body cap, rate limit, login). Its decisions come
from the table below, not from a database: the lab tests nginx, not the decisions.

Every other path echoes what reached "Django", so the internal listener's header policy can
be checked. Each request is recorded as one JSON line in EVIDENCE_FILE.
"""

import asyncio
import hmac
import json
import os
import time
import urllib.parse

from aiohttp import web

GATEWAY_SECRET = os.environ["PLUGINS_GATEWAY_SECRET"]
PORT = int(os.environ["PORT"])
EVIDENCE_FILE = os.environ["EVIDENCE_FILE"]


def record(seen: dict) -> None:
    with open(EVIDENCE_FILE, "a", encoding="utf-8") as evidence:
        evidence.write(json.dumps(seen) + "\n")

# identifier -> upstream and the paths it declares public (method set, match, caps).
PLUGINS = {
    "alpha": {"upstream": "plugin_alpha:20001"},
    "bravo": {"upstream": "plugin-bravo:20002"},
    "slow": {"upstream": "plugin_alpha:20001", "sleep_seconds": 0.002},
    # Refused by the availability check: not up, and being upgraded.
    "down": {"upstream": "plugin_alpha:20001", "availability": "unavailable"},
    "updating": {"upstream": "plugin_alpha:20001", "availability": "maintenance"},
    "noupstream": {"upstream": ""},
    "bogus": {"upstream": "plugin_alpha:20001", "deny": "something-new"},
    "emptydeny": {"upstream": "plugin_alpha:20001", "deny": ""},
    "closed": {"upstream": "plugin_alpha:20001", "deny": "forbidden"},
    "gone": {"upstream": "plugin-gone:20009"},
    # django_app failing the check: an error answer, and a connection dropped without one.
    "checkerror": {"fails": "error"},
    "checkdown": {"fails": "drop"},
}
PUBLIC_PATHS = [
    {"path": "/api/ping", "match": "exact", "methods": {"GET"}, "rate": 1000, "body": 0},
    {"path": "/api/public/", "match": "prefix", "methods": None, "rate": 10**9, "body": 8192},
    {"path": "/api/upload", "match": "exact", "methods": {"POST"}, "rate": 1000, "body": 1},
    {"path": "/api/limited", "match": "exact", "methods": {"GET"}, "rate": 3, "body": 0},
]
# Stands in for a person's login, which the real check accepts from a later version on: lets the
# lab see what nginx does with Authorization on a path that is not public.
LOGGED_IN = "Bearer lab-login"
rate_windows: dict[tuple, int] = {}


def deny(status: int, reason: str | None) -> web.Response:
    return web.Response(status=status, headers={"X-Plugin-Deny": reason} if reason is not None else {})


def allow(upstream: str, context: str, forward_authorization: bool) -> web.Response:
    headers = {
        "X-Plugin-Context": context,
        "X-Plugin-Forward-Authorization": "1" if forward_authorization else "0",
    }
    if upstream:
        headers["X-Plugin-Upstream"] = upstream
    return web.Response(status=200, headers=headers)


def canonical(raw_path: str, normalized_path: str) -> bool:
    decoded = urllib.parse.unquote(raw_path)
    if decoded != normalized_path:
        return False
    if any(segment in (".", "..") for segment in decoded.split("/")):
        return False
    return "/_epicstaff" not in urllib.parse.unquote(decoded)


def public_rule(method: str, path: str):
    for rule in PUBLIC_PATHS:
        matches = path == rule["path"] if rule["match"] == "exact" else path.startswith(rule["path"])
        if matches and (rule["methods"] is None or method in rule["methods"]):
            return rule
    return None


async def check(request: web.Request) -> web.Response:
    headers = request.headers
    record({"path": request.path, "headers": list(headers.items())})
    if not hmac.compare_digest(headers.get("X-Plugin-Gateway-Secret", ""), GATEWAY_SECRET):
        return web.Response(status=404)
    plugin = PLUGINS.get(headers.get("X-Plugin-Identifier", ""))
    if plugin is None:
        return deny(403, "not_found")
    if plugin.get("fails") == "error":
        return web.Response(status=500, text="Internal Server Error")
    if plugin.get("fails") == "drop":
        request.transport.close()
        return web.Response(status=200)
    if "deny" in plugin:
        return deny(403, plugin["deny"]) if plugin["deny"] else web.Response(status=403)
    raw_path = headers.get("X-Original-URI", "").split("?", 1)[0]
    path = headers.get("X-Original-Normalized-Path", "")
    if not canonical(raw_path, path):
        return deny(403, "not_found")
    if "availability" in plugin:
        return deny(403, plugin["availability"])
    if plugin.get("sleep_seconds"):
        await asyncio.sleep(plugin["sleep_seconds"])
    method = headers.get("X-Original-Method", "")
    rule = public_rule(method, path)
    identifier = headers["X-Plugin-Identifier"]
    if rule is not None:
        length = headers.get("X-Original-Content-Length", "")
        chunked = "chunked" in headers.get("X-Original-Transfer-Encoding", "").lower()
        if (length and int(length) > rule["body"] * 1024) or (chunked and not length):
            return deny(403, "too_large")
        window = (identifier, rule["path"], headers.get("X-Real-IP", ""), int(time.time() // 60))
        rate_windows[window] = rate_windows.get(window, 0) + 1
        if rate_windows[window] > rule["rate"]:
            return deny(403, "rate_limited")
        context = f"lab-context;{identifier};public;{method};{path}"
        return allow(plugin["upstream"], context, forward_authorization=True)
    if headers.get("Authorization") == LOGGED_IN:
        context = f"lab-context;{identifier};user;{method};{path}"
        return allow(plugin["upstream"], context, forward_authorization=False)
    return deny(401, "login")


async def django_api(request: web.Request) -> web.Response:
    body = await request.read()
    seen = {"path": request.raw_path, "headers": list(request.headers.items()), "body_bytes": len(body)}
    record(seen)
    return web.json_response({"django": True, **seen})


app = web.Application(client_max_size=64 * 1024 * 1024)
app.router.add_get("/api/plugin-gateway/check/", check)
app.router.add_route("*", "/{tail:.*}", django_api)

if __name__ == "__main__":
    web.run_app(app, port=PORT, access_log=None, print=None)
