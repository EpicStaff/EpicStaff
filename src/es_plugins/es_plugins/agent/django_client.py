"""The node's client for django_app's `/api/plugin-nodes/self/...` endpoints.

Every request goes to nginx's internal listener (`PLUGINS_INTERNAL_API_URL`) and carries
`Authorization: PluginNodeKey <PLUGINS_NODE_KEY>`. Documents from django_app are parsed with
`extra="ignore"`, so a newer django_app that adds a field does not stop an older node.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import ValidationError
from src.shared.models.plugin_nodes import (
    DesiredPackage,
    DesiredState,
    NodeReport,
    RuntimeCredentials,
)

DESIRED_STATE_PATH = "plugin-nodes/self/desired-state/"
PACKAGE_PATH = "plugin-nodes/self/packages/{package_id}/"
RUNTIME_CREDENTIALS_PATH = "plugin-nodes/self/placements/{placement_id}/runtime-credentials/"
REPORTS_PATH = "plugin-nodes/self/reports/"
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class NodeApiError(Exception):
    """A request to django_app failed.

    `transient` is true when trying again later may succeed (django_app or nginx not
    reachable, a 5xx, a timeout); false when the answer itself is the problem.
    """

    def __init__(self, message: str, *, status: int | None = None, transient: bool):
        super().__init__(message)
        self.status = status
        self.transient = transient


@dataclass(frozen=True)
class FetchedCredentials:
    credentials: RuntimeCredentials
    runtime_file: bytes
    """The `runtime_file` member exactly as django_app sent it, byte for byte.

    The parsed `credentials` drop fields this node does not know (`extra="ignore"`); the bytes
    keep them, so a plugin built against a newer SDK still gets every field.
    """


class DjangoNodeClient:
    def __init__(
        self,
        api_url: str,
        node_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._client = httpx.AsyncClient(
            base_url=api_url,
            headers={"Authorization": f"PluginNodeKey {node_key}", "Accept": "application/json"},
            timeout=_TIMEOUT,
            transport=transport,
            follow_redirects=False,
            # No proxy or .netrc from the environment: the API is on the internal network.
            trust_env=False,
        )
        self._desired_state_etag: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_desired_state(self) -> DesiredState | None:
        """Return the node's desired state, or None when it has not changed since the last call.

        Raises:
            NodeApiError: The request failed or the document is not a desired state.
        """
        headers = {}
        if self._desired_state_etag is not None:
            headers["If-None-Match"] = self._desired_state_etag
        response = await self._request("GET", DESIRED_STATE_PATH, headers=headers)
        if response.status_code == 304:
            return None
        desired_state = _parse(DesiredState, response)
        self._desired_state_etag = response.headers.get("ETag")
        return desired_state

    async def download_package(self, package: DesiredPackage, destination: Path) -> None:
        """Stream a package to `destination`, checking its size and sha256 against `package`.

        The file appears at `destination` only once both match; a partial or mismatching
        download is deleted.

        Raises:
            NodeApiError: The download failed, or the bytes are not the package the desired
                state names (not transient: the same request would return the same bytes).
        """
        partial = destination.with_name(destination.name + ".part")
        digest = hashlib.sha256()
        size = 0
        path = PACKAGE_PATH.format(package_id=package.package_id)
        try:
            async with self._client.stream("GET", path) as response:
                _raise_for_status(response, await _error_body(response))
                announced = response.headers.get("X-Package-Sha256")
                if announced is not None and announced != package.sha256:
                    raise NodeApiError(
                        f"package {package.package_id} is announced as sha256 {announced}, "
                        f"the desired state expects {package.sha256}",
                        transient=False,
                    )
                package_file = await asyncio.to_thread(partial.open, "wb")
                try:
                    async for chunk in response.aiter_bytes(_DOWNLOAD_CHUNK_BYTES):
                        size += len(chunk)
                        if size > package.size:
                            raise NodeApiError(
                                f"package {package.package_id} is larger than the "
                                f"{package.size} bytes the desired state names",
                                transient=False,
                            )
                        digest.update(chunk)
                        await asyncio.to_thread(package_file.write, chunk)
                finally:
                    await asyncio.to_thread(package_file.close)
        except httpx.HTTPError as error:
            partial.unlink(missing_ok=True)
            raise NodeApiError(
                f"downloading package {package.package_id}: {error}", transient=True
            ) from None
        except NodeApiError:
            partial.unlink(missing_ok=True)
            raise
        if size != package.size or digest.hexdigest() != package.sha256:
            partial.unlink(missing_ok=True)
            raise NodeApiError(
                f"package {package.package_id} has {size} bytes with sha256 {digest.hexdigest()}, "
                f"the desired state expects {package.size} bytes with sha256 {package.sha256}",
                transient=False,
            )
        partial.replace(destination)

    async def fetch_runtime_credentials(self, placement_id: int) -> FetchedCredentials:
        """Fetch a placement's runtime file. It holds secrets: never log it.

        Raises:
            NodeApiError: The request failed or the answer is not runtime credentials.
        """
        path = RUNTIME_CREDENTIALS_PATH.format(placement_id=placement_id)
        response = await self._request("POST", path)
        credentials = _parse(RuntimeCredentials, response)
        if credentials.placement_id != placement_id:
            raise NodeApiError(
                f"asked for placement {placement_id}, got {credentials.placement_id}",
                transient=False,
            )
        return FetchedCredentials(
            credentials=credentials,
            runtime_file=top_level_member(response.content, "runtime_file"),
        )

    async def send_report(self, report: NodeReport) -> None:
        """Send the node's report.

        Raises:
            NodeApiError: django_app did not accept it.
        """
        await self._request(
            "POST",
            REPORTS_PATH,
            content=report.model_dump_json().encode(),
            headers={"Content-Type": "application/json"},
        )

    async def _request(self, method: str, path: str, **arguments) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **arguments)
        except httpx.HTTPError as error:
            raise NodeApiError(f"{method} {path}: {error}", transient=True) from None
        _raise_for_status(response, response.text[:500])
        if len(response.content) > MAX_DOCUMENT_BYTES:
            raise NodeApiError(f"{method} {path}: the answer is too large", transient=False)
        return response


async def _error_body(response: httpx.Response) -> str:
    if response.status_code < 400:
        return ""
    await response.aread()
    return response.text[:500]


def _raise_for_status(response: httpx.Response, body: str) -> None:
    status = response.status_code
    if 200 <= status < 300 or status == 304:
        return
    if 300 <= status < 400:
        raise NodeApiError(f"unexpected redirect {status}", status=status, transient=False)
    transient = status >= 500 or status in (408, 429)
    raise NodeApiError(
        f"{response.request.method} {response.request.url.path} answered {status}: {body}",
        status=status,
        transient=transient,
    )


def _parse(model, response: httpx.Response):
    try:
        return model.model_validate_json(response.content, extra="ignore")
    except ValidationError as error:
        # include_input=False: runtime credentials carry secret settings, which must never
        # reach a log or a report through a validation message.
        summary = "; ".join(
            f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}"
            for problem in error.errors(include_input=False)
        )
        raise NodeApiError(
            f"{response.request.url.path} sent an invalid {model.__name__}: {summary}",
            transient=False,
        ) from None


def top_level_member(document: bytes, key: str) -> bytes:
    """Return the exact bytes of the value of `key` in a JSON object.

    Raises:
        NodeApiError: The document is not a JSON object with that key.
    """
    text = document.decode("utf-8")
    decoder = json.JSONDecoder()
    try:
        position = _skip_whitespace(text, 0)
        if text[position] != "{":
            raise ValueError("not a JSON object")
        position = _skip_whitespace(text, position + 1)
        while text[position] != "}":
            if text[position] != '"':
                raise ValueError("expected a member name")
            name, position = json.decoder.scanstring(text, position + 1)
            position = _skip_whitespace(text, position)
            if text[position] != ":":
                raise ValueError("expected ':'")
            start = _skip_whitespace(text, position + 1)
            _, end = decoder.raw_decode(text, start)
            if name == key:
                return text[start:end].encode("utf-8")
            position = _skip_whitespace(text, end)
            if text[position] == ",":
                position = _skip_whitespace(text, position + 1)
    except (IndexError, ValueError) as error:
        raise NodeApiError(f"the answer is not a JSON object: {error}", transient=False) from None
    raise NodeApiError(f"the answer has no {key}", transient=False)


def _skip_whitespace(text: str, position: int) -> int:
    while text[position] in " \t\n\r":
        position += 1
    return position
