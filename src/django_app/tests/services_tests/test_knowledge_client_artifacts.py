"""Contract of the knowledge client's GraphRAG artifact calls, against a fake knowledge service."""

import io
import json

import httpx
import pytest

from tables.clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientResourceNotFoundError,
    ClientTimeoutError,
    ClientValidationError,
)
from tables.clients.knowledge import KnowledgeClient


class FakeKnowledgeService:
    """Answers each request with the next queued response and records what it received."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests: list[tuple[str, str, bytes]] = []

    def __call__(self, request: httpx.Request):
        # Reading the body consumes a streamed upload exactly as the real server would.
        self.requests.append((request.method, request.url.path, request.read()))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def client(self) -> KnowledgeClient:
        return KnowledgeClient(transport=httpx.MockTransport(self))


class _StreamedBody(httpx.SyncByteStream):
    """A body that arrives over the wire, so it is unread until the client reads it."""

    def __init__(self, data: bytes):
        self._data = data

    def __iter__(self):
        yield self._data


def _error(status_code: int, code: str) -> httpx.Response:
    body = json.dumps({"code": code, "detail": "refused"}).encode()
    return httpx.Response(
        status_code, headers={"content-type": "application/json"}, stream=_StreamedBody(body)
    )


class _BreaksAfterFirstChunk(httpx.SyncByteStream):
    """A response body the server stops sending part way through."""

    def __iter__(self):
        yield b"first part of the tar"
        raise httpx.RemoteProtocolError("peer closed connection without sending complete message")


# --- download ---------------------------------------------------------------------------


def test_download_writes_the_whole_archive_into_the_destination():
    archive = bytes(range(256)) * 4096  # 1 MiB, more than one network chunk
    service = FakeKnowledgeService(httpx.Response(200, content=archive))
    destination = io.BytesIO()

    service.client().download_graph_artifacts(7, destination)

    assert destination.getvalue() == archive
    assert [(method, path) for method, path, _ in service.requests] == [
        ("GET", "/rags/graph/7/artifacts/")
    ]


@pytest.mark.parametrize(
    ("status_code", "code", "expected_error"),
    [
        pytest.param(409, "graph_artifacts_not_ready", ClientValidationError, id="409"),
        pytest.param(404, "not_found", ClientResourceNotFoundError, id="404"),
        pytest.param(503, "unavailable", ClientBadGatewayError, id="503"),
    ],
)
def test_a_refused_download_raises_with_the_services_reason_and_writes_nothing(
    status_code, code, expected_error
):
    destination = io.BytesIO()
    service = FakeKnowledgeService(_error(status_code, code))

    with pytest.raises(expected_error) as raised:
        service.client().download_graph_artifacts(7, destination)

    # The body of a streamed response is only there once read; the reason must survive.
    assert code in raised.value.detail
    assert destination.getvalue() == b""


def test_a_download_cut_off_mid_stream_raises_instead_of_leaving_a_short_archive():
    service = FakeKnowledgeService(httpx.Response(200, stream=_BreaksAfterFirstChunk()))

    with pytest.raises(ClientNotAvailableError):
        service.client().download_graph_artifacts(7, io.BytesIO())


@pytest.mark.parametrize(
    ("transport_error", "expected_error"),
    [
        pytest.param(httpx.ReadTimeout("timed out"), ClientTimeoutError, id="timeout"),
        pytest.param(httpx.ConnectError("refused"), ClientNotAvailableError, id="unreachable"),
    ],
)
def test_download_transport_failures(transport_error, expected_error):
    with pytest.raises(expected_error):
        FakeKnowledgeService(transport_error).client().download_graph_artifacts(7, io.BytesIO())


# --- upload -----------------------------------------------------------------------------


def test_upload_sends_the_archive_then_the_id_map_with_text_keys():
    archive = b"\x00tar bytes\x01" * 300_000  # about 3.3 MB, several upload chunks
    service = FakeKnowledgeService(httpx.Response(204), httpx.Response(204))

    service.client().upload_graph_artifacts(9, io.BytesIO(archive), {11: 51, 12: 52})

    (put_method, put_path, put_body), (post_method, post_path, post_body) = service.requests
    assert (put_method, put_path) == ("PUT", "/rags/graph/9/artifacts/")
    assert put_body == archive
    assert (post_method, post_path) == ("POST", "/rags/graph/9/artifacts/document-ids/")
    assert json.loads(post_body) == {"document_id_map": {"11": 51, "12": 52}}


def test_a_refused_archive_is_reported_and_the_id_map_is_never_sent():
    service = FakeKnowledgeService(_error(400, "invalid_artifact_archive"))

    with pytest.raises(ClientValidationError) as raised:
        service.client().upload_graph_artifacts(9, io.BytesIO(b"not a tar"), {11: 51})

    assert "invalid_artifact_archive" in raised.value.detail
    assert [method for method, _, _ in service.requests] == ["PUT"]


def test_a_refused_id_map_is_reported():
    service = FakeKnowledgeService(
        httpx.Response(204), _error(400, "invalid_artifact_archive")
    )

    with pytest.raises(ClientValidationError):
        service.client().upload_graph_artifacts(9, io.BytesIO(b"tar"), {11: 51})

    assert [method for method, _, _ in service.requests] == ["PUT", "POST"]
