from tables.models.knowledge_models import DocumentMetadata


MAX_FILE_SIZE = 12 * 1024 * 1024  # 12 MB

ALLOWED_FILE_TYPES = {choice[0] for choice in DocumentMetadata.DocumentFileType.choices}


# Default RAG configuration values
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150
DEFAULT_CHUNK_STRATEGY = "token"

# Validation limits
MIN_CHUNK_SIZE = 20
MAX_CHUNK_SIZE = 8000
MIN_CHUNK_OVERLAP = 0
MAX_CHUNK_OVERLAP = 1000

#Chunk preview 
CHUNKING_TIMEOUT = 50.0

UNIVERSAL_STRATEGIES = {"token", "character"}


FILE_TYPE_SPECIFIC_STRATEGIES = {
    "pdf": set(),  # Only universal strategies
    "csv": {"csv"},  # Universal + csv strategy
    "docx": set(),  # Only universal strategies
    "txt": set(),  # Only universal strategies
    "json": {"json"},  # Universal + json strategy
    "html": {"html"},  # Universal + html strategy
    "md": {"markdown"},  # Universal + markdown strategy
}
