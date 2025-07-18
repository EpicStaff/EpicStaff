import json
from tables.exceptions import GraphEntryPointException
from tables.models.graph_models import (
    ConditionalEdge,
    DecisionTableNode,
    GraphSessionMessage,
    LLMNode,
    StartNode,
)

from utils.singleton_meta import SingletonMeta
from utils.logger import logger
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService

from tables.request_models import (
    ConditionalEdgeData,
    CrewNodeData,
    DecisionTableNodeData,
    EdgeData,
    GraphData,
    GraphSessionMessageData,
    LLMNodeData,
    PythonNodeData,
    SessionData,
)

from tables.models import (
    CrewNode,
    Session,
    Edge,
    Graph,
    PythonNode,
)


class SessionManagerService(metaclass=SingletonMeta):

    def __init__(
        self,
        redis_service: RedisService,
        converter_service: ConverterService,
    ) -> None:
        self.redis_service = redis_service
        self.converter_service = converter_service

    def get_session(self, session_id: int) -> Session:
        return Session.objects.get(id=session_id)

    def stop_session(self, session_id: int) -> None:
        session: Session = self.get_session(session_id=session_id)
        # TODO: Send notify to redis channel to stop container

        session.status = Session.SessionStatus.END
        session.save()

    def get_session_status(self, session_id: int) -> Session.SessionStatus:
        session: Session = self.get_session(session_id=session_id)
        return session.status

    def create_session(
        self,
        graph_id: int,
        variables: dict | None = None,
    ) -> Session:

        start_node = StartNode.objects.filter(graph_id=graph_id).first()

        if variables is not None:
            pass
        elif start_node.variables is not None:
            variables = start_node.variables
        else:
            variables = dict()

        time_to_live = Graph.objects.get(pk=graph_id).time_to_live
        session = Session.objects.create(
            graph_id=graph_id,
            status=Session.SessionStatus.PENDING,
            variables=variables,
            time_to_live=time_to_live,
        )
        return session

    def create_session_data(
        self,
        session: Session,
    ) -> SessionData:
        graph: Graph = session.graph

        crew_node_list = CrewNode.objects.filter(graph=graph.pk)
        python_node_list = PythonNode.objects.filter(graph=graph.pk)
        edge_list = Edge.objects.filter(graph=graph.pk)
        conditional_edge_list = ConditionalEdge.objects.filter(graph=graph.pk)
        llm_node_list = LLMNode.objects.filter(graph=graph.pk)
        decision_table_node_list = DecisionTableNode.objects.filter(graph=graph.pk)
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

        llm_node_data_list: list[LLMNodeData] = []

        for item in llm_node_list:
            llm_node_data_list.append(
                self.converter_service.convert_llm_node_to_pydantic(llm_node=item)
            )

        edge_data_list: list[EdgeData] = []

        for item in edge_list:
            edge_data_list.append(
                EdgeData(start_key=item.start_key, end_key=item.end_key)
            )

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

        entry_point = start_edge.end_key
        graph_data = GraphData(
            name=graph.name,
            crew_node_list=crew_node_data_list,
            python_node_list=python_node_data_list,
            llm_node_list=llm_node_data_list,
            edge_list=edge_data_list,
            conditional_edge_list=conditional_edge_data_list,
            decision_table_node_list=decision_table_node_data_list,
            entry_point=entry_point,
        )
        session_data = SessionData(
            id=session.pk, graph=graph_data, initial_state=session.variables
        )

        # TODO: rewrite validate_session for graphs

        return session_data

    def run_session(self, graph_id: int, variables: dict | None = None) -> int:
        logger.info(f"'run_session' got variables: {variables}")

        # Choose to use variables from previous flow or left 'variables' param None
        variables = self.choose_variables(graph_id, variables)

        session: Session = self.create_session(graph_id=graph_id, variables=variables)
        session_data: SessionData = self.create_session_data(session=session)

        session.graph_schema = session_data.graph.model_dump()
        session.save()

        # Subscribers: crew, manager
        self.redis_service.publish_session_data(
            session_data=session_data,
        )
        logger.info(f"Session data published in Redis for session ID: {session.pk}.")

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
                f"Unsupported message_type: {data["message_data"]["message_type"]}"
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
                    f"There are no sessions for this graph which ended successfully"
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
