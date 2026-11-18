from typing import List

import main

# Dummy embedding function for testing
def embed(text: str) -> List[float]:
    # Returns a fixed-size dummy vector
    return [0.1] * 128

# Monkey-patch the embed function in main.py
main.embed = embed

if __name__ == "__main__":
    # The sandbox injects tool configuration values as module globals.
    main.connection_string = "couchbase://localhost"
    main.username = "Administrator"
    main.password = "password"

    result = main.main(
        query="Find relevant documents about AI",
        bucket_name="my_bucket",
        scope_name="my_scope",
        collection_name="my_collection",
        index_name="my_index",
        embedding_key="embedding",
        limit=3,
        scoped_index=True
    )

    print("Search Results:")
    print(result)
