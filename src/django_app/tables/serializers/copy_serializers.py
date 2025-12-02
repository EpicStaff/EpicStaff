from rest_framework import serializers
from tables.models import SourceCollection, Agent
from tables.services.import_services import TasksImportService, ToolsImportService
from tables.serializers.export_serializers import (
    AgentExportSerializer,
    CrewExportSerializer,
    GraphExportSerializer,
)
from tables.serializers.import_serializers import (
    AgentImportSerializer,
    CrewImportSerializer,
    GraphImportSerializer,
)
from tables.serializers.utils.mixins import (
    NestedAgentExportMixin,
    NestedCrewExportMixin,
)


class AgentCopySerializer(AgentExportSerializer):

    knowledge_collection = serializers.PrimaryKeyRelatedField(
        queryset=SourceCollection.objects.all(), allow_null=True, required=False
    )

    class Meta(AgentExportSerializer.Meta):
        exclude = None
        fields = "__all__"


class AgentCopyDeserializer(AgentImportSerializer):

    knowledge_collection = serializers.IntegerField(required=False, allow_null=True)

    class Meta(AgentImportSerializer.Meta):
        exclude = [
            "tags",
        ]

    def create(self, validated_data):
        knowledge_collection_id = validated_data.pop("knowledge_collection", None)
        agent = super().create(validated_data)
        agent.knowledge_collection = SourceCollection.objects.filter(
            collection_id=knowledge_collection_id
        ).first()
        agent.save()

        return agent


class NestedAgentCopySerializer(NestedAgentExportMixin, AgentCopySerializer):

    llm_config = serializers.SerializerMethodField()
    fcm_llm_config = serializers.SerializerMethodField()
    realtime_agent = serializers.SerializerMethodField()
    knowledge_collection = serializers.PrimaryKeyRelatedField(
        queryset=SourceCollection.objects.all(), allow_null=True, required=False
    )


class NestedAgentCopyDeserializer(AgentCopyDeserializer):

    tools = serializers.DictField(required=False)
    llm_config = serializers.IntegerField(required=False, allow_null=True)
    fcm_llm_config = serializers.IntegerField(required=False, allow_null=True)
    realtime_agent = serializers.IntegerField(required=False, allow_null=True)
    knowledge_collection = serializers.IntegerField(required=False, allow_null=True)


class CrewCopySerializer(CrewExportSerializer):

    agents = serializers.SerializerMethodField()
    knowledge_collection = serializers.PrimaryKeyRelatedField(
        queryset=SourceCollection.objects.all(), allow_null=True, required=False
    )

    agent_serializer_class = NestedAgentCopySerializer

    class Meta(CrewExportSerializer.Meta):
        exclude = ["id", "tags"]

    def get_agents(self, obj):
        agents = obj.agents.all().values_list("id", flat=True)
        return agents


class NestedCrewCopySerializer(NestedCrewExportMixin, CrewCopySerializer):

    tools = None
    llm_configs = None
    realtime_agents = None

    knowledge_collection = serializers.PrimaryKeyRelatedField(
        queryset=SourceCollection.objects.all(), allow_null=True, required=False
    )

    class Meta(CrewCopySerializer.Meta):
        exclude = ["tags"]


class CrewCopyDeserializer(CrewImportSerializer):

    agents = serializers.ListField(child=serializers.IntegerField(), required=False)
    knowledge_collection = serializers.IntegerField(required=False, allow_null=True)

    class Meta(CrewImportSerializer.Meta):
        exclude = ["id", "tags"]

    def create(self, validated_data):
        knowledge_collection_id = validated_data.pop("knowledge_collection", None)
        agent_ids = validated_data.pop("agents", [])
        agents = Agent.objects.filter(id__in=agent_ids)

        tools_data = validated_data.pop("tools", None)

        tasks = []
        tasks_data = validated_data.pop("tasks", [])
        tasks_service = TasksImportService()

        crew = super().create(validated_data)
        crew.knowledge_collection = SourceCollection.objects.filter(
            collection_id=knowledge_collection_id
        ).first()
        crew.agents.set(agents)
        crew.save()

        if tools_data:
            tools_service = ToolsImportService(tools_data)
            tools_service.create_tools()

        for t_data in tasks_data:
            tool_ids_data = t_data.pop("tools", {})
            agent_id = t_data.pop("agent", None)

            task = tasks_service.create_task(t_data, crew)

            for agent in agents:
                if agent.id == agent_id:
                    task.agent = agent
                    task.save()

            if tools_service:
                tools_service.assign_tools_to_task(task, tool_ids_data)

            tasks.append(task)

        for task, t_data in zip(tasks, tasks_data):
            context_ids = t_data.pop("context_tasks", [])
            tasks_service.add_task_context(task, context_ids)

        return crew


class NestedCrewCopyDeserializer(CrewCopyDeserializer):

    tools = None
    llm_configs = None
    realtime_agents = None

    agents = serializers.ListField(child=serializers.IntegerField(), required=False)
    knowledge_collection = serializers.IntegerField(required=False, allow_null=True)

    class Meta(CrewCopyDeserializer.Meta):
        exclude = ["tags"]
        extra_kwargs = {
            "id": {"read_only": False, "required": False, "validators": []},
        }


class GraphCopySerializer(GraphExportSerializer):

    crew_serializer_class = NestedCrewCopySerializer
    agent_serializer_class = NestedAgentCopySerializer


class GraphCopyDeserializer(GraphImportSerializer):

    crews = NestedCrewCopyDeserializer(
        many=True, required=False, allow_null=False, default=dict
    )
    agents = NestedAgentCopyDeserializer(
        many=True, required=False, allow_null=False, default=dict
    )

    crew_serializer_class = NestedCrewCopyDeserializer
    agent_serializer_class = NestedAgentCopyDeserializer
