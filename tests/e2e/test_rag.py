"""Naive RAG: collection, document upload, RAG + character chunking, indexing via mock embeddings."""

from fixtures.knowledge import CHUNKING, STORAGE_FILE_NAME, DocumentConfig, IndexedRag
from fixtures.llm import Quickstart
from helpers.api import ApiClient, page_results


def test_collection_is_created(rag_collection: dict) -> None:
    assert isinstance(rag_collection["collection_id"], int)
    assert rag_collection["collection_name"].startswith("e2e-kb-")


def test_document_is_uploaded(uploaded_document: dict, rag_collection: dict) -> None:
    [document] = uploaded_document["documents"]
    assert isinstance(document["document_id"], int)
    assert document["file_name"] == STORAGE_FILE_NAME
    assert document["source_collection"] == rag_collection["collection_id"]


def test_naive_rag_uses_the_quickstart_embedder(
    naive_rag: dict, rag_collection: dict, quickstart: Quickstart
) -> None:
    rag = naive_rag["naive_rag"]
    assert isinstance(rag["naive_rag_id"], int)
    assert rag["embedder"] == quickstart.embedding_config_id
    assert rag["collection_id"] == rag_collection["collection_id"]


def test_document_config_switches_to_the_character_chunker(
    document_config: DocumentConfig, uploaded_document: dict
) -> None:
    [listed] = document_config.list_body["configs"]
    assert listed["document_id"] == uploaded_document["documents"][0]["document_id"]
    updated = document_config.update_body["config"]
    assert updated["naive_rag_document_id"] == document_config.config_id
    assert {key: updated[key] for key in CHUNKING} == CHUNKING


def test_indexing_completes(indexed_rag: IndexedRag, naive_rag: dict) -> None:
    rag_id = naive_rag["naive_rag"]["naive_rag_id"]
    assert indexed_rag.accepted_body["rag_id"] == rag_id
    assert indexed_rag.accepted_body["rag_type"] == "naive"
    detail = indexed_rag.detail
    assert detail["rag_status"] == "completed", detail
    [config] = detail["document_configs"]
    assert config["status"] == "completed", config
    assert config["total_embeddings"] > 0, config


def test_chunks_contain_the_token(
    user_client: ApiClient, indexed_rag: IndexedRag, document_config: DocumentConfig, knowledge_token: str
) -> None:
    chunks = page_results(
        user_client.get(
            "/api/naive-rag-document-chunks/",
            params={"naive_rag_document_config": document_config.config_id},
        ).json()
    )
    assert any(knowledge_token in chunk["text"] for chunk in chunks), chunks


def embedding_inputs(call: dict) -> list[str]:
    raw_input = call["body"]["input"]
    return [str(item) for item in (raw_input if isinstance(raw_input, list) else [raw_input])]


def test_embeddings_went_to_mock_llm(indexed_rag: IndexedRag, knowledge_token: str) -> None:
    calls = indexed_rag.embedding_calls
    assert calls, "knowledge_new sent no /v1/embeddings request to mock-llm"
    assert all(call["body"]["model"] == "text-embedding-3-small" for call in calls)
    assert any(knowledge_token in text for call in calls for text in embedding_inputs(call)), (
        "no embeddings request since the indexing marker carried this run's knowledge token"
    )
