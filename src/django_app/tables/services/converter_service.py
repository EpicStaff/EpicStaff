from typing import Iterable
from tables.models.llm_models import (
    RealtimeConfig,
    RealtimeTranscriptionConfig,
    LLMConfig,
)
from tables.models import (
    Agent,
    Task,
    TaskContext,
    TaskPythonCodeTools,
    TaskTools,
    ToolConfig,
    LLMConfig,
    EmbeddingConfig,
    Crew,
    PythonCode,
    PythonCodeTool,
    LLMNode,
    RealtimeModel,
)

from tables.models.realtime_models import RealtimeAgentChat
from tables.models.graph_models import (
    Condition,
    ConditionGroup,
    ConditionalEdge,
    CrewNode,
    DecisionTableNode,
    Graph,
    PythonNode,
)
from tables.request_models import *
from tables.request_models import CrewData
from utils.singleton_meta import SingletonMeta

from tables.serializers.model_serializers import ToolConfigSerializer
from tables.validators.tool_config_validator import (
    ToolConfigValidator,
    validate_tool_configs,
)
from tables.validators.crew_memory_validator import CrewMemoryValidator

tool_config_serializer = ToolConfigSerializer(
    ToolConfigValidator(validate_missing_reqired_fields=True, validate_null_fields=True)
)
from tables.models.embedding_models import EmbeddingConfig


class ConverterService(metaclass=SingletonMeta):

    def __init__(self):
        self.memory_validator = CrewMemoryValidator()

    def convert_crew_to_pydantic(self, crew_id: int) -> CrewData:
        crew = Crew.objects.get(pk=crew_id).fill_with_defaults()

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
        task_list = Task.objects.filter(crew_id=crew_id)

        task_data_list: list[TaskData] = []
        for task in task_list:
            task_data_list.append(
                TaskData(
                    id=task.pk,
                    name=task.name,
                    agent_id=task.agent.pk,
                    instructions=task.instructions,
                    expected_output=task.expected_output,
                    order=task.order,
                    human_input=task.human_input,
                    async_execution=task.async_execution,
                    config=task.config,
                    output_model=task.output_model,
                    task_tool_id_list=TaskTools.objects.filter(task=task).values_list(
                        "tool_id", flat=True
                    ),
                    task_python_code_tool_id_list=TaskPythonCodeTools.objects.filter(
                        task=task
                    ).values_list("python_code_tool_id", flat=True),
                    task_context_id_list=TaskContext.objects.filter(
                        task=task
                    ).values_list("context_id", flat=True),
                )
            )

        assert len(task_data_list) > 0, "No tasks found for crew"

        agents_data = [
            self.convert_agent_to_pydantic(agent) for agent in crew.agents.all()
        ]
        crew_agents: Iterable[Agent] = crew.agents.all()

        configured_tools: Iterable[ToolConfig] = ToolConfig.objects.filter(
            agent__in=crew_agents
        ).distinct()

        python_code_tools = set()
        for agent in crew_agents:
            python_code_tools.update(agent.python_code_tools.all())

        tool_data_list = [
            self.convert_configured_tool_to_pydantic(tool_config)
            for tool_config in configured_tools
        ]
        python_code_tool_data_list = [
            self.convert_python_code_tool_to_pydantic(python_code_tool=python_code_tool)
            for python_code_tool in python_code_tools
        ]
        knowledge_collection_id = None
        if crew.knowledge_collection is not None:
            knowledge_collection_id = crew.knowledge_collection.pk

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
            tools=tool_data_list,
            python_code_tools=python_code_tool_data_list,
            knowledge_collection_id=knowledge_collection_id,
        )

        return crew_data

    def convert_agent_to_pydantic(self, agent: Agent) -> AgentData:
        agent = agent.fill_with_defaults()
        python_code_tool_id_list = agent.python_code_tools.values_list("id", flat=True)

        llm = self.convert_llm_config_to_pydantic(agent.llm_config)
        function_calling_llm = self.convert_llm_config_to_pydantic(agent.fcm_llm_config)
        knowledge_collection_id = None
        if agent.knowledge_collection is not None:
            knowledge_collection_id = agent.knowledge_collection.pk

        return AgentData(
            id=agent.pk,
            role=agent.role,
            goal=agent.goal,
            backstory=agent.backstory,
            tool_id_list=agent.configured_tools.values_list("id", flat=True),
            python_code_tool_id_list=python_code_tool_id_list,
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
        )

    def convert_rt_agent_chat_to_pydantic(
        self, rt_agent_chat: RealtimeAgentChat
    ) -> RealtimeAgentChatData:

        agent: Agent = rt_agent_chat.rt_agent.agent.fill_with_defaults()

        rt_config: RealtimeConfig = rt_agent_chat.realtime_config
        rt_transcription_config: RealtimeTranscriptionConfig = (
            rt_agent_chat.realtime_transcription_config
        )

        knowledge_collection_id = None
        if agent.knowledge_collection is not None:
            knowledge_collection_id = agent.knowledge_collection.pk

        rt_agent_chat_data = RealtimeAgentChatData(
            role=agent.role,
            goal=agent.goal,
            backstory=agent.backstory,
            knowledge_collection_id=knowledge_collection_id,
            llm=self.convert_llm_config_to_pydantic(agent.llm_config),
            memory=agent.memory,
            tools=[
                self.convert_configured_tool_to_pydantic(configured_tool)
                for configured_tool in agent.configured_tools.all()
            ],
            python_code_tools=[
                self.convert_python_code_tool_to_pydantic(python_code_tool)
                for python_code_tool in agent.python_code_tools.all()
            ],
            rt_model_name=rt_config.realtime_model.name,
            rt_api_key=rt_config.api_key,
            transcript_model_name=rt_transcription_config.realtime_transcription_model.name,
            transcript_api_key=rt_transcription_config.api_key,
            temperature=agent.default_temperature,
            search_limit=rt_agent_chat.search_limit,
            distance_threshold=rt_agent_chat.distance_threshold,
            connection_key=rt_agent_chat.connection_key,
            wake_word=rt_agent_chat.wake_word,
            stop_prompt=rt_agent_chat.stop_prompt,
            language=rt_agent_chat.language,
            voice_recognition_prompt=rt_agent_chat.voice_recognition_prompt,
            voice=rt_agent_chat.voice,
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
        )

    def convert_python_code_tool_to_pydantic(
        self, python_code_tool: PythonCodeTool
    ) -> PythonCodeData:
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

    def convert_configured_tool_to_pydantic(self, tool_config: ToolConfig) -> ToolData:

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

        return ToolData(
            name_alias=tool_config.tool.name_alias,
            tool_config=tool_config_data,
        )

    def convert_llm_config_to_pydantic(self, config: LLMConfig) -> LLMData | None:

        if not config or not config.model:
            return None

        return LLMData(
            provider=config.model.llm_provider.name,
            config=LLMConfigData(
                model=config.model.name,
                temperature=config.temperature,
                top_p=config.top_p,
                n=config.n,
                stop=config.stop,
                max_completion_tokens=config.max_completion_tokens,
                max_tokens=config.max_tokens,
                presence_penalty=config.presence_penalty,
                frequency_penalty=config.frequency_penalty,
                logit_bias=config.logit_bias,
                response_format=config.response_format,
                seed=config.seed,
                logprobs=config.logprobs,
                top_logprobs=config.top_logprobs,
                base_url=config.base_url,
                api_version=config.api_version,
                api_key=config.api_key,
                timeout=config.timeout,
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

    def convert_python_node_to_pydantic(self, python_node: PythonNode):
        python_code: PythonCode = python_node.python_code
        python_code_data = self.convert_python_code_to_pydantic(python_code=python_code)

        return PythonNodeData(
            node_name=python_node.node_name,
            python_code=python_code_data,
            input_map=python_node.input_map,
            output_variable_path=python_node.output_variable_path,
        )

    def convert_conditional_edge_to_pydantic(self, conditional_edge: ConditionalEdge):
        python_code = conditional_edge.python_code
        python_code_data = self.convert_python_code_to_pydantic(python_code=python_code)
        return ConditionalEdgeData(
            source=conditional_edge.source,
            python_code=python_code_data,
            then=conditional_edge.then,
            input_map=conditional_edge.input_map,
        )

    def convert_llm_node_to_pydantic(self, llm_node: LLMNode):
        llm_data = self.convert_llm_config_to_pydantic(config=llm_node.llm_config)
        return LLMNodeData(
            node_name=llm_node.node_name,
            llm_data=llm_data,
            input_map=llm_node.input_map,
            output_variable_path=llm_node.output_variable_path,
        )

    def convert_condition_to_pydantic(self, condition: Condition) -> ConditionData:
        return ConditionData(condition=condition.condition)

    def convert_condition_group_to_pydantic(self, condition_group: ConditionGroup):
        return ConditionGroupData(
            group_name=condition_group.group_name,
            group_type=condition_group.group_type,
            expression=condition_group.expression,
            manipulation=condition_group.manipulation,
            condition_list=[
                ConditionData(condition=condition.condition)
                for condition in condition_group.conditions.all()
            ],
            next_node=condition_group.next_node,
        )

    def convert_decision_table_node_to_pydantic(
        self, decision_table_node: DecisionTableNode
    ):
        condition_group_list = [
            self.convert_condition_group_to_pydantic(condition_group)
            for condition_group in decision_table_node.condition_groups.all()
        ]

        return DecisionTableNodeData(
            node_name=decision_table_node.node_name,
            conditional_group_list=condition_group_list,
            default_next_node=decision_table_node.default_next_node,
            next_error_node=decision_table_node.next_error_node,
        )

    def convert_crew_node_to_pydantic(self, crew_node: CrewNode):
        crew: Crew = crew_node.crew
        validate_tool_configs(crew)

        crew_data = self.convert_crew_to_pydantic(crew_id=crew.pk)
        return CrewNodeData(
            node_name=crew_node.node_name,
            crew=crew_data,
            input_map=crew_node.input_map,
            output_variable_path=crew_node.output_variable_path,
        )
