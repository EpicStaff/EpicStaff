"""The Weather backend: a FastAPI app the EpicStaff node serves behind its gateway.

The node runs it with `python -m epicstaff_plugin.serve`, which checks the gateway context
of every request before it reaches a route here; `context_from_scope` returns that context.
Public paths (see the manifest) get a public context; every other route is reached only by a
person logged in to EpicStaff, with a user context. Importing this module also registers the
install hook (`weather_plugin.install_hook`), which the same runner answers.

Routes that read or change EpicStaff call it on behalf of the person asking
(`EpicStaffClient.client_for_context`), so EpicStaff records that person on what Weather
does for them.

Weather keeps its saved places, its forecast runs and its popup results in its own database
(`weather_plugin.database`), which the lifespan opens before the first request: a backend
whose database cannot be reached does not start. The place search calls Open-Meteo through
the egress proxy (`weather_plugin.place_search`).

Refusals are `{"code": ...}` with a 4xx status: `invalid_request` (400) for input that breaks
a route's rules, `forbidden` (403) without the Weather permission a route needs,
`state_mismatch` (403) for a popup result posted from another organization, `not_found`
(404), `not_installed` (409) before the install hook set up the organization,
`already_configured` (409), `already_saved` (409), `secret_exists` (409, with a `message` for
the admin). When EpicStaff refuses a call, the answer is 502
`{"code": "epicstaff_error", "message": ...}`; when the place search fails, 502
`{"code": "lookup_failed"}`.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
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
from weather_plugin.database import WeatherDatabase
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
from weather_plugin.place_search import MAX_QUERY_LENGTH, LookupFailed, PlaceSearch
from weather_plugin.places import AlreadySaved, PlaceCandidate, SavedPlaces
from weather_plugin.popup_relay import (
    PopupRelayStore,
    RelayedResult,
    is_popup_state,
    organization_id_of,
)

WHOAMI_FIELDS = {"mode", "user", "org", "permissions", "request"}
NO_STORE = {"Cache-Control": "no-store"}
# The Weather permission that lets a person change the organization's Weather settings.
SETTINGS_PERMISSION = "delete"
# The Weather permission that lets a person add and remove the organization's saved places.
PLACES_PERMISSION = "update"
# The EpicStaff rights a person needs before Weather creates the LLM key and config for them.
LLM_SETUP_RIGHTS = (("secrets", "create"), ("llm_configs", "create"))
# The largest id a bigint column holds; a larger one in a path names no row.
MAX_ROW_ID = 2**63 - 1


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    database = await WeatherDatabase.open()
    place_search = PlaceSearch()
    app.state.places = SavedPlaces(database)
    app.state.forecast_runs = ForecastRuns(database)
    app.state.popup_relay = PopupRelayStore(database)
    app.state.place_search = place_search
    try:
        yield
    finally:
        await place_search.aclose()
        await database.close()


# No generated API pages: the public address serves only the routes below.
app = FastAPI(title="Weather", docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan)
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


async def _places_editor_context(context: UserContext) -> GatewayContext:
    if not context.has_permission(PLACES_PERMISSION):
        raise ApiError(403, "forbidden")
    return context


PlacesEditorContext = Annotated[GatewayContext, Depends(_places_editor_context)]


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


def _row_id(text: str) -> int | None:
    """Return the id a path segment names, or None when it can name no row."""
    if text.isascii() and text.isdecimal() and 0 < int(text) <= MAX_ROW_ID:
        return int(text)
    return None


def _search_query(query: Sequence[tuple[str, str]]) -> str:
    """Return the `q` of `?q=<text>`, stripped, given once and nothing else.

    Raises:
        ApiError: The query has another shape, or `q` is blank or over 100 characters.
    """
    if len(query) != 1 or query[0][0] != "q":
        raise ApiError(400, "invalid_request")
    text = query[0][1].strip()
    if not 1 <= len(text) <= MAX_QUERY_LENGTH:
        raise ApiError(400, "invalid_request")
    return text


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
    await request.app.state.forecast_runs.add(
        context.org.id, context.user.id, session_id, body.city
    )
    return {"session_id": session_id}


@app.get("/api/forecast/{session_id}")
async def get_forecast(
    session_id: str, request: Request, context: UserContext, epicstaff: EpicStaff
) -> JSONResponse:
    """A run's state, and its forecast once it finished; only for the person who started it."""
    run_id = _row_id(session_id)
    if run_id is None or not await request.app.state.forecast_runs.started_by(
        context.org.id, context.user.id, run_id
    ):
        raise ApiError(404, "not_found")
    session = await epicstaff.client_for_context(context).session(run_id)
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


@app.get("/api/places")
async def list_places(request: Request, context: UserContext) -> JSONResponse:
    """The organization's saved places."""
    places = await request.app.state.places.list(context.org.id)
    return JSONResponse(
        {"places": [place.model_dump(mode="json") for place in places]}, headers=NO_STORE
    )


@app.get("/api/places/search")
async def search_places(request: Request, context: UserContext) -> JSONResponse:
    """Places matching `?q=`, found through the egress proxy; up to five."""
    query = _search_query(request.query_params.multi_items())
    try:
        results = await request.app.state.place_search.search(query)
    except LookupFailed:
        raise ApiError(502, "lookup_failed") from None
    return JSONResponse(
        {"results": [result.model_dump(mode="json") for result in results]}, headers=NO_STORE
    )


@app.post("/api/places", status_code=201)
async def add_place(request: Request, context: PlacesEditorContext) -> dict[str, Any]:
    """Save one search result for the organization."""
    place = await _parsed(request, PlaceCandidate)
    try:
        saved = await request.app.state.places.add(context.org.id, context.user.id, place)
    except AlreadySaved:
        raise ApiError(409, "already_saved") from None
    return saved.model_dump(mode="json")


@app.delete("/api/places/{place_id}", status_code=204)
async def remove_place(place_id: str, request: Request, context: PlacesEditorContext) -> Response:
    """Remove a saved place; another organization's place is not found."""
    row_id = _row_id(place_id)
    if row_id is None or not await request.app.state.places.remove(context.org.id, row_id):
        raise ApiError(404, "not_found")
    return Response(status_code=204)


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
    await request.app.state.popup_relay.put(
        context.org.id, context.user.id, result.state, result.params
    )
    return Response(status_code=204)


@app.get("/api/popup-relay/{state}")
async def get_popup_result(state: str, request: Request, context: UserContext) -> JSONResponse:
    """`done` with the parameters, once, to the person who posted them; `pending` otherwise."""
    params = (
        await request.app.state.popup_relay.take(context.org.id, context.user.id, state)
        if is_popup_state(state)
        else None
    )
    body = {"status": "pending"} if params is None else {"status": "done", "params": params}
    return JSONResponse(body, headers=NO_STORE)
