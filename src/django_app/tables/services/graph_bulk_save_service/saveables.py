from tables.models.graph_models import Condition, ConditionGroup


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


class DecisionTableNodeSaveable:
    """
    Wraps a validated DecisionTableNodeBulkSerializer and its condition_groups data.

    Defers the actual save so it can be executed inside the atomic write phase.
    Replicates the nested logic from DecisionTableNodeModelViewSet._create_or_update_node.
    """

    def __init__(self, serializer, condition_groups_data, instance=None):
        self._serializer = serializer
        self._condition_groups_data = condition_groups_data
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

        if self._condition_groups_data:
            self._create_condition_groups(node, self._condition_groups_data)

        return node

    _GROUP_EXCLUDED_FIELDS = frozenset({"conditions", "decision_table_node", "id"})
    _CONDITION_EXCLUDED_FIELDS = frozenset({"condition_group", "id"})

    @staticmethod
    def _create_condition_groups(node, groups_data: list[dict]):
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
    Wraps a validated EdgeBulkSerializer and the parsed node refs for each end.

    Each ref is a (is_temp: bool, value: str|int) tuple.
    At write time, temp refs are resolved from temp_id_map to real DB ids.
    """

    def __init__(self, serializer, start_ref: tuple, end_ref: tuple, instance=None):
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

        is_temp, value = self._start_ref
        validated["start_node_id"] = temp_id_map[str(value)] if is_temp else value

        is_temp, value = self._end_ref
        validated["end_node_id"] = temp_id_map[str(value)] if is_temp else value

        if self._instance is None:
            s.create(validated)
        else:
            s.update(self._instance, validated)


class _ConditionalEdgeSaveable:
    """
    Wraps a validated ConditionalEdgeBulkSerializer and the parsed source ref.

    If source_temp_id was provided, it is resolved from temp_id_map at write time.
    """

    def __init__(self, serializer, source_ref: tuple, instance=None):
        self._s = serializer
        self._source_ref = source_ref
        self._instance = instance

    def resolve_and_save(self, temp_id_map: dict):
        s = self._s
        validated = dict(s.validated_data)

        _clean_for_write(validated)
        validated.pop("source_temp_id", None)

        is_temp, value = self._source_ref
        validated["source_node_id"] = temp_id_map[str(value)] if is_temp else value

        if self._instance is None:
            s.create(validated)
        else:
            s.update(self._instance, validated)
