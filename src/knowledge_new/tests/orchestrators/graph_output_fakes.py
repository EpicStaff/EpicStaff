"""A unit of work whose graph RAG output storage is a real directory of parquet files.

The orchestrators read index tables through graphrag's storage; pointing that at a
temporary directory exercises the real download, decoding and filtering. Only the
database lookup is faked.
"""

from pathlib import Path

import pandas
from domain.models import GraphPricingConfig
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag_llm.config import ModelConfig
from graphrag_storage import StorageConfig


class FakeGraphRagRepo:
    def __init__(
        self,
        output_directory: Path | None,
        pricing_config: GraphPricingConfig | None = None,
    ):
        # None plays a RAG id with no graph RAG row.
        self._output_directory = output_directory
        self.pricing_config = pricing_config
        self.requested_rag_ids: list[int] = []

    async def get_output_storage_config(self, rag_id: int) -> StorageConfig | None:
        self.requested_rag_ids.append(rag_id)
        if self._output_directory is None:
            return None
        return StorageConfig(type="file", base_dir=str(self._output_directory))

    async def get_config(self, rag_id: int) -> GraphRagConfig | None:
        """A config with stub models whose output storage is the temporary directory."""
        self.requested_rag_ids.append(rag_id)
        if self._output_directory is None:
            return None
        stub_model = ModelConfig(model_provider="openai", model="gpt-4o", api_key="stub-key")
        config = GraphRagConfig(
            output_storage=StorageConfig(type="file", base_dir=str(self._output_directory))
        )
        config.embedding_models["default_embedding_model"] = stub_model.model_copy()
        config.completion_models["default_completion_model"] = stub_model.model_copy()
        return config

    async def get_pricing_config(self, rag_id: int) -> GraphPricingConfig | None:
        return self.pricing_config


class FakeUoW:
    def __init__(self, repo: FakeGraphRagRepo):
        self.graph_rag_repo = repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def write_table(output_directory: Path, table_name: str, dataframe: pandas.DataFrame) -> None:
    """Write `dataframe` the way the indexer does: `<table_name>.parquet` in the output dir."""
    dataframe.to_parquet(output_directory / f"{table_name}.parquet")
