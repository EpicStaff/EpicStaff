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
    AgentNodeSerializer,
    AudioTranscriptionNodeSerializer,
    CodeAgentNodeSerializer,
    CrewNodeSerializer,
    EdgeSerializer,
    FileExtractorNodeSerializer,
    PythonNodeSerializer,
    SubGraphNodeSerializer,
    TaskNodeSerializer,
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
)
from tables.models.label_models import Label
from tables.serializers.base_serializer import BaseGraphEntityMixin
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
)


class GraphNoteSerializer(BaseGraphEntityMixin, serializers.ModelSerializer):
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta(BaseGraphEntityMixin.Meta):
        model = GraphNote
        fields = "__all__"


class GraphSessionMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphSessionMessage
        fields = "__all__"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        message_data = data.get("message_data") or {}
        if message_data.get("message_type") != "subgraph_start":
            return data

        exec_id = message_data.get("subgraph_execution_id")
        if not exec_id:
            return data

        subtree_messages = list(
            GraphSessionMessage.objects.filter(
                session_id=instance.session_id,
                message_data__subgraph_execution_ids__contains=[exec_id],
            )
            .exclude(id=instance.id)
            .values("parent_subgraph_execution_id", "message_data", "name")
        )

        exec_to_subgraph_id = {exec_id: message_data.get("subgraph_id")}
        counts_by_exec_id: dict[str, dict[str, int]] = {}
        seen_code_agent_streams = set()
        for msg in subtree_messages:
            msg_data = msg["message_data"] or {}
            msg_type = msg_data.get("message_type")
            if not msg_type:
                continue

            if msg_type == "subgraph_start":
                child_exec = msg_data.get("subgraph_execution_id")
                child_sgid = msg_data.get("subgraph_id")
                if child_exec and child_sgid is not None:
                    exec_to_subgraph_id[child_exec] = child_sgid

            parent_exec = msg["parent_subgraph_execution_id"]
            if not parent_exec:
                continue
            parent_exec = str(parent_exec)

            if msg_type == "code_agent_stream":
                dedup_key = (parent_exec, msg["name"])
                if dedup_key in seen_code_agent_streams:
                    continue
                seen_code_agent_streams.add(dedup_key)

            per_type = counts_by_exec_id.setdefault(parent_exec, {})
            per_type[msg_type] = per_type.get(msg_type, 0) + 1

        messages_count_by_subgraph: dict[int, dict[str, int]] = {}
        for e_id, per_type in counts_by_exec_id.items():
            sgid = exec_to_subgraph_id.get(e_id)
            if sgid is None:
                continue
            agg = messages_count_by_subgraph.setdefault(sgid, {})
            for msg_type, count in per_type.items():
                agg[msg_type] = agg.get(msg_type, 0) + count

        data["message_data"] = {
            **message_data,
            "messages_count_by_subgraph": messages_count_by_subgraph,
        }
        return data


class GraphOrganizationSerializer(serializers.ModelSerializer):
    # Read-only: org is derived from graph.org and the row is created
    # alongside its graph (see GraphViewSet.perform_create), so this
    # serializer only ever needs to expose the current state.
    class Meta:
        model = GraphOrganization
        fields = ["id", "graph", "persistent_variables", "user_variables"]
        read_only_fields = ["id", "graph", "persistent_variables", "user_variables"]


class GraphOrganizationUserSerializer(serializers.ModelSerializer):
    # TODO refactor to use user_variable for persistent variables
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
    task_node_list = TaskNodeSerializer(many=True, read_only=True)
    agent_node_list = AgentNodeSerializer(many=True, read_only=True)
    end_node_list = EndNodeSerializer(many=True, read_only=True, source="end_node")
    telegram_trigger_node_list = TelegramTriggerNodeSerializer(
        many=True, read_only=True
    )
    schedule_trigger_node_list = ScheduleTriggerNodeSerializer(
        many=True, read_only=True
    )
    label_ids = OrgScopedPrimaryKeyRelatedField(
        many=True,
        source="labels",
        queryset=Label.objects.filter(scope=Label.Scope.FLOW),
        required=False,
    )
    graph_note_list = GraphNoteSerializer(many=True, read_only=True)
    save_version = serializers.IntegerField(required=True)
    name = serializers.CharField(
        validators=[
            OrgScopedUniqueValidator(
                queryset=Graph.objects.all(),
                message="A flow with this name already exists.",
            )
        ]
    )

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
            "task_node_list",
            "agent_node_list",
            "start_node_list",
            "end_node_list",
            "time_to_live",
            "enable_persistent_variables",
            "epicchat_enabled",
            "telegram_trigger_node_list",
            "schedule_trigger_node_list",
            "label_ids",
            "graph_note_list",
            "save_version",
        ]
        # Derived on Domain save — never set directly by the client.
        read_only_fields = ["enable_persistent_variables"]

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
