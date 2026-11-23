__all__ = [
    "ArtifactStorageError",
    "ChunkingError",
    "ChunksNotIndexedError",
    "ContentStorageUnavailableError",
    "DocumentContentMissingError",
    "DocumentNotFoundError",
    "EmbeddingConfigNotFoundError",
    "EmbeddingError",
    "EntityNotFoundError",
    "FileTextExtractingError",
    "GraphArtifactsNotReadyError",
    "GraphNotIndexedError",
    "GraphRagConfigNotFoundError",
    "InvalidArtifactArchiveError",
    "KnowledgeError",
    "NoPreviewChunksProducedError",
    "NotRunningOperationError",
    "RagInProcessingError",
    "RagNotFoundError",
    "RelationshipNotFoundError",
    "RepositoryError",
    "SecretDecryptError",
    "UnsupportedError",
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


class SecretDecryptError(KnowledgeError):
    default_message = "Could not decrypt {field}: it is not a value sealed with the transport key."


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


class GraphNotIndexedError(KnowledgeError):
    default_message = "Graph index output not available for RAG(id={rag_id}). Run indexing first."


class RagNotFoundError(KnowledgeError):
    default_message = "RAG(id={rag_id}) not found."


class NotRunningOperationError(KnowledgeError):
    default_message = "No running {operation} for RAG(id={rag_id})."


class RagInProcessingError(KnowledgeError):
    default_message = "Cannot remove RAG(id={rag_id}) while it is being processed."


class EntityNotFoundError(KnowledgeError):
    default_message = "Entity(id={entity_id}) not found in RAG(id={rag_id}) graph index."


class RelationshipNotFoundError(KnowledgeError):
    default_message = (
        "Relationship(id={relationship_id}) not found in RAG(id={rag_id}) graph index."
    )


class InvalidArtifactArchiveError(KnowledgeError):
    default_message = "Invalid artifact archive: {reason}."


class GraphArtifactsNotReadyError(KnowledgeError):
    default_message = "Graph artifacts not ready for RAG(id={rag_id})."


class ArtifactStorageError(KnowledgeError):
    default_message = "Could not delete {failed_count} object(s) under '{prefix}'."


class DocumentContentMissingError(KnowledgeError):
    default_message = "The content of {documents} is missing from storage."


class ContentStorageUnavailableError(KnowledgeError):
    default_message = "Document storage could not be reached."
