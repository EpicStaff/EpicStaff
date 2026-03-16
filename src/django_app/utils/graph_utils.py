from collections import defaultdict
from typing import Iterable

from django.db import connection
from loguru import logger

from tables.models.base_models import BaseGlobalNode

"""
TODO: future improvement: use some cleaner approach

new model field for Nodes with concatenation node_name and node_id in morel lvl
pass node_name and node_id to langgraph, and concatenate in some LoggerService
etc
"""


def generate_node_name(id: int | None, node_name: str | None = None) -> str | None:
    if id is None:
        return None

    if node_name is not None:
        return f"{node_name} #{id}"

    node = BaseGlobalNode.find_globally(id)
    try:
        node_name = node.node_name
    except Exception as e:
        logger.exception(e)
        node_name = "unknown node"
    return f"{node_name} #{id}"


def resolve_node_names(ids: Iterable[int]) -> dict[int, str]:
    """Batch-resolve node IDs to formatted names, minimising DB round-trips.

    Runs a single UNION ALL query to identify which concrete table each ID
    belongs to, then one bulk SELECT per matching table.
    Returns ``{id: "name #id"}`` for every ID that is not None.
    """
    ids = list({i for i in ids if i is not None})
    if not ids:
        return {}

    node_models = BaseGlobalNode.get_all_node_models()
    if not node_models:
        return {i: f"unknown node #{i}" for i in ids}

    table_to_model = {m._meta.db_table: m for m in node_models}

    placeholders = ", ".join(["%s"] * len(ids))
    union_parts = [
        f"SELECT id, '{t}' as tbl FROM {t} WHERE id IN ({placeholders})"
        for t in table_to_model
    ]
    query = " UNION ALL ".join(union_parts)
    params = ids * len(table_to_model)

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()

    table_ids: dict[str, list[int]] = defaultdict(list)
    for id_val, tbl in rows:
        table_ids[tbl].append(id_val)

    result: dict[int, str] = {}
    for tbl, tbl_ids in table_ids.items():
        model = table_to_model[tbl]
        for instance in model.objects.filter(id__in=tbl_ids):
            try:
                name = instance.node_name
            except AttributeError:
                name = "unknown node"
            result[instance.id] = f"{name} #{instance.id}"

    for i in ids:
        if i not in result:
            result[i] = f"unknown node #{i}"

    return result


class NodeNameResolver:
    """Call-scoped, batch-prefetched node name resolver.

    Created once per graph build with all known IDs; passed explicitly
    into converter methods so ConverterService stays stateless.
    """

    def __init__(self, ids: Iterable[int] = ()):
        self._cache = resolve_node_names(ids)

    def __call__(self, id: int | None) -> str | None:
        if id is None:
            return None
        return self._cache.get(id) or generate_node_name(id)


#: Default resolver with an empty cache — falls back to individual DB lookups.
#: Use this as a default parameter value for converter methods so they work
#: correctly both with and without a pre-built batch resolver.
SINGLE_LOOKUP_RESOLVER = NodeNameResolver()
