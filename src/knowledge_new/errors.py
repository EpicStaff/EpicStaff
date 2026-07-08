from enums import DocumentErrorCode

__all__ = [
    "ChunkingError",
    "ChunksNotIndexedError",
    "DocumentNotFoundError",
    "EmbedderAuthError",
    "EmbedderRateLimitError",
    "EmbeddingConfigNotFoundError",
    "EmbeddingError",
    "FileTextExtractingError",
    "KnowledgeError",
    "NoPreviewChunksProducedError",
    "RagNotFoundError",
    "RepositoryError",
    "UnsupportedError",
]


class KnowledgeError(Exception):
    """Base error for all domain errors."""

    default_message: str = ""
    error_code: DocumentErrorCode = DocumentErrorCode.UNKNOWN

    def __init__(self, message: str = "", /, *args, **format_kwargs):
        if not message and self.default_message:
            message = self.default_message.format(**format_kwargs)
        super().__init__(message, *args)


class UnsupportedError(KnowledgeError):
    default_message = "Unsupported {that}: '{got}'"


class FileTextExtractingError(KnowledgeError):
    default_message = "{extractor} failed to extract text from binary content."
    error_code = DocumentErrorCode.CHUNKING_FAILED


class ChunkingError(KnowledgeError):
    default_message = "{chunker} failed to chunk text."
    error_code = DocumentErrorCode.CHUNKING_FAILED


class EmbeddingError(KnowledgeError):
    default_message = "{embedder} failed to embed text."
    error_code = DocumentErrorCode.EMBEDDING_FAILED


class EmbedderAuthError(EmbeddingError):
    default_message = "{embedder} authentication failed."
    error_code = DocumentErrorCode.EMBEDDER_AUTH


class EmbedderRateLimitError(EmbeddingError):
    default_message = "{embedder} rate limit exceeded."
    error_code = DocumentErrorCode.EMBEDDER_RATE_LIMIT


class RepositoryError(KnowledgeError):
    default_message = "Repository call {function} failed."


class NoPreviewChunksProducedError(KnowledgeError):
    default_message = (
        "No preview chunks produced for Document(id={document_id}) of RAG(id={rag_id})."
    )
    error_code = DocumentErrorCode.NO_CHUNKS_PRODUCED


class EmbeddingConfigNotFoundError(KnowledgeError):
    default_message = "Embedding config not found for RAG(id={rag_id})."


class DocumentNotFoundError(KnowledgeError):
    default_message = "Document(id={document_id}) not found for RAG(id={rag_id})."


class ChunksNotIndexedError(KnowledgeError):
    default_message = "Document(id={document_id}) chunks not indexed for RAG(id={rag_id})."


class RagNotFoundError(KnowledgeError):
    default_message = "RAG(id={rag_id}) not found."
