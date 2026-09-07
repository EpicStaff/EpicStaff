from .collection_models import (
    SourceCollection,
    DocumentMetadata,
    DocumentContent,
    BaseRagType,
)

from .naive_rag_models import (
    NaiveRag,
    NaiveRagDocumentConfig,
    NaiveRagChunk,
    NaiveRagEmbedding,
    AgentNaiveRag,
    NaiveRagSearchConfig,
    KnowledgeNodeNaiveRagSearchConfig,
    NaiveRagPreviewChunk,
)

from .graphrag_models import (
    GraphRag,
    AgentGraphRag,
    GraphRagDocument,
    GraphRagInputFileType,
    GraphRagChunkStrategyType,
    GraphRagIndexConfig,
    GraphRagBasicSearchConfig,
    KnowledgeNodeGraphRagBasicSearchConfig,
    KnowledgeNodeGraphRagLocalSearchConfig,
    GraphRagLocalSearchConfig,
)

KNOWLEDGE_NODE_SEARCH_CONFIG_MODELS = {
    "naive_search_config": KnowledgeNodeNaiveRagSearchConfig,
    "graph_basic_search_config": KnowledgeNodeGraphRagBasicSearchConfig,
    "graph_local_search_config": KnowledgeNodeGraphRagLocalSearchConfig,
}

__all__ = [
    # Collection models
    "SourceCollection",
    "DocumentMetadata",
    "DocumentContent",
    "BaseRagType",
    # Naive RAG models
    "NaiveRag",
    "NaiveRagDocumentConfig",
    "NaiveRagChunk",
    "NaiveRagEmbedding",
    "AgentNaiveRag",
    "NaiveRagSearchConfig",
    "KnowledgeNodeNaiveRagSearchConfig",
    "NaiveRagPreviewChunk",
    # Graph RAG models
    "GraphRag",
    "AgentGraphRag",
    "GraphRagDocument",
    "GraphRagInputFileType",
    "GraphRagChunkStrategyType",
    "GraphRagIndexConfig",
    "GraphRagBasicSearchConfig",
    "GraphRagLocalSearchConfig",
    "KnowledgeNodeGraphRagLocalSearchConfig",
    "KnowledgeNodeGraphRagBasicSearchConfig",
    "KNOWLEDGE_NODE_SEARCH_CONFIG_MODELS",
]
