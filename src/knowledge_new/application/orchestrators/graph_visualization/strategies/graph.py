from collections.abc import Sized

import numpy
import pandas
from application.commands import GetGraphVisualization
from application.orchestrators.graph_visualization.base import AbstractGraphVisualizationOrchestrator
from application.results import (
    GraphVisualizationResult,
    VisualizationCommunity,
    VisualizationEntity,
    VisualizationRelationship,
)
from domain.errors import GraphNotIndexedError
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag.data_model import DataReader
from graphrag_storage import create_storage
from graphrag_storage.tables.table_provider_factory import create_table_provider


def _to_str_list(value: object) -> list[str]:
    """Safely convert a parquet list column value to a list of strings.

    Parquet list columns may arrive as numpy arrays, Python lists, None, or
    scalar NaN — bare truthiness checks on numpy arrays raise ValueError.
    """
    if value is None:
        return []
    if isinstance(value, float) and pandas.isna(value):
        return []
    if isinstance(value, numpy.ndarray):
        return [str(v) for v in value]
    if isinstance(value, Sized):
        return [str(v) for v in value]
    return []


class GraphVisualizationOrchestrator(AbstractGraphVisualizationOrchestrator):
    async def on_execute(self, command: GetGraphVisualization) -> GraphVisualizationResult:
        async with self.uow:
            config = await self.uow.graph_rag_repo.get_config(command.rag_id)

        entities, relationships, communities = await self._read_graph_data(
            config, command.rag_id
        )

        if entities.empty:
            raise GraphNotIndexedError(rag_id=command.rag_id)

        if command.max_entities is not None:
            entities, relationships = self._apply_entity_limit(
                entities, relationships, command.max_entities
            )

        return GraphVisualizationResult(
            entities=self._build_entities(entities),
            relationships=self._build_relationships(relationships),
            communities=self._build_communities(communities),
        )

    @staticmethod
    async def _read_graph_data(
        config: GraphRagConfig,
        rag_id: int,
    ) -> tuple[pandas.DataFrame, pandas.DataFrame, pandas.DataFrame]:
        """Read entities, relationships and communities from the graph index output."""
        storage = create_storage(config.output_storage)
        table_provider = create_table_provider(config.table_provider, storage)
        reader = DataReader(table_provider)
        try:
            entities = await reader.entities()
            relationships = await reader.relationships()
            communities = await reader.communities()
        except (ValueError, FileNotFoundError) as error:
            raise GraphNotIndexedError(rag_id=rag_id) from error
        return entities, relationships, communities

    @staticmethod
    def _apply_entity_limit(
        entities: pandas.DataFrame,
        relationships: pandas.DataFrame,
        max_entities: int,
    ) -> tuple[pandas.DataFrame, pandas.DataFrame]:
        """Keep the top-N entities by degree and filter relationships to match."""
        if "degree" in entities.columns:
            entities = entities.sort_values("degree", ascending=False)
        entities = entities.head(max_entities)
        kept_titles = set(entities["title"])
        relationships = relationships[
            relationships["source"].isin(kept_titles) & relationships["target"].isin(kept_titles)
        ]
        return entities, relationships

    @staticmethod
    def _build_entities(dataframe: pandas.DataFrame) -> list[VisualizationEntity]:
        """Convert the entities DataFrame to result objects."""
        result = []
        for _, row in dataframe.iterrows():
            community_ids = _to_str_list(row.get("community_ids"))
            result.append(
                VisualizationEntity(
                    id=str(row["id"]),
                    title=str(row["title"]),
                    type=row.get("type") if pandas.notna(row.get("type")) else None,
                    description=(
                        str(row["description"]) if pandas.notna(row.get("description")) else None
                    ),
                    degree=int(row.get("degree", 0)),
                    community_ids=community_ids,
                )
            )
        return result

    @staticmethod
    def _build_relationships(dataframe: pandas.DataFrame) -> list[VisualizationRelationship]:
        """Convert the relationships DataFrame to result objects."""
        result = []
        for _, row in dataframe.iterrows():
            result.append(
                VisualizationRelationship(
                    id=str(row["id"]),
                    source=str(row["source"]),
                    target=str(row["target"]),
                    description=(
                        str(row["description"]) if pandas.notna(row.get("description")) else None
                    ),
                    weight=float(row.get("weight", 1.0)),
                )
            )
        return result

    @staticmethod
    def _build_communities(dataframe: pandas.DataFrame) -> list[VisualizationCommunity]:
        """Convert the communities DataFrame to result objects."""
        result = []
        for _, row in dataframe.iterrows():
            entity_ids = _to_str_list(row.get("entity_ids"))
            result.append(
                VisualizationCommunity(
                    id=str(row["id"]),
                    title=str(row["title"]),
                    level=int(row["level"]),
                    size=int(row.get("size", 0)),
                    entity_ids=entity_ids,
                )
            )
        return result
