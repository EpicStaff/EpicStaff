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

# Chunk preview
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


# GraphRag default configuration values
GRAPHRAG_DEFAULT_INPUT_FILE_TYPE = "text"
GRAPHRAG_DEFAULT_CHUNK_SIZE = 1200
GRAPHRAG_DEFAULT_CHUNK_OVERLAP = 100
GRAPHRAG_DEFAULT_CHUNK_STRATEGY = "tokens"
GRAPHRAG_DEFAULT_ENTITY_TYPES = ["organization", "person", "geo", "event"]
GRAPHRAG_DEFAULT_MAX_GLEANINGS = 1
GRAPHRAG_DEFAULT_MAX_CLUSTER_SIZE = 10

# GraphRag validation limits
GRAPHRAG_MIN_CHUNK_SIZE = 100
GRAPHRAG_MAX_CHUNK_SIZE = 10000
GRAPHRAG_MIN_CHUNK_OVERLAP = 0
GRAPHRAG_MAX_CHUNK_OVERLAP = 5000
GRAPHRAG_MIN_MAX_GLEANINGS = 0
GRAPHRAG_MAX_MAX_GLEANINGS = 10
GRAPHRAG_MIN_MAX_CLUSTER_SIZE = 1
GRAPHRAG_MAX_MAX_CLUSTER_SIZE = 100
