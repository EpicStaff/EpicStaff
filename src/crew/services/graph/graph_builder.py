import json

from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter

from models.state import State
from services.graph.nodes import (
    AudioTranscriptionNode,
    FileContentExtractorNode,
    KnowledgeNode,
    PythonNode,
    CrewNode,
    BaseNode,
    EndNode,
)

from services.agent_task_service import AgentTaskService
from services.graph.nodes.agent_node import AgentNode
from services.graph.nodes.task_node import TaskNode
from services.graph.remembered_outputs import RememberedOutputsStore
from services.graph.nodes.webhook_trigger_node import WebhookTriggerNode
from services.graph.nodes.telegram_trigger_node import TelegramTriggerNode
from services.graph.nodes.schedule_trigger_node import ScheduleTriggerNode
from services.graph.events import StopEvent
from services.graph.subgraphs.decision_table_node import (
    DecisionTableNodeSubgraph,
)
from services.graph.subgraphs.subgraph_node import SubGraphNode
from src.crew.services.graph.subgraphs.classification_decision_table_node import (
    ClassificationDecisionTableNodeSubgraph,
)
from services.crew.crew_parser_service import CrewParserService
from services.redis_service import RedisService
from src.shared.models import (
    DecisionTableNodeData,
    PythonCodeData,
    SessionData,
    SubGraphData,
    ClassificationDecisionTableNodeData,
)
from services.run_python_code_service import RunPythonCodeService
from services.knowledge_search_service import KnowledgeSearchService

from utils import map_variables_to_input


class ReturnCodeError(Exception): ...


class SessionGraphBuilder:
    def __init__(
        self,
        session_id: int,
        redis_service: RedisService,
        crew_parser_service: CrewParserService,
        python_code_executor_service: RunPythonCodeService,
        crewai_output_channel: str,
        knowledge_search_service: KnowledgeSearchService,
        stop_event: StopEvent,
        agent_task_service: AgentTaskService | None = None,
    ):
        """
        Initializes the SessionGraphBuilder with the required services and session details.

        Args:
            session_id (int): The unique identifier for the session.
            redis_service (RedisService): The service responsible for Redis operations.
            crew_parser_service (CrewParserService): The service responsible for parsing crew data.
            python_code_executor_service (RunPythonCodeService): The service responsible for executing Python code.
            crewai_output_channel (str): The output channel for CrewAI communications.
            agent_task_service (AgentTaskService | None): The service responsible for delegating TaskNode
                execution to the agent microservice. Required if the graph schema contains task nodes.
        """

        self.session_id = session_id
        self.redis_service = redis_service
        self.crew_parser_service = crew_parser_service
        self.python_code_executor_service = python_code_executor_service
        self.crewai_output_channel = crewai_output_channel
        self.knowledge_search_service = knowledge_search_service
        self.agent_task_service = agent_task_service
        self.remembered_outputs_store = RememberedOutputsStore(
            redis_service=redis_service
        )

        self._graph_builder = StateGraph(State)
        self._end_node_result: dict | None = {}
        self.stop_event = stop_event

    def add_conditional_edges(
        self,
        from_node: str,
        python_code_data: PythonCodeData,
        then: str | None = None,
        input_map: dict | None = None,
    ):
        """
        Adds a conditional edge to the graph from the given from_node to the then node,
        if the condition (python_code_data) is true.

        Args:
            from_node (str): The node from which the edge should be added.
            python_code_data (PythonCodeData): The condition to evaluate.
            input_map (dict | None): A mapping of input variables to be passed to the condition
                (defaults to an empty dictionary if not provided).

        Returns:
            None
        """

        if input_map is None:
            input_map = {}

        # name = f"{from_node}_conditional_edge"
        # @psutil_wrapper
        async def inner_decision_function(state: State):
            input_ = map_variables_to_input(state["variables"], input_map)
            additional_global_kwargs = {
                **input_,
                "state": {
                    "variables": state["variables"].model_dump(),
                    "state_history": state["state_history"],
                },
            }

            python_code_execution_data = (
                await self.python_code_executor_service.run_code(
                    python_code_data=python_code_data,
                    inputs=input_,
                    stop_event=self.stop_event,
                    additional_global_kwargs=additional_global_kwargs,
                )
            )

            result = json.loads(python_code_execution_data["result_data"])

            assert isinstance(
                result, str
            ), "output should be a string for decision edge"

            return result

        self._graph_builder.add_conditional_edges(
            source=from_node,
            path=inner_decision_function,
        )

    def add_edge(self, start_key: str, end_key: str):
        self._graph_builder.add_edge(start_key, end_key)

    def set_entrypoint(self, node_name: str):
        self._graph_builder.set_entry_point(node_name)

    def add_node(self, node: BaseNode):
        async def inner(state: State, writer: StreamWriter):
            return await node.run(state, writer)

        self._graph_builder.add_node(node.node_name, inner)

    def add_decision_table_node(
        self, decision_table_node_data: DecisionTableNodeData
    ) -> str:
        """
        Adds a decision table node to the graph builder.
        Args:
            decision_table_node_data (DecisionTableNodeData): The data for the decision table node.
        Returns:
            str: Subgraph
        """
        subgraph_builder = StateGraph(State)
        builder = DecisionTableNodeSubgraph(
            session_id=self.session_id,
            decision_table_node_data=decision_table_node_data,
            graph_builder=subgraph_builder,
            stop_event=self.stop_event,
            run_code_execution_service=self.python_code_executor_service,
        )
        subgraph: CompiledStateGraph = builder.build()

        self._graph_builder.add_node(decision_table_node_data.node_name, subgraph)

        async def condition(state: State, writer: StreamWriter):
            decision_node_variables = state["system_variables"]["nodes"][
                builder.node_name
            ]
            return decision_node_variables["result_node"]

        self._graph_builder.add_conditional_edges(
            decision_table_node_data.node_name, condition
        )

    def add_classification_decision_table_node(
        self, node_data: ClassificationDecisionTableNodeData
    ) -> str:
        subgraph_builder = StateGraph(State)
        builder = ClassificationDecisionTableNodeSubgraph(
            session_id=self.session_id,
            node_data=node_data,
            graph_builder=subgraph_builder,
            stop_event=self.stop_event,
            redis_service=self.redis_service,
        )
        subgraph: CompiledStateGraph = builder.build()

        self._graph_builder.add_node(node_data.node_name, subgraph)

        default_next_node = node_data.default_next_node

        async def condition(
            state: State,
            writer: StreamWriter,
            _default_next_node: str | None = default_next_node,
        ):
            result_node = state["system_variables"]["nodes"][builder.node_name][
                "result_node"
            ]
            return result_node or _default_next_node

        self._graph_builder.add_conditional_edges(node_data.node_name, condition)

    def add_subgraph_node(
        self,
        subgraph_node_data: SubGraphNode,
        unique_subgraph_list: list[SubGraphData],
        stop_event,
    ) -> str:
        """
        Adds a subgraph node to the graph builder.
        """
        builder = SubGraphNode(
            session_id=self.session_id,
            subgraph_node_data=subgraph_node_data,
            unique_subgraph_list=unique_subgraph_list,
            graph_builder=StateGraph(State),
            session_graph_builder=self,
            stop_event=stop_event,
        )

        async def inner(state: State, writer: StreamWriter):
            return await builder.run(state, writer)

        self._graph_builder.add_node(subgraph_node_data.node_name, inner)

    @property
    def end_node_result(self):
        """Getter for end_node_result"""
        return self._end_node_result

    @end_node_result.setter
    def end_node_result(self, value):
        """Setter for end_node_result, enforces dict type"""
        if not isinstance(value, dict):
            raise TypeError("end_node_result must be a dict")
        self._end_node_result = value

    def compile(self) -> CompiledStateGraph:
        # checkpointer = MemorySaver()
        return self._graph_builder.compile()  # checkpointer=checkpointer

    def compile_from_schema(self, session_data: SessionData) -> CompiledStateGraph:
        """
        Compiles a state graph from a given session schema.

        This method constructs and compiles a state graph based on the nodes and edges
        defined in the provided session data. It iterates over crew nodes, python nodes,
        and LLM nodes, adding each to the graph. Additionally, it processes edges and
        conditional edges to establish connections between nodes and sets the entry point
        of the graph.

        Args:
            session_data (SessionData): The data containing the graph schema with nodes
                and edges definitions.

        Returns:
            CompiledStateGraph: The compiled state graph ready for execution.
        """

        schema = session_data.graph

        if schema.task_node_list and self.agent_task_service is None:
            raise RuntimeError(
                f"Graph '{schema.name}' contains {len(schema.task_node_list)} task node(s) "
                "but no agent_task_service was provided to SessionGraphBuilder."
            )

        for task_node_data in schema.task_node_list:
            task_node = TaskNode(
                session_id=self.session_id,
                node_name=task_node_data.node_name,
                stop_event=self.stop_event,
                task_node_data=task_node_data,
                agent_task_service=self.agent_task_service,
                remembered_outputs_store=self.remembered_outputs_store,
            )
            self.add_node(task_node)

        if schema.agent_node_list and self.agent_task_service is None:
            raise RuntimeError(
                f"Graph '{schema.name}' contains {len(schema.agent_node_list)} agent node(s) "
                "but no agent_task_service was provided to SessionGraphBuilder."
            )

        for agent_node_data in schema.agent_node_list:
            agent_node = AgentNode(
                session_id=self.session_id,
                node_name=agent_node_data.node_name,
                stop_event=self.stop_event,
                agent_node_data=agent_node_data,
                agent_task_service=self.agent_task_service,
            )
            self.add_node(agent_node)

        for crew_node_data in schema.crew_node_list:
            crew_node = CrewNode(
                session_id=self.session_id,
                node_name=crew_node_data.node_name,
                crew_data=crew_node_data.crew,
                redis_service=self.redis_service,
                crewai_output_channel=self.crewai_output_channel,
                crew_parser_service=self.crew_parser_service,
                input_map=crew_node_data.input_map,
                output_variable_path=crew_node_data.output_variable_path,
                knowledge_search_service=self.knowledge_search_service,
                stop_event=self.stop_event,
            )
            self.add_node(crew_node)

        for python_node_data in schema.python_node_list:
            python_node = PythonNode(
                session_id=self.session_id,
                node_name=python_node_data.node_name,
                python_code_executor_service=self.python_code_executor_service,
                python_code_data=python_node_data.python_code,
                input_map=python_node_data.input_map,
                output_variable_path=python_node_data.output_variable_path,
                stop_event=self.stop_event,
            )
            self.add_node(python_node)

        for knowledge_node_data in schema.knowledge_node_list:
            knowledge_node = KnowledgeNode(
                session_id=self.session_id,
                node_name=knowledge_node_data.node_name,
                stop_event=self.stop_event,
                input_map=knowledge_node_data.input_map,
                output_variable_path=knowledge_node_data.output_variable_path,
                collection_id=knowledge_node_data.collection_id,
                rag_type_id=knowledge_node_data.rag_type_id,
                query=knowledge_node_data.query,
                rag_search_config=knowledge_node_data.rag_search_config,
                knowledge_search_service=self.knowledge_search_service,
                embedder_api_key=knowledge_node_data.embedder_api_key,
            )
            self.add_node(knowledge_node)

        for file_extractor_node_data in schema.file_extractor_node_list:
            file_extractor_node = FileContentExtractorNode(
                session_id=self.session_id,
                node_name=file_extractor_node_data.node_name,
                python_code_executor_service=self.python_code_executor_service,
                input_map=file_extractor_node_data.input_map,
                output_variable_path=file_extractor_node_data.output_variable_path,
                stop_event=self.stop_event,
                storage_allowed_paths=file_extractor_node_data.storage_allowed_paths,
                storage_org_prefix=file_extractor_node_data.storage_org_prefix,
                org_id=file_extractor_node_data.org_id,
            )
            self.add_node(file_extractor_node)

        for audio_transcription_node_data in schema.audio_transcription_node_list:
            audio_transcription_node = AudioTranscriptionNode(
                session_id=self.session_id,
                node_name=audio_transcription_node_data.node_name,
                python_code_executor_service=self.python_code_executor_service,
                input_map=audio_transcription_node_data.input_map,
                output_variable_path=audio_transcription_node_data.output_variable_path,
                stop_event=self.stop_event,
                storage_allowed_paths=audio_transcription_node_data.storage_allowed_paths,
                storage_org_prefix=audio_transcription_node_data.storage_org_prefix,
                org_id=audio_transcription_node_data.org_id,
            )
            self.add_node(audio_transcription_node)

        for edge in schema.edge_list:
            self.add_edge(edge.start_key, edge.end_key)

        for conditional_edge_data in schema.conditional_edge_list:
            self.add_conditional_edges(
                from_node=conditional_edge_data.source,
                python_code_data=conditional_edge_data.python_code,
                then=conditional_edge_data.then,
                input_map=conditional_edge_data.input_map,
            )

        for decision_table_node_data in schema.decision_table_node_list:
            self.add_decision_table_node(
                decision_table_node_data=decision_table_node_data
            )
        for ct_node_data in schema.classification_decision_table_node_list:
            self.add_classification_decision_table_node(node_data=ct_node_data)

        for subgraph_node_data in schema.subgraph_node_list:
            self.add_subgraph_node(
                subgraph_node_data=subgraph_node_data,
                unique_subgraph_list=session_data.unique_subgraph_list,
                stop_event=self.stop_event,
            )

        for webhook_trigger_node_data in schema.webhook_trigger_node_data_list:
            self.add_node(
                node=WebhookTriggerNode(
                    session_id=self.session_id,
                    node_name=webhook_trigger_node_data.node_name,
                    stop_event=self.stop_event,
                    python_code_executor_service=self.python_code_executor_service,
                    python_code_data=webhook_trigger_node_data.python_code,
                )
            )
        for telegram_trigger_node_data in schema.telegram_trigger_node_data_list:
            self.add_node(
                node=TelegramTriggerNode(
                    session_id=self.session_id,
                    node_name=telegram_trigger_node_data.node_name,
                    stop_event=self.stop_event,
                    field_list=telegram_trigger_node_data.field_list,
                )
            )

        for schedule_trigger_node_data in schema.schedule_trigger_node_data_list:
            self.add_node(
                node=ScheduleTriggerNode(
                    session_id=self.session_id,
                    node_name=schedule_trigger_node_data.node_name,
                    stop_event=self.stop_event,
                )
            )

        if schema.entrypoint is not None:
            self.set_entrypoint(schema.entrypoint)
        if schema.end_node is not None:
            end_node = EndNode(
                node_name=schema.end_node.node_name,
                session_graph_builder_instance=self,
                session_id=self.session_id,
                output_map=schema.end_node.output_map,
                stop_event=self.stop_event,
            )
            self.add_node(end_node)

        return self.compile()
