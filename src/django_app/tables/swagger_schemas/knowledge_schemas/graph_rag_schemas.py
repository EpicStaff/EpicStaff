from drf_spectacular.utils import OpenApiResponse
from tables.clients.errors import KnowledgeGraphNotIndexedError

# Upstream errors reach the browser through utils/exception_handler.py as
# {status_code, code, message}.
GRAPH_INDEX_READ_RESPONSES = {
    200: OpenApiResponse(description="Data read from the graph index output"),
    400: OpenApiResponse(description="Invalid query parameter or unsupported table"),
    404: OpenApiResponse(description="GraphRag, entity or relationship not found"),
    409: OpenApiResponse(
        description=(
            f"code={KnowledgeGraphNotIndexedError.code}: the graph has not been indexed yet"
        )
    ),
    502: OpenApiResponse(description="knowledge_new failed"),
    503: OpenApiResponse(description="knowledge_new unreachable"),
    504: OpenApiResponse(description="knowledge_new timed out"),
}
