from tables.exceptions import GraphEntryPointException
from tables.models import (
    AudioTranscriptionNode,
    CodeAgentNode,
    CrewNode,
    Edge,
    FileExtractorNode,
    Graph,
    GraphOrganizationUser,
    PythonNode,
    Session,
)
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ConditionalEdge,
    ConditionGroup,
    DecisionTableNode,
    GraphSessionMessage,
    LLMNode,
    StartNode,
    SubGraphNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from src.shared.models import (
    AudioTranscriptionNodeData,
    CodeAgentNodeData,
    ConditionalEdgeData,
    CrewNodeData,
    DecisionTableNodeData,
    EdgeData,
    FileExtractorNodeData,
    GraphData,
    GraphSessionMessageData,
    LLMNodeData,
    PythonNodeData,
    SessionData,
    SubGraphData,
    SubGraphNodeData,
    TelegramTriggerNodeData,
)
from tables.models import (
    CodeAgentNode,
    CrewNode,
    Session,
    Edge,
    Graph,
    GraphStorageFile,
    PythonNode,
    FileExtractorNode,
    AudioTranscriptionNode,
    GraphOrganizationUser,
)
from tables.constants.variables_constants import DOMAIN_VARIABLES_KEY
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.validators.end_node_validator import EndNodeValidator
from tables.validators.file_node_validator import FileNodeValidator
from tables.validators.subgraph_validator import SubGraphValidator
from utils.graph_utils import NodeNameResolver, resolve_node_names
from utils.logger import logger
from utils.singleton_meta import SingletonMeta


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

    def _resolve_template_variables(self, obj, context: dict):
        """Recursively resolve {variable} or {variable:default} templates in nested structures"""
        if isinstance(obj, str):
            import re

            pattern = r"\{([^}:]+)(?::([^}]*))?\}"

            def replace_template(match):
                var_name = match.group(1)
                default_value = match.group(2)
                if var_name in context:
                    return str(context[var_name])
                elif default_value is not None:
                    return default_value
                else:
                    return match.group(0)

            return re.sub(pattern, replace_template, obj)
        elif isinstance(obj, dict):
            return {
                self._resolve_template_variables(
                    k, context
                ): self._resolve_template_variables(v, context)
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [self._resolve_template_variables(item, context) for item in obj]
        else:
            return obj

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
            if start_node.variables:
                # Resolve template variables in start_node config using user-provided variables
                resolved_start_vars = self._resolve_template_variables(
                    start_node.variables, variables
                )
                start_node_variables = self._get_actual_variables(resolved_start_vars)
                if variables:
                    variables = self._deep_merge_dicts(start_node_variables, variables)
                else:
                    variables = start_node_variables

        variables = self._get_actual_variables(variables)

        # Remove 'shared' initialization dict - it's for Redis proxy, not storage
        variables_for_db = {k: v for k, v in variables.items() if k != "shared"}

        time_to_live = Graph.objects.get(pk=graph_id).time_to_live
        graph_user = GraphOrganizationUser.objects.filter(user__name=username).first()
        session = Session.objects.create(
            graph_id=graph_id,
            status=Session.SessionStatus.PENDING,
            variables=variables_for_db,
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
        variables = self._get_actual_variables(variables)
        logger.info(f"'run_session' got variables: {variables=}")

        # Choose to use variables from previous flow or left 'variables' param None
        variables = self.choose_variables(graph_id, variables)

        session: Session = self.create_session(
            graph_id=graph_id,
            variables=variables,
            username=username,
            entrypoint=entrypoint,
        )
        try:
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
            logger.info(
                f"Session data published in Redis for session ID: {session.pk}."
            )

        except Exception as e:
            msg = f"Error occured running a session: {e}"
            logger.exception(msg)
            session.status = Session.SessionStatus.ERROR
            session.status_data = {"reason": msg}
            raise e
        finally:
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
                # Merge: previous session vars as base, incoming trigger vars override
                if variables:
                    prev_session_vars.update(variables)
                variables = prev_session_vars
                logger.info(
                    f"Variables from previous session merged with trigger vars: {list(variables.keys())}"
                )
            except Exception as e:
                logger.error(
                    f"Error while retrieving variables from previous session. {e}"
                )
                return variables

        return variables

    def _get_actual_variables(self, variables: dict) -> dict:
        actual_variables = variables.get(DOMAIN_VARIABLES_KEY)
        output = actual_variables if actual_variables else variables
        return output

    def _deep_merge_dicts(self, base: dict, updates: dict) -> dict:
        """Merge updates into base, recursively merging nested dicts."""
        result = base.copy()

        for key, value in updates.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge_dicts(result[key], value)
            else:
                result[key] = value

        return result

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
        crew_node_list = CrewNode.objects.filter(graph=graph.pk).select_related("crew")
        python_node_list = PythonNode.objects.filter(graph=graph.pk).select_related(
            "python_code"
        )
        file_extractor_node_list = FileExtractorNode.objects.filter(graph=graph.pk)
        audio_transcription_node_list = AudioTranscriptionNode.objects.filter(
            graph=graph.pk
        )
        edge_list = Edge.objects.filter(graph=graph.pk)
        conditional_edge_list = ConditionalEdge.objects.filter(
            graph=graph.pk
        ).select_related("python_code")
        llm_node_list = LLMNode.objects.filter(graph=graph.pk).select_related(
            "llm_config__model__llm_provider"
        )
        decision_table_node_list = DecisionTableNode.objects.filter(
            graph=graph.pk
        ).prefetch_related("condition_groups__conditions")
        subgraph_node_list = SubGraphNode.objects.filter(graph=graph.pk).select_related(
            "subgraph"
        )
        webhook_trigger_node_list = WebhookTriggerNode.objects.filter(
            graph=graph.pk
        ).select_related("python_code")
        telegram_trigger_node_list = TelegramTriggerNode.objects.filter(graph=graph.pk)
        code_agent_node_list = CodeAgentNode.objects.filter(graph=graph.pk)
        classification_decision_table_node_list = (
            ClassificationDecisionTableNode.objects.filter(
                graph=graph.pk
            ).prefetch_related("condition_groups")
        )

        if file_extractor_node_list:
            self.file_node_validator.validate_file_nodes(file_extractor_node_list)
        if audio_transcription_node_list:
            self.file_node_validator.validate_file_nodes(audio_transcription_node_list)

        condition_group_next_ids = list(
            ConditionGroup.objects.filter(
                decision_table_node__in=decision_table_node_list
            ).values_list("next_node_id", flat=True)
        )

        # Build name cache directly from already-fetched node instances
        # to avoid re-querying the same tables via NodeNameResolver
        name_cache: dict[int, str] = {}
        for node_list in (
            crew_node_list,
            python_node_list,
            file_extractor_node_list,
            audio_transcription_node_list,
            llm_node_list,
            decision_table_node_list,
            classification_decision_table_node_list,
            subgraph_node_list,
            webhook_trigger_node_list,
            telegram_trigger_node_list,
            code_agent_node_list,
        ):
            for n in node_list:
                name_cache[n.id] = f"{n.node_name} #{n.id}"

        # IDs only referenced by edges/conditions (not node instances)
        # need to be resolved from DB — collect any that are missing
        edge_referenced_ids = set(
            [n.default_next_node_id for n in decision_table_node_list]
            + [n.next_error_node_id for n in decision_table_node_list]
            + [e.start_node_id for e in edge_list]
            + [e.end_node_id for e in edge_list]
            + [e.source_node_id for e in conditional_edge_list]
            + condition_group_next_ids
        )
        missing_ids = [
            i for i in edge_referenced_ids if i is not None and i not in name_cache
        ]
        if missing_ids:
            name_cache.update(resolve_node_names(missing_ids))

        resolver = NodeNameResolver(cache=name_cache)
        """
        TODO: future improvements: use cleaner approach
        """
        cv = self.converter_service

        crew_node_data_list = [
            cv.convert_crew_node_to_pydantic(crew_node=item, resolver=resolver)
            for item in crew_node_list
        ]
        python_node_data_list = [
            cv.convert_python_node_to_pydantic(
                python_node=item,
                resolver=resolver,
                graph_id=graph.pk,
                session_id=session.pk if session else None,
            )
            for item in python_node_list
        ]
        webhook_trigger_node_data_list = [
            cv.convert_webhook_trigger_node_to_pydantic(
                webhook_trigger_node=item, resolver=resolver
            )
            for item in webhook_trigger_node_list
        ]
        telegram_trigger_node_data_list = [
            cv.convert_telegram_trigger_node_to_pydantic(
                telegram_trigger_node=item, resolver=resolver
            )
            for item in telegram_trigger_node_list
        ]
        file_extractor_node_data_list = [
            cv.convert_file_extractor_node_to_pydantic(
                file_extractor_node=item, resolver=resolver
            )
            for item in file_extractor_node_list
        ]
        audio_transcription_node_data_list = [
            cv.convert_audio_transcription_node_to_pydantic(
                audio_transcription_node=item, resolver=resolver
            )
            for item in audio_transcription_node_list
        ]
        llm_node_data_list = [
            cv.convert_llm_node_to_pydantic(llm_node=item, resolver=resolver)
            for item in llm_node_list
        ]

        code_agent_node_data_list: list[CodeAgentNodeData] = []
        for item in code_agent_node_list:
            code_agent_node_data_list.append(
                CodeAgentNodeData(
                    node_name=resolver(item.id),
                    llm_config_id=item.llm_config_id,
                    agent_mode=item.agent_mode,
                    session_id=item.session_id,
                    system_prompt=item.system_prompt,
                    stream_handler_code=item.stream_handler_code,
                    libraries=item.libraries or [],
                    polling_interval_ms=item.polling_interval_ms,
                    silence_indicator_s=item.silence_indicator_s,
                    indicator_repeat_s=item.indicator_repeat_s,
                    chunk_timeout_s=item.chunk_timeout_s,
                    inactivity_timeout_s=item.inactivity_timeout_s,
                    max_wait_s=item.max_wait_s,
                    input_map=item.input_map,
                    output_variable_path=item.output_variable_path,
                    stream_config=item.stream_config or {},
                    output_schema=item.output_schema or {},
                )
            )

        entrypoint = session.entrypoint if session else None
        start_node_obj = StartNode.objects.filter(graph=graph.pk).first()
        start_node_id = start_node_obj.id if start_node_obj else None

        edge_data_list: list[EdgeData] = []
        for item in edge_list:
            edge_data = cv.convert_edge_to_pytdantic(edge=item, resolver=resolver)
            if start_node_id and item.start_node_id == start_node_id:
                if entrypoint is None:
                    entrypoint = edge_data.end_key
                continue
            edge_data_list.append(edge_data)

        if entrypoint is None:
            raise GraphEntryPointException()

        conditional_edge_data_list: list[ConditionalEdgeData] = []
        for item in conditional_edge_list:
            if item.source_node_id is None:
                logger.warning(
                    f"Conditional edge {item.pk} has no source_node_id, skipping."
                )
                continue
            conditional_edge_data_list.append(
                cv.convert_conditional_edge_to_pydantic(item, resolver=resolver)
            )

        if start_node_obj is None and entrypoint is None:
            raise GraphEntryPointException()

        decision_table_node_data_list = [
            cv.convert_decision_table_node_to_pydantic(
                decision_table_node=item, resolver=resolver
            )
            for item in decision_table_node_list
        ]

        subgraph_node_data_list: list[SubGraphNodeData] = []
        for item in subgraph_node_list:
            subgraph = item.subgraph

            if (
                unique_subgraphs is not None
                and item.subgraph_id not in unique_subgraphs
            ):
                subgraph_data = self._build_graph_data(subgraph, unique_subgraphs, None)
                variables = subgraph.start_node_list.first().variables or {}
                unique_subgraphs[item.subgraph_id] = SubGraphData(
                    id=subgraph.id,
                    data=subgraph_data,
                    initial_state=variables,
                )

            subgraph_node_data_list.append(
                cv.convert_subgraph_node_to_pydantic(
                    subgraph_node=item, subgraph=subgraph, resolver=resolver
                )
            )

        classification_dt_node_data_list = []
        for item in classification_decision_table_node_list:
            classification_dt_node_data_list.append(
                cv.convert_classification_decision_table_node_to_pydantic(
                    node=item, resolver=resolver
                )
            )

        end_node = self.end_node_validator.validate(graph_id=graph.pk)

        # TODO: remove validation
        end_node_data = (
            cv.convert_end_node_to_pydantic(end_node=end_node, resolver=resolver)
            if end_node is not None
            else None
        )

        return GraphData(
            graph_id=graph.pk,
            name=graph.name,
            crew_node_list=crew_node_data_list,
            webhook_trigger_node_data_list=webhook_trigger_node_data_list,
            python_node_list=python_node_data_list,
            file_extractor_node_list=file_extractor_node_data_list,
            audio_transcription_node_list=audio_transcription_node_data_list,
            llm_node_list=llm_node_data_list,
            code_agent_node_list=code_agent_node_data_list,
            edge_list=edge_data_list,
            conditional_edge_list=conditional_edge_data_list,
            decision_table_node_list=decision_table_node_data_list,
            subgraph_node_list=subgraph_node_data_list,
            entrypoint=entrypoint,
            end_node=end_node_data,
            telegram_trigger_node_data_list=telegram_trigger_node_data_list,
            classification_decision_table_node_list=classification_dt_node_data_list,
        )
