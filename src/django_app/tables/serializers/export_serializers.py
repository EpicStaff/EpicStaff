from enum import Enum
from rest_framework import serializers
from django.db.models import Prefetch

from tables.models.mcp_models import McpTool
from tables.models.crew_models import AgentConfiguredTools, AgentPythonCodeTools
from tables.models import (
    Agent,
    LLMConfig,
    PythonCodeTool,
    ToolConfig,
    PythonCode,
    Crew,
    Task,
    EmbeddingConfig,
    RealtimeAgent,
    RealtimeConfig,
    RealtimeTranscriptionConfig,
)
from tables.serializers.model_serializers import (
    GraphSerializer,
    CrewNodeSerializer,
    PythonNodeSerializer,
    ConditionalEdgeSerializer,
    FileExtractorNodeSerializer,
    EndNodeSerializer,
)
from tables.serializers.utils.mixins import (
    NestedAgentExportMixin,
    NestedCrewExportMixin,
)


class EntityType(str, Enum):
    AGENT = "Agent"
    CREW = "Project"
    GRAPH = "Flow"


class PythonCodeExportSerializer(serializers.ModelSerializer):

    class Meta:
        model = PythonCode
        fields = "__all__"


class PythonCodeToolExportSerializer(serializers.ModelSerializer):

    python_code = PythonCodeExportSerializer()

    class Meta:
        model = PythonCodeTool
        exclude = ["favorite"]


class ToolConfigExportSerializer(serializers.ModelSerializer):

    tool = serializers.SerializerMethodField()

    class Meta:
        model = ToolConfig
        fields = "__all__"

    def get_tool(self, instance):
        return instance.tool.name_alias

class McpToolExportSerilizer(serializers.ModelSerializer):
    class Meta:
        model = McpTool
        fields = "__all__"

class GeneralToolExportSerializer(serializers.Serializer):

    data = serializers.DictField(required=True)

    def to_representation(self, instance):
        tool_classes = (
            (PythonCodeTool, PythonCodeToolExportSerializer),
            (ToolConfig, ToolConfigExportSerializer),
            (McpTool, McpToolExportSerilizer)
        )
        tool = {}

        for tool_class, tool_serializer in tool_classes:
            if isinstance(instance, tool_class):
                tool = tool_serializer(instance).data

        if not tool:
            raise TypeError(
                f"Unsupported tool type for serialization: {type(instance)}"
            )

        return tool


class BaseConfigExportSerializer(serializers.ModelSerializer):

    model = serializers.SerializerMethodField()

    class Meta:
        abstract = True
        model = None
        exclude = ["api_key"]

    def get_model(self, config_instance):
        return config_instance.model.name


class EmbeddingConfigExportSerializer(BaseConfigExportSerializer):

    class Meta(BaseConfigExportSerializer.Meta):
        model = EmbeddingConfig


class LLMConfigExportSerializer(BaseConfigExportSerializer):

    class Meta(BaseConfigExportSerializer.Meta):
        model = LLMConfig


class RealtimeConfigExportSerializer(BaseConfigExportSerializer):

    class Meta(BaseConfigExportSerializer.Meta):
        model = RealtimeConfig
        exclude = ["api_key", "realtime_model"]

    def get_model(self, config_instance):
        return config_instance.realtime_model.name


class RealtimeTranscriptionConfigExportSerializer(BaseConfigExportSerializer):

    class Meta(BaseConfigExportSerializer.Meta):
        model = RealtimeTranscriptionConfig
        exclude = ["api_key", "realtime_transcription_model"]

    def get_model(self, config_instance):
        return config_instance.realtime_transcription_model.name


class RealtimeAgentExportSerializer(serializers.ModelSerializer):

    realtime_config = RealtimeConfigExportSerializer()
    realtime_transcription_config = RealtimeTranscriptionConfigExportSerializer()

    class Meta:
        model = RealtimeAgent
        exclude = ["agent"]


class NestedRealtimeAgentExportSerializer(RealtimeAgentExportSerializer):

    realtime_config = serializers.SerializerMethodField()
    realtime_transcription_config = serializers.SerializerMethodField()
    id = serializers.SerializerMethodField()

    def get_realtime_config(self, realtime_agent: RealtimeAgent):
        if realtime_agent.realtime_config:
            return realtime_agent.realtime_config.id

    def get_realtime_transcription_config(self, realtime_agent: RealtimeAgent):
        if realtime_agent.realtime_transcription_config:
            return realtime_agent.realtime_transcription_config.id

    def get_id(self, realtime_agent: RealtimeAgent):
        return realtime_agent.pk


class RealtimeDataExportSerializer(serializers.Serializer):

    realtime_configs = RealtimeConfigExportSerializer(many=True)
    realtime_transcription_configs = RealtimeTranscriptionConfigExportSerializer(
        many=True
    )
    realtime_agents = NestedRealtimeAgentExportSerializer(many=True)


class AgentExportSerializer(serializers.ModelSerializer):

    tools = serializers.SerializerMethodField()
    llm_config = LLMConfigExportSerializer()
    fcm_llm_config = LLMConfigExportSerializer()
    realtime_agent = RealtimeAgentExportSerializer()
    entity_type = serializers.SerializerMethodField()

    class Meta:
        model = Agent
        exclude = [
            "knowledge_collection",
        ]

    def get_tools(self, agent: Agent) -> list[dict]:
        return {
            "python_tools": GeneralToolExportSerializer(
                instance=PythonCodeTool.objects.filter(
                    agentpythoncodetools__agent_id=agent.pk
                ),
                many=True,
            ).data,
            "configured_tools": GeneralToolExportSerializer(
                instance=ToolConfig.objects.filter(
                    agentconfiguredtools__agent_id=agent.pk
                ),
                many=True,
            ).data,
            "mcp_tools": GeneralToolExportSerializer(
                instance=McpTool.objects.filter(agentmcptools__agent_id=agent.pk),
                many=True,
            ).data,
        }

    def get_entity_type(self, *args, **kwargs):
        return EntityType.AGENT.value


class NestedAgentExportSerializer(NestedAgentExportMixin, AgentExportSerializer):

    llm_config = serializers.SerializerMethodField()
    fcm_llm_config = serializers.SerializerMethodField()
    realtime_agent = serializers.SerializerMethodField()

    def get_tools(self, agent):
        return {
            "python_tools": list(
                PythonCodeTool.objects.filter(
                    agentpythoncodetools__agent_id=agent.pk
                ).values_list("id", flat=True)
            ),
            "configured_tools": list(
                ToolConfig.objects.filter(
                    agentconfiguredtools__agent_id=agent.pk
                ).values_list("id", flat=True)
            ),
            "mcp_tools": list(
                McpTool.objects.filter(
                    agentmcptools__agent_id=agent.pk
                ).values_list("id", flat=True)
            ),
        }

    def get_llm_config(self, agent: Agent):
        if agent.llm_config:
            return agent.llm_config.id

    def get_fcm_llm_config(self, agent: Agent):
        if agent.fcm_llm_config:
            return agent.fcm_llm_config.id

    def get_realtime_agent(self, agent: Agent):
        if agent.realtime_agent:
            return agent.realtime_agent.pk


class TaskExportSerializer(serializers.ModelSerializer):

    tools = serializers.SerializerMethodField()
    context_tasks = serializers.SerializerMethodField()

    class Meta:
        model = Task
        exclude = ["crew"]

    def get_tools(self, task: Task) -> list[dict]:
        return {
            "python_tools": list(
                task.task_python_code_tool_list.all().values_list("tool_id", flat=True)
            ),
            "configured_tools": list(
                task.task_configured_tool_list.all().values_list("tool_id", flat=True)
            ),
            "mcp_tools": list(
                task.task_mcp_tool_list.all().values_list("tool_id", flat=True)
            ),
        }

    def get_context_tasks(self, task: Task):
        return list(task.task_context_list.values_list("context_id", flat=True))


class CrewExportSerializer(serializers.ModelSerializer):

    agents = serializers.SerializerMethodField()
    tasks = serializers.SerializerMethodField()
    tools = serializers.SerializerMethodField()
    realtime_agents = serializers.SerializerMethodField()
    entity_type = serializers.SerializerMethodField()

    embedding_config = EmbeddingConfigExportSerializer(required=False, allow_null=True)

    memory_llm_config = serializers.SerializerMethodField()
    manager_llm_config = serializers.SerializerMethodField()
    planning_llm_config = serializers.SerializerMethodField()

    llm_configs = serializers.SerializerMethodField()

    agent_serializer_class = NestedAgentExportSerializer

    class Meta:
        model = Crew
        exclude = ["id", "tags", "knowledge_collection"]

    def get_tasks(self, crew: Crew):
        tasks = crew.task_set.all()
        return TaskExportSerializer(tasks, many=True).data

    def get_agents(self, crew: Crew):
        agents = crew.get_agents()
        return self.agent_serializer_class(agents, many=True).data

    def get_tools(self, crew: Crew):
        agent_configured_tools = ToolConfig.objects.filter(
            agentconfiguredtools__agent__crew=crew
        ).distinct()
        agent_python_tools = PythonCodeTool.objects.filter(
            agentpythoncodetools__agent__crew=crew
        ).distinct()
        agent_mcp_tools = McpTool.objects.filter(
            agentmcptools__agent__crew=crew
        ).distinct()

        task_configured_tools = ToolConfig.objects.filter(
            taskconfiguredtools__task__crew=crew
        ).distinct()
        task_python_tools = PythonCodeTool.objects.filter(
            taskpythoncodetools__task__crew=crew
        ).distinct()
        task_mcp_tools = McpTool.objects.filter(
            taskmcptools__task__crew=crew
        ).distinct()

        all_configured_tools = agent_configured_tools.union(task_configured_tools)
        all_python_tools = agent_python_tools.union(task_python_tools)
        all_mcp_tools = agent_mcp_tools.union(task_mcp_tools)

        return {
            "configured_tools": GeneralToolExportSerializer(
                instance=all_configured_tools, many=True
            ).data,
            "python_tools": GeneralToolExportSerializer(
                instance=all_python_tools, many=True
            ).data,
            "mcp_tools": GeneralToolExportSerializer(
                instance=all_mcp_tools, many=True
            ).data,
        }

    def get_memory_llm_config(self, crew: Crew):
        if crew.memory_llm_config:
            return crew.memory_llm_config.id

    def get_manager_llm_config(self, crew: Crew):
        if crew.manager_llm_config:
            return crew.manager_llm_config.id

    def get_planning_llm_config(self, crew: Crew):
        if crew.planning_llm_config:
            return crew.planning_llm_config.id

    def get_llm_configs(self, crew: Crew):
        config_ids = (
            crew.agents.exclude(llm_config__isnull=True, fcm_llm_config__isnull=True)
            .values_list("llm_config", "fcm_llm_config")
            .distinct()
        )

        unique_ids = set()

        if crew.memory_llm_config:
            unique_ids.add(crew.memory_llm_config.id)
        if crew.manager_llm_config:
            unique_ids.add(crew.manager_llm_config.id)
        if crew.planning_llm_config:
            unique_ids.add(crew.planning_llm_config.id)

        for llm_id, fcm_id in config_ids:
            if llm_id:
                unique_ids.add(llm_id)
            if fcm_id:
                unique_ids.add(fcm_id)

        llm_configs = LLMConfig.objects.filter(id__in=unique_ids)
        serializer = LLMConfigExportSerializer(instance=llm_configs, many=True)
        return serializer.data

    def get_realtime_agents(self, crew: Crew):
        agent_ids = crew.agents.values_list("id", flat=True)

        realtime_agents = (
            RealtimeAgent.objects.filter(agent_id__in=agent_ids)
            .select_related("agent")
            .prefetch_related(
                Prefetch(
                    "realtime_config",
                    queryset=RealtimeConfig.objects.select_related("realtime_model"),
                ),
                Prefetch(
                    "realtime_transcription_config",
                    queryset=RealtimeTranscriptionConfig.objects.select_related(
                        "realtime_transcription_model"
                    ),
                ),
            )
            .distinct()
        )

        unique_configs = set()
        unique_transcription_configs = set()

        for rt_agent in realtime_agents:
            if rt_agent.realtime_config:
                unique_configs.add(rt_agent.realtime_config)
            if rt_agent.realtime_transcription_config:
                unique_transcription_configs.add(rt_agent.realtime_transcription_config)

        data = {
            "realtime_agents": realtime_agents,
            "realtime_configs": list(unique_configs),
            "realtime_transcription_configs": list(unique_transcription_configs),
        }
        serializer = RealtimeDataExportSerializer(data)
        return serializer.data

    def get_entity_type(self, *args, **kwargs):
        return EntityType.CREW.value


class NestedCrewExportSerializer(NestedCrewExportMixin, CrewExportSerializer):

    tools = None
    llm_configs = None
    realtime_agents = None

    class Meta(CrewExportSerializer.Meta):
        exclude = ["tags", "knowledge_collection"]


class CrewNodeExportSerializer(CrewNodeSerializer):

    crew_id = serializers.IntegerField(read_only=True)

    class Meta(CrewNodeSerializer.Meta):
        fields = ["crew_id", "node_name", "input_map", "output_variable_path"]
        read_only_fields = []


class PythonNodeExportSerializer(PythonNodeSerializer):

    python_code = PythonCodeExportSerializer()


class ConditionalEdgeExportSerializer(ConditionalEdgeSerializer):

    python_code = PythonCodeExportSerializer()


class GraphExportSerializer(GraphSerializer):

    crew_node_list = CrewNodeExportSerializer(many=True)
    python_node_list = PythonNodeExportSerializer(many=True)
    conditional_edge_list = ConditionalEdgeExportSerializer(many=True)
    file_extractor_node_list = FileExtractorNodeSerializer(many=True)
    end_node_list = EndNodeSerializer(many=True, source="end_node")
    crews = serializers.SerializerMethodField()
    agents = serializers.SerializerMethodField()
    tools = serializers.SerializerMethodField()
    llm_configs = serializers.SerializerMethodField()
    realtime_agents = serializers.SerializerMethodField()
    entity_type = serializers.SerializerMethodField()

    crew_serializer_class = NestedCrewExportSerializer
    agent_serializer_class = NestedAgentExportSerializer

    class Meta(GraphSerializer.Meta):
        fields = "__all__"

    def get_crews(self, graph):
        unique_crews = (
            graph.crew_node_list.order_by("crew")
            .distinct("crew")
            .values_list("crew", flat=True)
        )
        crews = Crew.objects.filter(id__in=unique_crews)
        serializer = self.crew_serializer_class(instance=crews, many=True)
        return serializer.data

    def get_agents(self, graph):
        agents = Agent.objects.filter(crew__crewnode__graph=graph).distinct()
        serializer = self.agent_serializer_class(instance=agents, many=True)
        return serializer.data

    def get_tools(self, graph):
        agent_configured_tools = ToolConfig.objects.filter(
            agentconfiguredtools__agent__crew__crewnode__graph=graph
        ).distinct()
        agent_python_tools = PythonCodeTool.objects.filter(
            agentpythoncodetools__agent__crew__crewnode__graph=graph
        ).distinct()
        agent_mcp_tools = McpTool.objects.filter(
            agentmcptools__agent__crew__crewnode__graph=graph
        ).distinct()

        task_configured_tools = ToolConfig.objects.filter(
            taskconfiguredtools__task__crew__crewnode__graph=graph
        ).distinct()
        task_python_tools = PythonCodeTool.objects.filter(
            taskpythoncodetools__task__crew__crewnode__graph=graph
        ).distinct()
        task_mcp_tools = McpTool.objects.filter(
            taskmcptools__task__crew__crewnode__graph=graph
        ).distinct()

        
        all_configured_tools = agent_configured_tools.union(task_configured_tools)
        all_python_tools = agent_python_tools.union(task_python_tools)
        all_mcp_tools = agent_mcp_tools.union(task_mcp_tools)

        return {
            "configured_tools": GeneralToolExportSerializer(
                instance=all_configured_tools, many=True
            ).data,
            "python_tools": list(
                GeneralToolExportSerializer(instance=all_python_tools, many=True).data
            ),
            "mcp_tools": list(
                GeneralToolExportSerializer(instance=all_mcp_tools, many=True).data
            )
        }

    def get_llm_configs(self, graph):
        unique_ids = set()

        crew_ids = Crew.objects.filter(crewnode__graph=graph).values_list(
            "memory_llm_config", "manager_llm_config", "planning_llm_config"
        )
        for memory_id, manager_id, planning_id in crew_ids:
            if memory_id:
                unique_ids.add(memory_id)
            if manager_id:
                unique_ids.add(manager_id)
            if planning_id:
                unique_ids.add(planning_id)

        agent_config_ids = (
            Agent.objects.filter(crew__crewnode__graph=graph)
            .exclude(llm_config__isnull=True, fcm_llm_config__isnull=True)
            .values_list("llm_config", "fcm_llm_config")
            .distinct()
        )
        for llm_id, fcm_id in agent_config_ids:
            if llm_id:
                unique_ids.add(llm_id)
            if fcm_id:
                unique_ids.add(fcm_id)

        llm_configs = LLMConfig.objects.filter(id__in=unique_ids)
        serializer = LLMConfigExportSerializer(instance=llm_configs, many=True)
        return serializer.data

    def get_realtime_agents(self, graph: Crew):
        agent_ids = (
            Agent.objects.filter(crew__crewnode__graph=graph)
            .distinct()
            .values_list("id", flat=True)
        )

        realtime_agents = (
            RealtimeAgent.objects.filter(agent_id__in=agent_ids)
            .select_related("agent")
            .prefetch_related(
                Prefetch(
                    "realtime_config",
                    queryset=RealtimeConfig.objects.select_related("realtime_model"),
                ),
                Prefetch(
                    "realtime_transcription_config",
                    queryset=RealtimeTranscriptionConfig.objects.select_related(
                        "realtime_transcription_model"
                    ),
                ),
            )
            .distinct()
        )

        unique_configs = set()
        unique_transcription_configs = set()

        for rt_agent in realtime_agents:
            if rt_agent.realtime_config:
                unique_configs.add(rt_agent.realtime_config)
            if rt_agent.realtime_transcription_config:
                unique_transcription_configs.add(rt_agent.realtime_transcription_config)

        data = {
            "realtime_agents": realtime_agents,
            "realtime_configs": list(unique_configs),
            "realtime_transcription_configs": list(unique_transcription_configs),
        }
        serializer = RealtimeDataExportSerializer(data)
        return serializer.data

    def get_entity_type(self, *args, **kwargs):
        return EntityType.GRAPH.value
