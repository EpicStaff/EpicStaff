import lancedb
from settings import settings
from graphrag_vectors import register_vector_store
from graphrag_vectors.lancedb import LanceDBVectorStore
from graphrag_vectors.vector_store_config import VectorStoreConfig


def create_vector_store_config(
    rag_id: int,
    vector_size: int = 1536,
    type: str = "minio_lancedb",
    host: str = settings.MINIO_HOST,
    bucket: str = settings.MINIO_BUCKET,
    access_key: str = settings.MINIO_ACCESS_KEY,
    secret_key: str = settings.MINIO_SECRET_KEY,
) -> VectorStoreConfig:
    return VectorStoreConfig(
        type=type,
        vector_size=vector_size,
        db_uri=f"s3://{bucket}/graphrag/rag_{rag_id}/lancedb",
        host=host,
        access_key=access_key,
        secret_key=secret_key,
    )


def _build_storage_options(
    host: str,
    access_key: str | None,
    secret_key: str | None,
) -> dict[str, str]:
    secure = host.startswith("https")
    return {
        "aws_access_key_id": access_key or "",
        "aws_secret_access_key": secret_key or "",
        "aws_endpoint": host,
        "allow_http": "false" if secure else "true",
    }


class MinioLanceDBVectorStore(LanceDBVectorStore):
    def __init__(
        self,
        *,
        host: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        storage_options: dict[str, str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        if storage_options is None and host is not None:
            storage_options = _build_storage_options(host, access_key, secret_key)
        self._storage_options = storage_options

    def connect(self) -> None:
        self.db_connection = lancedb.connect(self.db_uri, storage_options=self._storage_options)
        if self.index_name and self.index_name in self.db_connection.table_names():
            self.document_collection = self.db_connection.open_table(self.index_name)


register_vector_store("minio_lancedb", MinioLanceDBVectorStore)
