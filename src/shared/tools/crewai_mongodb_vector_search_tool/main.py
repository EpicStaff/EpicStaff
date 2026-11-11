# MongoDB Vector Search Tool
#
# `connection_string` and `openai_api_key` are NOT function parameters:
# args_schema.json declares them with "input_type": "user_input", so they are
# set in the tool configuration and the sandbox injects them as module-level
# globals -- the agent never sees them.
from logging import getLogger
from typing import List

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

from epicstaff_common import require_setting, safe_error_message

logger = getLogger(__name__)

class MongoDBVectorSearchTool:
    """Standalone MongoDB vector search tool."""

    def __init__(
        self,
        query: str,
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

        self._openai_client = Client(api_key=require_setting(globals(), "openai_api_key"))

        self._client = MongoClient(
            require_setting(globals(), "connection_string"),
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
        except Exception as error:
            message = f"Error in vector search: {safe_error_message(error)}"
            logger.error(message)
            return message

def main(
    query: str,
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
    **kwargs,
) -> str:
    try:
        tool = MongoDBVectorSearchTool(
            query=query,
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
        return tool.run()
    except Exception as error:
        return f"Error executing tool: {safe_error_message(error)}"
