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
    KnowledgeNode,
    PythonNode,
    SubGraphNode,
)
from tables.models.knowledge_models import SourceCollection
from tables.serializers.knowledge_serializers import NestedSearchConfigSerializer
from tables.services.rag_assignment_service import SearchConfigService
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


class KnowledgeNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    """Plain node serializer (no search configs). Base for bulk-save, which
    persists the config blocks separately via its saveable."""

    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())
    source_collection = OrgScopedPrimaryKeyRelatedField(
        queryset=SourceCollection.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = KnowledgeNode
        fields = "__all__"

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # Merge with the instance so partial PATCH/bulk updates validate against the
        # final state, not just the changed fields.
        rag_type = attrs.get("rag_type", getattr(self.instance, "rag_type", None))
        source_collection = attrs.get(
            "source_collection", getattr(self.instance, "source_collection", None)
        )
        # A rag_type is only meaningful together with its own collection; the node
        # searches source_collection with rag_type's implementation, so they must match.
        if rag_type is not None:
            if source_collection is None:
                raise serializers.ValidationError(
                    {"source_collection": "Required when rag_type is set."}
                )
            if rag_type.source_collection_id != source_collection.pk:
                raise serializers.ValidationError(
                    {
                        "rag_type": "rag_type must belong to the node's source_collection."
                    }
                )
        return attrs


class KnowledgeNodeReadSerializer(KnowledgeNodeSerializer):
    """Adds the nested read-back of node-bound search configs (mirror of
    AgentReadSerializer.search_configs). Used for list/retrieve and inside
    GraphSerializer.knowledge_node_list."""

    search_configs = serializers.SerializerMethodField()

    def get_search_configs(self, node: KnowledgeNode) -> dict | None:
        return SearchConfigService.get_node_search_configs(node)


class KnowledgeNodeWriteSerializer(KnowledgeNodeSerializer):
    """Accepts a partial nested `search_configs` block and merges it into the
    node-bound config rows (mirror of AgentWriteSerializer). Only provided
    fields are touched — the FE may send just what changed."""

    search_configs = NestedSearchConfigSerializer(required=False, allow_null=True)

    def create(self, validated_data):
        search_configs_data = validated_data.pop("search_configs", None)
        node = super().create(validated_data)
        if search_configs_data:
            SearchConfigService.apply_node_search_configs(node, search_configs_data)
        return node

    def update(self, instance, validated_data):
        search_configs_data = validated_data.pop("search_configs", None)
        node = super().update(instance, validated_data)
        if search_configs_data:
            SearchConfigService.apply_node_search_configs(node, search_configs_data)
            node.refresh_from_db()
        return node

    def to_representation(self, instance):
        """Return the persisted nested config (read format), not the raw input."""
        data = super().to_representation(instance)
        data["search_configs"] = SearchConfigService.get_node_search_configs(instance)
        return data


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
