"""
Fixtures for knowledge service tests.
Adapted from tests/api_tests/knowledge_tests/conftest.py.
"""

import pytest

from tables.models.knowledge_models import (
    SourceCollection,
    DocumentMetadata,
    DocumentContent,
    BaseRagType,
    NaiveRag,
    NaiveRagDocumentConfig,
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
)
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.provider import Provider
from tables.models.llm_models import LLMConfig, LLMModel
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.constants.knowledge_constants import (
    GRAPHRAG_DEFAULT_INPUT_FILE_TYPE,
    GRAPHRAG_DEFAULT_CHUNK_SIZE,
    GRAPHRAG_DEFAULT_CHUNK_OVERLAP,
    GRAPHRAG_DEFAULT_CHUNK_STRATEGY,
    GRAPHRAG_DEFAULT_ENTITY_TYPES,
    GRAPHRAG_DEFAULT_MAX_GLEANINGS,
    GRAPHRAG_DEFAULT_MAX_CLUSTER_SIZE,
)


# ---------------------------------------------------------------------------
# Collections & documents
# ---------------------------------------------------------------------------


@pytest.fixture
def source_collection():
    return SourceCollection.objects.create(
        collection_name="Test Collection", user_id="test_user"
    )


@pytest.fixture
def empty_collection():
    return SourceCollection.objects.create(
        collection_name="Empty Collection", user_id="test_user_empty"
    )


@pytest.fixture
def document_content():
    return DocumentContent.objects.create(content=b"Test file content")


@pytest.fixture
def document_metadata(source_collection, document_content):
    return DocumentMetadata.objects.create(
        source_collection=source_collection,
        document_content=document_content,
        file_name="test_document.pdf",
        file_type="pdf",
        file_size=1024,
    )


@pytest.fixture
def multiple_documents(source_collection):
    documents = []
    for i in range(3):
        content = DocumentContent.objects.create(content=f"Test content {i}".encode())
        doc = DocumentMetadata.objects.create(
            source_collection=source_collection,
            document_content=content,
            file_name=f"test_doc_{i}.pdf",
            file_type="pdf",
            file_size=1024 + i * 100,
        )
        documents.append(doc)
    return documents


# ---------------------------------------------------------------------------
# Embedding configs
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider():
    provider, _ = Provider.objects.get_or_create(name="test-embedding-provider-svc")
    return provider


@pytest.fixture
def test_embedding_model(embedding_provider):
    model, _ = EmbeddingModel.objects.get_or_create(
        name="text-embedding-3-small-svc",
        defaults={"embedding_provider": embedding_provider},
    )
    return model


@pytest.fixture
def test_embedding_config(test_embedding_model):
    config, _ = EmbeddingConfig.objects.get_or_create(
        custom_name="Test Embedder Config Svc",
        defaults={
            "model": test_embedding_model,
            "task_type": "retrieval_document",
        },
    )
    return config


@pytest.fixture
def other_embedding_provider():
    """A provider that is DIFFERENT from the one used by test_embedding_config."""
    provider, _ = Provider.objects.get_or_create(name="other-embedding-provider-svc")
    return provider


@pytest.fixture
def other_provider_embedding_model(other_embedding_provider):
    model, _ = EmbeddingModel.objects.get_or_create(
        name="other-model-svc",
        defaults={"embedding_provider": other_embedding_provider},
    )
    return model


@pytest.fixture
def other_provider_embedding_config(other_provider_embedding_model):
    """EmbeddingConfig whose provider is DIFFERENT from test_embedding_config."""
    config, _ = EmbeddingConfig.objects.get_or_create(
        custom_name="Other Provider Embedder Config Svc",
        defaults={
            "model": other_provider_embedding_model,
            "task_type": "retrieval_document",
        },
    )
    return config


@pytest.fixture
def same_provider_embedding_config(test_embedding_model):
    """EmbeddingConfig with a different pk but SAME provider as test_embedding_config."""
    config, _ = EmbeddingConfig.objects.get_or_create(
        custom_name="Same Provider Alt Embedder Config Svc",
        defaults={
            "model": test_embedding_model,
            "task_type": "retrieval_query",
        },
    )
    return config


# ---------------------------------------------------------------------------
# LLM configs
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_provider():
    provider, _ = Provider.objects.get_or_create(name="openai-svc")
    return provider


@pytest.fixture
def llm_model(llm_provider):
    model, _ = LLMModel.objects.get_or_create(
        name="gpt-4o-svc", defaults={"llm_provider": llm_provider}
    )
    return model


@pytest.fixture
def llm_config(llm_model):
    config, _ = LLMConfig.objects.get_or_create(
        custom_name="Test LLM Config Svc",
        defaults={
            "model": llm_model,
            "temperature": 0.7,
            "is_visible": True,
        },
    )
    return config


# ---------------------------------------------------------------------------
# NaiveRag fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_rag_type(source_collection):
    return BaseRagType.objects.create(
        source_collection=source_collection, rag_type=BaseRagType.RagType.NAIVE
    )


@pytest.fixture
def naive_rag(base_rag_type, test_embedding_config):
    return NaiveRag.objects.create(
        base_rag_type=base_rag_type,
        embedder=test_embedding_config,
        rag_status=NaiveRag.NaiveRagStatus.NEW,
    )


@pytest.fixture
def naive_rag_document_config(naive_rag, document_metadata):
    return NaiveRagDocumentConfig.objects.create(
        naive_rag=naive_rag,
        document=document_metadata,
        chunk_strategy="token",
        chunk_size=1000,
        chunk_overlap=150,
        status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.NEW,
    )


# ---------------------------------------------------------------------------
# GraphRag fixtures
# ---------------------------------------------------------------------------


def _make_default_index_config():
    return GraphRagIndexConfig.objects.create(
        file_type=GRAPHRAG_DEFAULT_INPUT_FILE_TYPE,
        chunk_size=GRAPHRAG_DEFAULT_CHUNK_SIZE,
        chunk_overlap=GRAPHRAG_DEFAULT_CHUNK_OVERLAP,
        chunk_strategy=GRAPHRAG_DEFAULT_CHUNK_STRATEGY,
        entity_types=GRAPHRAG_DEFAULT_ENTITY_TYPES.copy(),
        max_gleanings=GRAPHRAG_DEFAULT_MAX_GLEANINGS,
        max_cluster_size=GRAPHRAG_DEFAULT_MAX_CLUSTER_SIZE,
    )


@pytest.fixture
def graph_rag(source_collection, test_embedding_config, llm_config):
    """GraphRag for source_collection created via the service (creates documents too)."""
    return GraphRagService.create_or_update_graph_rag(
        collection_id=source_collection.collection_id,
        embedder_id=test_embedding_config.pk,
        llm_id=llm_config.pk,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_naive_rag_config(naive_rag, document, status):
    """Create a NaiveRagDocumentConfig with an explicit status."""
    return NaiveRagDocumentConfig.objects.create(
        naive_rag=naive_rag,
        document=document,
        chunk_strategy="token",
        chunk_size=1000,
        chunk_overlap=150,
        status=status,
    )


def make_graph_rag_document(graph_rag, document, status):
    """Create a GraphRagDocument link with an explicit status."""
    return GraphRagDocument.objects.create(
        graph_rag=graph_rag,
        document=document,
        status=status,
    )
