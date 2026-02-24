from tables.validators.end_node_validator import EndNodeValidator
from tables.validators.subgraph_validator import SubGraphValidator
from tables.exceptions import GraphEntryPointException
from tables.models.graph_models import (
    ConditionalEdge,
    DecisionTableNode,
    GraphSessionMessage,
    LLMNode,
    StartNode,
    SubGraphNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)

from utils.singleton_meta import SingletonMeta
from utils.logger import logger
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.validators.file_node_validator import FileNodeValidator

from tables.request_models import (
    ConditionalEdgeData,
    CrewNodeData,
    DecisionTableNodeData,
    EdgeData,
    GraphData,
    GraphSessionMessageData,
    LLMNodeData,
    PythonNodeData,
    FileExtractorNodeData,
    AudioTranscriptionNodeData,
    SessionData,
    SubGraphNodeData,
    SubGraphData,
    TelegramTriggerNodeData,
)
from tables.models import (
    CrewNode,
    Session,
    Edge,
    Graph,
    PythonNode,
    FileExtractorNode,
    AudioTranscriptionNode,
    GraphOrganizationUser,
)


class SessionManagerService(metaclass=SingletonMeta):
    def __init__(
        self,
        redis_service: RedisService,
        converter_service: ConverterService,
    ) -> None:
        self.redis_service = redis_service
        self.converter_service = converter_service
        self.file_node_validator: FileNodeValidator = FileNodeValidator()
        self.end_node_validator: EndNodeValidator = EndNodeValidator()
        self.subgraph_validator = SubGraphValidator()

    def get_session(self, session_id: int) -> Session:
        return Session.objects.get(id=session_id)

    def stop_session(self, session_id: int) -> int:
        return self.redis_service.publish_stop_session(session_id=session_id)

    def get_session_status(self, session_id: int) -> Session.SessionStatus:
        session: Session = self.get_session(session_id=session_id)
        return session.status

    def create_session(
        self,
        graph_id: int,
        variables: dict | None = None,
        username: str | None = None,
        entrypoint: str | None = None,
    ) -> Session:
        if variables is None:
            variables = dict()
        # it might not exist if graph has no start node
        start_node = StartNode.objects.filter(graph_id=graph_id).first()

        if start_node is not None:
            if variables and start_node.variables:
                variables = {**start_node.variables, **variables}
            elif start_node.variables:
                variables = start_node.variables

        time_to_live = Graph.objects.get(pk=graph_id).time_to_live
        graph_user = GraphOrganizationUser.objects.filter(user__name=username).first()
        session = Session.objects.create(
            graph_id=graph_id,
            status=Session.SessionStatus.PENDING,
            variables=variables,
            time_to_live=time_to_live,
            graph_user=graph_user,
            entrypoint=entrypoint,
        )
        return session

    def create_session_data(
        self,
        session: Session,
    ) -> SessionData:
        self.subgraph_validator.validate(session.graph)

        unique_subgraphs: dict[int, SubGraphData] = {}
        graph_data = self._build_graph_data(session.graph, unique_subgraphs, session)

        return SessionData(
            id=session.pk,
            graph=graph_data,
            unique_subgraph_list=list(unique_subgraphs.values()),
            initial_state=session.variables,
        )

    def run_session(
        self,
        graph_id: int,
        variables: dict | None = None,
        username: str | None = None,
        entrypoint: str | None = None,
    ) -> int:
        logger.info(f"'run_session' got variables: {variables}")

        # Choose to use variables from previous flow or left 'variables' param None
        variables = self.choose_variables(graph_id, variables)

        session: Session = self.create_session(
            graph_id=graph_id,
            variables=variables,
            username=username,
            entrypoint=entrypoint,
        )
        session_data: SessionData = self.create_session_data(session=session)
        # TODO: add ping or waiting for crew to accept connections

        session.graph_schema = session_data.graph.model_dump(mode="json")
        received_n = self.redis_service.publish_session_data(
            session_data=session_data,
        )
        required_listeners = 2
        if received_n != required_listeners:
            logger.error("Data was sent but not received.")
            session.status = Session.SessionStatus.ERROR
            session.status_data = {
                "reason": f"Data was sent and received by ({received_n}) listeners, but ({required_listeners}) required."
            }
        logger.info(f"Session data published in Redis for session ID: {session.pk}.")

        session.save()

        return session.pk

    def register_message(self, data: dict, created_at_dt) -> None:
        if data["message_data"]["message_type"] == "user":
            graph_session_message_data = GraphSessionMessageData.model_validate(data)
            session = Session.objects.get(id=graph_session_message_data.session_id)
            GraphSessionMessage.objects.create(
                session=session,
                name=graph_session_message_data.name,
                execution_order=graph_session_message_data.execution_order,
                message_data=graph_session_message_data.message_data,
                uuid=graph_session_message_data.uuid,
                created_at=created_at_dt,
            )

            self.redis_service.publish_user_graph_message(
                session.id, str(graph_session_message_data.uuid), data
            )

        else:
            raise ValueError(
                f"Unsupported message_type: {data['message_data']['message_type']}"
            )

    def choose_variables(
        self, graph_id: int, variables: dict | None = None
    ) -> dict | None:
        """
        Function returns variables ether from previous session which ended successfully
        (with status: 'end') if 'persistent_variables' field in graph_obj is True and there
        is at least one session.
        OR
        Returns an emtpy dict
        """

        use_prev_vars = Graph.objects.filter(pk=graph_id, persistent_variables=True)
        m1 = "This run will be using variables from the last flow ended with status: 'end'"
        m2 = "This run will be using new variables"
        logger.info(f"{m1 if use_prev_vars else m2}")

        if use_prev_vars:
            # Get last session which ended successfully
            latest_ended_session_id = (
                Session.objects.filter(
                    graph_id=graph_id, status=Session.SessionStatus.END
                )
                .order_by("-id")
                .values_list("id", flat=True)
                .first()
            )
            if not latest_ended_session_id:
                logger.warning(
                    "There are no sessions for this graph which ended successfully"
                )
                return variables

            logger.info(f"LAST SESSION /W STATUS: END ID IS: {latest_ended_session_id}")

            try:
                # Retrieve variables from previous session
                message = (
                    GraphSessionMessage.objects.filter(
                        session_id=latest_ended_session_id
                    )
                    .order_by("-created_at")
                    .first()
                )
                prev_session_vars = message.message_data["state"]["variables"]
                logger.info(f"prev_session_var: {prev_session_vars}")
                variables = prev_session_vars
                logger.info(
                    f"Variables from previous session are set to current run: {variables}"
                )
            except Exception as e:
                logger.error(
                    f"Error while retrieving variables from previous session. {e}"
                )
                return variables

        return variables

    def _build_graph_data(
        self,
        graph: Graph,
        unique_subgraphs: dict[int, SubGraphData] | None = None,
        session: Session = None,
    ) -> GraphData:
        """Recursively build GraphData for a graph to handle subgraphs

        Args:
            graph: The graph to build data for
            unique_subgraphs: Dictionary to collect unique subgraphs (only used at top level)
        """
        crew_node_list = CrewNode.objects.filter(graph=graph.pk)
        python_node_list = PythonNode.objects.filter(graph=graph.pk)
        file_extractor_node_list = FileExtractorNode.objects.filter(graph=graph.pk)
        audio_transcription_node_list = AudioTranscriptionNode.objects.filter(
            graph=graph.pk
        )
        edge_list = Edge.objects.filter(graph=graph.pk)
        conditional_edge_list = ConditionalEdge.objects.filter(graph=graph.pk)
        llm_node_list = LLMNode.objects.filter(graph=graph.pk)
        decision_table_node_list = DecisionTableNode.objects.filter(graph=graph.pk)
        subgraph_node_list = SubGraphNode.objects.filter(graph=graph.pk)
        webhook_trigger_node_list = WebhookTriggerNode.objects.filter(graph=graph.pk)
        telegram_trigger_node_list = TelegramTriggerNode.objects.filter(graph=graph.pk)

        if file_extractor_node_list:
            self.file_node_validator.validate_file_nodes(file_extractor_node_list)
        if audio_transcription_node_list:
            self.file_node_validator.validate_file_nodes(audio_transcription_node_list)

        crew_node_data_list: list[CrewNodeData] = []
        for item in crew_node_list:
            crew_node_data_list.append(
                self.converter_service.convert_crew_node_to_pydantic(crew_node=item)
            )

        python_node_data_list: list[PythonNodeData] = []
        for item in python_node_list:
            python_node_data_list.append(
                self.converter_service.convert_python_node_to_pydantic(python_node=item)
            )

        webhook_trigger_node_data_list: list[PythonNodeData] = []
        for item in webhook_trigger_node_list:
            webhook_trigger_node_data_list.append(
                self.converter_service.convert_webhook_trigger_node_to_pydantic(
                    webhook_trigger_node=item
                )
            )

        telegram_trigger_node_data_list: list[TelegramTriggerNodeData] = []
        for item in telegram_trigger_node_list:
            telegram_trigger_node_data_list.append(
                self.converter_service.convert_telegram_trigger_node_to_pydantic(
                    telegram_trigger_node=item
                )
            )

        file_extractor_node_data_list: list[FileExtractorNodeData] = []
        for item in file_extractor_node_list:
            file_extractor_node_data_list.append(
                FileExtractorNodeData(
                    node_name=item.node_name,
                    input_map=item.input_map,
                    output_variable_path=item.output_variable_path,
                )
            )

        audio_transcription_node_data_list: list[AudioTranscriptionNode] = []
        for item in audio_transcription_node_list:
            audio_transcription_node_data_list.append(
                AudioTranscriptionNodeData(
                    node_name=item.node_name,
                    input_map=item.input_map,
                    output_variable_path=item.output_variable_path,
                )
            )

        llm_node_data_list: list[LLMNodeData] = []
        for item in llm_node_list:
            llm_node_data_list.append(
                self.converter_service.convert_llm_node_to_pydantic(llm_node=item)
            )

        edge_data_list: list[EdgeData] = []

        # If entrypoint is set for session than use it. If not, than use entrypoint from edges.
        entrypoint = session.entrypoint

        for item in edge_list:
            if item.start_key == "__start__":
                if entrypoint is None:
                    entrypoint = item.end_key
                continue
            edge_data_list.append(
                EdgeData(start_key=item.start_key, end_key=item.end_key)
            )

        if entrypoint is None:
            raise GraphEntryPointException()

        conditional_edge_data_list: list[ConditionalEdgeData] = []
        for item in conditional_edge_list:
            conditional_edge_data_list.append(
                self.converter_service.convert_conditional_edge_to_pydantic(item)
            )

        start_edge = Edge.objects.filter(start_key="__start__", graph=graph).first()
        if start_edge is None:
            raise GraphEntryPointException()

        decision_table_node_data_list: list[DecisionTableNodeData] = []
        for decision_table_node_list_item in decision_table_node_list:
            decision_table_node_data = (
                self.converter_service.convert_decision_table_node_to_pydantic(
                    decision_table_node=decision_table_node_list_item
                )
            )
            decision_table_node_data_list.append(decision_table_node_data)

        subgraph_node_data_list: list[SubGraphNodeData] = []
        for item in subgraph_node_list:
            subgraph = Graph.objects.get(pk=item.subgraph_id)

            if (
                unique_subgraphs is not None
                and item.subgraph_id not in unique_subgraphs
            ):
                subgraph_data = self._build_graph_data(
                    subgraph, unique_subgraphs, session
                )

                variables = subgraph.start_node_list.first().variables
                if not variables:
                    variables = dict()

                unique_subgraphs[item.subgraph_id] = SubGraphData(
                    id=subgraph.id,
                    data=subgraph_data,
                    initial_state=variables,
                )

            subgraph_node_data_list.append(
                SubGraphNodeData(
                    node_name=item.node_name,
                    subgraph_id=subgraph.id,
                    input_map=item.input_map,
                    output_variable_path=item.output_variable_path,
                )
            )

        end_node = self.end_node_validator.validate(graph_id=graph.pk)

        # TODO: remove validation
        if end_node is not None:
            end_node_data = self.converter_service.convert_end_node_to_pydantic(
                end_node=end_node
            )
        else:
            end_node_data = None

        return GraphData(
            name=graph.name,
            crew_node_list=crew_node_data_list,
            webhook_trigger_node_data_list=webhook_trigger_node_data_list,
            python_node_list=python_node_data_list,
            file_extractor_node_list=file_extractor_node_data_list,
            audio_transcription_node_list=audio_transcription_node_data_list,
            llm_node_list=llm_node_data_list,
            edge_list=edge_data_list,
            conditional_edge_list=conditional_edge_data_list,
            decision_table_node_list=decision_table_node_data_list,
            subgraph_node_list=subgraph_node_data_list,
            entrypoint=entrypoint,
            end_node=end_node_data,
            telegram_trigger_node_data_list=telegram_trigger_node_data_list,
        )
