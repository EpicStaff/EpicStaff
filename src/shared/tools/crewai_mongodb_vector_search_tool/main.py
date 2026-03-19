import sys
from logging import getLogger
from typing import Any, List

try:
    import pymongo
    from pymongo import MongoClient
    from pymongo.driver_info import DriverInfo
except ImportError:
    raise ImportError("pymongo is required. Install via `pip install pymongo`.")

try:
    from openai import Client
except ImportError:
    raise ImportError("openai is required. Install via `pip install openai`.")

logger = getLogger(__name__)

class MongoDBVectorSearchTool:
    """Standalone MongoDB vector search tool."""

    def __init__(
        self,
        query: str,
        openai_api_key: str,
        connection_string: str,
        database_name: str,
        collection_name: str,
        vector_index_name: str = "vector_index",
        text_key: str = "text",
        embedding_key: str = "embedding",
        dimensions: int = 1536,
        embedding_model: str = "text-embedding-3-large",
        limit: int = 4,
        oversampling_factor: int = 10,
        include_embeddings: bool = False,
    ):
        self.query = query
        self.connection_string = connection_string
        self.database_name = database_name
        self.collection_name = collection_name
        self.vector_index_name = vector_index_name
        self.text_key = text_key
        self.embedding_key = embedding_key
        self.dimensions = dimensions
        self.embedding_model = embedding_model
        self.limit = limit
        self.oversampling_factor = oversampling_factor
        self.include_embeddings = include_embeddings

        # OpenAI client using API key from args
        self._openai_client = Client(api_key=openai_api_key)

        # MongoDB client
        self._client = MongoClient(
            self.connection_string,
            driver=DriverInfo(name="StandaloneMongoDBVectorTool", version="1.0"),
        )
        self._coll = self._client[self.database_name][self.collection_name]

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [
            item.embedding
            for item in self._openai_client.embeddings.create(
                input=texts,
                model=self.embedding_model,
                dimensions=self.dimensions,
            ).data
        ]

    def run(self) -> str:
        from bson import json_util
        try:
            query_vector = self._embed_texts([self.query])[0]
            stage = {
                "index": self.vector_index_name,
                "path": self.embedding_key,
                "queryVector": query_vector,
                "numCandidates": self.limit * self.oversampling_factor,
                "limit": self.limit,
            }

            pipeline = [
                {"$vectorSearch": stage},
                {"$set": {"score": {"$meta": "vectorSearchScore"}}},
            ]
            if not self.include_embeddings:
                pipeline.append({"$project": {self.embedding_key: 0}})

            cursor = self._coll.aggregate(pipeline)
            return json_util.dumps(list(cursor))
        except Exception as e:
            logger.error(f"Error in vector search: {e}")
            return ""

def main(
    query: str,
    openai_api_key: str,
    connection_string: str,
    database_name: str,
    collection_name: str,
    vector_index_name: str = "vector_index",
    text_key: str = "text",
    embedding_key: str = "embedding",
    dimensions: int = 1536,
    embedding_model: str = "text-embedding-3-large",
    limit: int = 4,
    oversampling_factor: int = 10,
    include_embeddings: bool = False,
):
    """Entrypoint for CLI execution with explicit parameters."""
    tool = MongoDBVectorSearchTool(
        query=query,
        openai_api_key=openai_api_key,
        connection_string=connection_string,
        database_name=database_name,
        collection_name=collection_name,
        vector_index_name=vector_index_name,
        text_key=text_key,
        embedding_key=embedding_key,
        dimensions=dimensions,
        embedding_model=embedding_model,
        limit=limit,
        oversampling_factor=oversampling_factor,
        include_embeddings=include_embeddings,
    )
    result = tool.run()
    print(result)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MongoDB Vector Search Tool")
    parser.add_argument("--query", required=True, help="Query to search in MongoDB")
    parser.add_argument("--openai_api_key", required=True, help="OpenAI API Key")
    parser.add_argument("--connection_string", required=True, help="MongoDB connection string")
    parser.add_argument("--database_name", required=True, help="MongoDB database name")
    parser.add_argument("--collection_name", required=True, help="MongoDB collection name")
    parser.add_argument("--vector_index_name", default="vector_index", help="Vector index name")
    parser.add_argument("--text_key", default="text", help="Field name for document text")
    parser.add_argument("--embedding_key", default="embedding", help="Field name for embeddings")
    parser.add_argument("--dimensions", type=int, default=1536, help="Embedding dimensions")
    parser.add_argument("--embedding_model", default="text-embedding-3-large", help="OpenAI embedding model")
    parser.add_argument("--limit", type=int, default=4, help="Number of documents to return")
    parser.add_argument("--oversampling_factor", type=int, default=10, help="Oversampling factor")
    parser.add_argument("--include_embeddings", action="store_true", help="Include embeddings in results")

    args = parser.parse_args()
    main(**vars(args))