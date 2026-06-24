from django.db import transaction
from rest_framework import serializers

from tables.serializers.model_serializers.node_serializers.flow_control_serializers import (
    ConditionalEdgeSerializer,
    DecisionTableNodeSerializer,
    EndNodeSerializer,
    StartNodeSerializer,
    ClassificationDecisionTableNodeSerializer,
)
from tables.serializers.model_serializers.node_serializers.basic_node_serializers import (
    AudioTranscriptionNodeSerializer,
    CodeAgentNodeSerializer,
    CrewNodeSerializer,
    EdgeSerializer,
    FileExtractorNodeSerializer,
    PythonNodeSerializer,
    SubGraphNodeSerializer,
)
from tables.serializers.model_serializers.node_serializers.trigger_serializers import (
    TelegramTriggerNodeSerializer,
    WebhookTriggerNodeSerializer,
    ScheduleTriggerNodeSerializer,
)
from tables.serializers.model_serializers.tag_serializers import GraphTagSerializer
from tables.models.graph_models import (
    Graph,
    GraphNote,
    GraphOrganization,
    GraphOrganizationUser,
    GraphSessionMessage,
    StartNode,
)
from tables.models.label_models import Label
from tables.serializers.base_serializer import BaseGraphEntityMixin


class GraphNoteSerializer(BaseGraphEntityMixin, serializers.ModelSerializer):
    class Meta(BaseGraphEntityMixin.Meta):
        model = GraphNote
        fields = "__all__"


class GraphSessionMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphSessionMessage
        fields = "__all__"


class GraphOrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphOrganization
        fields = [
            "id",
            "graph",
            "organization",
            "persistent_variables",
            "user_variables",
        ]

    def validate(self, attrs):
        graph = attrs.get("graph") or getattr(self.instance, "graph", None)
        if not graph:
            raise serializers.ValidationError("Graph is required to validate variables")

        organization_variables = attrs.get("persistent_variables", {})
        user_variables = attrs.get("user_variables", {})

        qs = GraphOrganization.objects.filter(graph=graph)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError("This flow already has an organization")

        start_node: StartNode = graph.start_node_list.first()
        for key in user_variables:
            if key not in start_node.variables:
                raise serializers.ValidationError(
                    {
                        "user_variables": f"Provided user_variables have to be in flow domain. Variable `{key}` is not in domain."
                    }
                )
        for key in organization_variables:
            if key not in start_node.variables:
                raise serializers.ValidationError(
                    {
                        "persistent_variables": f"Provided persistent_variables have to be in flow domain. Variable `{key}` is not in domain."
                    }
                )
            if key in user_variables:
                raise serializers.ValidationError(
                    {
                        "user_variables": f"User variables and Organization variables cannot have same values. Issue with key `{key}`"
                    }
                )

        return super().validate(attrs)


class GraphOrganizationUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphOrganizationUser
        fields = ["id", "graph", "organization_user", "persistent_variables"]
        read_only_fields = ["id", "persistent_variables"]


class GraphLightBaseSerializer(serializers.ModelSerializer):
    tags = GraphTagSerializer(many=True, read_only=True)
    label_ids = serializers.PrimaryKeyRelatedField(
        many=True, read_only=True, source="labels"
    )

    class Meta:
        model = Graph
        fields = [
            "id",
            "name",
            "description",
            "tags",
            "epicchat_enabled",
            "label_ids",
            "created_at",
            "updated_at",
            "save_version",
        ]


class GraphLightSerializer(GraphLightBaseSerializer):
    subflows = serializers.SerializerMethodField()

    class Meta(GraphLightBaseSerializer.Meta):
        fields = GraphLightBaseSerializer.Meta.fields + ["subflows"]

    def get_subflows(self, obj):
        graphs = Graph.objects.get_transitive_subflows(obj.id)
        return GraphLightBaseSerializer(graphs, many=True).data


class GraphSerializer(serializers.ModelSerializer):
    # Reverse relationships
    crew_node_list = CrewNodeSerializer(many=True, read_only=True)
    python_node_list = PythonNodeSerializer(many=True, read_only=True)
    file_extractor_node_list = FileExtractorNodeSerializer(many=True, read_only=True)
    audio_transcription_node_list = AudioTranscriptionNodeSerializer(
        many=True, read_only=True
    )
    edge_list = EdgeSerializer(many=True, read_only=True)
    conditional_edge_list = ConditionalEdgeSerializer(many=True, read_only=True)
    webhook_trigger_node_list = WebhookTriggerNodeSerializer(many=True, read_only=True)
    start_node_list = StartNodeSerializer(many=True, read_only=True)
    decision_table_node_list = DecisionTableNodeSerializer(many=True, read_only=True)
    classification_decision_table_node_list = ClassificationDecisionTableNodeSerializer(
        many=True, read_only=True
    )
    subgraph_node_list = SubGraphNodeSerializer(many=True, read_only=True)
    code_agent_node_list = CodeAgentNodeSerializer(many=True, read_only=True)
    end_node_list = EndNodeSerializer(many=True, read_only=True, source="end_node")
    telegram_trigger_node_list = TelegramTriggerNodeSerializer(
        many=True, read_only=True
    )
    schedule_trigger_node_list = ScheduleTriggerNodeSerializer(
        many=True, read_only=True
    )
    label_ids = serializers.PrimaryKeyRelatedField(
        many=True, source="labels", queryset=Label.objects.all(), required=False
    )
    graph_note_list = GraphNoteSerializer(many=True, read_only=True)
    save_version = serializers.IntegerField(required=True)

    class Meta:
        model = Graph
        fields = [
            "id",
            "uuid",
            "name",
            "metadata",
            "description",
            "crew_node_list",
            "python_node_list",
            "file_extractor_node_list",
            "audio_transcription_node_list",
            "edge_list",
            "conditional_edge_list",
            "webhook_trigger_node_list",
            "decision_table_node_list",
            "classification_decision_table_node_list",
            "subgraph_node_list",
            "code_agent_node_list",
            "start_node_list",
            "end_node_list",
            "time_to_live",
            "persistent_variables",
            "epicchat_enabled",
            "telegram_trigger_node_list",
            "schedule_trigger_node_list",
            "label_ids",
            "graph_note_list",
            "save_version",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None:
            self.fields["save_version"].required = False

    def create(self, validated_data):
        labels = validated_data.pop("labels", [])
        validated_data.pop("save_version", None)
        instance = super().create(validated_data)
        instance.labels.set(labels)
        return instance

    def update(self, instance, validated_data):
        labels = validated_data.pop("labels", None)

        if "save_version" not in validated_data:
            raise serializers.ValidationError(
                {"save_version": "This field is required for updates."}
            )
        expected_save_version = validated_data.pop("save_version")

        with transaction.atomic():
            Graph.increment_version_if_current(
                pk=instance.pk, expected=expected_save_version
            )
            instance.refresh_from_db(fields=["save_version"])
            instance = super().update(instance, validated_data)

        if labels is not None:
            instance.labels.set(labels)

        instance.refresh_from_db(fields=["save_version"])
        return instance
