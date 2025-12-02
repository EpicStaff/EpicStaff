from copy import deepcopy
from tables.models.crew_models import (
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeTools,
    TaskMcpTools,
)
from tables.models import TaskPythonCodeTools, TaskConfiguredTools, TaskContext


class ToolsImportService:

    CONFIGURED_TOOLS_KEY = "configured_tools"
    PYTHON_TOOLS_KEY = "python_tools"
    MCP_TOOLS_KEY = "mcp_tools"

    def __init__(self, tools: dict[str, list]):
        from tables.serializers.import_serializers import (
            ToolConfigImportSerilizer,
            PythonCodeToolImportSerializer,
            McpToolImportSerializer,
        )

        self.TOOL_SERIALIZERS = {
            "configured_tools": ToolConfigImportSerilizer,
            "python_tools": PythonCodeToolImportSerializer,
            "mcp_tools": McpToolImportSerializer,
        }

        self.tools = tools
        self.mapped_tools = {}

        for key in self.TOOL_SERIALIZERS:
            self.mapped_tools[key] = {}

    def create_tools(self):
        """
        Creates tools that do not exist and map those that do exist
        """
        for tool_type, tool_data in self.tools.items():
            serializer_class = self.TOOL_SERIALIZERS.get(tool_type)

            for single_tool_data in tool_data:
                current_id = single_tool_data.pop("id")

                serializer = serializer_class(data=single_tool_data)
                serializer.is_valid(raise_exception=True)
                self.mapped_tools[tool_type][current_id] = serializer.save()

    def assign_tools_to_agent(self, agent, tool_ids: dict[str, list[int]] = None):
        """
        Assigns tools to agents based on previous IDs
        """
        configured_tools = self._get_tools_by_ids(
            self.CONFIGURED_TOOLS_KEY, tool_ids[self.CONFIGURED_TOOLS_KEY]
        )
        python_tools = self._get_tools_by_ids(
            self.PYTHON_TOOLS_KEY, tool_ids[self.PYTHON_TOOLS_KEY]
        )
        mcp_tools = self._get_tools_by_ids(
            self.MCP_TOOLS_KEY, tool_ids[self.MCP_TOOLS_KEY]
        )

        AgentPythonCodeTools.objects.filter(agent=agent).delete()

        AgentPythonCodeTools.objects.bulk_create(
            [
                AgentPythonCodeTools(agent=agent, pythoncodetool=tool)
                for tool in python_tools
            ]
        )

        AgentConfiguredTools.objects.filter(agent=agent).delete()
        AgentConfiguredTools.objects.bulk_create(
            [
                AgentConfiguredTools(agent=agent, toolconfig=tool)
                for tool in configured_tools
            ]
        )

        AgentMcpTools.objects.filter(agent=agent).delete()

        AgentMcpTools.objects.bulk_create(
            [AgentMcpTools(agent=agent, mcptool=tool) for tool in mcp_tools]
        )

    def assign_tools_to_task(self, task, tool_ids: dict[str, list[int]]):
        """
        Assigns tools to tasks based on previous IDs
        """
        configured_tools = self._get_tools_by_ids(
            self.CONFIGURED_TOOLS_KEY, tool_ids=tool_ids[self.CONFIGURED_TOOLS_KEY]
        )
        for tool in configured_tools:
            TaskConfiguredTools.objects.create(task=task, tool=tool)

        python_tools = self._get_tools_by_ids(
            self.PYTHON_TOOLS_KEY, tool_ids[self.PYTHON_TOOLS_KEY]
        )
        for tool in python_tools:
            TaskPythonCodeTools.objects.create(task=task, tool=tool)
        mcp_tools = self._get_tools_by_ids(
            self.MCP_TOOLS_KEY, tool_ids[self.MCP_TOOLS_KEY]
        )
        for tool in mcp_tools:
            TaskMcpTools.objects.create(task=task, tool=tool)

    def _get_tools_by_ids(self, tool_type, tool_ids):
        """
        Returns actuall tools based on mapped ids for given tools type
        """
        tools = set()
        for tool_id in tool_ids:
            tools.add(self.mapped_tools[tool_type][tool_id])
        return tools


class BaseConfigsImportService:

    def __init__(self, configs):
        self.configs = configs
        self.mapped_configs = {}
        self.serializer_class = None

    def create_configs(self):
        if not self.configs:
            return

        for config_data in self.configs:
            current_id = config_data.get("id")
            if current_id in self.mapped_configs:
                continue

            self.mapped_configs[current_id] = self.serializer_class().create(
                config_data
            )

    def get_config(self, config_id):
        return self.mapped_configs.get(config_id)


class LLMConfigsImportService(BaseConfigsImportService):

    def __init__(self, configs):
        from tables.serializers.import_serializers import LLMConfigImportSerializer

        super().__init__(configs)
        self.serializer_class = LLMConfigImportSerializer


class RealtimeConfigsImportService(BaseConfigsImportService):

    def __init__(self, configs):
        from tables.serializers.import_serializers import RealtimeConfigImportSerializer

        super().__init__(configs)
        self.serializer_class = RealtimeConfigImportSerializer


class RealtimeTranscriptionConfigsImportService(BaseConfigsImportService):

    def __init__(self, configs):
        from tables.serializers.import_serializers import (
            RealtimeTranscriptionConfigImportSerializer,
        )

        super().__init__(configs)
        self.serializer_class = RealtimeTranscriptionConfigImportSerializer


class RealtimeAgentImportService:

    def __init__(self, realtime_agents):
        from tables.serializers.import_serializers import RealtimeAgentImportSerializer

        self.serializer_class = RealtimeAgentImportSerializer
        self.realtime_agents = realtime_agents

    def create_agents(
        self, agents, rt_config_service=None, rt_transcription_config_service=None
    ):
        for agent_data in self.realtime_agents:
            current_id = agent_data.pop("id")
            rt_config_id = agent_data.pop("realtime_config", None)
            rt_transcription_config_id = agent_data.pop(
                "realtime_transcription_config", None
            )

            agent = agents.get(current_id)
            if not agent:
                continue

            serializer = self.serializer_class(
                data=agent_data, context={"agent": agent}
            )
            serializer.is_valid(raise_exception=True)
            rt_agent = serializer.save()

            if rt_config_service and rt_config_id:
                rt_agent.realtime_config = rt_config_service.get_config(rt_config_id)
            if rt_transcription_config_service and rt_transcription_config_id:
                rt_agent.realtime_transcription_config = (
                    rt_transcription_config_service.get_config(
                        rt_transcription_config_id
                    )
                )

            rt_agent.save()


class AgentsImportService:

    def __init__(self, agents, serializer_class):
        self.serializer_class = serializer_class
        self.agents = agents
        self.mapped_agents = {}

    def create_agents(
        self,
        tools_service: ToolsImportService | None,
        llm_configs_service: LLMConfigsImportService | None,
    ):
        """
        Creates agents using ToolsImportService and LLMConfigImportService
        to not duplicate already existing configs and tools
        """
        for agent_data in self.agents:
            current_id = agent_data.pop("id")
            tools = agent_data.pop("tools")
            llm_config_id = agent_data.pop("llm_config", None)
            fcm_llm_config_id = agent_data.pop("fcm_llm_config", None)

            serializer = self.serializer_class(data=agent_data)
            serializer.is_valid(raise_exception=True)
            agent = serializer.save()

            if tools_service:
                tools_service.assign_tools_to_agent(agent, tools)

            if llm_configs_service:
                agent.llm_config = llm_configs_service.get_config(llm_config_id)
                agent.fcm_llm_config = llm_configs_service.get_config(fcm_llm_config_id)
                agent.save()

            self.mapped_agents[current_id] = agent

    def assign_agents_to_crew(self, agent_ids: list[int], crew):
        """
        Assigns agents to crews based on previous agent IDs to not duplicate agents
        """
        agents = [
            self.mapped_agents[agent_id]
            for agent_id in agent_ids
            if agent_id in self.mapped_agents
        ]
        if not agents:
            raise ValueError(f"No agent with IDs {agent_ids}")

        crew.agents.set(agents)

    def assign_agent_to_task(self, task, agent_id: int):
        agent = self.mapped_agents.get(agent_id)
        if not agent:
            raise ValueError(f"No agent with ID {agent_id}")

        task.agent = agent
        task.save()


class TasksImportService:

    def __init__(self):
        from tables.serializers.import_serializers import TaskImportSerializer

        self.serializer_class = TaskImportSerializer
        self.mapped_tasks = {}

    def create_task(self, task_data, crew):
        current_id = task_data.pop("id", None)
        data = deepcopy(task_data)
        data.pop("context_tasks", None)

        serializer = self.serializer_class(data=data, context={"crew": crew})
        serializer.is_valid(raise_exception=True)
        task = serializer.save()

        self.mapped_tasks[current_id] = task
        return task

    def add_task_context(self, task, context_ids):
        for id_ in context_ids:
            context = self.mapped_tasks.get(id_)
            if not context:
                continue

            TaskContext.objects.create(task=task, context=context)


class CrewsImportService:

    def __init__(self, crews, serializer_class):
        from tables.serializers.import_serializers import TaskImportSerializer

        self.crew_serializer = serializer_class
        self.task_serializer = TaskImportSerializer
        self.crews = crews
        self.mapped_crews = {}

    def create_crews(
        self,
        agents_service: AgentsImportService | None,
        tools_service: ToolsImportService | None,
        llm_configs_service: LLMConfigsImportService | None,
    ):
        """
        Creates crews using AgentsImportService, ToolsImportService and LLMConfigsImportService
        to not duplicate any agents, tools or llm_configs
        """
        for crew_data in self.crews:
            current_id = crew_data.pop("id")
            agents_ids = crew_data.pop("agents")
            tasks_data = crew_data.pop("tasks")
            memory_llm_config_id = crew_data.pop("memory_llm_config", None)
            manager_llm_config_id = crew_data.pop("manager_llm_config", None)
            planning_llm_config_id = crew_data.pop("planning_llm_config", None)

            serializer = self.crew_serializer(data=crew_data)
            serializer.is_valid(raise_exception=True)
            crew = serializer.save()

            if agents_service:
                agents_service.assign_agents_to_crew(agents_ids, crew)

            if tools_service:
                task_service = TasksImportService()

                for t_data in tasks_data:
                    tool_ids_data = t_data.pop("tools", {})
                    context_ids = t_data.pop("context_tasks", [])
                    agent_id = t_data.pop("agent", None)

                    task = task_service.create_task(t_data, crew)
                    task_service.add_task_context(task, context_ids)

                    tools_service.assign_tools_to_task(task, tool_ids_data)
                    if agents_service:
                        agents_service.assign_agent_to_task(task, agent_id)

            if llm_configs_service:
                crew.memory_llm_config = llm_configs_service.get_config(
                    memory_llm_config_id
                )
                crew.manager_llm_config = llm_configs_service.get_config(
                    manager_llm_config_id
                )
                crew.planning_llm_config = llm_configs_service.get_config(
                    planning_llm_config_id
                )
                crew.save()

            self.mapped_crews[current_id] = crew
