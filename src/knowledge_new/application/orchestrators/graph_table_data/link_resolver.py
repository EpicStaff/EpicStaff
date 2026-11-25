"""Resolve the "linked to" relation between graph index tables.

Given a subject table (what the user is listing) and a picked row of another table,
produce a boolean mask over the subject rows: True where the row is linked, through
the graph index, to the picked row.

Edges are strict. Every supported pair resolves through a graph-meaningful column
(`relationships.source`/`target`, `communities.entity_ids`, `communities.parent`,
`text_units.document_ids`, ...). There is no shared-text_unit backbone: text_unit
co-mention produced results that looked like neighbours but were not, so every pair
outside `ALLOWED_PAIRS` is rejected with `UnsupportedError` and never silently
answered.

Helper naming: `_<subject>_filtered_by_<target>(subject, target_id, reader)` — the
dispatch key is `(subject_type, target_type)`, i.e. "list <subject> rows linked to
one <target> row". A target row that cannot be found yields an all-False mask: the
table filters to nothing, which keeps the error surface quiet while still matching
the user intent.
"""

from collections.abc import Iterable

import pandas
from application.orchestrators.graph_output import read_output_table
from domain.enums import GraphOutputTableEnum
from domain.errors import UnsupportedError
from graphrag_storage import Storage

# Columns the resolver needs per table. A superset of the user-facing columns in
# graph_table.py:_TABLE_COLUMNS — the extras are id arrays and link keys that the
# table response hides but the resolver joins on.
LINK_COLUMNS: dict[GraphOutputTableEnum, list[str]] = {
    GraphOutputTableEnum.ENTITIES: ["id", "title", "text_unit_ids"],
    GraphOutputTableEnum.RELATIONSHIPS: ["id", "source", "target", "text_unit_ids"],
    GraphOutputTableEnum.COMMUNITIES: [
        "id",
        "community",
        "level",
        "parent",
        "children",
        "entity_ids",
        "relationship_ids",
        "text_unit_ids",
    ],
    GraphOutputTableEnum.COMMUNITY_REPORTS: ["id", "community"],
    GraphOutputTableEnum.TEXT_UNITS: [
        "id",
        "entity_ids",
        "relationship_ids",
        "covariate_ids",
    ],
    GraphOutputTableEnum.DOCUMENTS: ["id", "text_unit_ids"],
    GraphOutputTableEnum.COVARIATES: ["id", "subject_id", "subject_type", "text_unit_ids"],
}

# The link relation each (subject, target) pair represents in the graph. Pairs
# outside this matrix are 400 — the UI must hide the tab. Same-table pairs mean a
# hierarchy (communities / community_reports) or shared-attribute (covariates)
# relation, not row-wise identity; see the per-pair helpers below.
_T = GraphOutputTableEnum
ALLOWED_PAIRS: dict[_T, frozenset[_T]] = {
    _T.ENTITIES: frozenset(
        {
            _T.ENTITIES,
            _T.RELATIONSHIPS,
            _T.COMMUNITIES,
            _T.COMMUNITY_REPORTS,
            _T.TEXT_UNITS,
            _T.DOCUMENTS,
            _T.COVARIATES,
        }
    ),
    _T.RELATIONSHIPS: frozenset(
        {
            _T.ENTITIES,
            _T.COMMUNITIES,
            _T.COMMUNITY_REPORTS,
            _T.TEXT_UNITS,
            _T.DOCUMENTS,
        }
    ),
    _T.COMMUNITIES: frozenset(
        {
            _T.ENTITIES,
            _T.RELATIONSHIPS,
            _T.COMMUNITIES,
            _T.COMMUNITY_REPORTS,
            _T.TEXT_UNITS,
            _T.DOCUMENTS,
        }
    ),
    _T.COMMUNITY_REPORTS: frozenset(
        {
            _T.ENTITIES,
            _T.RELATIONSHIPS,
            _T.COMMUNITIES,
            _T.COMMUNITY_REPORTS,
            _T.TEXT_UNITS,
            _T.DOCUMENTS,
        }
    ),
    _T.TEXT_UNITS: frozenset(
        {
            _T.ENTITIES,
            _T.RELATIONSHIPS,
            _T.COMMUNITIES,
            _T.COMMUNITY_REPORTS,
            _T.DOCUMENTS,
            _T.COVARIATES,
        }
    ),
    _T.DOCUMENTS: frozenset(
        {
            _T.ENTITIES,
            _T.RELATIONSHIPS,
            _T.COMMUNITIES,
            _T.COMMUNITY_REPORTS,
            _T.TEXT_UNITS,
            _T.COVARIATES,
        }
    ),
    _T.COVARIATES: frozenset(
        {
            _T.ENTITIES,
            _T.TEXT_UNITS,
            _T.DOCUMENTS,
            _T.COVARIATES,
        }
    ),
}


class LinkTableReader:
    """Read each graph index table at most once per request, with link columns."""

    def __init__(self, storage: Storage):
        self._storage = storage
        self._cache: dict[GraphOutputTableEnum, pandas.DataFrame | None] = {}

    async def read(self, table: GraphOutputTableEnum) -> pandas.DataFrame | None:
        if table not in self._cache:
            self._cache[table] = await read_output_table(self._storage, table, LINK_COLUMNS[table])
        return self._cache[table]

    def seed(self, table: GraphOutputTableEnum, dataframe: pandas.DataFrame) -> None:
        """Stash a dataframe the caller already loaded so `read` returns it without re-fetching."""
        self._cache[table] = dataframe


def _empty_mask(subject: pandas.DataFrame) -> pandas.Series:
    return pandas.Series(False, index=subject.index)


def _list_values(cell: object) -> list[object]:
    """Return the ids of a list-column cell: parquet decodes list columns as numpy arrays."""
    if cell is None or (isinstance(cell, float) and pandas.isna(cell)):
        return []
    # pandas list columns can also surface as plain lists depending on the backend.
    return list(cell)


def _row_by_id(dataframe: pandas.DataFrame, row_id: str) -> pandas.Series | None:
    rows = dataframe.loc[dataframe["id"].astype(str) == row_id]
    if rows.empty:
        return None
    return rows.iloc[0]


def _contains_any(column: pandas.Series, targets: Iterable[object]) -> pandas.Series:
    """Row-wise test: list-column cell intersects `targets`."""
    target_set = {str(value) for value in targets}
    if not target_set:
        return pandas.Series(False, index=column.index)
    mask = column.map(lambda cell: any(str(item) in target_set for item in _list_values(cell)))
    # Series.map with an object-returning lambda lands at `object` dtype; the downstream
    # `dataframe.loc[mask]` is cleaner against a proper bool Series.
    return mask.astype(bool)


async def _entity_title_by_id(entity_id: str, reader: LinkTableReader) -> str | None:
    entities = await reader.read(GraphOutputTableEnum.ENTITIES)
    if entities is None:
        return None
    row = _row_by_id(entities, entity_id)
    return None if row is None else str(row["title"])


async def _community_of_report(report_id: str, reader: LinkTableReader) -> object | None:
    """Return the integer `community` key of a community_report row, or None if missing."""
    reports = await reader.read(GraphOutputTableEnum.COMMUNITY_REPORTS)
    if reports is None:
        return None
    row = _row_by_id(reports, report_id)
    return None if row is None else row["community"]


async def _community_row_by_id(community_id: str, reader: LinkTableReader) -> pandas.Series | None:
    communities = await reader.read(GraphOutputTableEnum.COMMUNITIES)
    if communities is None:
        return None
    return _row_by_id(communities, community_id)


async def _community_row_by_community(
    community_key: object, reader: LinkTableReader
) -> pandas.Series | None:
    """Return the communities row whose `community` key equals `community_key`."""
    communities = await reader.read(GraphOutputTableEnum.COMMUNITIES)
    if communities is None:
        return None
    rows = communities.loc[communities["community"] == community_key]
    if rows.empty:
        return None
    return rows.iloc[0]


def _hierarchy_community_keys(community_row: pandas.Series) -> set[object]:
    """Return the parent + direct children `community` keys of a community row.

    Direct neighbours only — walking the whole tree would turn one click into the
    entire branch, which hides the step-by-step navigation the UI relies on.
    `communities.parent` is the parent's `community` as a string; missing / empty means
    "no parent". `communities.children` is a list of child `community` keys as strings.
    """
    keys: set[object] = set()
    parent = community_row.get("parent")
    if parent is not None and not (isinstance(parent, float) and pandas.isna(parent)):
        parent_text = str(parent)
        # graphrag writes the root community's parent as "" or "-1"; both mean no parent.
        if parent_text not in ("", "-1"):
            keys.add(parent_text)
    for child in _list_values(community_row.get("children")):
        keys.add(str(child))
    return keys


def _normalise_community_key(key: object) -> str | None:
    """Normalise a `community` key to a string, independent of pandas dtype.

    Parquet lands the `community` column as int on `communities` but as float on
    `community_reports` when any row has a null — `str(10)` is "10", `str(10.0)` is
    "10.0", and a naive string comparison silently misses every row. Integer-valued
    floats collapse back to the int form so both sides compare equal. Null returns
    None — that row is never a hit. GraphRAG only emits integer community ids, so
    non-integer floats cannot occur.
    """
    if key is None:
        return None
    if isinstance(key, float):
        if pandas.isna(key):
            return None
        # GraphRAG emits integer community ids; only the dtype ever lands as float.
        return str(int(key))
    return str(key)


def _mask_community_key_in(subject: pandas.DataFrame, keys: Iterable[object]) -> pandas.Series:
    """Mask subject rows whose `community` column is in `keys` (compared as strings).

    Both sides go through `_normalise_community_key`, so an int subject column and a
    float target key match when they point at the same community.
    """
    key_strings = {normalised for key in keys if (normalised := _normalise_community_key(key))}
    if not key_strings:
        return _empty_mask(subject)
    normalised_column = subject["community"].map(_normalise_community_key)
    return normalised_column.isin(key_strings).fillna(False).astype(bool)


# ---- Per-pair helpers (subject filtered by target) ---------------------------


async def _entities_filtered_by_entities(subject, target_id, reader):
    # List entities that share a relationship with the target entity.
    title = await _entity_title_by_id(target_id, reader)
    if title is None:
        return _empty_mask(subject)
    relationships = await reader.read(GraphOutputTableEnum.RELATIONSHIPS)
    if relationships is None:
        return _empty_mask(subject)
    endpoint_mask = (relationships["source"].astype(str) == title) | (
        relationships["target"].astype(str) == title
    )
    endpoints = relationships.loc[endpoint_mask]
    neighbour_titles = set(endpoints["source"].astype(str)) | set(endpoints["target"].astype(str))
    neighbour_titles.discard(title)
    return subject["title"].astype(str).isin(neighbour_titles)


async def _relationships_filtered_by_entities(subject, target_id, reader):
    # Subject = relationships; target = an entity. Relationships with that entity as endpoint.
    title = await _entity_title_by_id(target_id, reader)
    if title is None:
        return _empty_mask(subject)
    return (subject["source"].astype(str) == title) | (subject["target"].astype(str) == title)


async def _entities_filtered_by_relationships(subject, target_id, reader):
    # Subject = entities; target = a relationship. Both endpoint entities.
    relationships = await reader.read(GraphOutputTableEnum.RELATIONSHIPS)
    if relationships is None:
        return _empty_mask(subject)
    row = _row_by_id(relationships, target_id)
    if row is None:
        return _empty_mask(subject)
    endpoints = {str(row["source"]), str(row["target"])}
    return subject["title"].astype(str).isin(endpoints)


async def _communities_filtered_by_entities(subject, target_id, reader):
    # Subject = communities; target = an entity. Communities whose entity_ids list it.
    return _contains_any(subject["entity_ids"], [target_id])


async def _entities_filtered_by_communities(subject, target_id, reader):
    # Subject = entities; target = a community. Entities whose id ∈ community.entity_ids.
    row = await _community_row_by_id(target_id, reader)
    if row is None:
        return _empty_mask(subject)
    entity_ids = {str(item) for item in _list_values(row.get("entity_ids"))}
    return subject["id"].astype(str).isin(entity_ids)


async def _communities_filtered_by_relationships(subject, target_id, reader):
    return _contains_any(subject["relationship_ids"], [target_id])


async def _relationships_filtered_by_communities(subject, target_id, reader):
    row = await _community_row_by_id(target_id, reader)
    if row is None:
        return _empty_mask(subject)
    relationship_ids = {str(item) for item in _list_values(row.get("relationship_ids"))}
    return subject["id"].astype(str).isin(relationship_ids)


async def _text_units_filtered_by_entities(subject, target_id, reader):
    # text_units.entity_ids lists the entity id directly.
    return _contains_any(subject["entity_ids"], [target_id])


async def _entities_filtered_by_text_units(subject, target_id, reader):
    text_units = await reader.read(GraphOutputTableEnum.TEXT_UNITS)
    if text_units is None:
        return _empty_mask(subject)
    row = _row_by_id(text_units, target_id)
    if row is None:
        return _empty_mask(subject)
    entity_ids = {str(item) for item in _list_values(row.get("entity_ids"))}
    return subject["id"].astype(str).isin(entity_ids)


async def _text_units_filtered_by_relationships(subject, target_id, reader):
    return _contains_any(subject["relationship_ids"], [target_id])


async def _relationships_filtered_by_text_units(subject, target_id, reader):
    text_units = await reader.read(GraphOutputTableEnum.TEXT_UNITS)
    if text_units is None:
        return _empty_mask(subject)
    row = _row_by_id(text_units, target_id)
    if row is None:
        return _empty_mask(subject)
    relationship_ids = {str(item) for item in _list_values(row.get("relationship_ids"))}
    return subject["id"].astype(str).isin(relationship_ids)


async def _documents_filtered_by_entities(subject, target_id, reader):
    # Documents whose text_unit_ids intersect the text_units hosting the target entity.
    text_units = await reader.read(GraphOutputTableEnum.TEXT_UNITS)
    if text_units is None:
        return _empty_mask(subject)
    hosting_text_unit_ids = set(
        text_units.loc[_contains_any(text_units["entity_ids"], [target_id]), "id"].astype(str)
    )
    if not hosting_text_unit_ids:
        return _empty_mask(subject)
    return _contains_any(subject["text_unit_ids"], hosting_text_unit_ids)


async def _entities_filtered_by_documents(subject, target_id, reader):
    # Entities whose text_unit_ids intersect the document's text_unit_ids.
    documents = await reader.read(GraphOutputTableEnum.DOCUMENTS)
    if documents is None:
        return _empty_mask(subject)
    row = _row_by_id(documents, target_id)
    if row is None:
        return _empty_mask(subject)
    document_text_unit_ids = {str(item) for item in _list_values(row.get("text_unit_ids"))}
    if not document_text_unit_ids:
        return _empty_mask(subject)
    return _contains_any(subject["text_unit_ids"], document_text_unit_ids)


async def _documents_filtered_by_relationships(subject, target_id, reader):
    text_units = await reader.read(GraphOutputTableEnum.TEXT_UNITS)
    if text_units is None:
        return _empty_mask(subject)
    hosting_text_unit_ids = set(
        text_units.loc[_contains_any(text_units["relationship_ids"], [target_id]), "id"].astype(str)
    )
    if not hosting_text_unit_ids:
        return _empty_mask(subject)
    return _contains_any(subject["text_unit_ids"], hosting_text_unit_ids)


async def _relationships_filtered_by_documents(subject, target_id, reader):
    documents = await reader.read(GraphOutputTableEnum.DOCUMENTS)
    if documents is None:
        return _empty_mask(subject)
    row = _row_by_id(documents, target_id)
    if row is None:
        return _empty_mask(subject)
    document_text_unit_ids = {str(item) for item in _list_values(row.get("text_unit_ids"))}
    if not document_text_unit_ids:
        return _empty_mask(subject)
    return _contains_any(subject["text_unit_ids"], document_text_unit_ids)


async def _text_units_filtered_by_documents(subject, target_id, reader):
    # Route through documents.text_unit_ids — text_units.parquet does not always carry a
    # document_ids column, but every document row lists its own text unit ids.
    documents = await reader.read(GraphOutputTableEnum.DOCUMENTS)
    if documents is None:
        return _empty_mask(subject)
    row = _row_by_id(documents, target_id)
    if row is None:
        return _empty_mask(subject)
    text_unit_ids = {str(item) for item in _list_values(row.get("text_unit_ids"))}
    return subject["id"].astype(str).isin(text_unit_ids)


async def _documents_filtered_by_text_units(subject, target_id, reader):
    # See `_text_units_filtered_by_documents`: the join lives on the documents side.
    return _contains_any(subject["text_unit_ids"], [target_id])


async def _covariates_filtered_by_entities(subject, target_id, reader):
    # covariates.subject_id is an entity title (when subject_type == "entity").
    title = await _entity_title_by_id(target_id, reader)
    if title is None:
        return _empty_mask(subject)
    return subject["subject_id"].astype(str) == title


async def _entities_filtered_by_covariates(subject, target_id, reader):
    covariates = await reader.read(GraphOutputTableEnum.COVARIATES)
    if covariates is None:
        return _empty_mask(subject)
    row = _row_by_id(covariates, target_id)
    if row is None:
        return _empty_mask(subject)
    return subject["title"].astype(str) == str(row["subject_id"])


async def _covariates_filtered_by_text_units(subject, target_id, reader):
    text_units = await reader.read(GraphOutputTableEnum.TEXT_UNITS)
    if text_units is None:
        return _empty_mask(subject)
    row = _row_by_id(text_units, target_id)
    if row is None:
        return _empty_mask(subject)
    covariate_ids = {str(item) for item in _list_values(row.get("covariate_ids"))}
    return subject["id"].astype(str).isin(covariate_ids)


async def _text_units_filtered_by_covariates(subject, target_id, reader):
    covariates = await reader.read(GraphOutputTableEnum.COVARIATES)
    if covariates is None:
        return _empty_mask(subject)
    row = _row_by_id(covariates, target_id)
    if row is None:
        return _empty_mask(subject)
    text_unit_ids = {str(item) for item in _list_values(row.get("text_unit_ids"))}
    return subject["id"].astype(str).isin(text_unit_ids)


async def _covariates_filtered_by_documents(subject, target_id, reader):
    # Covariates whose text_units intersect the document's text_unit_ids.
    documents = await reader.read(GraphOutputTableEnum.DOCUMENTS)
    if documents is None:
        return _empty_mask(subject)
    row = _row_by_id(documents, target_id)
    if row is None:
        return _empty_mask(subject)
    document_text_unit_ids = {str(item) for item in _list_values(row.get("text_unit_ids"))}
    if not document_text_unit_ids:
        return _empty_mask(subject)
    return _contains_any(subject["text_unit_ids"], document_text_unit_ids)


async def _documents_filtered_by_covariates(subject, target_id, reader):
    covariates = await reader.read(GraphOutputTableEnum.COVARIATES)
    if covariates is None:
        return _empty_mask(subject)
    row = _row_by_id(covariates, target_id)
    if row is None:
        return _empty_mask(subject)
    covariate_text_unit_ids = {str(item) for item in _list_values(row.get("text_unit_ids"))}
    if not covariate_text_unit_ids:
        return _empty_mask(subject)
    return _contains_any(subject["text_unit_ids"], covariate_text_unit_ids)


async def _covariates_filtered_by_covariates(subject, target_id, reader):
    # Every covariate sharing the picked one's subject_id (same entity). The picked row
    # itself is included — the user clicked it, so showing it alongside its siblings is
    # less surprising than hiding it, and the UI can still de-duplicate on `id`.
    covariates = await reader.read(GraphOutputTableEnum.COVARIATES)
    if covariates is None:
        return _empty_mask(subject)
    row = _row_by_id(covariates, target_id)
    if row is None:
        return _empty_mask(subject)
    return subject["subject_id"].astype(str) == str(row["subject_id"])


# -- Hierarchy helpers reused across community / community_report pairs --


async def _communities_filtered_by_communities(subject, target_id, reader):
    # Hierarchy step (parent + direct children — different Leiden levels) plus
    # same-level cross-edge adjacency. On a flat (single-level) Leiden graph the
    # hierarchy branch is empty even though the visualization shows edges between
    # communities; the adjacency branch surfaces that same relation. Adjacency is
    # restricted to communities at the target's own level so one click never jumps
    # across levels — the step-by-step navigation the UI relies on. Overlapping
    # `communities.entity_ids` or `communities.relationship_ids` would miss the
    # relation entirely: Leiden entity sets are disjoint per level and GraphRAG
    # writes each relationship into one community only.
    row = await _community_row_by_id(target_id, reader)
    if row is None:
        return _empty_mask(subject)
    hierarchy_mask = _mask_community_key_in(subject, _hierarchy_community_keys(row))
    target_entity_ids = {str(item) for item in _list_values(row.get("entity_ids"))}
    adjacency_mask = await _community_cross_edge_mask(
        subject, target_entity_ids, row.get("level"), reader
    )
    not_self = subject["id"].astype(str) != str(target_id)
    return (hierarchy_mask | adjacency_mask) & not_self


async def _community_cross_edge_mask(
    subject: pandas.DataFrame,
    target_entity_ids: set[str],
    target_level: object,
    reader: LinkTableReader,
) -> pandas.Series:
    """Mask subject communities at `target_level` that share a cross-edge with the target.

    Walks `relationships` for every edge touching a target entity (by title), collects
    the far-side titles, maps them back to entity ids, then asks which subject
    communities at the same Leiden level list any of those ids in `entity_ids`.
    Restricting to the same level keeps one click on the target community's own tier —
    the hierarchy branch is the only path that crosses tiers. Returns an all-False mask
    when the target has no entities or the graph has no relationships table.
    """
    if not target_entity_ids:
        return _empty_mask(subject)
    entities = await reader.read(GraphOutputTableEnum.ENTITIES)
    relationships = await reader.read(GraphOutputTableEnum.RELATIONSHIPS)
    if entities is None or relationships is None:
        return _empty_mask(subject)
    target_titles = set(
        entities.loc[entities["id"].astype(str).isin(target_entity_ids), "title"].astype(str)
    )
    if not target_titles:
        return _empty_mask(subject)
    sources = relationships["source"].astype(str)
    targets = relationships["target"].astype(str)
    touching = relationships.loc[sources.isin(target_titles) | targets.isin(target_titles)]
    neighbour_titles = (
        set(touching["source"].astype(str)) | set(touching["target"].astype(str))
    ) - target_titles
    if not neighbour_titles:
        return _empty_mask(subject)
    neighbour_entity_ids = set(
        entities.loc[entities["title"].astype(str).isin(neighbour_titles), "id"].astype(str)
    )
    contains_neighbour = _contains_any(subject["entity_ids"], neighbour_entity_ids)
    if "level" not in subject.columns or target_level is None:
        return contains_neighbour
    same_level = subject["level"] == target_level
    return contains_neighbour & same_level.fillna(False).astype(bool)


async def _community_reports_filtered_by_community_reports(subject, target_id, reader):
    # Reports whose community is parent / direct child of the target report's community.
    community_key = await _community_of_report(target_id, reader)
    if community_key is None:
        return _empty_mask(subject)
    community_row = await _community_row_by_community(community_key, reader)
    if community_row is None:
        return _empty_mask(subject)
    hierarchy_keys = _hierarchy_community_keys(community_row)
    return _mask_community_key_in(subject, hierarchy_keys)


# -- Community <-> community_report through the `community` key --


async def _community_reports_filtered_by_communities(subject, target_id, reader):
    row = await _community_row_by_id(target_id, reader)
    if row is None:
        return _empty_mask(subject)
    # Normalise both sides to string — parquet can land `community` as int on
    # `communities` but object/float on `community_reports` when nulls are present,
    # and a dtype mismatch makes pandas return an all-False mask silently.
    return _mask_community_key_in(subject, [row["community"]])


async def _communities_filtered_by_community_reports(subject, target_id, reader):
    community_key = await _community_of_report(target_id, reader)
    if community_key is None:
        return _empty_mask(subject)
    # Normalise both sides to string — see `_community_reports_filtered_by_communities`.
    return _mask_community_key_in(subject, [community_key])


# -- Community_reports ↔ others: route through the report's community --


async def _entities_filtered_by_community_reports(subject, target_id, reader):
    community_key = await _community_of_report(target_id, reader)
    if community_key is None:
        return _empty_mask(subject)
    community_row = await _community_row_by_community(community_key, reader)
    if community_row is None:
        return _empty_mask(subject)
    entity_ids = {str(item) for item in _list_values(community_row.get("entity_ids"))}
    return subject["id"].astype(str).isin(entity_ids)


async def _community_reports_filtered_by_entities(subject, target_id, reader):
    # Reports whose community lists the entity in entity_ids.
    communities = await reader.read(GraphOutputTableEnum.COMMUNITIES)
    if communities is None:
        return _empty_mask(subject)
    owning_community_keys = set(
        communities.loc[_contains_any(communities["entity_ids"], [target_id]), "community"].astype(
            str
        )
    )
    return _mask_community_key_in(subject, owning_community_keys)


async def _relationships_filtered_by_community_reports(subject, target_id, reader):
    community_key = await _community_of_report(target_id, reader)
    if community_key is None:
        return _empty_mask(subject)
    community_row = await _community_row_by_community(community_key, reader)
    if community_row is None:
        return _empty_mask(subject)
    relationship_ids = {str(item) for item in _list_values(community_row.get("relationship_ids"))}
    return subject["id"].astype(str).isin(relationship_ids)


async def _community_reports_filtered_by_relationships(subject, target_id, reader):
    communities = await reader.read(GraphOutputTableEnum.COMMUNITIES)
    if communities is None:
        return _empty_mask(subject)
    owning_community_keys = set(
        communities.loc[
            _contains_any(communities["relationship_ids"], [target_id]), "community"
        ].astype(str)
    )
    return _mask_community_key_in(subject, owning_community_keys)


async def _text_units_filtered_by_communities(subject, target_id, reader):
    row = await _community_row_by_id(target_id, reader)
    if row is None:
        return _empty_mask(subject)
    text_unit_ids = {str(item) for item in _list_values(row.get("text_unit_ids"))}
    return subject["id"].astype(str).isin(text_unit_ids)


async def _communities_filtered_by_text_units(subject, target_id, reader):
    return _contains_any(subject["text_unit_ids"], [target_id])


async def _text_units_filtered_by_community_reports(subject, target_id, reader):
    community_key = await _community_of_report(target_id, reader)
    if community_key is None:
        return _empty_mask(subject)
    community_row = await _community_row_by_community(community_key, reader)
    if community_row is None:
        return _empty_mask(subject)
    text_unit_ids = {str(item) for item in _list_values(community_row.get("text_unit_ids"))}
    return subject["id"].astype(str).isin(text_unit_ids)


async def _community_reports_filtered_by_text_units(subject, target_id, reader):
    communities = await reader.read(GraphOutputTableEnum.COMMUNITIES)
    if communities is None:
        return _empty_mask(subject)
    owning_community_keys = set(
        communities.loc[
            _contains_any(communities["text_unit_ids"], [target_id]), "community"
        ].astype(str)
    )
    return _mask_community_key_in(subject, owning_community_keys)


async def _documents_filtered_by_communities(subject, target_id, reader):
    # Documents whose text_units intersect the community's text_unit_ids.
    row = await _community_row_by_id(target_id, reader)
    if row is None:
        return _empty_mask(subject)
    community_text_unit_ids = {str(item) for item in _list_values(row.get("text_unit_ids"))}
    if not community_text_unit_ids:
        return _empty_mask(subject)
    return _contains_any(subject["text_unit_ids"], community_text_unit_ids)


async def _communities_filtered_by_documents(subject, target_id, reader):
    # Communities whose text_unit_ids intersect the document's text_unit_ids.
    documents = await reader.read(GraphOutputTableEnum.DOCUMENTS)
    if documents is None:
        return _empty_mask(subject)
    row = _row_by_id(documents, target_id)
    if row is None:
        return _empty_mask(subject)
    document_text_unit_ids = {str(item) for item in _list_values(row.get("text_unit_ids"))}
    if not document_text_unit_ids:
        return _empty_mask(subject)
    return _contains_any(subject["text_unit_ids"], document_text_unit_ids)


async def _documents_filtered_by_community_reports(subject, target_id, reader):
    community_key = await _community_of_report(target_id, reader)
    if community_key is None:
        return _empty_mask(subject)
    community_row = await _community_row_by_community(community_key, reader)
    if community_row is None:
        return _empty_mask(subject)
    community_text_unit_ids = {
        str(item) for item in _list_values(community_row.get("text_unit_ids"))
    }
    if not community_text_unit_ids:
        return _empty_mask(subject)
    return _contains_any(subject["text_unit_ids"], community_text_unit_ids)


async def _community_reports_filtered_by_documents(subject, target_id, reader):
    documents = await reader.read(GraphOutputTableEnum.DOCUMENTS)
    if documents is None:
        return _empty_mask(subject)
    row = _row_by_id(documents, target_id)
    if row is None:
        return _empty_mask(subject)
    document_text_unit_ids = {str(item) for item in _list_values(row.get("text_unit_ids"))}
    if not document_text_unit_ids:
        return _empty_mask(subject)
    communities = await reader.read(GraphOutputTableEnum.COMMUNITIES)
    if communities is None:
        return _empty_mask(subject)
    owning_community_keys = set(
        communities.loc[
            _contains_any(communities["text_unit_ids"], document_text_unit_ids), "community"
        ].astype(str)
    )
    return _mask_community_key_in(subject, owning_community_keys)


# ---- Dispatch ((subject, target) -> helper) ----------------------------------

_RESOLVERS: dict[tuple[_T, _T], object] = {
    (_T.ENTITIES, _T.ENTITIES): _entities_filtered_by_entities,
    (_T.ENTITIES, _T.RELATIONSHIPS): _entities_filtered_by_relationships,
    (_T.ENTITIES, _T.COMMUNITIES): _entities_filtered_by_communities,
    (_T.ENTITIES, _T.COMMUNITY_REPORTS): _entities_filtered_by_community_reports,
    (_T.ENTITIES, _T.TEXT_UNITS): _entities_filtered_by_text_units,
    (_T.ENTITIES, _T.DOCUMENTS): _entities_filtered_by_documents,
    (_T.ENTITIES, _T.COVARIATES): _entities_filtered_by_covariates,
    (_T.RELATIONSHIPS, _T.ENTITIES): _relationships_filtered_by_entities,
    (_T.RELATIONSHIPS, _T.COMMUNITIES): _relationships_filtered_by_communities,
    (_T.RELATIONSHIPS, _T.COMMUNITY_REPORTS): _relationships_filtered_by_community_reports,
    (_T.RELATIONSHIPS, _T.TEXT_UNITS): _relationships_filtered_by_text_units,
    (_T.RELATIONSHIPS, _T.DOCUMENTS): _relationships_filtered_by_documents,
    (_T.COMMUNITIES, _T.ENTITIES): _communities_filtered_by_entities,
    (_T.COMMUNITIES, _T.RELATIONSHIPS): _communities_filtered_by_relationships,
    (_T.COMMUNITIES, _T.COMMUNITIES): _communities_filtered_by_communities,
    (_T.COMMUNITIES, _T.COMMUNITY_REPORTS): _communities_filtered_by_community_reports,
    (_T.COMMUNITIES, _T.TEXT_UNITS): _communities_filtered_by_text_units,
    (_T.COMMUNITIES, _T.DOCUMENTS): _communities_filtered_by_documents,
    (_T.COMMUNITY_REPORTS, _T.ENTITIES): _community_reports_filtered_by_entities,
    (_T.COMMUNITY_REPORTS, _T.RELATIONSHIPS): _community_reports_filtered_by_relationships,
    (_T.COMMUNITY_REPORTS, _T.COMMUNITIES): _community_reports_filtered_by_communities,
    (_T.COMMUNITY_REPORTS, _T.COMMUNITY_REPORTS): _community_reports_filtered_by_community_reports,
    (_T.COMMUNITY_REPORTS, _T.TEXT_UNITS): _community_reports_filtered_by_text_units,
    (_T.COMMUNITY_REPORTS, _T.DOCUMENTS): _community_reports_filtered_by_documents,
    (_T.TEXT_UNITS, _T.ENTITIES): _text_units_filtered_by_entities,
    (_T.TEXT_UNITS, _T.RELATIONSHIPS): _text_units_filtered_by_relationships,
    (_T.TEXT_UNITS, _T.COMMUNITIES): _text_units_filtered_by_communities,
    (_T.TEXT_UNITS, _T.COMMUNITY_REPORTS): _text_units_filtered_by_community_reports,
    (_T.TEXT_UNITS, _T.DOCUMENTS): _text_units_filtered_by_documents,
    (_T.TEXT_UNITS, _T.COVARIATES): _text_units_filtered_by_covariates,
    (_T.DOCUMENTS, _T.ENTITIES): _documents_filtered_by_entities,
    (_T.DOCUMENTS, _T.RELATIONSHIPS): _documents_filtered_by_relationships,
    (_T.DOCUMENTS, _T.COMMUNITIES): _documents_filtered_by_communities,
    (_T.DOCUMENTS, _T.COMMUNITY_REPORTS): _documents_filtered_by_community_reports,
    (_T.DOCUMENTS, _T.TEXT_UNITS): _documents_filtered_by_text_units,
    (_T.DOCUMENTS, _T.COVARIATES): _documents_filtered_by_covariates,
    (_T.COVARIATES, _T.ENTITIES): _covariates_filtered_by_entities,
    (_T.COVARIATES, _T.TEXT_UNITS): _covariates_filtered_by_text_units,
    (_T.COVARIATES, _T.DOCUMENTS): _covariates_filtered_by_documents,
    (_T.COVARIATES, _T.COVARIATES): _covariates_filtered_by_covariates,
}


def _is_allowed(subject_type: GraphOutputTableEnum, target_type: GraphOutputTableEnum) -> bool:
    return target_type in ALLOWED_PAIRS.get(subject_type, frozenset())


async def resolve_link_mask(
    subject: pandas.DataFrame,
    subject_type: GraphOutputTableEnum,
    target_type: GraphOutputTableEnum,
    target_id: str,
    reader: LinkTableReader,
) -> pandas.Series:
    """Return a mask over `subject` rows that are linked to (target_type, target_id).

    Raises `UnsupportedError` for pairs outside `ALLOWED_PAIRS`.
    """
    if not _is_allowed(subject_type, target_type):
        raise UnsupportedError(that="link pair", got=f"{subject_type.value}->{target_type.value}")
    if subject.empty:
        return _empty_mask(subject)
    resolver = _RESOLVERS[(subject_type, target_type)]
    return await resolver(subject, target_id, reader)
