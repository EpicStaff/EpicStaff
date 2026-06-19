from enum import StrEnum

__all__ = [
    "ChunkStrategyEnum",
    "FileExtensionEnum",
]


class ChunkStrategyEnum(StrEnum):
    CHARACTER = "character"
    CSV = "csv"
    HTML = "html"
    JSON = "json"
    MARKDOWN = "markdown"
    TOKEN = "token"


class FileExtensionEnum(StrEnum):
    TXT = ".txt"
    MD = ".md"
    JSON = ".json"
    PDF = ".pdf"
    DOCX = ".docx"
    CSV = ".csv"
    HTML = ".html"
