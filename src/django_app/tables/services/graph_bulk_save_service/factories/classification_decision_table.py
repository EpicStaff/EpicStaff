from tables.services.graph_bulk_save_service.factories.base import NodeSaveableFactory
from tables.services.graph_bulk_save_service.saveables import (
    ClassificationDecisionTableNodeSaveable,
)


class ClassificationDecisionTableNodeSaveableFactory(NodeSaveableFactory):
    """
    Factory for ClassificationDecisionTableNode.
    preprocess_data() pops condition_groups before serializer runs.
    No deferred routing refs — CDT uses CharField node names, not FK IDs.
    """

    def preprocess_data(self, data: dict, payload_temp_ids: set) -> tuple[dict, dict]:
        condition_groups_data = data.pop("condition_groups", None)
        extra = {"condition_groups": condition_groups_data}
        return data, extra

    def build(self, serializer, extra: dict, instance=None):
        return ClassificationDecisionTableNodeSaveable(
            serializer,
            extra.get("condition_groups"),
            instance=instance,
        )
