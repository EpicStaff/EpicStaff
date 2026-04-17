from django.db.models import Prefetch

from src.shared.models import (
    AgentData,
    AudioTranscriptionNodeData,
    BaseToolData,
    ConditionalEdgeData,
    ConditionData,
    ConditionGroupData,
    ConfiguredToolData,
    CrewData,
    CrewNodeData,
    DecisionTableNodeData,
    EdgeData,
    EmbedderConfigData,
    EmbedderData,
    EndNodeData,
    FileExtractorNodeData,
    GraphRagSearchConfig,
    LLMConfigData,
    LLMData,
    LLMNodeData,
    McpToolData,
    NaiveRagSearchConfig,
    NgrokConfigData,
    PythonCodeData,
    PythonCodeToolData,
    PythonNodeData,
    RagSearchConfig,
    RealtimeAgentChatData,
    SubGraphNodeData,
    TaskData,
    TelegramTriggerNodeData,
    TelegramTriggerNodeFieldData,
    ToolConfigData,
    WebhookTriggerNodeData,
)

from tables.models import (
    Agent,
    Crew,
    EmbeddingConfig,
    LLMConfig,
    LLMNode,
    PythonCode,
    PythonCodeTool,
    Task,
    ToolConfig,
)
from tables.models.crew_models import (
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeToolConfigs,
    AgentPythonCodeTools,
    TaskConfiguredTools,
    TaskMcpTools,
    TaskPythonCodeToolConfigs,
    TaskPythonCodeTools,
)
from tables.models.knowledge_models.naive_rag_models import AgentNaiveRag
from tables.models.graph_models import (
    AudioTranscriptionNode,
    Condition,
    ConditionalEdge,
    ConditionGroup,
    CrewNode,
    DecisionTableNode,
    Edge,
    EndNode,
    FileExtractorNode,
    Graph,
    PythonNode,
    SubGraphNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.llm_models import (
    LLMConfig,
    RealtimeConfig,
    RealtimeTranscriptionConfig,
)
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeToolConfig
from tables.models.realtime_models import RealtimeAgentChat
from tables.models.webhook_models import NgrokWebhookConfig
from tables.serializers.model_serializers import ToolConfigSerializer
from tables.validators.crew_memory_validator import CrewMemoryValidator
from tables.validators.task_validator import TaskValidator
from tables.validators.tool_config_validator import (
    ToolConfigValidator,
    validate_tool_configs,
)
from utils.graph_utils import (
    SINGLE_LOOKUP_RESOLVER,
    NodeNameResolver,
)
from utils.singleton_meta import SingletonMeta
from tables.services.rag_assignment_service import SearchConfigService

tool_config_serializer = ToolConfigSerializer(
    ToolConfigValidator(validate_missing_reqired_fields=True, validate_null_fields=True)
)
from tables.models.embedding_models import EmbeddingConfig


class ConverterService(metaclass=SingletonMeta):
    def __init__(self):
        self.memory_validator = CrewMemoryValidator()
        self.task_validator = TaskValidator()

    def build_rag_search_config(
        self, rag_type_id: str | None, all_search_configs: dict | None
    ) -> RagSearchConfig | None:
        """
        Factory method to build appropriate RAG search config based on rag_type.

        Handles nested graph format:
            {"search_method": "basic", "basic": {...}, "local": {...}}
        Extracts only the active method's params for the flat pydantic model.

        Returns:
            NaiveRagSearchConfig | GraphRagSearchConfig | None
        """

        if not rag_type_id or not all_search_configs:
            return None

        try:
            rag_type, _ = rag_type_id.split(":", 1)
        except ValueError:
            return None

        rag_specific_config = all_search_configs.get(rag_type)
        if not rag_specific_config:
            return None

        rag_config_map = {
            "naive": lambda config: NaiveRagSearchConfig(rag_type="naive", **config),
            "graph": lambda config: GraphRagSearchConfig(rag_type="graph", **config),
        }

        if rag_type == "naive":
            return NaiveRagSearchConfig(rag_type="naive", **rag_specific_config)

        if rag_type == "graph":
            search_method = rag_specific_config.get("search_method", "basic")
            active_params = rag_specific_config.get(search_method) or {}
            return GraphRagSearchConfig(
                search_params={"search_method": search_method, **active_params},
            )

        return None

    def convert_crew_to_pydantic(self, crew_id: int) -> CrewData:
        crew = (
            Crew.objects.select_related(
                "manager_llm_config__model__llm_provider",
                "planning_llm_config__model__llm_provider",
                "memory_llm_config__model__llm_provider",
                "embedding_config__model__embedding_provider",
            )
            .get(pk=crew_id)
            .fill_with_defaults()
        )

        manager_llm = self.convert_llm_config_to_pydantic(crew.manager_llm_config)
        planning_llm = self.convert_llm_config_to_pydantic(crew.planning_llm_config)

        embedder = None
        memory_llm = None
        if crew.memory:
            memory_llm_config = crew.memory_llm_config
            embedding_config = crew.embedding_config
            # memory configs validation
            self.memory_validator.validate_memory_configs(
                memory_llm_config, embedding_config
            )

            embedder = self.convert_embedding_config_to_pydantic(embedding_config)
            memory_llm = self.convert_llm_config_to_pydantic(memory_llm_config)
        task_list = (
            Task.objects.filter(crew_id=crew_id)
            .select_related("agent")
            .prefetch_related(
                Prefetch(
                    "task_configured_tool_list",
                    queryset=TaskConfiguredTools.objects.select_related("tool__tool"),
                ),
                Prefetch(
                    "task_python_code_tool_list",
                    queryset=TaskPythonCodeTools.objects.select_related(
                        "tool__python_code"
                    ),
                ),
                Prefetch(
                    "task_python_code_tool_config_list",
                    queryset=TaskPythonCodeToolConfigs.objects.select_related(
                        "tool__tool__python_code"
                    ),
                ),
                Prefetch(
                    "task_mcp_tool_list",
                    queryset=TaskMcpTools.objects.select_related("tool"),
                ),
                "task_context_list",
            )
        )
        self.task_validator.validate_assigned_agents(task_list)
        task_data_list: list[TaskData] = []

        crew_base_tools: list[BaseToolData] = []

        for task in task_list:
            base_tools = self._get_task_base_tools(task=task)
            crew_base_tools.extend(base_tools)  # TODO: make it unique
            assert not (
                crew.process == "sequential" and task.agent is None
            ), f"Task {task.name} has no agent, but it's required for sequential process."

            task_data_list.append(
                TaskData(
                    id=task.pk,
                    name=task.name,
                    agent_id=task.agent.pk,
                    instructions=task.instructions,
                    knowledge_query=task.knowledge_query,
                    expected_output=task.expected_output,
                    order=task.order,
                    human_input=task.human_input,
                    async_execution=task.async_execution,
                    config=task.config,
                    output_model=task.output_model,
                    tool_unique_name_list=[tool.unique_name for tool in base_tools],
                    task_context_id_list=[
                        tc.context_id for tc in task.task_context_list.all()
                    ],
                )
            )

        assert len(task_data_list) > 0, "No tasks found for crew"

        # Fetch agents separately with prefetched tools (crew.fill_with_defaults()
        # invalidates prefetch cache via agents.set(), so we query independently)
        agents = list(
            Agent.objects.filter(crew=crew)
            .select_related(
                "llm_config__model__llm_provider",
                "fcm_llm_config__model__llm_provider",
                "knowledge_collection",
                "naive_search_config",
            )
            .prefetch_related(
                Prefetch(
                    "python_code_tools",
                    queryset=AgentPythonCodeTools.objects.select_related(
                        "pythoncodetool__python_code"
                    ),
                ),
                Prefetch(
                    "python_code_tool_configs",
                    queryset=AgentPythonCodeToolConfigs.objects.select_related(
                        "pythoncodetoolconfig__tool__python_code"
                    ),
                ),
                Prefetch(
                    "configured_tools",
                    queryset=AgentConfiguredTools.objects.select_related(
                        "toolconfig__tool"
                    ),
                ),
                Prefetch(
                    "mcp_tools",
                    queryset=AgentMcpTools.objects.select_related("mcptool"),
                ),
                Prefetch(
                    "agent_naive_rags",
                    queryset=AgentNaiveRag.objects.select_related("naive_rag"),
                ),
            )
        )

        agents_data = []
        for agent in agents:
            agent = agent.fill_with_defaults(
                crew_id=crew_id, crew_temperature=crew.default_temperature
            )
            agent_base_tools = self._get_agent_base_tools(agent=agent)
            crew_base_tools.extend(agent_base_tools)

            llm = self.convert_llm_config_to_pydantic(agent.llm_config)
            function_calling_llm = self.convert_llm_config_to_pydantic(
                agent.fcm_llm_config
            )

            knowledge_collection_id = None
            if agent.knowledge_collection is not None:
                knowledge_collection_id = agent.knowledge_collection.pk

            rag_type_id = agent.get_rag_type_and_id()
            all_search_configs = SearchConfigService.get_search_configs(agent)
            rag_search_config = self.build_rag_search_config(
                rag_type_id, all_search_configs
            )

            agents_data.append(
                AgentData(
                    id=agent.pk,
                    role=agent.role,
                    goal=agent.goal,
                    backstory=agent.backstory,
                    tool_unique_name_list=[
                        tool.unique_name for tool in agent_base_tools
                    ],
                    allow_delegation=agent.allow_delegation,
                    memory=agent.memory,
                    max_iter=agent.max_iter,
                    max_rpm=agent.max_rpm,
                    max_execution_time=agent.max_execution_time,
                    max_retry_limit=agent.max_retry_limit,
                    respect_context_window=agent.respect_context_window,
                    cache=agent.cache,
                    allow_code_execution=agent.allow_code_execution,
                    llm=llm,
                    function_calling_llm=function_calling_llm,
                    knowledge_collection_id=knowledge_collection_id,
                    rag_type_id=rag_type_id,
                    rag_search_config=rag_search_config,
                )
            )

        crew_data = CrewData(
            id=crew.pk,
            name=crew.name,
            agents=agents_data,
            process=crew.process,
            memory=crew.memory,
            tasks=task_data_list,
            config=crew.config,
            max_rpm=crew.max_rpm,
            cache=crew.cache,
            full_output=crew.full_output,
            planning=crew.planning,
            embedder=embedder,
            memory_llm=memory_llm,
            manager_llm=manager_llm,
            planning_llm=planning_llm,
            tools=list(
                {tool.unique_name: tool for tool in crew_base_tools}.values()
            ),  # TODO: Unique only
        )

        return crew_data

    def _get_agent_base_tools(self, agent: Agent) -> list[BaseToolData]:
        python_tools = [entry.pythoncodetool for entry in agent.python_code_tools.all()]
        python_tool_configs = [
            entry.pythoncodetoolconfig for entry in agent.python_code_tool_configs.all()
        ]
        configured_tools = [entry.toolconfig for entry in agent.configured_tools.all()]
        mcp_tools = [entry.mcptool for entry in agent.mcp_tools.all()]

        all_tools = python_tools + python_tool_configs + configured_tools + mcp_tools
        return [self.convert_tool_to_base_tool_pydantic(tool) for tool in all_tools]

    def _get_task_base_tools(self, task: Task) -> list[BaseToolData]:
        tools = (
            [entry.tool for entry in task.task_configured_tool_list.all()]
            + [entry.tool for entry in task.task_python_code_tool_list.all()]
            + [entry.tool for entry in task.task_python_code_tool_config_list.all()]
            + [entry.tool for entry in task.task_mcp_tool_list.all()]
        )
        return [self.convert_tool_to_base_tool_pydantic(tool) for tool in tools]

    def convert_tool_to_base_tool_pydantic(
        self,
        tool: PythonCodeTool | ToolConfig | McpTool | PythonCodeToolConfig,
    ) -> BaseToolData:
        if isinstance(tool, PythonCodeTool):
            unique_name = f"python-code-tool:{tool.pk}"
            data = self.convert_python_code_tool_to_pydantic(tool)
        elif isinstance(tool, PythonCodeToolConfig):
            unique_name = f"python-code-tool-config:{tool.pk}"
            data = self.convert_python_code_tool_config_to_pydantic(tool)
        elif isinstance(tool, ToolConfig):
            unique_name = f"configured-tool:{tool.pk}"
            data = self.convert_configured_tool_to_pydantic(tool)
        elif isinstance(tool, McpTool):
            unique_name = f"mcp-tool:{tool.pk}"
            data = self.convert_mcp_tool_to_pydantic(tool)
        else:
            raise TypeError(f"Tool type of {type(tool)} is not supported")

        return BaseToolData(unique_name=unique_name, data=data)

    def convert_agent_to_pydantic(self, agent: Agent, crew_id: int) -> AgentData:
        agent = agent.fill_with_defaults(crew_id=crew_id)
        agent_base_tool_list = self._get_agent_base_tools(
            agent=agent
        )  # TODO: optimize it, duplicated db requests may occur

        llm = self.convert_llm_config_to_pydantic(agent.llm_config)
        function_calling_llm = self.convert_llm_config_to_pydantic(agent.fcm_llm_config)

        knowledge_collection_id = None
        if agent.knowledge_collection is not None:
            knowledge_collection_id = agent.knowledge_collection.pk

        # Build RAG search config using factory method
        rag_type_id = agent.get_rag_type_and_id()
        all_search_configs = SearchConfigService.get_search_configs(agent)
        rag_search_config = self.build_rag_search_config(
            rag_type_id, all_search_configs
        )

        return AgentData(
            id=agent.pk,
            role=agent.role,
            goal=agent.goal,
            backstory=agent.backstory,
            tool_unique_name_list=[tool.unique_name for tool in agent_base_tool_list],
            allow_delegation=agent.allow_delegation,
            memory=agent.memory,
            max_iter=agent.max_iter,
            max_rpm=agent.max_rpm,
            max_execution_time=agent.max_execution_time,
            max_retry_limit=agent.max_retry_limit,
            respect_context_window=agent.respect_context_window,
            cache=agent.cache,
            allow_code_execution=agent.allow_code_execution,
            llm=llm,
            function_calling_llm=function_calling_llm,
            knowledge_collection_id=knowledge_collection_id,
            rag_type_id=rag_type_id,
            rag_search_config=rag_search_config,
        )

    def convert_rt_agent_chat_to_pydantic(
        self, rt_agent_chat: RealtimeAgentChat
    ) -> RealtimeAgentChatData:
        agent: Agent = rt_agent_chat.rt_agent.agent.fill_with_defaults(crew_id=None)

        rt_config: RealtimeConfig = rt_agent_chat.realtime_config
        rt_transcription_config: RealtimeTranscriptionConfig = (
            rt_agent_chat.realtime_transcription_config
        )

        knowledge_collection_id = None
        if agent.knowledge_collection is not None:
            knowledge_collection_id = agent.knowledge_collection.pk

        # Build RAG search config using factory method
        rag_type_id = agent.get_rag_type_and_id()
        all_search_configs = SearchConfigService.get_search_configs(agent)
        rag_search_config = self.build_rag_search_config(
            rag_type_id, all_search_configs
        )

        rt_agent_chat_data = RealtimeAgentChatData(
            role=agent.role,
            goal=agent.goal,
            backstory=agent.backstory,
            knowledge_collection_id=knowledge_collection_id,
            rag_type_id=rag_type_id,
            rag_search_config=rag_search_config,
            llm=self.convert_llm_config_to_pydantic(agent.llm_config),
            memory=agent.memory,
            tools=self._get_agent_base_tools(agent=agent),
            rt_model_name=rt_config.realtime_model.name,
            rt_api_key=rt_config.api_key,
            transcript_model_name=rt_transcription_config.realtime_transcription_model.name
            if rt_transcription_config
            else None,
            transcript_api_key=rt_transcription_config.api_key
            if rt_transcription_config
            else None,
            temperature=agent.default_temperature,
            connection_key=rt_agent_chat.connection_key,
            wake_word=rt_agent_chat.wake_word,
            stop_prompt=rt_agent_chat.stop_prompt,
            language=rt_agent_chat.language,
            voice_recognition_prompt=rt_agent_chat.voice_recognition_prompt,
            voice=rt_agent_chat.voice,
            input_audio_format=rt_agent_chat.input_audio_format.value,
            output_audio_format=rt_agent_chat.output_audio_format.value,
            rt_provider=rt_config.realtime_model.provider.name
            if rt_config.realtime_model.provider
            else "openai",
        )

        return rt_agent_chat_data

    def convert_python_code_to_pydantic(self, python_code: PythonCode):
        libraries = python_code.get_libraries_list()
        venv_name = str(python_code.pk)
        if not libraries:
            venv_name = "default"
        return PythonCodeData(
            venv_name=venv_name,
            code=python_code.code,
            entrypoint=python_code.entrypoint,
            libraries=libraries,
            global_kwargs=python_code.global_kwargs,
        )

    def convert_python_code_tool_to_pydantic(
        self, python_code_tool: PythonCodeTool
    ) -> PythonCodeToolData:
        python_code: PythonCode = python_code_tool.python_code

        python_code_data = self.convert_python_code_to_pydantic(python_code)
        python_code_tool_data = PythonCodeToolData(
            id=python_code_tool.pk,
            name=python_code_tool.name,
            description=python_code_tool.description,
            args_schema=python_code_tool.args_schema,
            python_code=python_code_data,
        )

        return python_code_tool_data

    def convert_python_code_tool_config_to_pydantic(
        self, python_code_tool_config: PythonCodeToolConfig
    ) -> PythonCodeToolData:
        python_code_tool: PythonCodeTool = python_code_tool_config.tool
        python_configuration = python_code_tool_config.configuration

        assert isinstance(
            python_configuration, dict
        ), "Error reading python tool configuration. How did you even pass validation?"

        python_code: PythonCode = python_code_tool.python_code
        python_code.global_kwargs = python_configuration
        python_code_data = self.convert_python_code_to_pydantic(
            python_code_tool.python_code
        )
        python_code_tool_data = PythonCodeToolData(
            id=python_code_tool.pk,
            name=python_code_tool.name,
            description=python_code_tool.description,
            args_schema=python_code_tool.args_schema,
            python_code=python_code_data,
        )
        return python_code_tool_data

    def convert_configured_tool_to_pydantic(
        self, tool_config: ToolConfig
    ) -> ConfiguredToolData:
        data: dict = tool_config_serializer.to_representation(
            tool_config, format="pydantic"
        )
        configuration = data["configuration"]

        tool_llm_config_id = configuration.pop("llm_config", None)
        llm_config = None
        if tool_llm_config_id:
            llm_config = LLMConfig.objects.get(
                pk=tool_llm_config_id
            ).fill_with_defaults()

        tool_embedding_config_id = configuration.pop("embedding_config", None)

        embedding_config = None
        if tool_embedding_config_id:
            embedding_config = EmbeddingConfig.objects.get(pk=tool_embedding_config_id)

        tool_config_data = ToolConfigData(
            id=tool_config.pk,
            llm=self.convert_llm_config_to_pydantic(llm_config),
            embedder=self.convert_embedding_config_to_pydantic(embedding_config),
            tool_init_configuration=configuration,
        )

        return ConfiguredToolData(
            name_alias=tool_config.tool.name_alias,
            tool_config=tool_config_data,
        )

    def convert_mcp_tool_to_pydantic(self, mcp_tool: McpTool) -> McpToolData:
        return McpToolData(
            transport=mcp_tool.transport,
            tool_name=mcp_tool.tool_name,
            timeout=mcp_tool.timeout,
            auth=mcp_tool.auth,
            init_timeout=mcp_tool.init_timeout,
        )

    def convert_llm_config_to_pydantic(self, config: LLMConfig) -> LLMData | None:
        if not config or not config.model:
            return None

        return LLMData(
            provider=config.model.llm_provider.name,
            config=LLMConfigData(
                model=config.model.name,
                timeout=config.timeout,
                temperature=config.temperature,
                top_p=config.top_p,
                stop=config.stop,
                max_tokens=config.max_tokens,
                presence_penalty=config.presence_penalty,
                frequency_penalty=config.frequency_penalty,
                logit_bias=config.logit_bias,
                response_format=config.response_format,
                seed=config.seed,
                base_url=config.model.base_url,
                api_version=config.model.api_version,
                api_key=config.api_key,
                deployment_id=config.model.deployment_id,
                headers=config.headers,
                extra_headers=config.extra_headers,
            ),
        )

    def convert_embedding_config_to_pydantic(
        self, embedding_config: EmbeddingConfig
    ) -> EmbedderData | None:
        if not embedding_config:
            return None

        return EmbedderData(
            provider=(
                embedding_config.model.embedding_provider.name
                if embedding_config.model.embedding_provider
                else None
            ),
            config=EmbedderConfigData(
                model=embedding_config.model.name,
                base_url=embedding_config.model.base_url,
                api_key=embedding_config.api_key,
            ),
        )

    def convert_python_node_to_pydantic(
        self,
        python_node: PythonNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> PythonNodeData:
        python_code_data = self.convert_python_code_to_pydantic(
            python_code=python_node.python_code
        )
        return PythonNodeData(
            node_name=resolver(python_node.id),
            python_code=python_code_data,
            input_map=python_node.input_map,
            output_variable_path=python_node.output_variable_path,
            stream_config=python_node.stream_config or {},
        )

    def convert_conditional_edge_to_pydantic(
        self,
        conditional_edge: ConditionalEdge,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> ConditionalEdgeData:
        python_code_data = self.convert_python_code_to_pydantic(
            python_code=conditional_edge.python_code
        )
        return ConditionalEdgeData(
            source=resolver(conditional_edge.source_node_id),
            python_code=python_code_data,
            input_map=conditional_edge.input_map,
        )

    def convert_llm_node_to_pydantic(
        self, llm_node: LLMNode, resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER
    ) -> LLMNodeData:
        llm_data = self.convert_llm_config_to_pydantic(config=llm_node.llm_config)
        return LLMNodeData(
            node_name=resolver(llm_node.id),
            llm_data=llm_data,
            input_map=llm_node.input_map,
            output_variable_path=llm_node.output_variable_path,
        )

    def convert_condition_to_pydantic(self, condition: Condition) -> ConditionData:
        return ConditionData(condition=condition.condition)

    def convert_condition_group_to_pydantic(
        self,
        condition_group: ConditionGroup,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> ConditionGroupData:
        return ConditionGroupData(
            group_name=condition_group.group_name,
            group_type=condition_group.group_type,
            expression=condition_group.expression,
            manipulation=condition_group.manipulation,
            condition_list=[
                ConditionData(condition=condition.condition)
                for condition in condition_group.conditions.all()
            ],
            next_node=resolver(condition_group.next_node_id),
        )

    def convert_decision_table_node_to_pydantic(
        self,
        decision_table_node: DecisionTableNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> DecisionTableNodeData:
        condition_group_list = [
            self.convert_condition_group_to_pydantic(condition_group, resolver)
            for condition_group in decision_table_node.condition_groups.all()
        ]
        return DecisionTableNodeData(
            node_name=resolver(decision_table_node.id),
            conditional_group_list=condition_group_list,
            default_next_node=resolver(decision_table_node.default_next_node_id),
            next_error_node=resolver(decision_table_node.next_error_node_id),
        )

    def convert_crew_node_to_pydantic(
        self, crew_node: CrewNode, resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER
    ) -> CrewNodeData:
        crew: Crew = crew_node.crew
        validate_tool_configs(crew)
        crew_data = self.convert_crew_to_pydantic(crew_id=crew.pk)
        return CrewNodeData(
            node_name=resolver(crew_node.id),
            crew=crew_data,
            input_map=crew_node.input_map,
            output_variable_path=crew_node.output_variable_path,
            stream_config=crew_node.stream_config or {},
        )

    def convert_end_node_to_pydantic(
        self, end_node: EndNode, resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER
    ) -> EndNodeData:
        return EndNodeData(
            node_name=resolver(end_node.id),
            output_map=end_node.output_map,
        )

    def convert_webhook_trigger_node_to_pydantic(
        self,
        webhook_trigger_node: WebhookTriggerNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> WebhookTriggerNodeData:
        python_code_data = self.convert_python_code_to_pydantic(
            python_code=webhook_trigger_node.python_code
        )
        return WebhookTriggerNodeData(
            node_name=resolver(webhook_trigger_node.id),
            python_code=python_code_data,
        )

    def convert_telegram_trigger_node_to_pydantic(
        self,
        telegram_trigger_node: TelegramTriggerNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> TelegramTriggerNodeData:
        field_data = [
            TelegramTriggerNodeFieldData(
                parent=field.parent,
                field_name=field.field_name,
                variable_path=field.variable_path,
            )
            for field in telegram_trigger_node.fields.all()
        ]
        return TelegramTriggerNodeData(
            node_name=resolver(telegram_trigger_node.id),
            field_list=field_data,
        )

    def convert_edge_to_pytdantic(
        self, edge: Edge, resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER
    ) -> EdgeData:
        return EdgeData(
            start_key=resolver(edge.start_node_id),
            end_key=resolver(edge.end_node_id),
        )

    def convert_file_extractor_node_to_pydantic(
        self,
        file_extractor_node: FileExtractorNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> FileExtractorNodeData:
        return FileExtractorNodeData(
            node_name=resolver(file_extractor_node.id),
            input_map=file_extractor_node.input_map,
            output_variable_path=file_extractor_node.output_variable_path,
        )

    def convert_audio_transcription_node_to_pydantic(
        self,
        audio_transcription_node: AudioTranscriptionNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> AudioTranscriptionNodeData:
        return AudioTranscriptionNodeData(
            node_name=resolver(audio_transcription_node.id),
            input_map=audio_transcription_node.input_map,
            output_variable_path=audio_transcription_node.output_variable_path,
        )

    def convert_subgraph_node_to_pydantic(
        self,
        subgraph_node: SubGraphNode,
        subgraph: Graph,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> SubGraphNodeData:
        return SubGraphNodeData(
            node_name=resolver(subgraph_node.id),
            subgraph_id=subgraph.id,
            input_map=subgraph_node.input_map,
            output_variable_path=subgraph_node.output_variable_path,
        )

    def convert_ngrok_webhook_config_to_pydantic(
        self, ngrok_webhook_config: NgrokWebhookConfig
    ) -> NgrokConfigData:
        return NgrokConfigData(
            name=ngrok_webhook_config.name,
            auth_token=ngrok_webhook_config.auth_token,
            domain=ngrok_webhook_config.domain,
            region=ngrok_webhook_config.region,
        )
