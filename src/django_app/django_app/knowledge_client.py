import httpx
from django.conf import settings

from src.shared.models import (
    CancelRequest,
    IndexRequest,
    PrechunkRequest,
    PrechunkResponse,
    SearchRequest,
    SearchResponse,
)

_INDEX_TIMEOUT = 10.0
_PRECHUNK_TIMEOUT = 5.0
_SEARCH_TIMEOUT = 5.0


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(base_url=settings.KNOWLEDGE_NEW_URL, timeout=timeout)


def index(request: IndexRequest) -> None:
    with _client(_INDEX_TIMEOUT) as c:
        c.post("/index", json=request.model_dump(mode="json")).raise_for_status()


def cancel(request: CancelRequest) -> None:
    with _client(_INDEX_TIMEOUT) as c:
        c.post("/cancel", json=request.model_dump(mode="json")).raise_for_status()


def prechunk(request: PrechunkRequest) -> PrechunkResponse:
    with _client(_PRECHUNK_TIMEOUT) as c:
        resp = c.post("/prechunk", json=request.model_dump(mode="json"))
        resp.raise_for_status()
        return PrechunkResponse(**resp.json())


def search(request: SearchRequest) -> SearchResponse:
    with _client(_SEARCH_TIMEOUT) as c:
        resp = c.post("/search", json=request.model_dump(mode="json"))
        resp.raise_for_status()
        return SearchResponse(**resp.json())


def index_status(rag_id: int, rag_strategy: str) -> dict:
    with _client(_INDEX_TIMEOUT) as c:
        resp = c.get(
            "/index/status", params={"rag_id": rag_id, "rag_strategy": rag_strategy}
        )
        resp.raise_for_status()
        return resp.json()
