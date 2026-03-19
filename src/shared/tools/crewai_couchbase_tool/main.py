import json
from typing import List

try:
    import couchbase.search as search
    from couchbase.cluster import Cluster
    from couchbase.options import SearchOptions
    from couchbase.auth import PasswordAuthenticator
    from couchbase.vector_search import VectorQuery, VectorSearch
except ImportError as e:
    raise ImportError(
        "couchbase package is required. Install it with: pip install couchbase"
    ) from e


def embed(text: str) -> List[float]:
    """
    Replace this with your real embedding implementation.
    Must return List[float].
    """
    raise NotImplementedError("Embedding function must be implemented externally")


def main(
    query: str,
    connection_string: str,
    username: str,
    password: str,
    bucket_name: str,
    scope_name: str,
    collection_name: str,
    index_name: str,
    embedding_key: str = "embedding",
    limit: int = 3,
    scoped_index: bool = True,
) -> str:
    authenticator = PasswordAuthenticator(username, password)
    cluster = Cluster(connection_string, authenticator)

    bucket = cluster.bucket(bucket_name)
    scope = bucket.scope(scope_name)

    query_embedding = embed(query)

    search_request = search.SearchRequest.create(
        VectorSearch.from_vector_query(
            VectorQuery(
                embedding_key,
                query_embedding,
                limit,
            )
        )
    )

    try:
        if scoped_index:
            result = scope.search(
                index_name,
                search_request,
                SearchOptions(limit=limit, fields=["*"]),
            )
        else:
            result = cluster.search(
                index_name,
                search_request,
                SearchOptions(limit=limit, fields=["*"]),
            )

        rows = []
        for row in result.rows():
            rows.append(row.fields)

        return json.dumps(rows, indent=2)

    except Exception as e:
        return f"Search failed with error: {e}"