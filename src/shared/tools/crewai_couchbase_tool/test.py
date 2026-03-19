from main import main
from typing import List

# Dummy embedding function for testing
def embed(text: str) -> List[float]:
    # Returns a fixed-size dummy vector
    return [0.1] * 128

# Monkey-patch the embed function in main.py
import main
main.embed = embed

if __name__ == "__main__":
    result = main.main(
        query="Find relevant documents about AI",
        connection_string="couchbase://localhost",
        username="Administrator",
        password="password",
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