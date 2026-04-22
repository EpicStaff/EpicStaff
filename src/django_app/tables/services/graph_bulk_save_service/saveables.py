from tables.models.graph_models import (
    ClassificationConditionGroup,
    Condition,
    ConditionGroup,
    DecisionTableNode,
)
from tables.services.graph_bulk_save_service.data_types import NodeRef


"""
Fields present on the wire (bulk-save payload) that must never reach DB.
Add new wire-only fields here; all saveable classes
strip them automatically via _clean_for_write().
"""
_WIRE_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "temp_id",  # client-side temp node reference, not a model field, never persisted
    }
)


def _clean_for_write(validated: dict) -> None:
    """Strip wire-only fields from a validated-data dict before any ORM write."""
    for field in _WIRE_ONLY_FIELDS:
        validated.pop(field, None)


class _SerializerSaveable:
    """
    Wraps a validated DRF serializer and calls create/update directly.

    DRF's .save() raises AssertionError if .data was ever accessed on the
    serializer instance (e.g. by an IDE debugger during Pass 1). Calling
    create/update directly bypasses that guard so the code works identically
    in debug and production modes.

    Returns the saved model instance so callers can register temp_id mappings.
    """

    def __init__(self, serializer):
        self._s = serializer

    def save(self):
        s = self._s
        validated = dict(s.validated_data)
        _clean_for_write(validated)
        if s.instance is None:
            return s.create(validated)
        return s.update(s.instance, validated)


class _DecisionTableNodeRefsSaveable:
    """
    Deferred resolver for the three routing node-id fields of DecisionTableNode
    that may reference a temp_id belonging to a node created in the same request:
        - DecisionTableNode.default_next_node_id
        - DecisionTableNode.next_error_node_id
        - ConditionGroup.next_node_id  (one per condition group)

    resolve_and_save() is called after ALL _NodeSaveable instances have run, so
    temp_id_map is fully populated regardless of node ordering in the payload.

    Uses QuerySet.update() — bypasses model.save() / clean() intentionally.
    content_hash is a dynamic @property on both models so no stale-hash issue.
    """

    def __init__(
        self,
        default_next_ref: NodeRef | None,
        next_error_ref: NodeRef | None,
        group_refs: list[NodeRef | None],
    ):
        self._default_next_ref = default_next_ref
        self._next_error_ref = next_error_ref
        self._group_refs = group_refs

        # Populated by DecisionTableNodeSaveable.save() after DB writes.
        self._decision_table_node_id: int | None = None
        self._group_ids: list[int] = []

    def set_node_id(self, node_id: int) -> None:
        """Called by DecisionTableNodeSaveable after the node is saved."""
        self._decision_table_node_id = node_id

    def set_group_ids(self, groups: list) -> None:
        """
        Called by DecisionTableNodeSaveable after bulk_create returns.
        groups is the list of ConditionGroup instances in the same positional
        order as group_refs.
        """
        self._group_ids = [g.id for g in groups]

    def resolve_and_save(self, temp_id_map: dict) -> None:
        node_updates: dict = {}

        if self._default_next_ref is not None:
            ref = self._default_next_ref
            node_updates["default_next_node_id"] = (
                temp_id_map[str(ref.value)] if ref.is_temp else ref.value
            )

        if self._next_error_ref is not None:
            ref = self._next_error_ref
            node_updates["next_error_node_id"] = (
                temp_id_map[str(ref.value)] if ref.is_temp else ref.value
            )

        if node_updates:
            DecisionTableNode.objects.filter(id=self._decision_table_node_id).update(
                **node_updates
            )

        for group_id, ref in zip(self._group_ids, self._group_refs):
            if ref is not None:
                ConditionGroup.objects.filter(id=group_id).update(
                    next_node_id=temp_id_map[str(ref.value)]
                    if ref.is_temp
                    else ref.value
                )


class DecisionTableNodeSaveable:
    """
    Wraps a validated DecisionTableNodeBulkSerializer and its condition_groups data.

    Defers the actual save so it can be executed inside the atomic write phase.
    Replicates the nested logic from DecisionTableNodeModelViewSet._create_or_update_node.

    If any routing field (default_next_node_id, next_error_node_id, or a
    condition group's next_node_id) references a temp_id, a
    _DecisionTableNodeRefsSaveable is wired in via the deferred_refs_saveable
    argument. That saveable runs after all nodes are saved (alongside edge
    saveables) and performs a QuerySet.update() to resolve the deferred ids.
    """

    def __init__(
        self,
        serializer,
        condition_groups_data,
        deferred_refs_saveable=None,
        instance=None,
    ):
        self._serializer = serializer
        self._condition_groups_data = condition_groups_data
        self._deferred = deferred_refs_saveable  # _DecisionTableNodeRefsSaveable | None
        self._instance = instance

    def save(self):
        s = self._serializer
        validated = dict(s.validated_data)
        _clean_for_write(validated)
        node = (
            s.create(validated)
            if s.instance is None
            else s.update(s.instance, validated)
        )

        if self._instance is not None:
            Condition.objects.filter(condition_group__decision_table_node=node).delete()
            ConditionGroup.objects.filter(decision_table_node=node).delete()

        # Inform the deferred saveable of the saved node id before group creation,
        # so it is always set even when condition_groups_data is empty.
        if self._deferred is not None:
            self._deferred.set_node_id(node.id)

        created_groups = []
        if self._condition_groups_data:
            created_groups = self._create_condition_groups(
                node, self._condition_groups_data
            )

        if self._deferred is not None:
            self._deferred.set_group_ids(created_groups)

        return node

    _GROUP_EXCLUDED_FIELDS = frozenset({"conditions", "decision_table_node", "id"})
    _CONDITION_EXCLUDED_FIELDS = frozenset({"condition_group", "id"})

    @staticmethod
    def _create_condition_groups(node, groups_data: list[dict]) -> list:
        """Create ConditionGroup and Condition records. Returns the created groups list."""
        groups_to_create = []
        conditions_map = []

        excluded_group = DecisionTableNodeSaveable._GROUP_EXCLUDED_FIELDS
        excluded_cond = DecisionTableNodeSaveable._CONDITION_EXCLUDED_FIELDS

        for group_data in groups_data:
            group_copy = {
                k: v for k, v in group_data.items() if k not in excluded_group
            }
            groups_to_create.append(
                ConditionGroup(decision_table_node=node, **group_copy)
            )
            conditions_map.append(group_data.get("conditions", []))

        created_groups = ConditionGroup.objects.bulk_create(groups_to_create)

        conditions_to_create = []
        for group, conditions_data in zip(created_groups, conditions_map):
            for cond_data in conditions_data:
                cond_copy = {
                    k: v for k, v in cond_data.items() if k not in excluded_cond
                }
                conditions_to_create.append(
                    Condition(condition_group=group, **cond_copy)
                )

        if conditions_to_create:
            Condition.objects.bulk_create(conditions_to_create)

        return created_groups


class ClassificationDecisionTableNodeSaveable:
    """
    Wraps a validated ClassificationDecisionTableNodeBulkSerializer and its condition_groups data.
    On update, deletes old ClassificationConditionGroup records and bulk_creates new ones.
    """

    def __init__(self, serializer, condition_groups_data, instance=None):
        self._serializer = serializer
        self._condition_groups_data = condition_groups_data
        self._instance = instance

    _GROUP_EXCLUDED_FIELDS = frozenset({"id", "classification_decision_table_node"})

    def save(self):
        s = self._serializer
        validated = dict(s.validated_data)
        _clean_for_write(validated)
        node = (
            s.create(validated)
            if s.instance is None
            else s.update(s.instance, validated)
        )

        if self._instance is not None and self._condition_groups_data is not None:
            ClassificationConditionGroup.objects.filter(
                classification_decision_table_node=node
            ).delete()

        if self._condition_groups_data:
            excluded = self._GROUP_EXCLUDED_FIELDS
            groups_to_create = []

            for group_data in self._condition_groups_data:
                gd = {k: v for k, v in group_data.items() if k not in excluded}
                groups_to_create.append(
                    ClassificationConditionGroup(
                        classification_decision_table_node=node, **gd
                    )
                )

            ClassificationConditionGroup.objects.bulk_create(groups_to_create)

        return node


class _NodeSaveable:
    """
    Wraps an inner saveable (any node type) and an optional temp_id.

    After the inner save(), if temp_id is set the real DB id is registered
    in the shared temp_id_map so edge saveables can resolve it.
    """

    def __init__(self, inner, temp_id: str | None):
        self._inner = inner
        self._temp_id = temp_id

    def save(self, temp_id_map: dict):
        instance = self._inner.save()
        if self._temp_id and instance is not None:
            temp_id_map[self._temp_id] = instance.id


class _EdgeSaveable:
    """
    Wraps a validated EdgeBulkSerializer and the parsed NodeRef for each end.
    At write time, temp refs are resolved from temp_id_map to real DB ids.
    """

    def __init__(self, serializer, start_ref: NodeRef, end_ref: NodeRef, instance=None):
        self._s = serializer
        self._start_ref = start_ref
        self._end_ref = end_ref
        self._instance = instance

    def resolve_and_save(self, temp_id_map: dict):
        s = self._s
        validated = dict(s.validated_data)

        _clean_for_write(validated)
        validated.pop("start_temp_id", None)
        validated.pop("end_temp_id", None)

        validated["start_node_id"] = (
            temp_id_map[str(self._start_ref.value)]
            if self._start_ref.is_temp
            else self._start_ref.value
        )
        validated["end_node_id"] = (
            temp_id_map[str(self._end_ref.value)]
            if self._end_ref.is_temp
            else self._end_ref.value
        )

        if self._instance is None:
            s.create(validated)
        else:
            s.update(self._instance, validated)


class _ConditionalEdgeSaveable:
    """
    Wraps a validated ConditionalEdgeBulkSerializer and the parsed source ref.

    If source_temp_id was provided, it is resolved from temp_id_map at write time.
    """

    def __init__(self, serializer, source_ref: NodeRef, instance=None):
        self._s = serializer
        self._source_ref = source_ref
        self._instance = instance

    def resolve_and_save(self, temp_id_map: dict):
        s = self._s
        validated = dict(s.validated_data)

        _clean_for_write(validated)
        validated.pop("source_temp_id", None)

        validated["source_node_id"] = (
            temp_id_map[str(self._source_ref.value)]
            if self._source_ref.is_temp
            else self._source_ref.value
        )

        if self._instance is None:
            s.create(validated)
        else:
            s.update(self._instance, validated)
