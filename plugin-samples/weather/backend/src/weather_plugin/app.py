"""The Weather backend: a FastAPI app the EpicStaff node serves behind its gateway.

The node runs it with `python -m epicstaff_plugin.serve`, which checks the gateway context
of every request before it reaches a route here; `context_from_scope` returns that context.
Public paths (see the manifest) get a public context; every other route is reached only by a
person logged in to EpicStaff, with a user context. Importing this module also registers the
install hook (`weather_plugin.install_hook`), which the same runner answers.

Routes that read or change EpicStaff call it on behalf of the person asking
(`EpicStaffClient.client_for_context`), so EpicStaff records that person on what Weather
does for them.

Refusals are `{"code": ...}` with a 4xx status: `invalid_request` (400) for input that breaks
a route's rules, `forbidden` (403) without the Weather permission a route needs,
`state_mismatch` (403) for a popup result posted from another organization, `not_found`
(404), `not_installed` (409) before the install hook set up the organization,
`already_configured` (409), `secret_exists` (409, with a `message` for the admin). When
EpicStaff refuses a call, the answer is 502
`{"code": "epicstaff_error", "message": ...}`.
"""

from typing import Annotated, Any

from epicstaff_plugin.client import EpicStaffApiError, EpicStaffClient, ServiceAccountUnavailable
from epicstaff_plugin.contracts.gateway_context import GatewayContext
from epicstaff_plugin.gateway import context_from_scope
from epicstaff_plugin.runtime import runtime_config
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

# Imported for its effect: registers the install hook with the SDK's hook registry.
from weather_plugin import install_hook  # noqa: F401
from weather_plugin.demo_provider import parse_authorization_request, redirect_page
from weather_plugin.forecast_flow import find_forecast_flow
from weather_plugin.forecast_runs import ForecastRuns, forecast_of, forecast_status
from weather_plugin.org_settings import (
    AlreadyConfigured,
    SecretExists,
    UnknownModel,
    configure_llm,
    find_llm_config,
    list_llm_models,
)
from weather_plugin.popup_relay import PopupRelayStore, RelayedResult, organization_id_of

WHOAMI_FIELDS = {"mode", "user", "org", "permissions", "request"}
NO_STORE = {"Cache-Control": "no-store"}
# The Weather permission that lets a person change the organization's Weather settings.
SETTINGS_PERMISSION = "delete"
# The EpicStaff rights a person needs before Weather creates the LLM key and config for them.
LLM_SETUP_RIGHTS = (("secrets", "create"), ("llm_configs", "create"))

# No generated API pages: the public address serves only the routes below.
app = FastAPI(title="Weather", docs_url=None, redoc_url=None, openapi_url=None)
app.state.popup_relay = PopupRelayStore()
app.state.forecast_runs = ForecastRuns()
# Created on first use: it reads the runtime file, which exists only once the node runs us.
app.state.epicstaff = None


class ApiError(Exception):
    """A refusal, answered `{"code": code}` (and `message`, when given) with `status_code`."""

    def __init__(self, status_code: int, code: str, message: str | None = None):
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message


@app.exception_handler(ApiError)
async def _api_error(request: Request, error: ApiError) -> JSONResponse:
    body = {"code": error.code}
    if error.message is not None:
        body["message"] = error.message
    return JSONResponse(body, status_code=error.status_code)


@app.exception_handler(EpicStaffApiError)
async def _epicstaff_error(request: Request, error: EpicStaffApiError) -> JSONResponse:
    return JSONResponse({"code": "epicstaff_error", "message": error.message}, status_code=502)


@app.exception_handler(ServiceAccountUnavailable)
async def _no_service_account(request: Request, error: ServiceAccountUnavailable) -> JSONResponse:
    return JSONResponse({"code": "not_installed"}, status_code=409)


async def _user_context(request: Request) -> GatewayContext:
    context = context_from_scope(request.scope)
    # The gateway sends a user context on every path the manifest does not declare public;
    # only a manifest that declared one of these routes public would get here without one.
    if not context.is_user:
        raise ApiError(401, "login_required")
    return context


UserContext = Annotated[GatewayContext, Depends(_user_context)]


async def _settings_context(context: UserContext) -> GatewayContext:
    if not context.has_permission(SETTINGS_PERMISSION):
        raise ApiError(403, "forbidden")
    return context


SettingsContext = Annotated[GatewayContext, Depends(_settings_context)]


def _epicstaff(request: Request) -> EpicStaffClient:
    if request.app.state.epicstaff is None:
        request.app.state.epicstaff = EpicStaffClient(runtime_config())
    return request.app.state.epicstaff


EpicStaff = Annotated[EpicStaffClient, Depends(_epicstaff)]


class ForecastRequest(BaseModel):
    """The body of `POST /api/forecast`."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    city: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class LlmSettingsRequest(BaseModel):
    """The body of `PUT /api/org-settings/llm`. The key is never logged or returned."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    llm_model_id: Annotated[int, Field(gt=0)]
    api_key: Annotated[str, StringConstraints(min_length=1, max_length=4096)]


async def _parsed[Model: BaseModel](request: Request, model: type[Model]) -> Model:
    try:
        return model.model_validate_json(await request.body())
    except ValidationError:
        raise ApiError(400, "invalid_request") from None


@app.get("/api/ping")
async def ping(request: Request) -> dict[str, str]:
    """A public path (see the manifest): reachable without logging in to EpicStaff."""
    return {"status": "ok", "mode": context_from_scope(request.scope).mode}


@app.get("/api/forecast/status")
async def get_forecast_status(context: UserContext, epicstaff: EpicStaff) -> dict[str, Any]:
    """Whether the install hook has created the forecast flow in this organization."""
    return {"flow": await find_forecast_flow(epicstaff.client_for_context(context))}


@app.post("/api/forecast", status_code=202)
async def start_forecast(
    request: Request, context: UserContext, epicstaff: EpicStaff
) -> dict[str, int]:
    """Run the forecast flow for a city, on behalf of the person asking."""
    body = await _parsed(request, ForecastRequest)
    person_client = epicstaff.client_for_context(context)
    flow = await find_forecast_flow(person_client)
    if flow is None:
        raise ApiError(409, "not_installed")
    session_id = await person_client.run_flow(flow["id"], {"city": body.city})
    request.app.state.forecast_runs.add(session_id, context.user.id, context.org.id)
    return {"session_id": session_id}


@app.get("/api/forecast/{session_id}")
async def get_forecast(
    session_id: str, request: Request, context: UserContext, epicstaff: EpicStaff
) -> JSONResponse:
    """A run's state, and its forecast once it finished; only for the person who started it."""
    if not session_id.isdecimal() or not request.app.state.forecast_runs.started_by(
        int(session_id), context.user.id, context.org.id
    ):
        raise ApiError(404, "not_found")
    session = await epicstaff.client_for_context(context).session(int(session_id))
    return JSONResponse(
        {"status": forecast_status(session), "forecast": forecast_of(session)}, headers=NO_STORE
    )


@app.get("/api/org-settings")
async def get_org_settings(context: SettingsContext, epicstaff: EpicStaff) -> dict[str, Any]:
    """The organization's Weather settings: the LLM config Weather uses, if it has one."""
    return {"llm_config": await find_llm_config(epicstaff.client_for_context(context))}


@app.get("/api/llm-models")
async def get_llm_models(context: SettingsContext, epicstaff: EpicStaff) -> list[dict[str, Any]]:
    """The LLM models an admin can pick for Weather's summaries."""
    return await list_llm_models(epicstaff.client_for_context(context))


@app.put("/api/org-settings/llm")
async def put_llm_settings(
    request: Request, context: SettingsContext, epicstaff: EpicStaff
) -> dict[str, Any]:
    """Store the admin's LLM key as a Secret and create the LLM config that uses it."""
    body = await _parsed(request, LlmSettingsRequest)
    person_client = epicstaff.client_for_context(context)
    # EpicStaff checks only Weather's declared access on this call, not the admin's own
    # rights: Weather checks those itself, so it never does for someone what they could
    # not do in EpicStaff.
    person = await person_client.person(context.user.id)
    if person is None or not all(
        person.has_epicstaff_permission(resource_type, action)
        for resource_type, action in LLM_SETUP_RIGHTS
    ):
        raise ApiError(403, "forbidden")
    try:
        config = await configure_llm(person_client, body.llm_model_id, body.api_key)
    except AlreadyConfigured:
        raise ApiError(409, "already_configured") from None
    except SecretExists as error:
        raise ApiError(409, "secret_exists", error.message) from None
    except UnknownModel:
        raise ApiError(400, "invalid_request") from None
    return {"llm_config": config}


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
