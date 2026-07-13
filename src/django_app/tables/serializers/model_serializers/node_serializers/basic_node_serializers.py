from loguru import logger
from rest_framework import serializers

from tables.serializers.model_serializers.python_serializers import PythonCodeSerializer
from tables.models.crew_models import Crew
from tables.models.llm_models import LLMConfig
from tables.serializers.model_serializers.crew_serializers import (
    CrewSerializer,
)
from tables.models.graph_models import (
    AudioTranscriptionNode,
    CodeAgentNode,
    CrewNode,
    Edge,
    FileExtractorNode,
    Graph,
    PythonNode,
    SubGraphNode,
)
from tables.serializers.base_serializer import (
    BaseGraphEntityMixin,
    ContentHashWritableMixin,
)
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    resolve_active_org_id,
)
from tables.serializers.utils.mixins import (
    NestedPythonCodeMixin,
    assert_node_ref_in_graph,
)


class CrewNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    crew = CrewSerializer(read_only=True)
    crew_id = serializers.IntegerField(write_only=True)
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = CrewNode
        fields = "__all__"
        read_only_fields = ["crew"]

    def validate_crew_id(self, value):
        # Org isolation: the referenced crew must be in the caller's active org.
        # Out-of-org and non-existent ids are rejected identically (no leak).
        request = self.context.get("request")
        if request is None:
            # No request in context => org scope cannot be applied. Deny (fail-safe)
            # instead of allowing any crew, and log so the missing context surfaces.
            logger.warning(
                "CrewNodeSerializer.validate_crew_id was resolved without a request "
                "in the serializer context; rejecting crew_id because org scope "
                "cannot be applied. Construct the serializer with the request in "
                "its context."
            )
            raise serializers.ValidationError("Invalid crew_id: crew does not exist.")
        crews = Crew.objects.only("id").filter(org_id=resolve_active_org_id(request))
        if not crews.filter(id=value).exists():
            raise serializers.ValidationError("Invalid crew_id: crew does not exist.")
        return value

    def update(self, instance, validated_data):
        if "crew_id" in validated_data:
            instance.crew_id = validated_data["crew_id"]
        return super().update(instance, validated_data)


class PythonNodeSerializer(
    ContentHashWritableMixin, NestedPythonCodeMixin, serializers.ModelSerializer
):
    python_code = PythonCodeSerializer()
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = PythonNode
        fields = "__all__"


class FileExtractorNodeSerializer(
    ContentHashWritableMixin, serializers.ModelSerializer
):
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = FileExtractorNode
        fields = "__all__"


class AudioTranscriptionNodeSerializer(
    ContentHashWritableMixin, serializers.ModelSerializer
):
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = AudioTranscriptionNode
        fields = "__all__"


class CodeAgentNodeSerializer(serializers.ModelSerializer):
    # Org isolation: only an LLMConfig from the caller's active org may be referenced.
    llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(), required=False, allow_null=True
    )
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = CodeAgentNode
        fields = "__all__"


class EdgeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta(BaseGraphEntityMixin.Meta):
        model = Edge
        fields = "__all__"

    def validate(self, attrs):
        graph = attrs.get("graph") or getattr(self.instance, "graph", None)
        for field in ("start_node_id", "end_node_id"):
            node_id = attrs.get(field, getattr(self.instance, field, None))
            assert_node_ref_in_graph(node_id, graph, field)
        return attrs


class SubGraphNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    # Org isolation: the referenced sub-flow must be in the caller's active org.
    subgraph = OrgScopedPrimaryKeyRelatedField(
        queryset=Graph.objects.all(), required=False, allow_null=True
    )
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta(BaseGraphEntityMixin.Meta):
        model = SubGraphNode
        fields = "__all__"

    def validate(self, attrs):
        graph = attrs.get("graph") or getattr(self.instance, "graph", None)
        subgraph = attrs.get("subgraph") or getattr(self.instance, "subgraph", None)

        if graph and subgraph and graph == subgraph:
            raise serializers.ValidationError("Graph and subgraph cannot be the same.")

        return attrs

    def to_representation(self, instance):
        from tables.serializers.model_serializers.graph_serializers import (
            GraphLightSerializer,
        )

        data = super().to_representation(instance)
        data["subgraph_detail"] = GraphLightSerializer(instance.subgraph).data
        return data
