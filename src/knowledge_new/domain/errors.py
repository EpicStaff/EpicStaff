__all__ = [
    "ArtifactStorageError",
    "ChunkingError",
    "ChunksNotIndexedError",
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
    default_message = "The {that} '{got}' isn't supported."


class FileTextExtractingError(KnowledgeError):
    default_message = "The text couldn't be extracted from the file."


class ChunkingError(KnowledgeError):
    default_message = "The text couldn't be split into chunks."


class EmbeddingError(KnowledgeError):
    default_message = "The text couldn't be embedded."


class SecretDecryptError(KnowledgeError):
    default_message = "The {field} couldn't be decrypted."


class RepositoryError(KnowledgeError):
    default_message = "Repository call {function} failed."


class NoPreviewChunksProducedError(KnowledgeError):
    default_message = "The document produced no chunks."


class EmbeddingConfigNotFoundError(KnowledgeError):
    default_message = "The knowledge source has no embedding settings."


class DocumentNotFoundError(KnowledgeError):
    default_message = "The document wasn't found."


class GraphRagConfigNotFoundError(KnowledgeError):
    default_message = "The knowledge source has no graph settings."


class ChunksNotIndexedError(KnowledgeError):
    default_message = "The document's chunks weren't indexed."


class GraphNotIndexedError(KnowledgeError):
    default_message = "The graph isn't indexed yet."


class RagNotFoundError(KnowledgeError):
    default_message = "The knowledge source wasn't found."


class NotRunningOperationError(KnowledgeError):
    default_message = "No {operation} is running for this knowledge source."


class RagInProcessingError(KnowledgeError):
    default_message = "The knowledge source can't be removed while it's being processed."


class EntityNotFoundError(KnowledgeError):
    default_message = "The entity wasn't found in the graph."


class RelationshipNotFoundError(KnowledgeError):
    default_message = "The relationship wasn't found in the graph."


class InvalidArtifactArchiveError(KnowledgeError):
    default_message = "The archive isn't valid: {reason}."


class GraphArtifactsNotReadyError(KnowledgeError):
    default_message = "The graph files aren't ready yet."


class ArtifactStorageError(KnowledgeError):
    default_message = "Could not delete {failed_count} object(s) under '{prefix}'."
