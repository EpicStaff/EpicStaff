from enum import StrEnum

__all__ = [
    "ChunkStrategyEnum",
    "EmbedderProviderEnum",
    "FileExtensionEnum",
]


class ChunkStrategyEnum(StrEnum):
    CHARACTER = "character"
    CSV = "csv"
    HTML = "html"
    JSON = "json"
    MARKDOWN = "markdown"
    TOKEN = "token"


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
