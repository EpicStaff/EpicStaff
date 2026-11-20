import asyncio

import pandas
import pyarrow
from application.commands import (
    GetEntityDetail,
    GetGraphVisualization,
    GetRelationshipDetail,
)
from application.orchestrators.graph_output import open_graph_output_storage, read_output_table
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
from domain.enums import GraphOutputTableEnum
from domain.errors import EntityNotFoundError, GraphNotIndexedError, RelationshipNotFoundError
from graphrag_storage import Storage
from loguru import logger

_ENTITY_COLUMNS = ["id", "title", "type", "degree"]
_RELATIONSHIP_COLUMNS = ["id", "source", "target", "weight"]
_COMMUNITY_COLUMNS = ["community", "level", "entity_ids"]
_DETAIL_COLUMNS = ["id", "description"]


async def _read_index_table(
    storage: Storage, table_name: str, columns: list[str], rag_id: int
) -> pandas.DataFrame:
    """Return `columns` of an index output table, every column present.

    Raises:
        GraphNotIndexedError: The index run has not written this table.
    """
    return _require_table(await read_output_table(storage, table_name, columns), columns, rag_id)


def _require_table(
    dataframe: pandas.DataFrame | None, columns: list[str], rag_id: int
) -> pandas.DataFrame:
    if dataframe is None:
        raise GraphNotIndexedError(rag_id=rag_id)
    return dataframe.reindex(columns=columns)


async def _read_communities(storage: Storage, rag_id: int) -> pandas.DataFrame:
    """Return the communities table, or an empty one when it cannot be used.

    Communities only group the graph: without them the entities are still drawable, so
    an absent, unreadable or incomplete table means "no communities", not an error.
    """
    try:
        communities = await read_output_table(
            storage, GraphOutputTableEnum.COMMUNITIES, _COMMUNITY_COLUMNS
        )
    except pyarrow.ArrowInvalid as error:
        # A first index run and an update run rewrite the active slot's files in place
        # (graphrag's file storage truncates, then writes), so a concurrent read can
        # see a torn file. The next request reads it whole.
        logger.warning(
            "Ignoring unreadable communities table of RAG(id={}): {}", rag_id, str(error)
        )
        communities = None
    if communities is None or set(_COMMUNITY_COLUMNS) - set(communities.columns):
        return pandas.DataFrame(columns=_COMMUNITY_COLUMNS)
    return communities


def _matching_descriptions(dataframe: pandas.DataFrame, record_id: str) -> list[object]:
    """Return the description of the first row whose id is `record_id`; empty if none."""
    matched = dataframe.loc[dataframe["id"].astype(str) == record_id, "description"]
    return matched.head(1).tolist()


def _description_text(description: object) -> str | None:
    return str(description) if pandas.notna(description) else None


def _keep_search_matches(
    entities: pandas.DataFrame,
    relationships: pandas.DataFrame,
    search: str,
) -> tuple[pandas.DataFrame, pandas.DataFrame]:
    """Keep entities whose title contains `search` as plain text, plus their direct neighbours.

    The kept entities' `matches_search` column marks the ones that matched themselves.
    """
    # The "string" dtype keeps a missing title missing (na=False) instead of the text "nan".
    matched_mask = (
        entities["title"].astype("string").str.contains(search, case=False, regex=False, na=False)
    )
    entities = entities.assign(matches_search=matched_mask)
    matched_titles = set(entities.loc[matched_mask, "title"])

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


def _keep_top_entities(
    entities: pandas.DataFrame,
    relationships: pandas.DataFrame,
    max_entities: int,
) -> tuple[pandas.DataFrame, pandas.DataFrame]:
    """Keep `max_entities` entities and the relationships between them.

    Search matches rank ahead of their neighbours, so the cap never drops a match in
    favour of a better-connected neighbour; within each group the highest degree wins.
    """
    # A multi-column sort_values is a stable lexsort, so ties keep the file order.
    entities = entities.sort_values(["matches_search", "degree"], ascending=False).head(
        max_entities
    )
    kept_titles = set(entities["title"])
    relationships = relationships[
        relationships["source"].isin(kept_titles) & relationships["target"].isin(kept_titles)
    ]
    return entities, relationships


def _community_ids_by_entity(
    communities: pandas.DataFrame, entity_ids: set[str]
) -> dict[str, list[str]]:
    """Map each of `entity_ids` that is in a community to its community ids, top level first.

    graphrag's entities table has no community column: membership is the `entity_ids`
    list on each communities row. Level 0 is the coarsest Leiden level, so sorting by
    level puts the top-level community first. An entity in no community is absent.
    """
    # explode unpacks the numpy arrays parquet list columns decode to, and turns an
    # empty or missing list into NaN, which the isin filter drops.
    memberships = communities.explode("entity_ids")
    memberships = memberships[memberships["entity_ids"].isin(entity_ids)]
    # A null community id would otherwise reach the response as the text "nan", and
    # a column holding one decodes as float: the int cast keeps "10" from being "10.0".
    memberships = memberships.dropna(subset=["community"])
    memberships = memberships.sort_values(["level", "community"])
    return (
        memberships["community"]
        .astype("int64")
        .astype(str)
        .groupby(memberships["entity_ids"], sort=False)
        .agg(list)
        .to_dict()
    )


def _build_visualization(
    entities: pandas.DataFrame,
    relationships: pandas.DataFrame,
    communities: pandas.DataFrame,
    search: str | None,
    max_entities: int,
) -> GraphVisualizationResult:
    total_entities = len(entities)
    total_relationships = len(relationships)

    # Without a search every entity counts as a match, so only degree decides the cap.
    entities = entities.assign(degree=entities["degree"].fillna(0).astype(int), matches_search=True)
    relationships = relationships.assign(weight=relationships["weight"].fillna(1.0).astype(float))

    if search:
        entities, relationships = _keep_search_matches(entities, relationships, search)
    entities, relationships = _keep_top_entities(entities, relationships, max_entities)
    # Mapped after the cap, so only the entities in the response are grouped.
    community_ids = _community_ids_by_entity(communities, set(entities["id"].astype(str)))

    return GraphVisualizationResult(
        entities=[
            VisualizationEntity(
                id=str(record["id"]),
                title=str(record["title"]),
                type=record["type"] if pandas.notna(record["type"]) else None,
                degree=record["degree"],
                community_ids=community_ids.get(str(record["id"]), []),
            )
            for record in entities.to_dict("records")
        ],
        relationships=[
            VisualizationRelationship(
                id=str(record["id"]),
                source=str(record["source"]),
                target=str(record["target"]),
                weight=record["weight"],
            )
            for record in relationships.to_dict("records")
        ],
        total_entities=total_entities,
        total_relationships=total_relationships,
    )


class GraphVisualizationOrchestrator(AbstractGraphVisualizationOrchestrator):
    async def on_execute(self, command: GetGraphVisualization) -> GraphVisualizationResult:
        storage = await open_graph_output_storage(self.uow, command.rag_id)
        # A TaskGroup cancels the other downloads as soon as one fails. Missing tables
        # are judged after it, so GraphNotIndexedError is not wrapped in an ExceptionGroup.
        async with asyncio.TaskGroup() as task_group:
            entities_task = task_group.create_task(
                read_output_table(storage, GraphOutputTableEnum.ENTITIES, _ENTITY_COLUMNS)
            )
            relationships_task = task_group.create_task(
                read_output_table(
                    storage, GraphOutputTableEnum.RELATIONSHIPS, _RELATIONSHIP_COLUMNS
                )
            )
            communities_task = task_group.create_task(_read_communities(storage, command.rag_id))
        entities = _require_table(entities_task.result(), _ENTITY_COLUMNS, command.rag_id)
        relationships = _require_table(
            relationships_task.result(), _RELATIONSHIP_COLUMNS, command.rag_id
        )

        if entities.empty:
            raise GraphNotIndexedError(rag_id=command.rag_id)

        return await asyncio.to_thread(
            _build_visualization,
            entities,
            relationships,
            communities_task.result(),
            command.search,
            command.max_entities,
        )


class EntityDetailOrchestrator(AbstractEntityDetailOrchestrator):
    """Look up a single entity's description from the graph index output."""

    async def on_execute(self, command: GetEntityDetail) -> EntityDetailResult:
        storage = await open_graph_output_storage(self.uow, command.rag_id)
        entities = await _read_index_table(
            storage, GraphOutputTableEnum.ENTITIES, _DETAIL_COLUMNS, command.rag_id
        )

        descriptions = await asyncio.to_thread(_matching_descriptions, entities, command.entity_id)
        if not descriptions:
            raise EntityNotFoundError(entity_id=command.entity_id, rag_id=command.rag_id)
        return EntityDetailResult(description=_description_text(descriptions[0]))


class RelationshipDetailOrchestrator(AbstractRelationshipDetailOrchestrator):
    """Look up a single relationship's description from the graph index output."""

    async def on_execute(self, command: GetRelationshipDetail) -> RelationshipDetailResult:
        storage = await open_graph_output_storage(self.uow, command.rag_id)
        relationships = await _read_index_table(
            storage, GraphOutputTableEnum.RELATIONSHIPS, _DETAIL_COLUMNS, command.rag_id
        )

        descriptions = await asyncio.to_thread(
            _matching_descriptions, relationships, command.relationship_id
        )
        if not descriptions:
            raise RelationshipNotFoundError(
                relationship_id=command.relationship_id, rag_id=command.rag_id
            )
        return RelationshipDetailResult(description=_description_text(descriptions[0]))
