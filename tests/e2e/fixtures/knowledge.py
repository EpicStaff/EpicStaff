"""Storage and RAG resources.

knowledge_token -> knowledge_file_content -> stored_file                       (storage)
rag_collection -> uploaded_document -> naive_rag -> document_config -> indexed_rag
                   (knowledge_file_content)        (quickstart embedder)    (mock_llm, timings)

Storage files and RAG documents are separate (no API attaches a storage file to a
collection), so the same bytes are uploaded twice.
"""

import time
import uuid
from dataclasses import dataclass

import pytest

from fixtures.llm import Quickstart
from helpers.api import ApiClient
from helpers.bootstrap import unique_suffix
from helpers.mock_llm import EMBEDDINGS_PATH, MockLlmClient
from helpers.polling import poll
from helpers.timings import Timings

STORAGE_FOLDER = "e2e"
STORAGE_FILE_NAME = "kb.txt"
# Character chunking: the default `token` chunker downloads the gpt2 tokenizer from
# huggingface.co at indexing time.
CHUNKING = {"chunk_strategy": "character", "chunk_size": 500, "chunk_overlap": 50}
INDEXING_PICKUP_TIMEOUT_SECONDS = 30
INDEXING_TIMEOUT_SECONDS = 240
RAG_POLL_INTERVAL_SECONDS = 0.25
# Any other status (completed, failed, partial, cancelled, outdated) ends the wait.
IN_PROGRESS_RAG_STATUSES = frozenset({"new", "processing"})


@dataclass(frozen=True)
class DocumentConfig:
    list_body: dict
    update_body: dict
    config_id: int


@dataclass(frozen=True)
class IndexedRag:
    accepted_body: dict
    detail: dict
    embedding_calls: list[dict]


@pytest.fixture(scope="session")
def knowledge_token() -> str:
    """Unique marker the RAG chunks, the knowledge search and the agent answer must carry."""
    return f"E2E-TOKEN-{uuid.uuid4()}"


@pytest.fixture(scope="session")
def knowledge_file_content(knowledge_token: str) -> bytes:
    # Shorter than one chunk (500 characters), so the token is never split.
    return (
        "EpicStaff end-to-end knowledge file.\n"
        f"The secret token is {knowledge_token}.\n"
        "Answer questions about the token from this file only.\n"
    ).encode()


@pytest.fixture(scope="session")
def stored_file(user_client: ApiClient, knowledge_file_content: bytes) -> dict:
    """Upload through nginx's streamed upload location as a raw body, not multipart."""
    return user_client.post(
        "/api/storage/upload/stream",
        params={"path": STORAGE_FOLDER, "filename": STORAGE_FILE_NAME},
        content=knowledge_file_content,
        headers={"Content-Type": "application/octet-stream"},
    ).json()


@pytest.fixture(scope="session")
def rag_collection(user_client: ApiClient) -> dict:
    return user_client.post(
        "/api/source-collections/",
        json={"collection_name": f"e2e-kb-{unique_suffix()}"},
        expect=201,
    ).json()


@pytest.fixture(scope="session")
def uploaded_document(
    user_client: ApiClient, rag_collection: dict, knowledge_file_content: bytes
) -> dict:
    return user_client.post(
        f"/api/documents/source-collection/{rag_collection['collection_id']}/upload/",
        files={"files": (STORAGE_FILE_NAME, knowledge_file_content, "text/plain")},
        expect=201,
    ).json()


@pytest.fixture(scope="session")
def naive_rag(
    user_client: ApiClient, rag_collection: dict, uploaded_document: dict, quickstart: Quickstart
) -> dict:
    """Created after the upload: a signal creates the per-document configs at that moment."""
    return user_client.post(
        f"/api/naive-rag/collections/{rag_collection['collection_id']}/naive-rag/",
        json={"embedder_id": quickstart.embedding_config_id},
    ).json()


@pytest.fixture(scope="session")
def document_config(user_client: ApiClient, naive_rag: dict) -> DocumentConfig:
    rag_id = naive_rag["naive_rag"]["naive_rag_id"]
    list_body = user_client.get(f"/api/naive-rag/{rag_id}/document-configs/").json()
    config_id = list_body["configs"][0]["naive_rag_document_id"]
    update_body = user_client.put(
        f"/api/naive-rag/{rag_id}/document-configs/{config_id}/", json=CHUNKING
    ).json()
    return DocumentConfig(list_body, update_body, config_id)


@pytest.fixture(scope="session")
def indexed_rag(
    user_client: ApiClient,
    naive_rag: dict,
    document_config: DocumentConfig,
    mock_llm: MockLlmClient,
    timings: Timings,
) -> IndexedRag:
    """Index the document once and wait for a final RAG status. Never re-posts the request.

    If the RAG keeps its pre-request status for INDEXING_PICKUP_TIMEOUT_SECONDS, the
    request never reached knowledge_new; that fails at once instead of after the full budget.
    """
    rag_id = naive_rag["naive_rag"]["naive_rag_id"]

    def fetch_detail() -> dict:
        return user_client.get(f"/api/naive-rag/{rag_id}/").json()

    def embedding_call_count() -> str:
        count = len(mock_llm.calls_since(marker, EMBEDDINGS_PATH))
        return f"mock-llm embedding calls since the indexing request: {count}"

    initial_status = fetch_detail()["rag_status"]
    marker = mock_llm.marker()
    started = time.monotonic()
    accepted = user_client.post(
        "/api/process-rag-indexing/",
        json={
            "rag_id": rag_id,
            "rag_type": "naive",
            "document_config_ids": [document_config.config_id],
        },
        expect=202,
    ).json()

    poll(
        fetch_detail,
        lambda detail: detail["rag_status"] != initial_status,
        timeout=INDEXING_PICKUP_TIMEOUT_SECONDS,
        interval=RAG_POLL_INTERVAL_SECONDS,
        describe=(
            f"RAG {rag_id} to leave status {initial_status!r}: the indexing request was not "
            "picked up (is knowledge_new running and reachable?)"
        ),
        diagnostics=embedding_call_count,
    )
    detail = poll(
        fetch_detail,
        lambda detail: detail["rag_status"] not in IN_PROGRESS_RAG_STATUSES,
        timeout=INDEXING_TIMEOUT_SECONDS,
        interval=RAG_POLL_INTERVAL_SECONDS,
        describe=f"RAG {rag_id} to finish indexing",
        diagnostics=embedding_call_count,
    )
    timings.record("rag_indexing_seconds", time.monotonic() - started)
    return IndexedRag(
        accepted_body=accepted,
        detail=detail,
        embedding_calls=mock_llm.calls_since(marker, EMBEDDINGS_PATH),
    )
