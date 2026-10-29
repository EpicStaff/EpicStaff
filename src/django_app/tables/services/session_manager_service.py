from dataclasses import replace

from django.db import transaction
from django.utils import timezone
from rbac.access.principals import is_pinned_org_principal
from rbac.identity.api_keys.principals import SystemServicePrincipal
from src.shared.bench_log import BENCH_LEVEL
from src.shared.models import (
    AgentNodeData,
    EdgeData,
    GraphData,
    GraphSessionMessageData,
    KnowledgeNodeData,
    SessionData,
    SubGraphData,
    SubGraphNodeData,
    TaskNodeData,
)
from tables.constants.variables_constants import DOMAIN_VARIABLES_KEY
from tables.exceptions import GraphEntryPointException, SubGraphValidationError
from tables.models import (
    AudioTranscriptionNode,
    Edge,
    FileExtractorNode,
    Graph,
    KeyValueNode,
    KnowledgeNode,
    PythonNode,
    Session,
    SessionCallback,
)
from tables.models.graph_models import (
    AgentNode,
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    ConditionGroup,
    DecisionTableNode,
    GraphSessionMessage,
    ScheduleTriggerNode,
    StartNode,
    SubGraphNode,
    TaskNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.session_models import (
    SessionPrincipal,
    SessionTrigger,
    SessionWarningMessage,
)
from tables.services.agent_node_payload_service import AgentNodePayloadService
from tables.services.converter_service import ConverterService, secret_names_prefetch
from tables.services.persistent_variables_service import PersistentVariablesService
from tables.services.redis_service import RedisService
from tables.services.run_admission import (
    RunAdmissionRefusedError,
    RunKind,
    RunSubject,
    assert_run_admitted,
    assert_still_admitted,
)
from tables.services.secrets import (
    UndeclaredSecretError,
    secret_declaration_validator,
    secret_encryption,
)
from tables.services.session_callbacks.service import SessionCallbackService
from tables.services.surface_knowledge_warning_service import (
    SurfaceKnowledgeWarningService,
)
from tables.services.task_node_payload_service import TaskNodePayloadService
from tables.services.trigger_spec import TriggerSpec
from tables.validators.end_node_validator import EndNodeValidator
from tables.validators.file_node_validator import FileNodeValidator
from tables.validators.knowledge_node_validator import KnowledgeNodeValidator
from tables.validators.subgraph_validator import SubGraphValidator
from utils.graph_utils import (
    NodeNameResolver,
    generate_node_name,
    resolve_node_names,
    runtime_node_name,
)
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
        self.knowledge_node_validator: KnowledgeNodeValidator = KnowledgeNodeValidator()
        self.end_node_validator: EndNodeValidator = EndNodeValidator()
        self.subgraph_validator = SubGraphValidator()
        self.persistent_variables_service = PersistentVariablesService()
        self.surface_knowledge_warning_service = SurfaceKnowledgeWarningService()

    def get_session(self, session_id: int) -> Session:
        return Session.objects.get(id=session_id)

    def stop_session(self, session_id: int) -> int:
        return self.redis_service.publish_stop_session(session_id=session_id)

    def stop_running_session(self, session: Session) -> None:
        received_n = self.stop_session(session_id=session.pk)
        if received_n == 0:
            logger.error("Session {} was stopped, but no crew instance is listening.", session.pk)
            self._mark_session_error(
                session=session, reason="No crew instance received the stop session command."
            )
            try:
                SessionCallbackService().enqueue(
                    session_id=session.pk, status=Session.SessionStatus.ERROR, token_usage={}
                )
            except Exception as exc:  # a callback failure must never mask the stop error
                logger.error("Session {} callback enqueue failed: {}", session.pk, exc)

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
                self._resolve_template_variables(k, context): self._resolve_template_variables(
                    v, context
                )
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [self._resolve_template_variables(item, context) for item in obj]
        else:
            return obj

    def create_session(
        self,
        graph: Graph,
        *,
        start_node: StartNode | None,
        variables: dict | None = None,
        graph_user=None,
        trigger: TriggerSpec,
        entrypoint: str | None = None,
        parent_session_id: int | None = None,
        token_budget: int | None = None,
        user=None,
        api_key=None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
    ) -> Session:
        if variables is None:
            variables = {}

        if start_node is not None and start_node.variables:
            # Resolve template variables in start_node config using user-provided variables
            resolved_start_vars = self._resolve_template_variables(start_node.variables, variables)
            start_node_variables = self._get_actual_variables(resolved_start_vars)
            if variables:
                variables = self.persistent_variables_service.deep_merge(
                    start_node_variables, variables
                )
            else:
                variables = start_node_variables

        status_data = {"token_budget": token_budget} if token_budget is not None else {}
        # Trigger nodes name the entrypoint; manual/parent-flow triggers have no
        # node id, so generate_node_name returns None and an explicitly passed
        # entrypoint wins.
        entrypoint = (
            generate_node_name(trigger.node_id, trigger.node_name, trigger.node_number)
            or entrypoint
        )

        with transaction.atomic():
            # Passing the instance caches it on session.graph for create_session_data.
            session = Session.objects.create(
                graph=graph,
                status=Session.SessionStatus.PENDING,
                variables=variables,
                time_to_live=graph.time_to_live,
                graph_user=graph_user,
                entrypoint=entrypoint,
                parent_session_id=parent_session_id,
                status_data=status_data,
            )
            SessionTrigger.objects.create(session=session, **trigger.to_fields())
            SessionPrincipal.objects.create(
                session=session, **self._resolve_principal_fields(user, api_key)
            )
            if callback_url is not None:
                # Same transaction as the Session: the status listener must find the row
                # even if the run finishes before this request returns.
                SessionCallback.objects.create(
                    session=session,
                    url=callback_url,
                    encrypted_secret=secret_encryption.encrypt(text=callback_secret).encryptedtext,
                )
        logger.log(
            BENCH_LEVEL, "bench {checkpoint}", checkpoint="session_created", session_id=session.pk
        )
        return session

    def create_session_data(
        self,
        session: Session,
        *,
        start_node: StartNode | None,
        token_budget: int | None = None,
        run_type: str = "",
    ) -> SessionData:
        self.subgraph_validator.validate(session.graph)

        unique_subgraphs: dict[int, SubGraphData] = {}
        graph_data = self._build_graph_data(
            session.graph, unique_subgraphs, session, start_node=start_node
        )

        return SessionData(
            id=session.pk,
            org_id=session.graph.org_id,
            graph=graph_data,
            unique_subgraph_list=list(unique_subgraphs.values()),
            initial_state=dict(session.variables),
            run_type=run_type,
            token_budget=token_budget,
        )

    def _stop_refused_session(self, session: Session, refusal: RunAdmissionRefusedError) -> None:
        """End a session that run admission refused after it was created.

        Crew never hears of the session, so nothing else would end it or revoke the
        storage account issued for it.
        """
        now = timezone.now()
        Session.objects.filter(pk=session.pk).update(
            status=Session.SessionStatus.STOP,
            status_data={"reason": str(refusal.detail)},
            status_updated_at=now,
            finished_at=now,
        )
        from storage_credentials.services.session_credential_service import (
            session_credential_service,
        )

        session_credential_service.revoke_for_session(session.pk)

    def _mark_session_error(self, session: Session, reason: str) -> None:
        now = timezone.now()
        Session.objects.filter(pk=session.pk).update(
            status=Session.SessionStatus.ERROR,
            status_data={"reason": reason},
            status_updated_at=now,
            finished_at=now,
        )

    def run_session(
        self,
        graph_id: int,
        *,
        variables: dict | None = None,
        user=None,
        trigger: TriggerSpec,
        entrypoint: str | None = None,
        parent_session_id: int | None = None,
        token_budget: int | None = None,
        api_key=None,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        allow_persistent_override: bool = False,
    ) -> int:
        """Create a session and publish it to crew.

        `callback_url` / `callback_secret`: delivered on the terminal status by the
        callback sender; validated by the caller.

        Raises:
            RunAdmissionRefusedError: The run is refused. Before the session is created,
                nothing is written; refused again just before the publish, the session
                is stopped and nothing is published.
        """
        variables = self._get_actual_variables(variables)
        # Keys only: values hold user input and base64-encoded uploads, and the log
        # truncation runs after the whole message has been formatted.
        logger.info("'run_session' got variables with keys: {}", list(variables))

        # Nothing on the run path reads the canvas JSON in metadata; org is joined
        # here because issuing session storage credentials reads graph.org.
        graph = Graph.objects.defer("metadata").select_related("org").get(pk=graph_id)
        # Before anything is written: building the run variables can create
        # persistent-variable rows.
        admission = assert_run_admitted(RunSubject(RunKind.FLOW, graph.pk, graph.org_id))
        # The server does not require a start node (the editor only hides its delete
        # button); without one, the run needs an entrypoint from its trigger.
        start_node = StartNode.objects.filter(graph_id=graph_id).first()
        run_vars = self.persistent_variables_service.build_run_variables(
            graph=graph,
            user=user,
            payload=variables,
            allow_persistent_override=allow_persistent_override,
        )

        if trigger.trigger_type == SessionTrigger.TriggerType.MANUAL:
            trigger = replace(trigger, triggered_by_user=run_vars.graph_user)

        session: Session = self.create_session(
            graph=graph,
            start_node=start_node,
            variables=run_vars.variables,
            graph_user=run_vars.graph_user,
            trigger=trigger,
            entrypoint=entrypoint,
            parent_session_id=parent_session_id,
            token_budget=token_budget,
            user=user,
            api_key=api_key,
            callback_url=callback_url,
            callback_secret=callback_secret,
        )
        try:
            violations = secret_declaration_validator.violations(graph_id=graph_id)
            if violations:
                raise UndeclaredSecretError(
                    "Session aborted: " + " ".join(violation.describe() for violation in violations)
                )

            session_data: SessionData = self.create_session_data(
                session=session,
                start_node=start_node,
                token_budget=token_budget,
                run_type=trigger.trigger_type,
            )
            # TODO: add ping or waiting for crew to accept connections

            # Issue temporary storage credentials if needed
            from storage_credentials.services.session_credential_service import (
                session_credential_service,
            )

            storage_credentials = session_credential_service.issue_for_session(
                session_data=session_data,
                session_orm=session,
                org=graph.org,
            )

            Session.objects.filter(pk=session.pk).update(
                graph_schema=session_data.graph.model_dump(mode="json"),
            )
            # Again just before crew hears of the session: a suspension that committed
            # while it was being built must not reach crew.
            assert_still_admitted(admission)
            received_n = self.redis_service.publish_session_data(
                session_data=session_data,
                org_id=graph.org_id,
                storage_credentials=storage_credentials,
            )
            logger.log(
                BENCH_LEVEL,
                "bench {checkpoint}",
                checkpoint="published",
                session_id=session.pk,
                received_n=received_n,
            )
            if received_n == 0:
                logger.error(
                    "Session {} was published, but no crew instance is listening.", session.pk
                )
                self._mark_session_error(
                    session=session, reason="No crew instance received the session."
                )
            logger.info("Session data published in Redis for session ID: {}.", session.pk)

        except RunAdmissionRefusedError as refusal:
            self._stop_refused_session(session=session, refusal=refusal)
            raise
        except Exception as e:
            msg = f"Error occured running a session: {e}"
            logger.exception(msg)
            self._mark_session_error(session=session, reason=msg)
            raise

        if session.status == Session.SessionStatus.ERROR:
            # Publish was not received; the status handler will never see this session end.
            try:
                SessionCallbackService().enqueue(
                    session_id=session.pk, status=Session.SessionStatus.ERROR, token_usage={}
                )
            except Exception as exc:  # a callback failure must never mask the session error
                logger.error("Session {} callback enqueue failed: {}", session.pk, exc)

        surface_knowledge_warnings = self.surface_knowledge_warning_service.build_warnings(graph)
        all_warnings = run_vars.warnings + surface_knowledge_warnings
        if all_warnings:
            SessionWarningMessage.objects.create(session_id=session.pk, messages=all_warnings)
        return session.pk

    # message_type values handled generically by the branch below: this is a
    # plain GraphSessionMessage row + redis republish. "user" is the original
    # AnswerToLLM path (kept byte-for-byte). Adding a message_type here never
    # requires a migration -- message_data is a free-form JSONField.
    _GENERIC_MESSAGE_TYPES = ("user",)

    def register_message(self, data: dict, created_at_dt) -> None:
        if data["message_data"]["message_type"] in self._GENERIC_MESSAGE_TYPES:
            graph_session_message_data = GraphSessionMessageData.model_validate(data)
            session = Session.objects.select_related("graph").get(
                id=graph_session_message_data.session_id
            )
            GraphSessionMessage.objects.create(
                session=session,
                name=graph_session_message_data.name,
                execution_order=graph_session_message_data.execution_order,
                message_data=graph_session_message_data.message_data,
                uuid=graph_session_message_data.uuid,
                created_at=created_at_dt,
            )

            self.redis_service.publish_user_graph_message(session.id, data)

        else:
            raise ValueError(f"Unsupported message_type: {data['message_data']['message_type']}")

    def _get_actual_variables(self, variables: dict) -> dict:
        actual_variables = variables.get(DOMAIN_VARIABLES_KEY)
        output = actual_variables if actual_variables else variables
        return output

    def _build_graph_data(
        self,
        graph: Graph,
        unique_subgraphs: dict[int, SubGraphData] | None = None,
        session: Session = None,
        *,
        start_node: StartNode | None,
        visiting_graph_ids: set[int] | None = None,
        parent_graph: Graph | None = None,
    ) -> GraphData:
        """Recursively build GraphData for a graph to handle subgraphs

        Args:
            graph: The graph to build data for
            unique_subgraphs: Dictionary to collect unique subgraphs (only used at top level)
            start_node: The graph's start node, already loaded by the caller, or
                None when the graph has none.
            visiting_graph_ids: Set of graph IDs currently being visited in the recursion stack.
                Used to detect cycles that bypass the validator.
            parent_graph: The graph whose subgraph reference led to this call, used only to
                name the offending edge if the re-entry guard below fires.
        """
        if visiting_graph_ids is None:
            visiting_graph_ids = set()

        # Guard against re-entry into a graph currently being built
        if graph.pk in visiting_graph_ids:
            parent_name = parent_graph.name if parent_graph else f"Flow {graph.pk}"
            raise SubGraphValidationError(
                f"Recursion detected: '{parent_name}' references '{graph.name}' which creates "
                f"a cycle."
            )

        visiting_graph_ids_for_recursion = visiting_graph_ids | {graph.pk}
        python_node_list = (
            PythonNode.objects.filter(graph=graph.pk)
            .defer("test_input")
            .select_related("python_code__venv")
            .prefetch_related(secret_names_prefetch("python_code__secrets"))
        )
        knowledge_node_list = KnowledgeNode.objects.filter(graph=graph.pk).select_related(
            "source_collection",
            "naive_search_config",
            "graph_basic_search_config",
            "graph_local_search_config",
            "graph_global_search_config",
            "graph_drift_search_config",
        )
        file_extractor_node_list = FileExtractorNode.objects.filter(graph=graph.pk)
        key_value_node_list = KeyValueNode.objects.filter(graph=graph.pk)
        audio_transcription_node_list = AudioTranscriptionNode.objects.filter(graph=graph.pk)
        edge_list = Edge.objects.filter(graph=graph.pk)
        decision_table_node_list = DecisionTableNode.objects.filter(
            graph=graph.pk
        ).prefetch_related("condition_groups__conditions")
        subgraph_node_list = (
            SubGraphNode.objects.filter(graph=graph.pk)
            .select_related("subgraph")
            .defer("subgraph__metadata")
        )
        webhook_trigger_node_list = (
            WebhookTriggerNode.objects.filter(graph=graph.pk)
            .defer("test_payload")
            .select_related("python_code__venv")
            .prefetch_related(secret_names_prefetch("python_code__secrets"))
        )
        telegram_trigger_node_list = TelegramTriggerNode.objects.filter(graph=graph.pk).defer(
            "test_payload"
        )
        schedule_trigger_node_list = ScheduleTriggerNode.objects.filter(graph=graph.pk)
        classification_decision_table_node_list = (
            ClassificationDecisionTableNode.objects.filter(graph=graph.pk)
            .select_related("pre_python_code__venv", "post_python_code__venv")
            .prefetch_related(
                "condition_groups",
                secret_names_prefetch("pre_python_code__secrets"),
                secret_names_prefetch("post_python_code__secrets"),
            )
        )
        task_node_list = (
            TaskNode.objects.filter(graph=graph.pk)
            .select_related(
                "inline_surface",
                "agent_definition",
                "agent_definition__llm_config",
                "agent_definition__llm_config__model",
                "agent_definition__llm_config__model__llm_provider",
                "agent_definition__fcm_llm_config",
                "agent_definition__fcm_llm_config__model",
                "agent_definition__fcm_llm_config__model__llm_provider",
            )
            .prefetch_related(
                "surface_list__python_tools",
                "surface_list__mcp_tools",
                "surface_list__storage_items",
                "surface_list__knowledge__naive_search_config",
                "surface_list__knowledge__graph_basic_search_config",
                "surface_list__knowledge__graph_local_search_config",
                "surface_list__knowledge__graph_global_search_config",
                "surface_list__knowledge__graph_drift_search_config",
                "inline_surface__python_tools",
                "inline_surface__mcp_tools",
                "inline_surface__storage_items",
                "inline_surface__knowledge__naive_search_config",
                "inline_surface__knowledge__graph_basic_search_config",
                "inline_surface__knowledge__graph_local_search_config",
                "inline_surface__knowledge__graph_global_search_config",
                "inline_surface__knowledge__graph_drift_search_config",
            )
        )
        agent_node_list = (
            AgentNode.objects.filter(graph=graph.pk)
            .select_related(
                "inline_surface",
                "agent_definition",
                "agent_definition__llm_config",
                "agent_definition__llm_config__model",
                "agent_definition__llm_config__model__llm_provider",
                "agent_definition__fcm_llm_config",
                "agent_definition__fcm_llm_config__model",
                "agent_definition__fcm_llm_config__model__llm_provider",
            )
            .prefetch_related(
                "tasks",
                "tasks__context_tasks",
                "surface_list__python_tools",
                "surface_list__mcp_tools",
                "surface_list__storage_items",
                "surface_list__knowledge__naive_search_config",
                "surface_list__knowledge__graph_basic_search_config",
                "surface_list__knowledge__graph_local_search_config",
                "surface_list__knowledge__graph_global_search_config",
                "surface_list__knowledge__graph_drift_search_config",
                "inline_surface__python_tools",
                "inline_surface__mcp_tools",
                "inline_surface__storage_items",
                "inline_surface__knowledge__naive_search_config",
                "inline_surface__knowledge__graph_basic_search_config",
                "inline_surface__knowledge__graph_local_search_config",
                "inline_surface__knowledge__graph_global_search_config",
                "inline_surface__knowledge__graph_drift_search_config",
            )
        )

        if file_extractor_node_list:
            self.file_node_validator.validate_file_nodes(file_extractor_node_list)
        if audio_transcription_node_list:
            self.file_node_validator.validate_file_nodes(audio_transcription_node_list)
        if knowledge_node_list:
            self.knowledge_node_validator.validate_runnable(knowledge_node_list)

        condition_group_next_ids = list(
            ConditionGroup.objects.filter(
                decision_table_node__in=decision_table_node_list
            ).values_list("next_node_id", flat=True)
        )

        classification_condition_group_next_ids = list(
            ClassificationConditionGroup.objects.filter(
                classification_decision_table_node__in=classification_decision_table_node_list
            ).values_list("next_node_id", flat=True)
        )

        # Build name cache directly from already-fetched node instances
        # to avoid re-querying the same tables via NodeNameResolver
        name_cache: dict[int, str] = {}
        for node_list in (
            python_node_list,
            knowledge_node_list,
            file_extractor_node_list,
            key_value_node_list,
            audio_transcription_node_list,
            decision_table_node_list,
            classification_decision_table_node_list,
            subgraph_node_list,
            webhook_trigger_node_list,
            telegram_trigger_node_list,
            schedule_trigger_node_list,
            task_node_list,
            agent_node_list,
        ):
            for node in node_list:
                name_cache[node.id] = runtime_node_name(
                    node_name=node.node_name, node_number=node.node_number, node_id=node.id
                )

        # IDs only referenced by edges/conditions (not node instances)
        # need to be resolved from DB — collect any that are missing
        edge_referenced_ids = set(
            [n.default_next_node_id for n in decision_table_node_list]
            + [n.next_error_node_id for n in decision_table_node_list]
            + [n.default_next_node_id for n in classification_decision_table_node_list]
            + [n.next_error_node_id for n in classification_decision_table_node_list]
            + [e.start_node_id for e in edge_list]
            + [e.end_node_id for e in edge_list]
            + condition_group_next_ids
            + classification_condition_group_next_ids
        )
        missing_ids = [i for i in edge_referenced_ids if i is not None and i not in name_cache]
        if missing_ids:
            name_cache.update(resolve_node_names(missing_ids, graph_ids=[graph.pk]))

        resolver = NodeNameResolver(cache=name_cache, graph_id=graph.pk)
        """
        TODO: future improvements: use cleaner approach
        """
        cv = self.converter_service
        # Read once per graph from the Graph row, never from node or tool config:
        # it becomes the X-Organization-Id header of sandbox callback tools.
        org_id = graph.org_id

        python_node_data_list = [
            cv.convert_python_node_to_pydantic(
                python_node=item,
                resolver=resolver,
                graph_id=graph.pk,
                session_id=session.pk if session else None,
                org_id=org_id,
            )
            for item in python_node_list
        ]
        knowledge_node_data_list: list[KnowledgeNodeData] = [
            cv.convert_knowledge_node_to_pydantic(knowledge_node=item, resolver=resolver)
            for item in knowledge_node_list
        ]
        webhook_trigger_node_data_list = [
            cv.convert_webhook_trigger_node_to_pydantic(
                webhook_trigger_node=item,
                resolver=resolver,
                graph_id=graph.pk,
                session_id=session.pk if session else None,
                org_id=org_id,
            )
            for item in webhook_trigger_node_list
        ]
        telegram_trigger_node_data_list = [
            cv.convert_telegram_trigger_node_to_pydantic(
                telegram_trigger_node=item, resolver=resolver
            )
            for item in telegram_trigger_node_list
        ]
        schedule_trigger_node_data_list = [
            cv.convert_schedule_trigger_node_to_pydantic(
                schedule_trigger_node=item, resolver=resolver
            )
            for item in schedule_trigger_node_list
        ]
        file_extractor_node_data_list = [
            cv.convert_file_extractor_node_to_pydantic(
                file_extractor_node=item,
                resolver=resolver,
                graph_id=graph.pk,
                session_id=session.pk if session else None,
                org_id=org_id,
            )
            for item in file_extractor_node_list
        ]
        key_value_node_data_list = [
            cv.convert_key_value_node_to_pydantic(key_value_node=item, resolver=resolver)
            for item in key_value_node_list
        ]
        audio_transcription_node_data_list = [
            cv.convert_audio_transcription_node_to_pydantic(
                audio_transcription_node=item,
                resolver=resolver,
                graph_id=graph.pk,
                session_id=session.pk if session else None,
                org_id=org_id,
            )
            for item in audio_transcription_node_list
        ]

        task_node_payload_service = TaskNodePayloadService(cv)
        task_node_data_list: list[TaskNodeData] = [
            task_node_payload_service.build_task_node_data(
                item,
                node_name=resolver(item.id),
                graph_id=graph.pk,
                session_id=session.pk if session else None,
                org_id=org_id,
            )
            for item in task_node_list
        ]

        agent_node_payload_service = AgentNodePayloadService(cv)
        agent_node_data_list: list[AgentNodeData] = [
            agent_node_payload_service.build_agent_node_data(
                item,
                node_name=resolver(item.id),
                graph_id=graph.pk,
                session_id=session.pk if session else None,
                org_id=org_id,
            )
            for item in agent_node_list
        ]

        entrypoint = session.entrypoint if session else None
        start_node_id = start_node.id if start_node else None

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

        if start_node is None and entrypoint is None:
            raise GraphEntryPointException()

        decision_table_node_data_list = [
            cv.convert_decision_table_node_to_pydantic(decision_table_node=item, resolver=resolver)
            for item in decision_table_node_list
        ]

        subgraph_node_data_list: list[SubGraphNodeData] = []
        for item in subgraph_node_list:
            subgraph = item.subgraph

            if unique_subgraphs is not None and item.subgraph_id not in unique_subgraphs:
                subgraph_start_node = subgraph.start_node_list.first()
                subgraph_data = self._build_graph_data(
                    subgraph,
                    unique_subgraphs,
                    None,
                    start_node=subgraph_start_node,
                    visiting_graph_ids=visiting_graph_ids_for_recursion,
                    parent_graph=graph,
                )
                # Not None here: _build_graph_data raises GraphEntryPointException without one.
                variables = self._get_actual_variables(subgraph_start_node.variables or {})
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
                    node=item,
                    resolver=resolver,
                    graph_id=graph.pk,
                    session_id=session.pk if session else None,
                    org_id=org_id,
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
            webhook_trigger_node_data_list=webhook_trigger_node_data_list,
            python_node_list=python_node_data_list,
            knowledge_node_list=knowledge_node_data_list,
            file_extractor_node_list=file_extractor_node_data_list,
            key_value_node_list=key_value_node_data_list,
            audio_transcription_node_list=audio_transcription_node_data_list,
            task_node_list=task_node_data_list,
            agent_node_list=agent_node_data_list,
            edge_list=edge_data_list,
            decision_table_node_list=decision_table_node_data_list,
            subgraph_node_list=subgraph_node_data_list,
            entrypoint=entrypoint,
            end_node=end_node_data,
            telegram_trigger_node_data_list=telegram_trigger_node_data_list,
            schedule_trigger_node_data_list=schedule_trigger_node_data_list,
            classification_decision_table_node_list=classification_dt_node_data_list,
        )

    def _resolve_principal_fields(self, user, api_key) -> dict:
        # First: a plugin credential is not an ApiKey, so the run view passes
        # api_key=None and the USER branch would otherwise read a missing email.
        if is_pinned_org_principal(user):
            person = user.person
            return {
                "kind": SessionPrincipal.ActionKind.PLUGIN,
                "plugin_identifier": user.plugin_identifier,
                "user": person,
                "email": person.email if person is not None else None,
            }
        if user is None:
            return {"kind": SessionPrincipal.ActionKind.TRIGGER}
        if isinstance(user, SystemServicePrincipal):
            return {
                "kind": SessionPrincipal.ActionKind.API_KEY_SYSTEM,
                "api_key": api_key,
            }
        if api_key is not None:
            return {
                "kind": SessionPrincipal.ActionKind.API_KEY_USER,
                "api_key": api_key,
                "user": user,
                "email": user.email,
            }
        return {
            "kind": SessionPrincipal.ActionKind.USER,
            "user": user,
            "email": user.email,
        }
