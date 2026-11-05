# Qdrant Vector Search Tool
#
# `qdrant_url`, `qdrant_api_key` and `openai_api_key` are NOT function
# parameters: args_schema.json declares them with "input_type": "user_input",
# so they are set in the tool configuration and the sandbox injects them as
# module-level globals -- the agent never sees them.
import json
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
import openai
from epicstaff_common import require_setting, resolve_setting, safe_error_message


def _vectorize_query(query: str, api_key: str, model: str) -> list[float]:
    client = openai.Client(api_key=api_key)
    embedding = (
        client.embeddings.create(
            input=[query],
            model=model,
        )
        .data[0]
        .embedding
    )
    return embedding


def main(
    query: str,
    collection_name: str,
    filter_by: Optional[str] = None,
    filter_value: Optional[str] = None,
    limit: int = 3,
    score_threshold: float = 0.35,
    embedding_model: str = "text-embedding-3-large",
    **kwargs,
) -> str:
    """
    Perform vector similarity search in Qdrant using OpenAI embeddings.

    Returns:
        str: JSON string with search results, or an error message.
    """
    try:
        qdrant_url = require_setting(globals(), "qdrant_url")
        openai_api_key = require_setting(globals(), "openai_api_key")

        client = QdrantClient(
            url=qdrant_url,
            api_key=resolve_setting(globals(), "qdrant_api_key"),
        )

        search_filter = None
        if filter_by and filter_value:
            search_filter = Filter(
                must=[
                    FieldCondition(
                        key=filter_by,
                        match=MatchValue(value=filter_value),
                    )
                ]
            )

        query_vector = _vectorize_query(
            query=query,
            api_key=openai_api_key,
            model=embedding_model,
        )

        search_results = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=search_filter,
            limit=limit,
            score_threshold=score_threshold,
        )

        results = []
        for point in search_results:
            payload = point[1][0].payload
            results.append(
                {
                    "metadata": payload.get("metadata", {}),
                    "context": payload.get("text", ""),
                    "score": point[1][0].score,
                }
            )

        return json.dumps(results, indent=2)
    except Exception as error:
        return f"Error executing tool: {safe_error_message(error)}"
