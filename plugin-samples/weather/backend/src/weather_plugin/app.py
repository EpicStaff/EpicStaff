"""The Weather backend: a FastAPI app the EpicStaff node serves behind its gateway.

The node runs it with `python -m epicstaff_plugin.serve`, which checks the gateway context
of every request before it reaches a route here; `context_from_scope` returns that context.
Public paths (see the manifest) get a public context; every other route is reached only by a
person logged in to EpicStaff, with a user context.

Refusals are `{"code": ...}` with a 4xx status: `invalid_request` (400) for input that breaks
a route's rules, `state_mismatch` (403) for a popup result posted from another organization.
"""

from typing import Annotated, Any

from epicstaff_plugin.contracts.gateway_context import GatewayContext
from epicstaff_plugin.gateway import context_from_scope
from epicstaff_plugin.runtime import runtime_config
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from weather_plugin.demo_provider import parse_authorization_request, redirect_page
from weather_plugin.popup_relay import PopupRelayStore, RelayedResult, organization_id_of

WHOAMI_FIELDS = {"mode", "user", "org", "permissions", "request"}
NO_STORE = {"Cache-Control": "no-store"}

# No generated API pages: the public address serves only the routes below.
app = FastAPI(title="Weather", docs_url=None, redoc_url=None, openapi_url=None)
app.state.popup_relay = PopupRelayStore()


class ApiError(Exception):
    """A refusal, answered `{"code": code}` with `status_code`."""

    def __init__(self, status_code: int, code: str):
        super().__init__(code)
        self.status_code = status_code
        self.code = code


@app.exception_handler(ApiError)
async def _api_error(request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse({"code": error.code}, status_code=error.status_code)


async def _user_context(request: Request) -> GatewayContext:
    context = context_from_scope(request.scope)
    # The gateway sends a user context on every path the manifest does not declare public;
    # only a manifest that declared one of these routes public would get here without one.
    if not context.is_user:
        raise ApiError(401, "login_required")
    return context


UserContext = Annotated[GatewayContext, Depends(_user_context)]


@app.get("/api/ping")
async def ping(request: Request) -> dict[str, str]:
    """A public path (see the manifest): reachable without logging in to EpicStaff."""
    return {"status": "ok", "mode": context_from_scope(request.scope).mode}


@app.get("/api/whoami")
async def whoami(context: UserContext) -> dict[str, Any]:
    """Who is asking, from which organization, and what they may do in Weather."""
    return context.model_dump(mode="json", include=WHOAMI_FIELDS)


@app.get("/api/settings")
async def settings() -> dict[str, Any]:
    """The deployment's settings this backend uses; secret ones are never returned."""
    return {"units": runtime_config().setting("units")}


@app.get("/api/demo-provider")
async def demo_provider(request: Request) -> HTMLResponse:
    """A public path: the stand-in OAuth provider's page, `?state=<popup state>&coop=0|1`."""
    try:
        authorization = parse_authorization_request(request.query_params.multi_items())
    except ValueError:
        raise ApiError(400, "invalid_request") from None
    headers = dict(NO_STORE)
    if authorization.severs_opener:
        headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return HTMLResponse(redirect_page(authorization.state), headers=headers)


@app.post("/api/popup-relay", status_code=204)
async def post_popup_result(request: Request, context: UserContext) -> Response:
    """Keep a popup's result for five minutes, for this person in this organization."""
    # Read as JSON whatever the Content-Type: a fetch that posts a JSON string without one
    # sends text/plain. That is safe here, because the request is authenticated only by its
    # bearer token, never by a cookie a cross-site form could send along.
    try:
        result = RelayedResult.model_validate_json(await request.body())
    except ValueError:
        raise ApiError(400, "invalid_request") from None
    if organization_id_of(result.state) != context.org.id:
        raise ApiError(403, "state_mismatch")
    request.app.state.popup_relay.put(context.user.id, context.org.id, result.state, result.params)
    return Response(status_code=204)


@app.get("/api/popup-relay/{state}")
async def get_popup_result(state: str, request: Request, context: UserContext) -> JSONResponse:
    """`done` with the parameters, once, to the person who posted them; `pending` otherwise."""
    params = request.app.state.popup_relay.take(context.user.id, context.org.id, state)
    body = {"status": "pending"} if params is None else {"status": "done", "params": params}
    return JSONResponse(body, headers=NO_STORE)
