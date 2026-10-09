from collections import defaultdict
from collections.abc import Iterable

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


def resolve_node_names(ids: Iterable[int], *, graph_ids: Iterable[int]) -> dict[int, str]:
    """Batch-resolve node IDs to formatted names, minimising DB round-trips.

    Runs a single UNION ALL query to identify which concrete table each ID
    belongs to, then one bulk SELECT per matching table.
    Returns ``{id: "name #id"}`` for every ID that is not None.

    Only a node in one of ``graph_ids`` resolves to its name. Any other id
    (nonexistent, or in another graph or organization) becomes
    ``"unknown node #id"``, so a stored reference to a foreign node never
    exposes that node's name.
    """
    ids = list({i for i in ids if i is not None})
    if not ids:
        return {}
    graph_ids = list(set(graph_ids))

    node_models = BaseGlobalNode.get_all_node_models()
    if not node_models or not graph_ids:
        return {i: f"unknown node #{i}" for i in ids}

    table_to_model = {m._meta.db_table: m for m in node_models}

    id_placeholders = ", ".join(["%s"] * len(ids))
    graph_placeholders = ", ".join(["%s"] * len(graph_ids))
    union_parts = [
        f"SELECT id, '{t}' as tbl FROM {t} "
        f"WHERE {m._meta.get_field('graph').column} IN ({graph_placeholders}) "
        f"AND id IN ({id_placeholders})"
        for t, m in table_to_model.items()
    ]
    query = " UNION ALL ".join(union_parts)
    params = (graph_ids + ids) * len(table_to_model)

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()

    table_ids: dict[str, list[int]] = defaultdict(list)
    for id_val, tbl in rows:
        table_ids[tbl].append(id_val)

    result: dict[int, str] = {}
    for tbl, tbl_ids in table_ids.items():
        model = table_to_model[tbl]
        for instance in model.objects.filter(id__in=tbl_ids, graph_id__in=graph_ids):
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

    Created once per graph build, seeded with a ``cache`` of names the caller
    already resolved; passed explicitly into converter methods so
    ConverterService stays stateless.

    With ``graph_id`` set, an id missing from the cache resolves only within
    that graph, so a reference to another graph's node never exposes its name,
    and the result is memoized. Without it, a miss falls back to an unscoped
    lookup that is not memoized (the module-level default instance would
    otherwise cache names for the process lifetime): use that only for a node's
    own id, never for a reference stored on it.
    """

    def __init__(self, cache: dict[int, str] | None = None, graph_id: int | None = None):
        self._cache = cache if cache is not None else {}
        self._graph_id = graph_id

    def __call__(self, id: int | None) -> str | None:
        if id is None:
            return None
        if id in self._cache:
            return self._cache[id]
        if self._graph_id is None:
            return generate_node_name(id)
        self._cache[id] = resolve_node_names([id], graph_ids=[self._graph_id])[id]
        return self._cache[id]


#: Default resolver with an empty cache — falls back to individual DB lookups.
#: Use this as a default parameter value for converter methods so they work
#: correctly both with and without a pre-built batch resolver.
SINGLE_LOOKUP_RESOLVER = NodeNameResolver()
