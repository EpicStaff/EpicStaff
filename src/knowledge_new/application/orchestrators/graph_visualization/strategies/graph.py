from collections.abc import Sized

import numpy
import pandas
from application.commands import (
    GetEntityDetail,
    GetGraphVisualization,
    GetRelationshipDetail,
)
from application.orchestrators.graph_visualization.base import (
    AbstractEntityDetailOrchestrator,
    AbstractGraphVisualizationOrchestrator,
    AbstractRelationshipDetailOrchestrator,
)
from application.results import (
    EntityDetailResult,
    GraphVisualizationResult,
    RelationshipDetailResult,
    VisualizationEntity,
    VisualizationRelationship,
)
from domain.errors import EntityNotFoundError, GraphNotIndexedError, RelationshipNotFoundError
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

        entities, relationships = await self._read_graph_data(config, command.rag_id)

        if entities.empty:
            raise GraphNotIndexedError(rag_id=command.rag_id)

        total_entities = len(entities)
        total_relationships = len(relationships)

        if command.search:
            entities, relationships = self._apply_search_filter(
                entities, relationships, command.search
            )

        if command.max_entities is not None:
            entities, relationships = self._apply_entity_limit(
                entities, relationships, command.max_entities
            )

        return GraphVisualizationResult(
            entities=self._build_entities(entities),
            relationships=self._build_relationships(relationships),
            total_entities=total_entities,
            total_relationships=total_relationships,
        )

    @staticmethod
    async def _read_graph_data(
        config: GraphRagConfig,
        rag_id: int,
    ) -> tuple[pandas.DataFrame, pandas.DataFrame]:
        """Read entities and relationships from the graph index output."""
        storage = create_storage(config.output_storage)
        table_provider = create_table_provider(config.table_provider, storage)
        reader = DataReader(table_provider)
        try:
            entities = await reader.entities()
            relationships = await reader.relationships()
        except (ValueError, FileNotFoundError) as error:
            raise GraphNotIndexedError(rag_id=rag_id) from error
        return entities, relationships

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
    def _apply_search_filter(
        entities: pandas.DataFrame,
        relationships: pandas.DataFrame,
        search: str,
    ) -> tuple[pandas.DataFrame, pandas.DataFrame]:
        """Filter entities by title match and include their direct neighbours."""
        matched_mask = entities["title"].str.contains(search, case=False, na=False)
        matched_titles = set(entities.loc[matched_mask, "title"])

        # Find entities connected to the matched set via any relationship.
        connected_from_source = relationships.loc[
            relationships["source"].isin(matched_titles), "target"
        ]
        connected_from_target = relationships.loc[
            relationships["target"].isin(matched_titles), "source"
        ]
        all_titles = matched_titles | set(connected_from_source) | set(connected_from_target)

        entities = entities[entities["title"].isin(all_titles)]
        relationships = relationships[
            relationships["source"].isin(all_titles) & relationships["target"].isin(all_titles)
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
                    weight=float(row.get("weight", 1.0)),
                )
            )
        return result


class EntityDetailOrchestrator(AbstractEntityDetailOrchestrator):
    """Look up a single entity's description from the graph index output."""

    async def on_execute(self, command: GetEntityDetail) -> EntityDetailResult:
        async with self.uow:
            config = await self.uow.graph_rag_repo.get_config(command.rag_id)

        entities, _ = await GraphVisualizationOrchestrator._read_graph_data(
            config, command.rag_id
        )

        match = entities[entities["id"].astype(str) == command.entity_id]
        if match.empty:
            raise EntityNotFoundError(entity_id=command.entity_id, rag_id=command.rag_id)

        row = match.iloc[0]
        description = (
            str(row["description"]) if pandas.notna(row.get("description")) else None
        )
        return EntityDetailResult(description=description)


class RelationshipDetailOrchestrator(AbstractRelationshipDetailOrchestrator):
    """Look up a single relationship's description from the graph index output."""

    async def on_execute(self, command: GetRelationshipDetail) -> RelationshipDetailResult:
        async with self.uow:
            config = await self.uow.graph_rag_repo.get_config(command.rag_id)

        _, relationships = await GraphVisualizationOrchestrator._read_graph_data(
            config, command.rag_id
        )

        match = relationships[relationships["id"].astype(str) == command.relationship_id]
        if match.empty:
            raise RelationshipNotFoundError(
                relationship_id=command.relationship_id, rag_id=command.rag_id
            )

        row = match.iloc[0]
        description = (
            str(row["description"]) if pandas.notna(row.get("description")) else None
        )
        return RelationshipDetailResult(description=description)
