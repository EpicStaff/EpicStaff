import pandas
from application.commands import GetMetrics
from application.orchestrators.metrics.base import AbstractMetricsOrchestrator
from application.results import MetricsResult
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag.data_model import DataReader
from graphrag_storage import create_storage
from graphrag_storage.tables.table_provider_factory import create_table_provider


class GraphMetricsOrchestrator(AbstractMetricsOrchestrator):
    async def on_execute(self, command: GetMetrics) -> MetricsResult:
        async with self.uow:
            config = await self.uow.graph_rag_repo.get_config(command.rag_id)
        text_units = await self._read_text_units(config)
        if text_units.empty:
            return MetricsResult(total_chunks=0, avg_chunk_size=0.0)
        return MetricsResult(
            total_chunks=len(text_units),
            avg_chunk_size=float(text_units["n_tokens"].dropna().mean() or 0.0),
        )

    @staticmethod
    async def _read_text_units(config: GraphRagConfig) -> pandas.DataFrame:
        storage = create_storage(config.output_storage)
        table_provider = create_table_provider(config.table_provider, storage)
        reader = DataReader(table_provider)
        return await reader.text_units()
