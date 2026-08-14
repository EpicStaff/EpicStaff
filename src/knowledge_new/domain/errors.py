__all__ = [
    "ChunkingError",
    "ChunksNotIndexedError",
    "DocumentNotFoundError",
    "EmbeddingConfigNotFoundError",
    "EmbeddingError",
    "FileTextExtractingError",
    "GraphRagConfigNotFoundError",
    "KnowledgeError",
    "NoPreviewChunksProducedError",
    "RagNotFoundError",
    "RepositoryError",
    "UnsupportedError",
    "NotRunningOperationError",
]


class KnowledgeError(Exception):
    """Base error for all domain errors."""

    default_message: str = ""

    def __init__(self, message: str = "", /, *args, **format_kwargs):
        if not message and self.default_message:
            message = self.default_message.format(**format_kwargs)
        super().__init__(message, *args)


class UnsupportedError(KnowledgeError):
    default_message = "Unsupported {that}: '{got}'"


class FileTextExtractingError(KnowledgeError):
    default_message = "{extractor} failed to extract text from binary content."


class ChunkingError(KnowledgeError):
    default_message = "{chunker} failed to chunk text."


class EmbeddingError(KnowledgeError):
    default_message = "{embedder} failed to embed text."


class RepositoryError(KnowledgeError):
    default_message = "Repository call {function} failed."


class NoPreviewChunksProducedError(KnowledgeError):
    default_message = (
        "No preview chunks produced for Document(id={document_id}) of RAG(id={rag_id})."
    )


class EmbeddingConfigNotFoundError(KnowledgeError):
    default_message = "Embedding config not found for RAG(id={rag_id})."


class DocumentNotFoundError(KnowledgeError):
    default_message = "Document(id={document_id}) not found for RAG(id={rag_id})."


class GraphRagConfigNotFoundError(KnowledgeError):
    default_message = "Config not found for RAG(id={rag_id})."


class ChunksNotIndexedError(KnowledgeError):
    default_message = "Document(id={document_id}) chunks not indexed for RAG(id={rag_id})."


class RagNotFoundError(KnowledgeError):
    default_message = "RAG(id={rag_id}) not found."


class NotRunningOperationError(KnowledgeError):
    default_message = "No running {operation} for RAG(id={rag_id})."
