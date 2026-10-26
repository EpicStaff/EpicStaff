"""A plugin backend's client for EpicStaff's API, authenticated as the plugin's service account."""

import asyncio
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Self

import httpx

from epicstaff_plugin.client.errors import EpicStaffApiError, ServiceAccountUnavailable
from epicstaff_plugin.contracts.gateway_context import GatewayContext
from epicstaff_plugin.contracts.service_account_api import (
    MAX_PEOPLE_LOOKUP,
    ON_BEHALF_OF_HEADER,
    ORGANIZATION_HEADER,
    PERSON_CACHE_MAX_SECONDS,
    SERVICE_ACCOUNT_AUTHORIZATION_SCHEME,
    PeopleLookupRequest,
    PeopleLookupResponse,
    PluginPerson,
    ServiceAccountInfo,
    on_behalf_of_header_value,
)
from epicstaff_plugin.runtime.runtime_config import RuntimeConfig, runtime_config

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_POLL_SECONDS = 2
# Session statuses after which a run changes no more.
FINISHED_SESSION_STATUSES = frozenset({"end", "error", "stop", "expired"})
SUCCEEDED_SESSION_STATUS = "end"

_ME_PATH = "plugin-runtime/me/"
_PERSON_PATH = "plugin-runtime/people/{user_id}/"
_PEOPLE_LOOKUP_PATH = "plugin-runtime/people/lookup/"
_RUN_SESSION_PATH = "run-session/"
_SESSION_PATH = "sessions/{session_id}/"
_UPLOAD_STREAM_PATH = "storage/upload/stream"


@dataclass(frozen=True)
class FlowSession:
    """A flow run as `GET /api/sessions/{id}/` describes it.

    `variables` are the run's final variables once it finished (EpicStaff's
    `status_data.variables`), and None before. `document` is the whole answer.
    """

    id: int
    status: str
    variables: dict[str, Any] | None
    document: dict[str, Any]

    @property
    def finished(self) -> bool:
        return self.status in FINISHED_SESSION_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.status == SUCCEEDED_SESSION_STATUS

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "FlowSession":
        status = document.get("status")
        status_data = document.get("status_data")
        variables = status_data.get("variables") if isinstance(status_data, dict) else None
        finished = status in FINISHED_SESSION_STATUSES
        return cls(
            id=int(document["id"]),
            status=str(status),
            variables=variables if finished and isinstance(variables, dict) else None,
            document=document,
        )


class _PersonCache:
    def __init__(self, seconds: float, clock: Callable[[], float]):
        if not 0 <= seconds <= PERSON_CACHE_MAX_SECONDS:
            raise ValueError(
                f"a person may be cached for at most {PERSON_CACHE_MAX_SECONDS} seconds"
            )
        self._seconds = seconds
        self._clock = clock
        self._entries: dict[tuple[int, int], tuple[float, PluginPerson | None]] = {}

    def get(self, org_id: int, user_id: int) -> tuple[bool, PluginPerson | None]:
        entry = self._entries.get((org_id, user_id))
        if entry is None:
            return False, None
        expires_at, person = entry
        if expires_at <= self._clock():
            del self._entries[(org_id, user_id)]
            return False, None
        return True, person

    def put(self, org_id: int, user_id: int, person: PluginPerson | None) -> None:
        if self._seconds:
            self._entries[(org_id, user_id)] = (self._clock() + self._seconds, person)


class EpicStaffClient:
    """Calls EpicStaff's API with the plugin's service-account keys from the runtime file.

    One instance per process is enough; it holds a connection pool. `for_org` gives the
    client for one organization the plugin is granted to, and `client_for_context` the
    client that acts for the person a gateway context names. EpicStaff is reached on its
    internal address (`epicstaff_api_url`), never through a proxy, without following
    redirects, with a 30 s timeout.

    People read from the people endpoints are cached in this process for
    `person_cache_seconds` (at most 30, 0 turns the cache off), so a person who lost access
    can still appear for that long.
    """

    def __init__(
        self,
        runtime: RuntimeConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        person_cache_seconds: float = PERSON_CACHE_MAX_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._runtime = runtime
        self._people = _PersonCache(person_cache_seconds, clock)
        self._http = httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=timeout_seconds,
        )

    @property
    def runtime(self) -> RuntimeConfig:
        """The runtime file the keys come from; by default this process's (`runtime_config()`)."""
        if self._runtime is None:
            self._runtime = runtime_config()
        return self._runtime

    def for_org(self, org_id: int) -> "OrgClient":
        """Return the client that calls EpicStaff as the plugin in this organization.

        Its calls raise `ServiceAccountUnavailable` while the runtime file holds no service
        account for the organization.
        """
        return OrgClient(self, _positive_id(org_id, "an organization id"))

    def client_for_context(self, context: GatewayContext) -> "OrgClient":
        """Return the client that acts for the person of a gateway context, in their organization.

        Equals `for_org(context.org.id).on_behalf_of(context.user.id)`.

        Raises:
            ValueError: The context is public: there is no person to act for.
        """
        if not context.is_user or context.org is None or context.user is None:
            raise ValueError("a public request has no person to act for")
        return self.for_org(context.org.id).on_behalf_of(context.user.id)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exception: object) -> None:
        await self.aclose()

    async def _send(
        self,
        org_id: int,
        on_behalf_of: int | None,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        json: Any,
        content: bytes | None,
        headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        used = self._service_account_key(org_id)
        response = await self._request(
            used, org_id, on_behalf_of, method, path, params, json, content, headers
        )
        if response.status_code == httpx.codes.UNAUTHORIZED:
            # The node fetched new credentials since the key was read: the old key is
            # refused once its grace period ends. One retry with the current key.
            current = self._service_account_key(org_id)
            if current != used:
                response = await self._request(
                    current, org_id, on_behalf_of, method, path, params, json, content, headers
                )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise EpicStaffApiError.from_response(response, method=method, path=path)
        return response

    def _service_account_key(self, org_id: int) -> str:
        entry = self.runtime.service_account(org_id)
        if entry is None:
            raise ServiceAccountUnavailable(org_id)
        return entry.key

    async def _request(
        self,
        key: str,
        org_id: int,
        on_behalf_of: int | None,
        method: str,
        path: str,
        params: Mapping[str, Any] | None,
        json: Any,
        content: bytes | None,
        headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        request_headers = {
            **(headers or {}),
            "Authorization": f"{SERVICE_ACCOUNT_AUTHORIZATION_SCHEME} {key}",
            ORGANIZATION_HEADER: str(org_id),
            "Accept": "application/json",
        }
        if on_behalf_of is not None:
            request_headers[ON_BEHALF_OF_HEADER] = on_behalf_of_header_value(on_behalf_of)
        url = self.runtime.epicstaff_api_url.rstrip("/") + "/" + path.lstrip("/")
        return await self._http.request(
            method, url, params=params, json=json, content=content, headers=request_headers
        )


class OrgClient:
    """Calls EpicStaff as the plugin in one organization, alone or on behalf of a person.

    Paths are relative to EpicStaff's API: `graphs/` is `/api/graphs/`. Every call takes the
    organization's key from the runtime file at the time of the call, and raises
    `EpicStaffApiError` when EpicStaff answers 400 or more.

    On behalf of a person, EpicStaff checks that the person may use the plugin (403
    `on_behalf_of_not_allowed` otherwise) and records them on what the call does. It checks
    only the plugin's declared access, never the person's own EpicStaff rights: read those
    with `person()` and check them before doing something the person could not do.
    """

    def __init__(self, owner: EpicStaffClient, org_id: int, on_behalf_of: int | None = None):
        self._owner = owner
        self._org_id = org_id
        self._on_behalf_of = on_behalf_of

    @property
    def org_id(self) -> int:
        return self._org_id

    @property
    def on_behalf_of_user_id(self) -> int | None:
        """The person this client acts for, or None for the plugin acting alone."""
        return self._on_behalf_of

    def on_behalf_of(self, user_id: int) -> "OrgClient":
        """Return a client for the same organization that acts for this person."""
        on_behalf_of_header_value(user_id)
        return OrgClient(self._owner, self._org_id, user_id)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Call EpicStaff and return its answer, which has a status below 400.

        Raises:
            ServiceAccountUnavailable: The runtime file holds no key for the organization.
            EpicStaffApiError: EpicStaff answered 400 or more.
            httpx.HTTPError: EpicStaff could not be reached, or did not answer in time.
        """
        return await self._owner._send(
            self._org_id,
            self._on_behalf_of,
            method,
            path,
            params=params,
            json=json,
            content=content,
            headers=headers,
        )

    async def get(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        """`GET` a path and return the decoded JSON answer."""
        return _decoded(await self.request("GET", path, params=params))

    async def post(self, path: str, json: Any = None) -> Any:
        """`POST` JSON to a path and return the decoded JSON answer (None when empty)."""
        return _decoded(await self.request("POST", path, json=json))

    async def put(self, path: str, json: Any = None) -> Any:
        """`PUT` JSON to a path and return the decoded JSON answer (None when empty)."""
        return _decoded(await self.request("PUT", path, json=json))

    async def patch(self, path: str, json: Any = None) -> Any:
        """`PATCH` JSON to a path and return the decoded JSON answer (None when empty)."""
        return _decoded(await self.request("PATCH", path, json=json))

    async def delete(self, path: str) -> Any:
        """`DELETE` a path and return the decoded JSON answer (None when empty)."""
        return _decoded(await self.request("DELETE", path))

    async def me(self) -> ServiceAccountInfo:
        """Return the service account: the plugin, the organization, its declared access."""
        response = await self.request("GET", _ME_PATH)
        return ServiceAccountInfo.model_validate_json(response.content, extra="ignore")

    async def person(self, user_id: int) -> PluginPerson | None:
        """Return a person who may use the plugin in this organization, or None.

        None stands for everyone else: unknown, inactive, not a member, or without the
        plugin's `read` action. Cached as the client is configured.
        """
        user_id = _positive_id(user_id, "a user id")
        cache = self._owner._people
        cached, person = cache.get(self._org_id, user_id)
        if cached:
            return person
        try:
            response = await self.request("GET", _PERSON_PATH.format(user_id=user_id))
        except EpicStaffApiError as error:
            if error.status != httpx.codes.NOT_FOUND:
                raise
            person = None
        else:
            person = PluginPerson.model_validate_json(response.content, extra="ignore")
        cache.put(self._org_id, user_id, person)
        return person

    async def people(self, user_ids: Iterable[int]) -> list[PluginPerson]:
        """Return the people among `user_ids` who may use the plugin, sorted by user id.

        Asks EpicStaff in batches of 100; people in the cache are not asked for again.
        """
        wanted = sorted({_positive_id(user_id, "a user id") for user_id in user_ids})
        cache = self._owner._people
        found: dict[int, PluginPerson] = {}
        missing: list[int] = []
        for user_id in wanted:
            cached, person = cache.get(self._org_id, user_id)
            if not cached:
                missing.append(user_id)
            elif person is not None:
                found[user_id] = person
        for start in range(0, len(missing), MAX_PEOPLE_LOOKUP):
            batch = missing[start : start + MAX_PEOPLE_LOOKUP]
            response = await self.request(
                "POST",
                _PEOPLE_LOOKUP_PATH,
                json=PeopleLookupRequest(user_ids=batch).model_dump(mode="json"),
            )
            answered = PeopleLookupResponse.model_validate_json(
                response.content, extra="ignore"
            ).by_user_id()
            for user_id in batch:
                person = answered.get(user_id)
                cache.put(self._org_id, user_id, person)
                if person is not None:
                    found[user_id] = person
        return [found[user_id] for user_id in sorted(found)]

    async def run_flow(self, graph_id: int, variables: Mapping[str, Any] | None = None) -> int:
        """Start a run of a flow with these variables and return its session id.

        Needs `flows: use` in the plugin's declared access.
        """
        document = await self.post(
            _RUN_SESSION_PATH, {"graph_id": graph_id, "variables": dict(variables or {})}
        )
        return int(document["session_id"])

    async def session(self, session_id: int) -> FlowSession:
        """Return a flow run's status, and its final variables once it finished."""
        document = await self.get(_SESSION_PATH.format(session_id=session_id))
        return FlowSession.from_document(document)

    async def wait_for_session(
        self, session_id: int, *, timeout: float, poll_seconds: float = DEFAULT_POLL_SECONDS
    ) -> FlowSession:
        """Poll a flow run every `poll_seconds` until it finished, and return it.

        Raises:
            TimeoutError: The run had not finished after `timeout` seconds.
        """
        async with asyncio.timeout(timeout):
            while not (session := await self.session(session_id)).finished:
                await asyncio.sleep(poll_seconds)
        return session

    async def upload_file(self, path: str, filename: str, content: bytes) -> dict[str, Any]:
        """Store a file in the organization's storage, in folder `path` under `filename`.

        Needs `files: create`, and `files: update` to replace a file that is already there.
        Returns EpicStaff's answer to the upload.
        """
        response = await self.request(
            "POST",
            _UPLOAD_STREAM_PATH,
            params={"path": path, "filename": filename},
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
        return response.json()


def _decoded(response: httpx.Response) -> Any:
    return response.json() if response.content else None


def _positive_id(value: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{what} is a positive integer, not {value!r}")
    return value
