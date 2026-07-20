from tables.models.crew_models import (
    Agent,
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeTools,
    AgentPythonCodeToolConfigs,
)
from tables.models.knowledge_models.naive_rag_models import NaiveRagSearchConfig
from tables.models.realtime_models import RealtimeAgent
from tables.services.copy_services.base_copy_service import BaseCopyService


class AgentCopyService(BaseCopyService):
    """Copy service for Agent entities.

    Duplicates all scalar configuration fields. Tool relationships
    (configured tools, python code tools, MCP tools) are re-linked
    to the same tool objects -- tools are not cloned. If a RealtimeAgent
    is attached, it is fully duplicated.

    Unlike other copy services, the ``name`` parameter maps to the
    agent's ``role`` field and no unique-name resolution is performed.
    """

    def copy(
        self, agent: Agent, name: str | None = None, org_id: int | None = None
    ) -> Agent:
        new_agent = Agent.objects.create(
            role=name if name else agent.role,
            goal=agent.goal,
            backstory=agent.backstory,
            max_iter=agent.max_iter,
            max_rpm=agent.max_rpm,
            max_execution_time=agent.max_execution_time,
            memory=agent.memory,
            allow_delegation=agent.allow_delegation,
            cache=agent.cache,
            allow_code_execution=agent.allow_code_execution,
            max_retry_limit=agent.max_retry_limit,
            respect_context_window=agent.respect_context_window,
            default_temperature=agent.default_temperature,
            llm_config=agent.llm_config,
            fcm_llm_config=agent.fcm_llm_config,
            knowledge_collection=agent.knowledge_collection,
            org_id=org_id if org_id is not None else agent.org_id,
        )

        for row in agent.configured_tools.all():
            AgentConfiguredTools.objects.create(
                agent=new_agent, toolconfig=row.toolconfig
            )

        for row in agent.python_code_tools.all():
            AgentPythonCodeTools.objects.create(
                agent=new_agent, pythoncodetool=row.pythoncodetool
            )

        for row in agent.python_code_tool_configs.all():
            AgentPythonCodeToolConfigs.objects.create(
                agent=new_agent, pythoncodetoolconfig=row.pythoncodetoolconfig
            )

        for row in agent.mcp_tools.all():
            AgentMcpTools.objects.create(agent=new_agent, mcptool=row.mcptool)

        try:
            realtime_agent = agent.realtime_agent
            RealtimeAgent.objects.create(
                agent=new_agent,
                wake_word=realtime_agent.wake_word,
                stop_prompt=realtime_agent.stop_prompt,
                language=realtime_agent.language,
                voice_recognition_prompt=realtime_agent.voice_recognition_prompt,
                voice=realtime_agent.voice,
                realtime_config=realtime_agent.realtime_config,
                realtime_transcription_config=realtime_agent.realtime_transcription_config,
            )
        except RealtimeAgent.DoesNotExist:
            pass

        try:
            search_config = agent.naive_search_config
            NaiveRagSearchConfig.objects.create(
                agent=new_agent,
                search_limit=search_config.search_limit,
                similarity_threshold=search_config.similarity_threshold,
            )
        except NaiveRagSearchConfig.DoesNotExist:
            pass

        return new_agent
