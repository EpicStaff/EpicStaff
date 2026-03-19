import json
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
import openai


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
    qdrant_url: str,
    openai_api_key: str,
    qdrant_api_key: Optional[str] = None,
    filter_by: Optional[str] = None,
    filter_value: Optional[str] = None,
    limit: int = 3,
    score_threshold: float = 0.35,
    embedding_model: str = "text-embedding-3-large",
) -> str:
    """
    Perform vector similarity search in Qdrant using OpenAI embeddings.

    Returns:
        str: JSON string with search results.
    """

    client = QdrantClient(
        url=qdrant_url,
        api_key=qdrant_api_key if qdrant_api_key else None,
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