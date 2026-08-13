from enum import StrEnum

from src.shared.enums.knowledge_new import (
    ChunkStrategyEnum,
    DocumentStatusEnum,
    GraphSearchMethodEnum,
    RAGStrategy,
)

__all__ = [
    "ChunkStrategyEnum",
    "DocumentErrorCode",
    "DocumentStatusEnum",
    "EmbedderProviderEnum",
    "FileExtensionEnum",
    "GraphSearchMethodEnum",
    "IndexStatusEnum",
    "RAGStrategy",
]


class DocumentErrorCode(StrEnum):
    CHUNKING_FAILED = "chunking_failed"
    NO_CHUNKS_PRODUCED = "no_chunks_produced"
    EMBEDDING_FAILED = "embedding_failed"
    EMBEDDER_AUTH = "embedder_auth"
    EMBEDDER_RATE_LIMIT = "embedder_rate_limit"
    UNKNOWN = "unknown"
    NONE = "none"


class EmbedderProviderEnum(StrEnum):
    COHERE = "cohere"
    GEMINI = "gemini"
    MISTRAL = "mistral"
    OPENAI = "openai"
    TOGETHER_AI = "together_ai"


class IndexStatusEnum(StrEnum):
    NEW = "new"
    PROCESSING = "processing"
    COMPLETED = "completed"
    WARNING = "warning"  # deprecated
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"
    OUTDATED = "outdated"


class FileExtensionEnum(StrEnum):
    TXT = ".txt"
    MD = ".md"
    JSON = ".json"
    PDF = ".pdf"
    DOCX = ".docx"
    CSV = ".csv"
    HTML = ".html"
