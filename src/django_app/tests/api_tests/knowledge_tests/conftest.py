"""
Fixtures for knowledge API tests
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tables.models.knowledge_models import (
    SourceCollection,
    DocumentMetadata,
    DocumentContent,
    BaseRagType,
    NaiveRag,
    NaiveRagDocumentConfig,
    NaiveRagChunk,
)
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.provider import Provider
from tables.models.crew_models import Agent
from tables.models.llm_models import LLMConfig, LLMModel


@pytest.fixture
def source_collection():
    """Create a test source collection."""
    return SourceCollection.objects.create(
        collection_name="Test Collection", user_id="test_user"
    )


@pytest.fixture
def empty_collection():
    """Create an empty source collection."""
    return SourceCollection.objects.create(
        collection_name="Empty Collection", user_id="test_user"
    )


@pytest.fixture
def document_content():
    """Create test document content."""
    return DocumentContent.objects.create(content=b"Test file content")


@pytest.fixture
def document_metadata(source_collection, document_content):
    """Create test document metadata."""
    return DocumentMetadata.objects.create(
        source_collection=source_collection,
        document_content=document_content,
        file_name="test_document.pdf",
        file_type="pdf",
        file_size=1024,
    )


@pytest.fixture
def multiple_documents(source_collection):
    """Create multiple test documents."""
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


@pytest.fixture
def test_pdf_file():
    """Create a test PDF file."""
    content = b"%PDF-1.4 test content"
    return SimpleUploadedFile(
        name="test.pdf", content=content, content_type="application/pdf"
    )


@pytest.fixture
def test_txt_file():
    """Create a test TXT file."""
    content = b"Test text file content"
    return SimpleUploadedFile(
        name="test.txt", content=content, content_type="text/plain"
    )


@pytest.fixture
def test_json_file():
    """Create a test JSON file."""
    content = b'{"key": "value"}'
    return SimpleUploadedFile(
        name="test.json", content=content, content_type="application/json"
    )


@pytest.fixture
def large_file():
    """Create a file that exceeds size limit."""
    # Create a 13MB file (exceeds 12MB limit)
    content = b"x" * (13 * 1024 * 1024)
    return SimpleUploadedFile(
        name="large.pdf", content=content, content_type="application/pdf"
    )


@pytest.fixture
def invalid_file_type():
    """Create a file with invalid extension."""
    content = b"test content"
    return SimpleUploadedFile(
        name="test.xyz", content=content, content_type="application/octet-stream"
    )


@pytest.fixture
def embedding_provider():
    """Create a test embedding provider."""
    provider, _ = Provider.objects.get_or_create(name="test-embedding-provider")
    return provider


@pytest.fixture
def test_embedding_model(embedding_provider):
    """Create a test embedding model."""
    model, _ = EmbeddingModel.objects.get_or_create(
        name="text-embedding-3-small",
        defaults={"embedding_provider": embedding_provider},
    )
    return model


@pytest.fixture
def test_embedding_config(test_embedding_model):
    """Create a test embedding config."""
    config, _ = EmbeddingConfig.objects.get_or_create(
        custom_name="Test Embedder Config",
        defaults={
            "model": test_embedding_model,
            "task_type": "retrieval_document",
        },
    )
    return config


@pytest.fixture
def base_rag_type(source_collection):
    """Create a base RAG type."""
    return BaseRagType.objects.create(
        source_collection=source_collection, rag_type=BaseRagType.RagType.NAIVE
    )


@pytest.fixture
def naive_rag(base_rag_type, test_embedding_config):
    """Create a NaiveRag instance."""
    return NaiveRag.objects.create(
        base_rag_type=base_rag_type,
        embedder=test_embedding_config,
        rag_status=NaiveRag.NaiveRagStatus.NEW,
    )


@pytest.fixture
def naive_rag_document_config(naive_rag, document_metadata):
    """Create a NaiveRag document configuration."""
    return NaiveRagDocumentConfig.objects.create(
        naive_rag=naive_rag,
        document=document_metadata,
        chunk_strategy="token",
        chunk_size=1000,
        chunk_overlap=150,
        status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.NEW,
    )


@pytest.fixture
def naive_rag_chunks(naive_rag_document_config):
    """Create test NaiveRag chunks."""
    chunks = []
    for i in range(0, 3):
        chunk = NaiveRagChunk.objects.create(
            naive_rag_document_config=naive_rag_document_config,
            text=f"Chunk {i} content",
            chunk_index=i,
            token_count=100,
        )
        chunks.append(chunk)
    return chunks


@pytest.fixture
def processing_naive_rag(base_rag_type, test_embedding_config):
    """Create a NaiveRag instance with PROCESSING status."""
    return NaiveRag.objects.create(
        base_rag_type=base_rag_type,
        embedder=test_embedding_config,
        rag_status=NaiveRag.NaiveRagStatus.PROCESSING,
    )


@pytest.fixture
def agent_without_rag(default_org):
    """Create an agent without RAG assignment."""
    return Agent.objects.create(
        role="Test Agent",
        goal="Test Goal",
        backstory="Test Backstory",
        org=default_org,
    )


@pytest.fixture
def llm_provider():
    """Create LLM provider for tests."""
    provider, _ = Provider.objects.get_or_create(name="openai")
    return provider


@pytest.fixture
def llm_model(llm_provider):
    """Create LLM model for tests."""
    model, _ = LLMModel.objects.get_or_create(
        name="gpt-4o", defaults={"llm_provider": llm_provider}
    )
    return model


@pytest.fixture
def llm_config(llm_model):
    """Create LLM config for tests."""
    config, _ = LLMConfig.objects.get_or_create(
        custom_name="Test LLM Config",
        defaults={
            "model": llm_model,
            "temperature": 0.7,
            "is_visible": True,
        },
    )
    return config
