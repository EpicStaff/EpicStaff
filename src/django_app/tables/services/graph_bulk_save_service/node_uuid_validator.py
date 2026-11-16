from collections import Counter
from uuid import UUID

from django.db import IntegrityError
from tables.models import Graph
from tables.models.base_models import NODE_UUID_CONSTRAINT_SUFFIX, NodeIdentityMixin
from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY

DUPLICATE_UUID_MESSAGE = "This uuid is used by more than one node in the request."
TAKEN_UUID_MESSAGE = "This uuid is already used by another node of this flow."


class NodeUuidValidator:
    """
    Checks the client-sent uuids of the nodes a bulk save creates.

    The database enforces uuid uniqueness per node table only, so a uuid must be
    checked against all node tables of the graph here. Lookups are limited to the
    target graph: a uuid used in another graph is not a conflict. Error messages
    never repeat the uuid or describe the node that holds it.

    The check is only race-free because bulk save already serialises writers of
    the graph with its save_version compare-and-set.
    """

    def find_errors(
        self,
        graph: Graph,
        created_uuids: dict[str, list[tuple[int, UUID]]],
        deleted_data: dict,
    ) -> dict[str, list[dict]]:
        """Return per-list errors for uuids that are duplicated or already used in the graph.

        Args:
            created_uuids: (payload index, uuid) pairs of the created nodes, keyed by list key.
            deleted_data: The request's `deleted` block. Nodes deleted by the same
                request free their uuid, because deletions are written first.
        """
        occurrences = Counter(
            node_uuid for entries in created_uuids.values() for _, node_uuid in entries
        )
        if not occurrences:
            return {}

        taken_uuids = NodeIdentityMixin.active_node_uuids(
            graph,
            among=set(occurrences),
            excluded_ids_by_model={
                config.model_class: deleted_data.get(config.delete_key) or []
                for config in NODE_TYPE_REGISTRY
            },
        )
        errors: dict[str, list[dict]] = {}
        for list_key, entries in created_uuids.items():
            for index, node_uuid in entries:
                if occurrences[node_uuid] > 1:
                    message = DUPLICATE_UUID_MESSAGE
                elif node_uuid in taken_uuids:
                    message = TAKEN_UUID_MESSAGE
                else:
                    continue
                errors.setdefault(list_key, []).append(
                    {"index": index, "errors": {"uuid": [message]}}
                )
        return errors

    @staticmethod
    def is_uuid_conflict(error: IntegrityError) -> bool:
        """Return True when the error is a violation of the per-graph node uuid constraint."""
        diagnostics = getattr(error.__cause__, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None) or ""
        return constraint_name.endswith(NODE_UUID_CONSTRAINT_SUFFIX)
