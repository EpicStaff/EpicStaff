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
            community_ids = row.get("community_ids")
            if community_ids is None or (isinstance(community_ids, float) and pandas.isna(community_ids)):
                community_ids = []
            result.append(
                VisualizationEntity(
                    id=str(row["id"]),
                    title=str(row["title"]),
                    type=row.get("type") if pandas.notna(row.get("type")) else None,
                    description=(
                        str(row["description"]) if pandas.notna(row.get("description")) else None
                    ),
                    degree=int(row.get("degree", 0)),
                    community_ids=[str(cid) for cid in community_ids] if community_ids else [],
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
            entity_ids = row.get("entity_ids")
            if entity_ids is None or (isinstance(entity_ids, float) and pandas.isna(entity_ids)):
                entity_ids = []
            result.append(
                VisualizationCommunity(
                    id=str(row["id"]),
                    title=str(row["title"]),
                    level=int(row["level"]),
                    size=int(row.get("size", 0)),
                    entity_ids=[str(eid) for eid in entity_ids] if entity_ids else [],
                )
            )
        return result
