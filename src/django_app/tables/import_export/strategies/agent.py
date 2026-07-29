from copy import deepcopy

from django.db.models import Q

from tables.models import (
    Agent,
    RealtimeAgent,
    LLMConfig,
    AgentPythonCodeTools,
    AgentMcpTools,
    PythonCodeTool,
    McpTool,
)
from tables.models.realtime_models import (
    OpenAIRealtimeConfig,
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
)
from tables.models.knowledge_models.naive_rag_models import NaiveRagSearchConfig
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.agent import AgentImportSerializer
from tables.import_export.serializers.rag_configs import (
    NaiveRagSearchConfigImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.utils import create_filters


class AgentStrategy(EntityImportExportStrategy):
    entity_type = EntityType.AGENT
    serializer_class = AgentImportSerializer

    def get_instance(self, entity_id: int):
        return Agent.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: Agent) -> dict:
        return {"id": instance.id, "name": instance.role}

    def extract_dependencies_from_instance(self, instance: Agent):
        deps = {}

        llm_configs = set()
        if instance.llm_config:
            llm_configs.add(instance.llm_config.id)
        if instance.fcm_llm_config:
            llm_configs.add(instance.fcm_llm_config.id)

        deps[EntityType.LLM_CONFIG] = llm_configs
        deps[EntityType.PYTHON_CODE_TOOL] = instance.python_code_tools.values_list(
            "pythoncodetool_id", flat=True
        )
        deps[EntityType.MCP_TOOL] = instance.mcp_tools.values_list(
            "mcptool_id", flat=True
        )

        # Provider config dependencies (new architecture)
        try:
            rt_agent = instance.realtime_agent
            if rt_agent.openai_config_id:
                deps[EntityType.OPENAI_REALTIME_CONFIG] = [rt_agent.openai_config_id]
            if rt_agent.elevenlabs_config_id:
                deps[EntityType.ELEVENLABS_REALTIME_CONFIG] = [
                    rt_agent.elevenlabs_config_id
                ]
            if rt_agent.gemini_config_id:
                deps[EntityType.GEMINI_REALTIME_CONFIG] = [rt_agent.gemini_config_id]
        except RealtimeAgent.DoesNotExist:
            pass

        return deps

    def export_entity(self, instance: Agent) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> Agent:
        org_id = kwargs.get("org_id")
        llm_config, fcm_llm_config = self._get_llm_configs(data, id_mapper)
        python_tools, mcp_tools = self._get_tools(data, id_mapper)
        realtime_data = data.pop("realtime_agent", None)
        naive_search_config_data = data.pop("naive_search_config", None)

        agent = self._create_agent(data, org_id)
        self._assign_tools(agent, python_tools, mcp_tools)
        self._create_realtime_agent(agent, realtime_data, id_mapper)
        self._create_naive_search_config(agent, naive_search_config_data)

        agent.llm_config = llm_config
        agent.fcm_llm_config = fcm_llm_config
        agent.save()

        return agent

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int = None
    ) -> Agent:
        """Shallow search of existing agent"""
        data_copy = deepcopy(data)
        data_copy.pop("id", None)

        llm_config, fcm_llm_config = self._get_llm_configs(data_copy, id_mapper)
        python_tools, mcp_tools = self._get_tools(data_copy, id_mapper)

        data_copy.pop("realtime_agent", None)
        data_copy.pop("naive_search_config", None)

        filters, null_filters = create_filters(data_copy)

        potential_candidates = (
            Agent.objects.filter(**filters, **null_filters)
            .filter(self.get_org_scope_q(org_id))
            .select_related("llm_config", "fcm_llm_config")
            .prefetch_related("python_code_tools", "mcp_tools")
        ).all()

        existing = None
        for agent in potential_candidates:
            # If there are configs and agent has no configs - skip
            if not agent.llm_config and llm_config:
                continue
            if not agent.fcm_llm_config and fcm_llm_config:
                continue
            if agent.python_code_tools.count() != len(python_tools):
                continue
            if agent.mcp_tools.count() != len(mcp_tools):
                continue

            # if any name of llm_config does not match - skip
            if llm_config and not (
                (agent.llm_config.custom_name == llm_config.custom_name)
                and (agent.llm_config.model.name == llm_config.model.name)
                and (
                    agent.llm_config.model.llm_provider.name
                    == llm_config.model.llm_provider.name
                )
            ):
                continue

            # if any name of fcm_llm_config does not match - skip
            if fcm_llm_config and not (
                (agent.fcm_llm_config.custom_name == fcm_llm_config.custom_name)
                and (agent.fcm_llm_config.model.name == fcm_llm_config.model.name)
                and (
                    agent.fcm_llm_config.model.llm_provider.name
                    == fcm_llm_config.model.llm_provider.name
                )
            ):
                continue

            python_tool_names = [tool.name for tool in python_tools]
            mcp_tool_names = [tool.name for tool in mcp_tools]
            current_python_tool_names = list(
                agent.python_code_tools.values_list("pythoncodetool__name", flat=True)
            )
            current_mcp_tool_names = list(
                agent.mcp_tools.values_list("mcptool__name", flat=True)
            )

            python_tools_match = set(current_python_tool_names) == set(
                python_tool_names
            )
            mcp_tools_match = set(current_mcp_tool_names) == set(mcp_tool_names)

            # Check just tool names to avoid deep comparison
            if not python_tools_match or not mcp_tools_match:
                continue

            existing = agent
            break

        return existing

    def get_org_scope_q(self, org_id: int) -> Q:
        if org_id is None:
            return Q()
        return Q(org_id=org_id)

    def _get_llm_configs(self, data: dict, id_mapper: IDMapper):
        old_llm_config_id = data.pop("llm_config", None)
        old_fcm_llm_config_id = data.pop("fcm_llm_config", None)

        llm_config_id = id_mapper.get_or_none(EntityType.LLM_CONFIG, old_llm_config_id)
        fcm_llm_config_id = id_mapper.get_or_none(
            EntityType.LLM_CONFIG, old_fcm_llm_config_id
        )

        llm_config = None
        fcm_llm_config = None

        if llm_config_id:
            llm_config = LLMConfig.objects.get(id=llm_config_id)
        if fcm_llm_config_id:
            fcm_llm_config = LLMConfig.objects.get(id=fcm_llm_config_id)

        return llm_config, fcm_llm_config

    def _get_tools(self, data: dict, id_mapper: IDMapper):
        tools = data.pop("tools", {})

        python_tool_ids = [
            id_mapper.get_or_none(EntityType.PYTHON_CODE_TOOL, tool_id)
            for tool_id in tools.get(EntityType.PYTHON_CODE_TOOL, [])
        ]
        python_tools = PythonCodeTool.objects.filter(id__in=python_tool_ids)

        mcp_tool_ids = [
            id_mapper.get_or_none(EntityType.MCP_TOOL, tool_id)
            for tool_id in tools.get(EntityType.MCP_TOOL, [])
        ]
        mcp_tools = McpTool.objects.filter(id__in=mcp_tool_ids)

        return python_tools, mcp_tools

    def _create_agent(self, data: dict, org_id) -> Agent:
        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.save(org_id=org_id)

    def _assign_tools(self, agent: Agent, python_tools: list, mcp_tools: list):
        AgentPythonCodeTools.objects.bulk_create(
            [
                AgentPythonCodeTools(agent=agent, pythoncodetool_id=tool.id)
                for tool in python_tools
            ]
        )
        AgentMcpTools.objects.bulk_create(
            [AgentMcpTools(agent=agent, mcptool_id=tool.id) for tool in mcp_tools]
        )

    def _create_realtime_agent(self, agent, data, id_mapper: IDMapper):
        if not data:
            return

        # Strip any legacy fields from old exports that no longer exist on the model
        data.pop("realtime_config", None)
        data.pop("realtime_transcription_config", None)
        data.pop("language", None)
        data.pop("voice_recognition_prompt", None)

        # Resolve new provider config FKs
        old_openai_id = data.pop("openai_config", None)
        old_elevenlabs_id = data.pop("elevenlabs_config", None)
        old_gemini_id = data.pop("gemini_config", None)

        openai_config = (
            OpenAIRealtimeConfig.objects.filter(
                id=id_mapper.get_or_none(
                    EntityType.OPENAI_REALTIME_CONFIG, old_openai_id
                )
            ).first()
            if old_openai_id
            else None
        )

        elevenlabs_config = (
            ElevenLabsRealtimeConfig.objects.filter(
                id=id_mapper.get_or_none(
                    EntityType.ELEVENLABS_REALTIME_CONFIG, old_elevenlabs_id
                )
            ).first()
            if old_elevenlabs_id
            else None
        )

        gemini_config = (
            GeminiRealtimeConfig.objects.filter(
                id=id_mapper.get_or_none(
                    EntityType.GEMINI_REALTIME_CONFIG, old_gemini_id
                )
            ).first()
            if old_gemini_id
            else None
        )

        realtime_agent = RealtimeAgent.objects.create(
            agent=agent,
            openai_config=openai_config,
            elevenlabs_config=elevenlabs_config,
            gemini_config=gemini_config,
            **data,
        )
        return realtime_agent

    def _create_naive_search_config(self, agent, data) -> NaiveRagSearchConfig:
        if not data:
            return

        data["agent"] = agent.id
        serializer = NaiveRagSearchConfigImportSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.save()
