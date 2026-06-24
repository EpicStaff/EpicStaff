from tables.services.graph_bulk_save_service.data_types import NodeRef, ParsedNodeRef
from tables.services.graph_bulk_save_service.factories.base import NodeSaveableFactory
from tables.services.graph_bulk_save_service.saveables import (
    _ClassificationDecisionTableNodeRefsSaveable,
    ClassificationDecisionTableNodeSaveable,
)


class ClassificationDecisionTableNodeSaveableFactory(NodeSaveableFactory):
    _NODE_ROUTING_PAIRS = (
        ("default_next_node_id", "default_next_node_temp_id"),
        ("next_error_node_id", "next_error_node_temp_id"),
    )
    _GROUP_ROUTING_PAIR = ("next_node_id", "next_node_temp_id")

    def preprocess_data(self, data: dict, payload_temp_ids: set) -> tuple[dict, dict]:
        condition_groups_data = data.pop("condition_groups", None)

        routing_errors: list[str] = []
        node_routing_refs: dict[str, NodeRef | None] = {}

        for id_field, temp_field in self._NODE_ROUTING_PAIRS:
            parsed = self._parse_optional_routing_ref(
                data, id_field, temp_field, payload_temp_ids
            )
            if parsed.error:
                routing_errors.append(parsed.error)
            else:
                node_routing_refs[id_field] = parsed.ref
                if parsed.ref is not None and parsed.ref.is_temp:
                    data[id_field] = None
                elif parsed.ref is None:
                    data.setdefault(id_field, None)

        group_routing_refs: list[NodeRef | None] = []

        if condition_groups_data:
            id_field, temp_field = self._GROUP_ROUTING_PAIR
            for group_idx, group_data in enumerate(condition_groups_data):
                parsed = self._parse_optional_routing_ref(
                    group_data,
                    id_field,
                    temp_field,
                    payload_temp_ids,
                    context=f"condition_groups[{group_idx}]",
                )
                if parsed.error:
                    routing_errors.append(parsed.error)
                    group_routing_refs.append(None)
                else:
                    group_routing_refs.append(parsed.ref)
                    if parsed.ref is not None and parsed.ref.is_temp:
                        group_data[id_field] = None
                    elif parsed.ref is None:
                        group_data.setdefault(id_field, None)

        extra = {
            "condition_groups": condition_groups_data,
            "node_routing_refs": node_routing_refs,
            "group_routing_refs": group_routing_refs,
            "routing_errors": routing_errors,
        }
        return data, extra

    def build(self, serializer, extra: dict, instance=None):
        return ClassificationDecisionTableNodeSaveable(
            serializer,
            extra.get("condition_groups"),
            instance=instance,
        )

    def build_deferred(self, inner_saveable, extra: dict):
        node_routing_refs: dict = extra.get("node_routing_refs", {})
        group_routing_refs: list = extra.get("group_routing_refs", [])

        default_next_ref = node_routing_refs.get("default_next_node_id")
        next_error_ref = node_routing_refs.get("next_error_node_id")

        has_any_ref = (
            default_next_ref is not None
            or next_error_ref is not None
            or any(r is not None for r in group_routing_refs)
        )
        if not has_any_ref:
            return None

        deferred = _ClassificationDecisionTableNodeRefsSaveable(
            default_next_ref=default_next_ref,
            next_error_ref=next_error_ref,
            group_refs=group_routing_refs,
        )
        inner_saveable._deferred = deferred
        return deferred

    @staticmethod
    def _parse_optional_routing_ref(
        data: dict,
        id_field: str,
        temp_field: str,
        payload_temp_ids: set,
        context: str = "",
    ) -> ParsedNodeRef:
        node_id = data.get(id_field)
        temp_id = data.pop(temp_field, None)

        has_id = node_id is not None
        has_temp = temp_id is not None

        prefix = f"{context}: " if context else ""

        if has_id and has_temp:
            return ParsedNodeRef(
                error=f"{prefix}Provide at most one of {id_field} or {temp_field}, not both."
            )

        if has_temp:
            temp_str = str(temp_id)
            if temp_str not in payload_temp_ids:
                return ParsedNodeRef(
                    error=(
                        f"{prefix}{temp_field}={temp_str!r} does not match any temp_id "
                        f"in the node lists of this request."
                    )
                )
            return ParsedNodeRef(ref=NodeRef(is_temp=True, value=temp_str))

        if has_id:
            return ParsedNodeRef(ref=NodeRef(is_temp=False, value=node_id))

        return ParsedNodeRef()
