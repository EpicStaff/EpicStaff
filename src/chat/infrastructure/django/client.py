import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from application.ports import (
    ALL_CHATS_ACTIONS,
    OPERATOR_NAME_MAX_LENGTH,
    AbstractFlowRunner,
    AbstractIdentityProvider,
    CallerCredentials,
    GraphContract,
    IntrospectedUser,
    RunStatus,
)
from domain.errors import (
    FlowForbiddenError,
    FlowNotFoundError,
    FlowStartError,
    InvalidTokenError,
    NotMemberError,
    RunNotFoundError,
    UpstreamUnavailableError,
)
from settings import Settings

DOMAIN_VARIABLES_KEY = "variables"
# A server that ignores `offset` would otherwise page forever.
MAX_RESULT_PAGES = 50


def _display_name(value: object) -> str | None:
    """The introspected name, cut to the stored length; None when missing, blank or not a string.

    The name is a label: a malformed one must not fail the operator's request.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:OPERATOR_NAME_MAX_LENGTH]


class DjangoClient(AbstractFlowRunner, AbstractIdentityProvider):
    """Django's REST API over httpx. System-key calls carry `X-Api-Key`; user calls carry the user's JWT."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=settings.CHAT_DJANGO_URL,
            transport=transport,
            timeout=settings.CHAT_DJANGO_TIMEOUT,
            headers={"Host": settings.CHAT_DJANGO_HOST_HEADER}
            if settings.CHAT_DJANGO_HOST_HEADER
            else None,
        )
        self._system_headers = {"X-Api-Key": settings.DJANGO_API_KEY}
        # httpx applies its timeout per phase (connect, write, read, pool); this bounds the whole call.
        self._deadline = settings.CHAT_DJANGO_TIMEOUT

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            async with asyncio.timeout(self._deadline):
                return await self._client.request(method, url, **kwargs)
        except (httpx.HTTPError, TimeoutError) as error:
            raise UpstreamUnavailableError(f"{type(error).__name__} calling {url}") from error

    @staticmethod
    def _fail_on_error(response: httpx.Response) -> None:
        """Any status the caller did not handle itself means Django is unhealthy or misconfigured."""
        if response.status_code >= 400:
            raise UpstreamUnavailableError(
                f"HTTP {response.status_code} from {response.request.url.path}"
            )

    @staticmethod
    @contextmanager
    def _parsing(response: httpx.Response) -> Iterator[None]:
        """A 2xx body that is not JSON or lacks the expected keys means Django is not the API we know."""
        try:
            yield
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as error:  # ValueError covers JSON decoding
            raise UpstreamUnavailableError(
                f"Malformed body from {response.request.url.path}: {error!r}"
            ) from error

    def _org_headers(self, org_id: int) -> dict:
        return {**self._system_headers, "X-Organization-Id": str(org_id)}

    async def start_run(
        self, *, org_id, graph_id, variables, token_budget, callback_url, callback_secret
    ) -> int:
        body = {
            "graph_id": graph_id,
            "variables": variables,
            "token_budget": token_budget,
            "callback_url": callback_url,
            "callback_secret": callback_secret,
        }
        response = await self._request(
            "POST", "/api/run-session/", json=body, headers=self._org_headers(org_id)
        )
        if response.status_code == 404:
            raise FlowNotFoundError(graph_id)
        if response.status_code != 201:
            raise FlowStartError(f"HTTP {response.status_code}: {response.text[:300]}")
        with self._parsing(response):
            return int(response.json()["session_id"])

    async def stop_run(self, session_id: int) -> None:
        response = await self._request(
            "POST", f"/api/sessions/{session_id}/stop/", headers=self._system_headers
        )
        if response.status_code != 404:
            self._fail_on_error(response)

    async def run_status(self, org_id: int, session_id: int) -> RunStatus:
        response = await self._request(
            "GET", f"/api/sessions/{session_id}/", headers=self._org_headers(org_id)
        )
        if response.status_code == 404:
            raise RunNotFoundError(session_id)
        self._fail_on_error(response)
        with self._parsing(response):
            data = response.json()
            return RunStatus(status=data["status"], token_usage=data.get("token_usage") or {})

    async def run_result(self, org_id: int, session_id: int) -> object | None:
        params = {"session_id": session_id, "limit": 200, "offset": 0}
        for _ in range(MAX_RESULT_PAGES):
            response = await self._request(
                "GET",
                "/api/graph-session-messages/",
                params=params,
                headers=self._org_headers(org_id),
            )
            if response.status_code == 404:
                return None
            self._fail_on_error(response)
            with self._parsing(response):
                page = response.json()
                for message in page.get("results", []):
                    data = message.get("message_data") or {}
                    if data.get("message_type") == "graph_end":
                        return data.get("end_node_result")
                if not page.get("next"):
                    return None
            params["offset"] += params["limit"]
        return None

    async def graph_contract(self, caller: CallerCredentials, graph_id: int) -> GraphContract:
        response = await self._request(
            "GET",
            f"/api/graphs/{graph_id}/",
            headers={
                "Authorization": f"Bearer {caller.bearer_token}",
                "X-Organization-Id": str(caller.org_id),
            },
        )
        if response.status_code == 401:
            raise InvalidTokenError("EpicStaff rejected the bearer token.")
        if response.status_code == 403:
            raise FlowForbiddenError()
        if response.status_code == 404:
            raise FlowNotFoundError(graph_id)
        self._fail_on_error(response)
        with self._parsing(response):
            data = response.json()
            start_nodes, end_nodes = (
                data.get("start_node_list") or [],
                data.get("end_node_list") or [],
            )
            start_variables = None
            if start_nodes:
                declared = start_nodes[0].get("variables") or {}
                # The start node stores the Domain {"variables": {...}, "persistent_variables": ...}.
                start_variables = declared.get(DOMAIN_VARIABLES_KEY, declared) or {}
            return GraphContract(
                start_variables=start_variables,
                output_map=(end_nodes[0].get("output_map") or {}) if end_nodes else None,
            )

    async def introspect(self, jwt: str) -> IntrospectedUser | None:
        response = await self._request(
            "POST", "/api/auth/introspect/", json={"token": jwt}, headers=self._system_headers
        )
        self._fail_on_error(response)
        with self._parsing(response):
            data = response.json()
            if not data.get("active"):
                return None
            return IntrospectedUser(
                user_id=int(data["user_id"]),
                org_ids=[int(i) for i in data.get("org_ids", [])],
                is_superadmin=bool(data.get("is_superadmin")),
                display_name=_display_name(data.get("display_name")),
            )

    async def chats_actions(self, jwt: str, org_id: int) -> set[str]:
        response = await self._request(
            "GET",
            "/api/permissions/me/",
            headers={"Authorization": f"Bearer {jwt}", "X-Organization-Id": str(org_id)},
        )
        if response.status_code in (403, 404):
            raise NotMemberError(org_id)
        if response.status_code == 401:
            return set()
        self._fail_on_error(response)
        with self._parsing(response):
            permissions = response.json().get("permissions")
            if permissions == "*":
                return set(ALL_CHATS_ACTIONS)
            return set((permissions or {}).get("chats") or [])
