import uuid
from collections import defaultdict

from loguru import logger

from tables.models import Graph
from tables.models.base_models import NodeIdentityMixin


class KeptNodeUuids:
    """Give nodes created from an export file or version snapshot the uuid they carry.

    The node import serializers treat ``uuid`` as read-only, so a node is created
    with a fresh uuid first; ``save`` then writes the kept ones, one UPDATE per
    node table.

    Data the user cannot edit must never fail a restore or import, so a uuid that
    cannot be kept is dropped with a warning and the node keeps its fresh uuid:

    - it is not a valid uuid;
    - an earlier node of the same data already kept it (the first node in data
      order wins, across all node types);
    - an active node of the target graph already holds it.

    Soft-deleted nodes do not count: the per-graph unique index ignores them.

    The check is only race-free because every caller already serialises on the
    Graph row (restore: increment_version_if_current; replace-import:
    select_for_update and a version bump).
    """

    def __init__(self, graph: Graph):
        self._graph = graph
        self._taken = NodeIdentityMixin.active_node_uuids(graph)
        self._nodes_by_model: dict[type, list] = defaultdict(list)

    def keep(self, node, raw_uuid) -> None:
        """Queue ``raw_uuid`` for ``node``; a missing uuid leaves the fresh one."""
        if raw_uuid is None:
            return
        kept_uuid = self._parse(raw_uuid)
        if kept_uuid is None:
            self._warn(node, "is not a valid uuid")
            return
        if kept_uuid in self._taken:
            self._warn(node, "is already used by another node of this graph")
            return
        self._taken.add(kept_uuid)
        node.uuid = kept_uuid
        self._nodes_by_model[type(node)].append(node)

    def save(self) -> None:
        """Write the queued uuids to the database."""
        for model, nodes in self._nodes_by_model.items():
            model.objects.bulk_update(nodes, ["uuid"])
        self._nodes_by_model.clear()

    @staticmethod
    def _parse(raw_uuid) -> uuid.UUID | None:
        if isinstance(raw_uuid, uuid.UUID):
            return raw_uuid
        if not isinstance(raw_uuid, str):
            return None
        try:
            return uuid.UUID(raw_uuid)
        except ValueError:
            return None

    def _warn(self, node, reason: str) -> None:
        # The raw value is not logged: it comes from a file and can be any size.
        logger.warning(
            "Graph {}: the uuid of restored or imported {} node {} {}; it gets a new uuid",
            self._graph.id,
            type(node).__name__,
            node.id,
            reason,
        )
