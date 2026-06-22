from enum import StrEnum

__all__ = [
    "RAGStrategy",
    "ChunkStrategyEnum",
    "DocumentStatusEnum",
    "EmbedderProviderEnum",
    "FileExtensionEnum",
]


class RAGStrategy(StrEnum):
    NAIVE = "naive"
    GRAPH = "graph"


class ChunkStrategyEnum(StrEnum):
    CHARACTER = "character"
    CSV = "csv"
    HTML = "html"
    JSON = "json"
    MARKDOWN = "markdown"
    TOKEN = "token"


class DocumentStatusEnum(StrEnum):
    NEW = "new"
    PROCESSING = "processing"
    CHUNKING = "chunking"
    CHUNKED = "chunked"
    COMPLETED = "completed"
    WARNING = "warning"
    FAILED = "failed"


class EmbedderProviderEnum(StrEnum):
    COHERE = "cohere"
    GEMINI = "gemini"
    MISTRAL = "mistral"
    OPENAI = "openai"
    TOGETHER_AI = "together_ai"


class FileExtensionEnum(StrEnum):
    TXT = ".txt"
    MD = ".md"
    JSON = ".json"
    PDF = ".pdf"
    DOCX = ".docx"
    CSV = ".csv"
    HTML = ".html"
