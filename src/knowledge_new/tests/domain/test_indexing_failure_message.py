import pytest
from domain.enums import ChunkStrategyEnum, DocumentStatusEnum, IndexStatusEnum
from domain.errors import (
    ArtifactStorageError,
    ChunkingError,
    NoPreviewChunksProducedError,
    RepositoryError,
    SecretDecryptError,
)
from domain.models import ChunkingConfig, Document, Rag

FAILURES = [
    pytest.param(
        "Failed to index all documents.", "Failed to index all documents.", id="literal-text"
    ),
    pytest.param(
        NoPreviewChunksProducedError(document_id=7, rag_id=1),
        "The document produced no chunks.",
        id="domain-error",
    ),
    pytest.param(
        ChunkingError(chunker="TokenChunker"),
        "The text couldn't be split into chunks.",
        id="domain-error-with-format-kwargs",
    ),
    pytest.param(
        SecretDecryptError(field="embedding API key"),
        "The embedding API key couldn't be decrypted.",
        id="readable-field-name",
    ),
    pytest.param(
        RepositoryError(function="NaiveRagRepository.get_rag"),
        "Indexing failed because of a server error.",
        id="repository-error-names-internals",
    ),
    pytest.param(
        ArtifactStorageError(failed_count=2, prefix="rag_1/slot_a/"),
        "Indexing failed because of a server error.",
        id="storage-error-names-internals",
    ),
    pytest.param(
        RuntimeError("401 from https://provider.example: key sk-raw rejected"),
        "Indexing failed because of a server error.",
        id="unexpected-error",
    ),
    pytest.param(
        ExceptionGroup(
            "GraphRAG indexing failed for RAG(id=1) in workflow(s): extract_graph.",
            [ValueError("/srv/graphrag/rag_1/output is not writable")],
        ),
        "Indexing failed because of a server error.",
        id="exception-group",
    ),
]


@pytest.mark.parametrize(("failure", "expected_message"), FAILURES)
def test_failed_rag_stores_a_readable_message(failure, expected_message):
    rag = Rag(id=1, status=IndexStatusEnum.PROCESSING, indexing_document_ids={7})

    rag.mark_as_failed(failure)

    assert rag.status == IndexStatusEnum.FAILED
    assert rag.error_message == expected_message


@pytest.mark.parametrize(("failure", "expected_message"), FAILURES)
def test_failed_document_stores_a_readable_message(failure, expected_message):
    document = Document(
        id=7,
        name="doc.txt",
        content=b"text",
        status=DocumentStatusEnum.PROCESSING,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER, chunk_size=50, chunk_overlap=0
        ),
    )

    document.mark_as_failed(failure)

    assert document.status == DocumentStatusEnum.FAILED
    assert document.error_message == expected_message
