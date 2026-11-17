# Couchbase FTS Vector Search Tool
#
# `connection_string`, `username` and `password` are NOT function parameters:
# args_schema.json declares them with "input_type": "user_input", so they are
# set in the tool configuration and the sandbox injects them as module-level
# globals -- the agent never sees them.
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

from epicstaff_common import require_setting, safe_error_message


def embed(text: str) -> List[float]:
    """
    Replace this with your real embedding implementation.
    Must return List[float].
    """
    raise NotImplementedError("Embedding function must be implemented externally")


def main(
    query: str,
    bucket_name: str,
    scope_name: str,
    collection_name: str,
    index_name: str,
    embedding_key: str = "embedding",
    limit: int = 3,
    scoped_index: bool = True,
    **kwargs,
) -> str:
    try:
        authenticator = PasswordAuthenticator(
            require_setting(globals(), "username"),
            require_setting(globals(), "password"),
        )
        cluster = Cluster(require_setting(globals(), "connection_string"), authenticator)

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

    except Exception as error:
        return f"Search failed with error: {safe_error_message(error)}"
