from tables.models.knowledge_models import DocumentMetadata

ALLOWED_FILE_TYPES = {choice[0] for choice in DocumentMetadata.DocumentFileType.choices}


# Content types for inline document preview (Content-Disposition: inline)
PREVIEW_CONTENT_TYPES = {
    DocumentMetadata.DocumentFileType.PDF: "application/pdf",
    DocumentMetadata.DocumentFileType.CSV: "text/csv; charset=utf-8",
    DocumentMetadata.DocumentFileType.DOCX: (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    DocumentMetadata.DocumentFileType.TXT: "text/plain; charset=utf-8",
    DocumentMetadata.DocumentFileType.JSON: "application/json; charset=utf-8",
    DocumentMetadata.DocumentFileType.HTML: "text/html; charset=utf-8",
    DocumentMetadata.DocumentFileType.MD: "text/markdown; charset=utf-8",
}


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
MAX_TOKEN_FIELD_VALUE = 2_000_000

# Search config bounds, shared by surface knowledge and collection-level search configs.
MIN_TOKEN_FIELD_VALUE = 100
MIN_OPTIONAL_TOKEN_FIELD_VALUE = 1
SEARCH_PROMPT_MAX_LENGTH = 10_000
SEARCH_LIMIT_MIN = 1
SEARCH_LIMIT_MAX = 1000
SIMILARITY_THRESHOLD_MIN = 0
SIMILARITY_THRESHOLD_MAX = 1
PROPORTION_MIN = 0.0
PROPORTION_MAX = 1.0
TOP_K_MIN = 1
TOP_K_MAX = 100
TOP_P_MIN = 0.0
TOP_P_MAX = 1.0
DRIFT_K_FOLLOWUPS_MIN = 1
DRIFT_K_FOLLOWUPS_MAX = 100
PRIMER_FOLDS_MIN = 1
PRIMER_FOLDS_MAX = 100
CONVERSATION_HISTORY_MAX_TURNS_MIN = 1
CONVERSATION_HISTORY_MAX_TURNS_MAX = 50
RESPONSE_MAX_LENGTH_MIN = 1
RESPONSE_MAX_LENGTH_MAX = 10_000
DYNAMIC_SEARCH_THRESHOLD_MIN = 0
DYNAMIC_SEARCH_THRESHOLD_MAX = 5
DYNAMIC_SEARCH_NUM_REPEATS_MIN = 1
DYNAMIC_SEARCH_NUM_REPEATS_MAX = 5
COMMUNITY_LEVEL_MIN = 0
COMMUNITY_LEVEL_MAX = 10
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0
DRIFT_CONCURRENCY_MIN = 1
DRIFT_CONCURRENCY_MAX = 256
DRIFT_N_DEPTH_MIN = 1
DRIFT_N_DEPTH_MAX = 10
LOCAL_SEARCH_N_MIN = 1
LOCAL_SEARCH_N_MAX = 10
