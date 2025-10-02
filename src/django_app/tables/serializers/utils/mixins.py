from tables.models import Agent


class NestedAgentExportMixin:
    """
    A mixin that defines methods for exporting `Agent` fields data when
    agent is being used as part of another entity in serializer.

    Feilds that can be defined in a child class:
        `tools`: dictionary where `key` is tools name and `value` is list of tool IDs
        `llm_config`: integer field
        `fcm_llm_config`: integer field
        `realtime_agent`: integer field

    Methods:
        `get_tools`: returns lists of IDs for each tool type that agent has in database
        `get_llm_config`: returns an ID of agent's LLMConfig
        `get_fcm_llm_config`: returns an ID of agent's FCM LLMConfig
        `get_realtime_agent`: returns an ID of realtime agent that is related to agent
    """

    def get_tools(self, agent):
        return {
            "python_tools": list(
                agent.python_code_tools.all().values_list("id", flat=True)
            ),
            "configured_tools": list(
                agent.configured_tools.all().values_list("id", flat=True)
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


class NestedCrewExportMixin:
    """
    A mixin that defines methods for exporting `Crew` fields data when
    crew is being used as part of another entity in serializer.

    Feilds that can be defined in a child class:
        `agents`: a list of integers

    Methods:
        `get_ageants`: returns a list of agent IDs for this crew
    """

    def get_agents(self, crew):
        agents = list(crew.agents.all().values_list("id", flat=True))
        return agents
