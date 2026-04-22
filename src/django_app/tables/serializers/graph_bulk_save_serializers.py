from rest_framework import serializers

from tables.serializers.model_serializers import (
    AudioTranscriptionNodeSerializer,
    ClassificationDecisionTableNodeSerializer,
    ConditionalEdgeSerializer,
    CrewNodeSerializer,
    DecisionTableNodeSerializer,
    EdgeSerializer,
    EndNodeSerializer,
    FileExtractorNodeSerializer,
    LLMNodeSerializer,
    GraphNoteSerializer,
    PythonNodeSerializer,
    StartNodeSerializer,
    SubGraphNodeSerializer,
    WebhookTriggerNodeSerializer,
)
from tables.serializers.telegram_trigger_serializers import (
    TelegramTriggerNodeSerializer,
)


class BulkSaveEntityMixin:
    """
    Adjusts any node serializer for bulk-save input:
    id: optional/nullable, absent or null for new entities.
    temp_id: wire-only UUID, FE assigns to new nodes so edges can reference them
    before real DB ids are known. Never persisted
    """

    def get_fields(self):
        fields = super().get_fields()
        fields["id"] = serializers.IntegerField(required=False, allow_null=True)
        fields["temp_id"] = serializers.UUIDField(
            required=False, allow_null=True, default=None
        )
        return fields


class CrewNodeBulkSerializer(BulkSaveEntityMixin, CrewNodeSerializer):
    pass


class PythonNodeBulkSerializer(BulkSaveEntityMixin, PythonNodeSerializer):
    pass


class FileExtractorNodeBulkSerializer(BulkSaveEntityMixin, FileExtractorNodeSerializer):
    pass


class AudioTranscriptionNodeBulkSerializer(
    BulkSaveEntityMixin, AudioTranscriptionNodeSerializer
):
    pass


class LLMNodeBulkSerializer(BulkSaveEntityMixin, LLMNodeSerializer):
    pass


class StartNodeBulkSerializer(BulkSaveEntityMixin, StartNodeSerializer):
    pass


class EndNodeBulkSerializer(BulkSaveEntityMixin, EndNodeSerializer):
    pass


class SubGraphNodeBulkSerializer(BulkSaveEntityMixin, SubGraphNodeSerializer):
    pass


class ClassificationDecisionTableNodeBulkSerializer(
    BulkSaveEntityMixin, ClassificationDecisionTableNodeSerializer
):
    pass


class DecisionTableNodeBulkSerializer(BulkSaveEntityMixin, DecisionTableNodeSerializer):
    pass


class GraphNoteBulkSerializer(BulkSaveEntityMixin, GraphNoteSerializer):
    pass


class WebhookTriggerNodeBulkSerializer(
    BulkSaveEntityMixin, WebhookTriggerNodeSerializer
):
    pass


class TelegramTriggerNodeBulkSerializer(
    BulkSaveEntityMixin, TelegramTriggerNodeSerializer
):
    pass


class EdgeBulkSerializer(BulkSaveEntityMixin, EdgeSerializer):
    """
    Bulk-save serializer for Edge.

    Edge endpoints now reference nodes by global node ID, not node_name.
    For nodes that are being created in the same bulk-save request (no DB id yet),
    FE supplies a temp UUID assigned to that node.  Exactly one of
    (start_node_id, start_temp_id) and one of (end_node_id, end_temp_id) must be set.
    """

    # Make model id fields optional — temp_id may be used instead.
    start_node_id = serializers.IntegerField(required=False, allow_null=True)
    end_node_id = serializers.IntegerField(required=False, allow_null=True)

    # Wire-only; resolved to real IDs in the service before DB write.
    start_temp_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    end_temp_id = serializers.UUIDField(required=False, allow_null=True, default=None)

    def get_validators(self):
        # UniqueTogetherValidator (generated from Edge's UniqueConstraint) calls
        # enforce_required_fields(), which forces required=True on start_node_id /
        # end_node_id even though they're declared optional here (temp_id may be used
        # instead). The DB unique constraint still enforces correctness inside the
        # atomic transaction, so we can safely drop these DRF-level validators.
        from rest_framework.validators import UniqueTogetherValidator

        return [
            v
            for v in super().get_validators()
            if not isinstance(v, UniqueTogetherValidator)
        ]

    def validate(self, attrs):
        start_id = attrs.get("start_node_id")
        start_temp = attrs.get("start_temp_id")
        end_id = attrs.get("end_node_id")
        end_temp = attrs.get("end_temp_id")

        if bool(start_id) == bool(start_temp):
            raise serializers.ValidationError(
                "Provide exactly one of start_node_id or start_temp_id."
            )
        if bool(end_id) == bool(end_temp):
            raise serializers.ValidationError(
                "Provide exactly one of end_node_id or end_temp_id."
            )
        return attrs


class ConditionalEdgeBulkSerializer(BulkSaveEntityMixin, ConditionalEdgeSerializer):
    """
    Bulk-save serializer for ConditionalEdge.

    source_node_id references the node this edge originates from.
    If that node is new in the same request, use source_temp_id instead.
    Exactly one of (source_node_id, source_temp_id) must be set.
    """

    source_node_id = serializers.IntegerField(required=False, allow_null=True)
    source_temp_id = serializers.UUIDField(
        required=False, allow_null=True, default=None
    )

    def get_validators(self):
        from rest_framework.validators import UniqueTogetherValidator

        return [
            v
            for v in super().get_validators()
            if not isinstance(v, UniqueTogetherValidator)
        ]

    def validate(self, attrs):
        source_id = attrs.get("source_node_id")
        source_temp = attrs.get("source_temp_id")

        if bool(source_id) == bool(source_temp):
            raise serializers.ValidationError(
                "Provide exactly one of source_node_id or source_temp_id."
            )
        return attrs


class DeletedEntitiesSerializer(serializers.Serializer):
    # Edge id fields declared explicitly because edges are not in NODE_TYPE_REGISTRY.
    edge_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    conditional_edge_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )

    def get_fields(self):
        # Node id fields are injected from NODE_TYPE_REGISTRY so adding a new
        # node type to the registry automatically adds its delete field here.
        # Lazy import avoids a circular dependency at module load time.
        from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY

        fields = super().get_fields()
        for config in NODE_TYPE_REGISTRY:
            fields[config.delete_key] = serializers.ListField(
                child=serializers.IntegerField(), required=False, default=list
            )
        return fields


class GraphBulkSaveInputSerializer(serializers.Serializer):
    """
    Validates the top-level request shape at the API boundary
    Edge lists declared explicitly because edges are not in NODE_TYPE_REGISTRY
    """

    edge_list = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )
    conditional_edge_list = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )
    deleted = DeletedEntitiesSerializer(required=False, default=dict)

    def get_fields(self):
        """
        Node list fields are injected from NODE_TYPE_REGISTRY so adding a new
        node type automatically adds its list field here.
        """
        from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY

        fields = super().get_fields()
        for config in NODE_TYPE_REGISTRY:
            fields[config.list_key] = serializers.ListField(
                child=serializers.DictField(), required=False, default=list
            )
        return fields
