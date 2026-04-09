from abc import ABC, abstractmethod

from tables.services.graph_bulk_save_service.saveables import _SerializerSaveable


class NodeSaveableFactory(ABC):
    """NodeSaveableFactory — strategy for building a saveable for one node type"""

    def preprocess_data(self, data: dict, payload_temp_ids: set) -> tuple[dict, dict]:
        """
        Override preprocess_data when a node type has fields that must be
        extracted before the serializer runs (e.g. nested relations, wire-only
        routing temp_ids).
        Returns (data_for_serializer, extra_data_for_build).
        The default passes data through unchanged.

        payload_temp_ids: the full set of temp_id strings declared across all
        node lists in this request — used to validate *_node_temp_id references.
        """
        return data, {}

    # Build the inner saveable from the validated serializer and extra data
    # extracted in preprocess_data.
    @abstractmethod
    def build(self, serializer, extra: dict, instance=None): ...

    def build_deferred(self, inner_saveable, extra: dict):
        """
        Return a deferred ref saveable (implements resolve_and_save(temp_id_map)),
        or None if this node type has no deferred routing refs.
        Called after build(); override only for node types with temp routing refs.
        """
        return None


class DefaultNodeSaveableFactory(NodeSaveableFactory):
    def build(self, serializer, extra: dict, instance=None):
        """Standard node types: just wrap the serializer"""
        return _SerializerSaveable(serializer)
