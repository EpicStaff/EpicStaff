from typing import Any, NamedTuple

from ai_models.models import EmbeddingConfig, LLMConfig
from ai_models.repository import CatalogRepository
from ai_models.services.config_parameters import (
    embedding_config_parameters,
    llm_config_parameters,
)
from ai_models.services.connection_arguments import (
    embedding_config_connection,
    llm_config_connection,
)
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from loguru import logger
from src.shared.models import (
    ArgsSchema,
    AudioTranscriptionNodeData,
    BaseToolData,
    ClassificationConditionGroupData,
    ClassificationDecisionTableNodeData,
    ConditionData,
    ConditionGroupData,
    DecisionTableNodeData,
    EdgeData,
    EmbedderConfigData,
    EmbedderData,
    EndNodeData,
    FileExtractorNodeData,
    GraphRagSearchConfig,
    KeyValueNodeData,
    KnowledgeNodeData,
    LLMConfigData,
    LLMData,
    LocalhostConfigData,
    McpToolData,
    NaiveRagSearchConfig,
    NgrokConfigData,
    PromptConfigData,
    PythonCodeData,
    PythonCodeToolData,
    PythonNodeData,
    RagSearchConfig,
    RealtimeAgentChatData,
    ScheduleTriggerNodeData,
    SubGraphNodeData,
    TelegramTriggerNodeData,
    TelegramTriggerNodeFieldData,
    WebhookTriggerAuthData,
    WebhookTriggerNodeData,
    variables_to_args_schema,
)
from src.shared.models.storage_scope import StorageGrant
from src.shared.models.system_one import SYSTEM_ONE_PROMPT_KIND, SystemOneConfigData
from storage_credentials.exceptions import (
    CredentialScopeValidationError,
    TemporaryCredentialIssueError,
)
from storage_credentials.resource_names import org_storage_prefix
from storage_credentials.services.session_credential_service import session_credential_service
from tables.exceptions import ConfigProviderMissingError
from tables.models import PythonCode, PythonCodeTool, Secret
from tables.models.graph_models import (
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    Condition,
    ConditionGroup,
    DecisionTableNode,
    Edge,
    EndNode,
    FileExtractorNode,
    Graph,
    GraphStorageFile,
    KeyValueNode,
    KnowledgeNode,
    PythonNode,
    ScheduleTriggerNode,
    SubGraphNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.llm_models import SystemOneConfig
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeToolConfig
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
    RealtimeAgentChat,
)
from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    WebhookTrigger,
    WebhookTriggerAuth,
)
from tables.services.rag_assignment_service import SearchConfigService
from tables.services.rag_registry import resolve_rag_in_collection
from tables.services.realtime_surface_service import RealtimeSurfaceService
from tables.services.run_admission import RunAdmissionRefusedError
from tables.services.secrets import assert_tool_secrets_declared, secret_resolver
from tables.services.secrets.declaration_validator import binned_secret_names
from tables.services.storage_grants.flags import storage_grant_of
from utils.graph_utils import (
    SINGLE_LOOKUP_RESOLVER,
    NodeNameResolver,
)
from utils.singleton_meta import SingletonMeta


class NodeRagCredentials(NamedTuple):
    """Secret ids, raw extra headers and connections of a knowledge node's RAG embedder and LLM.

    Headers and connections keep their `epicstaff_secret(<name>)` markers; SecretResolver
    fills them on the published copy only. Connections are keyed by LiteLLM argument. The
    LLM parts are None for naive RAGs, which have no LLM, and everything is None for a node
    without a RAG.
    """

    embedder_api_key_secret_id: int | None = None
    llm_api_key_secret_id: int | None = None
    embedder_extra_headers: dict[str, str] | None = None
    llm_extra_headers: dict[str, str] | None = None
    embedder_connection: dict[str, str] | None = None
    embedder_parameters: dict[str, Any] | None = None
    llm_connection: dict[str, str] | None = None
    llm_parameters: dict[str, Any] | None = None


def secret_names_prefetch(lookup: str) -> Prefetch:
    """Prefetch the secrets at `lookup` for `convert_python_code_to_pydantic`.

    Loads names only: the payload carries secret names, and the encrypted
    `value` has no reason to leave the database here.
    """
    return Prefetch(lookup, queryset=Secret.objects.only("id", "name"))


class ConverterService(metaclass=SingletonMeta):
    def __init__(self):
        self.realtime_surface_service = RealtimeSurfaceService(converter_service=self)

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

        {
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

    def convert_knowledge_node_to_pydantic(
        self, knowledge_node: KnowledgeNode, resolver
    ) -> KnowledgeNodeData:
        collection_id = knowledge_node.source_collection_id

        # rag_type ("naive"/"graph") and rag_id are stored verbatim; the knowledge
        # service resolves the RAG by (collection, rag_id, rag_type), same as the agent.
        rag_type_id = (
            f"{knowledge_node.rag_type}:{knowledge_node.rag_id}"
            if knowledge_node.rag_type and knowledge_node.rag_id
            else None
        )
        all_search_configs = SearchConfigService.get_node_search_configs(knowledge_node)
        rag_search_config = self.build_rag_search_config(rag_type_id, all_search_configs)
        rag_credentials = self._node_rag_credentials(knowledge_node)
        return KnowledgeNodeData(
            node_name=resolver(knowledge_node.id),
            collection_id=collection_id,
            rag_type_id=rag_type_id,
            query=knowledge_node.query,
            rag_search_config=rag_search_config,
            input_map=knowledge_node.input_map,
            output_variable_path=knowledge_node.output_variable_path,
            embedder_api_key_secret_id=rag_credentials.embedder_api_key_secret_id,
            llm_api_key_secret_id=rag_credentials.llm_api_key_secret_id,
            embedder_extra_headers=rag_credentials.embedder_extra_headers,
            llm_extra_headers=rag_credentials.llm_extra_headers,
            embedder_connection=rag_credentials.embedder_connection,
            embedder_parameters=rag_credentials.embedder_parameters,
            llm_connection=rag_credentials.llm_connection,
            llm_parameters=rag_credentials.llm_parameters,
        )

    @staticmethod
    def _node_rag_credentials(knowledge_node: KnowledgeNode) -> NodeRagCredentials:
        """Credentials of the node's RAG, resolved once by the same (collection,
        rag_id, rag_type) coordinates the knowledge service searches by."""
        if not (knowledge_node.rag_type and knowledge_node.rag_id):
            return NodeRagCredentials()
        rag = resolve_rag_in_collection(
            knowledge_node.rag_type,
            knowledge_node.rag_id,
            knowledge_node.source_collection,
        )
        embedder = rag.embedder
        # Only graph RAGs carry an LLM (graph search synthesis); naive RAGs have none.
        llm = getattr(rag, "llm", None)
        return NodeRagCredentials(
            embedder_api_key_secret_id=embedder.api_key_secret_id if embedder else None,
            llm_api_key_secret_id=llm.api_key_secret_id if llm else None,
            embedder_extra_headers=embedder.extra_headers if embedder else None,
            llm_extra_headers=llm.extra_headers if llm else None,
            embedder_connection=embedding_config_connection(embedder) if embedder else None,
            embedder_parameters=embedding_config_parameters(embedder) if embedder else None,
            llm_connection=llm_config_connection(llm) if llm else None,
            llm_parameters=llm_config_parameters(llm) if llm else None,
        )

    def _resolve_allowed_paths_for_graph(self, graph_id: int) -> list[str]:
        return list(
            GraphStorageFile.objects.filter(graph_id=graph_id)
            .select_related("storage_file")
            .values_list("storage_file__path", flat=True)
        )

    def attached_storage_paths(self, graph_id: int) -> list[str]:
        """Return the paths of the files and folders attached to a graph.

        A caller converting several nodes of one graph reads this once and hands it to
        each conversion as `attached_storage_paths`, so the number of queries does not
        grow with the number of nodes.
        """
        return self._resolve_allowed_paths_for_graph(graph_id)

    def _resolve_storage_scope(
        self,
        graph_id: int | None,
        org_id: int | None,
        extra_paths: list[str],
        attached_storage_paths: list[str] | None = None,
    ) -> tuple[list[str] | None, str | None]:
        """Return `(storage_allowed_paths, storage_org_prefix)` for one code slot.

        Allowed paths are the graph's attached files followed by `extra_paths`, the
        folders the run itself may write to (`sessions/<id>/` in a real run). Both
        are None when there is no graph to scope the slot by. Flow-node code always uses
        storage, so its callers must pass the graph. `attached_storage_paths` are the graph's
        attached paths when the caller has them already; they are read from the graph
        when omitted.
        """
        if graph_id is None:
            return None, None
        if attached_storage_paths is None:
            attached_storage_paths = self._resolve_allowed_paths_for_graph(graph_id)
        allowed_paths = attached_storage_paths + extra_paths
        return allowed_paths, self.storage_prefix_for_org(org_id)

    @staticmethod
    def storage_prefix_for_org(org_id: int | None) -> str | None:
        """Return the storage key prefix of an organization, or None without one."""
        return org_storage_prefix(org_id) if org_id is not None else None

    def _resolve_org_prefix_for_graph(self, graph_id: int) -> str | None:
        return self.storage_prefix_for_org(self._resolve_authoritative_org_id_for_graph(graph_id))

    def _resolve_authoritative_org_id_for_graph(self, graph_id: int) -> int | None:
        """Authoritative RBAC org for a graph, read directly from `Graph.org_id`.

        The storage prefix (`_resolve_org_prefix_for_graph`) derives from the same
        column. This value is the only source of truth for the `X-Organization-Id`
        header injected into sandbox callback tools -- never derive it from
        agent/tool config input. A caller passing `org_id` into the converters
        instead must have read it from the Graph row itself.
        """
        return Graph.objects.filter(pk=graph_id).values_list("org_id", flat=True).first()

    def _org_id_for_graph(self, graph_id: int | None, org_id: int | None) -> int | None:
        """Return `org_id` when the caller already has it, else read it from the graph."""
        if org_id is None and graph_id is not None:
            return self._resolve_authoritative_org_id_for_graph(graph_id)
        return org_id

    def convert_tool_to_base_tool_pydantic(
        self,
        tool: PythonCodeTool | McpTool | PythonCodeToolConfig,
        graph_id: int | None = None,
        session_id: int | None = None,
        storage_allowed_paths_override: list[str] | None = None,
        storage_org_prefix_override: str | None = None,
        org_id_override: int | None = None,
    ) -> BaseToolData:
        if isinstance(tool, PythonCodeTool):
            unique_name = f"python-code-tool:{tool.pk}"
            data = self.convert_python_code_tool_to_pydantic(
                tool,
                graph_id=graph_id,
                session_id=session_id,
                storage_allowed_paths_override=storage_allowed_paths_override,
                storage_org_prefix_override=storage_org_prefix_override,
                org_id_override=org_id_override,
            )
        elif isinstance(tool, PythonCodeToolConfig):
            unique_name = f"python-code-tool-config:{tool.pk}"
            data = self.convert_python_code_tool_config_to_pydantic(
                tool,
                graph_id=graph_id,
                session_id=session_id,
                storage_allowed_paths_override=storage_allowed_paths_override,
            )
        elif isinstance(tool, McpTool):
            unique_name = f"mcp-tool:{tool.pk}"
            data = self.convert_mcp_tool_to_pydantic(tool)
        else:
            raise TypeError(f"Tool type of {type(tool)} is not supported")

        return BaseToolData(unique_name=unique_name, data=data)

    def convert_rt_agent_definition_chat_to_pydantic(
        self, rt_agent_chat: RealtimeAgentChat, user_id: int | None = None
    ) -> RealtimeAgentChatData:
        ad = rt_agent_chat.rt_agent_definition.agent_definition.fill_with_defaults()

        surface_resolution = self.realtime_surface_service.resolve(ad)

        # Resolve provider-specific fields from the active config FK snapshot
        rt_model_name = None
        rt_api_key_secret_id = None
        rt_base_url = None
        rt_provider = None
        transcript_model_name = None
        transcript_api_key_secret_id = None

        if rt_agent_chat.openai_config_id is not None:
            cfg: OpenAIRealtimeConfig = rt_agent_chat.openai_config
            rt_provider = "openai"
            rt_model_name = cfg.model_name
            rt_api_key_secret_id = cfg.api_key_secret_id
            rt_base_url = cfg.base_url
            transcript_model_name = cfg.transcription_model_name
            transcript_api_key_secret_id = cfg.transcription_api_key_secret_id
        elif rt_agent_chat.elevenlabs_config_id is not None:
            cfg: ElevenLabsRealtimeConfig = rt_agent_chat.elevenlabs_config
            rt_provider = "elevenlabs"
            rt_model_name = cfg.model_name
            rt_api_key_secret_id = cfg.api_key_secret_id
        elif rt_agent_chat.gemini_config_id is not None:
            cfg: GeminiRealtimeConfig = rt_agent_chat.gemini_config
            rt_provider = "gemini"
            rt_model_name = cfg.model_name
            rt_api_key_secret_id = cfg.api_key_secret_id

        if rt_provider is None or rt_model_name is None or rt_api_key_secret_id is None:
            raise ValidationError(
                f"RealtimeAgentChat ID {rt_agent_chat.pk} has no resolvable "
                "provider config (openai_config, elevenlabs_config, and "
                "gemini_config are all null on this session snapshot, or the "
                "active config has no api_key_secret assigned) — cannot build "
                "realtime session data. The referenced provider config was "
                "likely deleted after this chat was created."
            )

        # The LLM config is where the user sets temperature; the agent's
        # default_temperature only covers an LLM config that leaves it unset.
        # Read through the catalog like every run path, so a config whose settings the
        # model no longer accepts refuses the session.
        llm_temperature = (
            llm_config_parameters(ad.llm_config).get("temperature")
            if ad.llm_config is not None
            else None
        )
        temperature = ad.default_temperature if llm_temperature is None else llm_temperature

        rt_agent_chat_data = RealtimeAgentChatData(
            role=ad.name,
            goal=ad.description or "assist the user",
            backstory=ad.instructions or "You are a helpful voice assistant",
            org_id=ad.org_id,
            user_id=user_id,
            rt_agent_definition_id=rt_agent_chat.rt_agent_definition_id,
            knowledge_collection_id=surface_resolution.knowledge_collection_id,
            rag_type_id=surface_resolution.rag_type_id,
            rag_search_config=surface_resolution.rag_search_config,
            rag_embedder_api_key_secret_id=surface_resolution.rag_embedder_api_key_secret_id,
            rag_llm_api_key_secret_id=surface_resolution.rag_llm_api_key_secret_id,
            rag_embedder_extra_headers=surface_resolution.rag_embedder_extra_headers,
            rag_llm_extra_headers=surface_resolution.rag_llm_extra_headers,
            rag_embedder_connection=surface_resolution.rag_embedder_connection,
            rag_embedder_parameters=surface_resolution.rag_embedder_parameters,
            rag_llm_connection=surface_resolution.rag_llm_connection,
            rag_llm_parameters=surface_resolution.rag_llm_parameters,
            llm=self.convert_llm_config_to_pydantic(ad.llm_config),
            memory=False,
            tools=surface_resolution.tools,
            rt_model_name=rt_model_name,
            rt_api_key_secret_id=rt_api_key_secret_id,
            rt_base_url=rt_base_url,
            transcript_model_name=transcript_model_name,
            transcript_api_key_secret_id=transcript_api_key_secret_id,
            temperature=temperature,
            connection_key=rt_agent_chat.connection_key,
            wake_word=rt_agent_chat.wake_word,
            stop_prompt=rt_agent_chat.stop_prompt,
            language=rt_agent_chat.language,
            voice_recognition_prompt=rt_agent_chat.voice_recognition_prompt,
            voice=rt_agent_chat.voice,
            input_audio_format=rt_agent_chat.input_audio_format,
            output_audio_format=rt_agent_chat.output_audio_format,
            rt_provider=rt_provider,
        )

        # Check if any tools require storage and mint credentials if needed
        try:
            union_allowed_paths = set()
            needs_storage = False

            for tool in surface_resolution.tools:
                tool_data = tool.data
                if isinstance(tool_data, PythonCodeToolData) and tool_data.python_code.use_storage:
                    needs_storage = True
                    if tool_data.python_code.storage_allowed_paths:
                        union_allowed_paths.update(tool_data.python_code.storage_allowed_paths)

            if needs_storage and not union_allowed_paths:
                # A realtime chat has no folder of its own, so nothing can be
                # granted: start the chat without an account. The realtime
                # service answers a storage tool call with a clear error.
                logger.warning(
                    "Realtime chat {} has storage tools but no attached files; "
                    "starting without storage credentials",
                    rt_agent_chat.id,
                )
            elif needs_storage:
                rt_agent_chat_data.storage_credentials = (
                    session_credential_service.issue_for_realtime_chat(
                        realtime_agent_chat=rt_agent_chat,
                        storage_allowed_paths=list(union_allowed_paths),
                        org_id=ad.org_id,
                    )
                )
        except (
            TemporaryCredentialIssueError,
            CredentialScopeValidationError,
            RunAdmissionRefusedError,
        ):
            raise
        except Exception as error:
            logger.exception(
                "Failed to mint temporary storage credentials for realtime chat {}: {}",
                rt_agent_chat.id,
                error,
            )
            raise TemporaryCredentialIssueError() from error

        return rt_agent_chat_data

    def convert_python_code_to_pydantic(
        self,
        python_code: PythonCode,
        use_storage: bool = False,
        storage_allowed_paths: list[str] | None = None,
        storage_org_prefix: str | None = None,
        session_id: int | None = None,
        org_id: int | None = None,
        storage_grant: StorageGrant | None = None,
        system_venv: str | None = None,
    ):
        return PythonCodeData(
            storage_grant=storage_grant,
            venv_id=int(python_code.venv.resource_id) if python_code.venv_id else None,
            system_venv=system_venv,
            code=python_code.code,
            entrypoint=python_code.entrypoint,
            global_kwargs=python_code.global_kwargs,
            execution_timeout=python_code.execution_timeout,
            use_storage=use_storage,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            # The declaration is the allow-list: everything selected is injected,
            # whether the code reads it or not. That is what makes a computed name
            # -- get_secret(f"KEY_{env}") -- work, since no static parse could see
            # it. The parser is now only a validator (declaration_validator.py).
            # Names only: resolution happens in redis_service, on the copy that
            # goes to Redis -- never on the caller's object.
            # Iterating .all() reuses a prefetch of `secrets` when the caller made one.
            secret_names=[secret.name for secret in python_code.secrets.all()],
            org_id=org_id,
        )

    @staticmethod
    def _get_user_input_defaults(variables: list[dict]) -> dict:
        return {
            var["name"]: var["default_value"]
            for var in variables
            if var.get("input_type") in ("user_input", "mixed")
            and var.get("default_value") is not None
        }

    def convert_python_code_tool_to_pydantic(
        self,
        python_code_tool: PythonCodeTool,
        graph_id: int | None = None,
        session_id: int | None = None,
        storage_allowed_paths_override: list[str] | None = None,
        storage_org_prefix_override: str | None = None,
        org_id_override: int | None = None,
    ) -> PythonCodeToolData:
        storage_allowed_paths = None
        storage_org_prefix = None
        if python_code_tool.use_storage:
            if storage_allowed_paths_override is not None:
                storage_allowed_paths = storage_allowed_paths_override
            elif graph_id is not None:
                storage_allowed_paths = self._resolve_allowed_paths_for_graph(graph_id)
            if session_id is not None and storage_allowed_paths is not None:
                # `storage_allowed_paths_override` may be a list shared across
                # several tool conversions in the same caller loop (see
                # `base_node_payload_service._build_tool_pool`) -- rebuild rather
                # than `.append()` so we never mutate a caller-owned list.
                storage_allowed_paths = [*storage_allowed_paths, f"sessions/{session_id}/"]
            if storage_org_prefix_override is not None:
                storage_org_prefix = storage_org_prefix_override
            elif graph_id is not None:
                storage_org_prefix = self._resolve_org_prefix_for_graph(graph_id)

        org_id = org_id_override
        if org_id is None and graph_id is not None:
            org_id = self._resolve_authoritative_org_id_for_graph(graph_id)

        variables = python_code_tool.variables or []
        user_defaults = self._get_user_input_defaults(variables)
        python_code_data = self.convert_python_code_to_pydantic(
            python_code_tool.python_code,
            use_storage=python_code_tool.use_storage,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            org_id=org_id,
            system_venv=python_code_tool.system_venv,
        )
        # A PythonCodeTool is org-owned, not graph-owned, so the session-start graph
        # walk cannot reach it. Gate it here, where the tool is already in hand and
        # its name is available for the error.
        assert_tool_secrets_declared(
            tool_name=python_code_tool.name,
            code=python_code_tool.python_code.code,
            declared=set(python_code_data.secret_names),
            binned=binned_secret_names(python_code_tool.python_code),
        )
        merged_kwargs = {**user_defaults, **(python_code_data.global_kwargs or {})}
        python_code_data = PythonCodeData(
            **{**python_code_data.model_dump(), "global_kwargs": merged_kwargs},
            # model_dump() omits secret_names (exclude=True), so a plain re-splat
            # would silently drop the declaration for tools.
            secret_names=python_code_data.secret_names,
        )
        return PythonCodeToolData(
            id=python_code_tool.pk,
            name=python_code_tool.name,
            description=python_code_tool.description,
            variables=variables,
            args_schema=ArgsSchema(**variables_to_args_schema(variables)),
            python_code=python_code_data,
        )

    def convert_python_code_tool_config_to_pydantic(
        self,
        python_code_tool_config: PythonCodeToolConfig,
        graph_id: int | None = None,
        session_id: int | None = None,
        storage_allowed_paths_override: list[str] | None = None,
    ) -> PythonCodeToolData:
        python_code_tool: PythonCodeTool = python_code_tool_config.tool
        python_configuration = python_code_tool_config.configuration

        assert isinstance(python_configuration, dict), (
            "Error reading python tool configuration. How did you even pass validation?"
        )

        storage_allowed_paths = None
        storage_org_prefix = None
        if python_code_tool.use_storage:
            if storage_allowed_paths_override is not None:
                storage_allowed_paths = storage_allowed_paths_override
            elif graph_id is not None:
                storage_allowed_paths = self._resolve_allowed_paths_for_graph(graph_id)
            if session_id is not None and storage_allowed_paths is not None:
                # See `convert_python_code_tool_to_pydantic` -- rebuild instead of
                # `.append()` to avoid mutating a caller-owned override list.
                storage_allowed_paths = [*storage_allowed_paths, f"sessions/{session_id}/"]
            if graph_id is not None:
                storage_org_prefix = self._resolve_org_prefix_for_graph(graph_id)

        org_id = None
        if graph_id is not None:
            org_id = self._resolve_authoritative_org_id_for_graph(graph_id)

        variables = python_code_tool.variables or []
        user_defaults = self._get_user_input_defaults(variables)
        global_kwargs = {**user_defaults, **python_configuration}

        python_code: PythonCode = python_code_tool.python_code
        python_code.global_kwargs = global_kwargs
        python_code_data = self.convert_python_code_to_pydantic(
            python_code_tool.python_code,
            use_storage=python_code_tool.use_storage,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            org_id=org_id,
            system_venv=python_code_tool.system_venv,
        )
        # A configured tool reaches the session through this method only, so gating
        # convert_python_code_tool_to_pydantic alone would leave it ungated.
        assert_tool_secrets_declared(
            tool_name=python_code_tool.name,
            code=python_code.code,
            declared=set(python_code_data.secret_names),
            binned=binned_secret_names(python_code),
        )

        return PythonCodeToolData(
            id=python_code_tool.pk,
            name=python_code_tool.name,
            description=python_code_tool.description,
            variables=variables,
            args_schema=ArgsSchema(**variables_to_args_schema(variables)),
            python_code=python_code_data,
        )

    def convert_mcp_tool_to_pydantic(self, mcp_tool: McpTool) -> McpToolData:
        return McpToolData(
            transport=mcp_tool.transport,
            tool_name=mcp_tool.tool_name,
            name=mcp_tool.name,
            timeout=mcp_tool.timeout,
            auth_secret_id=mcp_tool.auth_secret_id,
            init_timeout=mcp_tool.init_timeout,
        )

    def convert_llm_config_to_pydantic(self, config: LLMConfig) -> LLMData | None:
        """Convert an LLM config into the payload sent to crew.

        Returns:
            None when the config is missing or has no model; nothing is configured.

        Raises:
            ConfigProviderMissingError: The config's model has no provider, because
                the provider was deleted.
            ConfigNeedsReviewError: A stored setting is one the model does not accept.
        """
        if not config or not config.model:
            return None

        if config.model.llm_provider is None:
            raise ConfigProviderMissingError("LLM", config.custom_name)

        return LLMData(
            provider=config.model.llm_provider.name,
            config=self.convert_llm_config_data(config),
        )

    def convert_system_one_config_to_pydantic(self, config: SystemOneConfig) -> SystemOneConfigData:
        """Convert a System One config into the payload sent to crew.

        `api_key` stays empty here: SecretResolver fills it from `api_key_secret_id`.
        """
        return SystemOneConfigData(
            id=config.id,
            provider=config.provider,
            model_name=config.model_name,
            api_key_secret_id=config.api_key_secret_id,
            llm_data=(
                self.convert_llm_config_to_pydantic(config.llm_config)
                if config.llm_config
                else None
            ),
        )

    def convert_llm_config_data(self, config: LLMConfig) -> LLMConfigData:
        """Convert an LLMConfig that has a model into its LLMConfigData.

        Sends the stored settings that are set, as they are. A model whose provider was
        deleted (NULL) converts without raising, with no settings and only the connection
        keys sent before the catalog existed. Issues no query when the caller selected
        `model__llm_provider`.

        Raises:
            ConfigNeedsReviewError: A stored setting is one the model does not accept: a
                catalog update lowered its limit, dropped the choice or dropped the setting.
        """
        provider = config.model.llm_provider
        provider_name = provider.name if provider else ""
        return LLMConfigData(
            model=config.model.name,
            custom_name=config.custom_name,
            timeout=config.timeout,
            parameters=llm_config_parameters(config),
            connection=llm_config_connection(config),
            main_secret_argument=_main_secret_argument(provider_name),
            api_key_secret_id=config.api_key_secret_id,
            extra_headers=config.extra_headers,
            input_cost_per_token=config.input_cost_per_token,
            output_cost_per_token=config.output_cost_per_token,
        )

    def convert_embedding_config_to_pydantic(
        self, embedding_config: EmbeddingConfig
    ) -> EmbedderData | None:
        """Convert an embedding config into the payload sent to crew.

        Returns:
            None when the config is missing; nothing is configured.

        Raises:
            ConfigProviderMissingError: The config has no model, or its model has no
                provider, because the model or provider was deleted.
            ConfigNeedsReviewError: A stored setting is one the model does not accept.
        """
        if not embedding_config:
            return None

        if embedding_config.model is None or embedding_config.model.embedding_provider is None:
            raise ConfigProviderMissingError("Embedding", embedding_config.custom_name)

        provider_name = embedding_config.model.embedding_provider.name
        return EmbedderData(
            provider=provider_name,
            config=EmbedderConfigData(
                model=embedding_config.model.name,
                parameters=embedding_config_parameters(embedding_config),
                connection=embedding_config_connection(embedding_config),
                main_secret_argument=_main_secret_argument(provider_name),
                api_key_secret_id=embedding_config.api_key_secret_id,
                extra_headers=embedding_config.extra_headers,
            ),
        )

    def _convert_code_slot(
        self,
        python_code: PythonCode,
        graph_id: int | None,
        session_id: int | None,
        extra_storage_paths: list[str] | None,
        org_id: int | None,
        storage_grant: StorageGrant | None = None,
        attached_storage_paths: list[str] | None = None,
    ) -> PythonCodeData:
        org_id = self._org_id_for_graph(graph_id, org_id)
        writable_paths = list(extra_storage_paths or [])
        if session_id is not None:
            writable_paths.append(f"sessions/{session_id}/")
        storage_allowed_paths, storage_org_prefix = self._resolve_storage_scope(
            graph_id=graph_id,
            org_id=org_id,
            extra_paths=writable_paths,
            attached_storage_paths=attached_storage_paths,
        )

        return self.convert_python_code_to_pydantic(
            python_code=python_code,
            use_storage=True,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            org_id=org_id,
            storage_grant=storage_grant,
        )

    def convert_python_node_to_pydantic(
        self,
        python_node: PythonNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
        graph_id: int | None = None,
        session_id: int | None = None,
        extra_storage_paths: list[str] | None = None,
        org_id: int | None = None,
        attached_storage_paths: list[str] | None = None,
    ) -> PythonNodeData:
        """Convert a python node into the data a run sends to the sandbox.

        Args:
            session_id: The running session; its `sessions/<id>/` folder becomes
                writable when the node uses storage.
            extra_storage_paths: Further writable folders for a run without a
                session, such as a test-mode run's own folder.
            org_id: `Graph.org_id` of `graph_id` when the caller already loaded
                the graph row; read from the graph when omitted.
            attached_storage_paths: `attached_storage_paths(graph_id)` when the caller
                already read it; read from the graph when omitted.
        """
        python_code_data = self._convert_code_slot(
            python_code=python_node.python_code,
            graph_id=graph_id,
            session_id=session_id,
            extra_storage_paths=extra_storage_paths,
            org_id=org_id,
            storage_grant=storage_grant_of(python_node),
            attached_storage_paths=attached_storage_paths,
        )
        return PythonNodeData(
            node_name=resolver(python_node.id),
            python_code=python_code_data,
            input_map=python_node.input_map,
            output_variable_path=python_node.output_variable_path,
        )

    def convert_condition_to_pydantic(self, condition: Condition) -> ConditionData:
        return ConditionData(condition=condition.condition)

    def convert_condition_group_to_pydantic(
        self,
        condition_group: ConditionGroup,
        *,
        resolver: NodeNameResolver,
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

    def convert_classification_decision_table_node_to_pydantic(
        self,
        node: ClassificationDecisionTableNode,
        *,
        resolver: NodeNameResolver,
        graph_id: int | None = None,
        session_id: int | None = None,
        org_id: int | None = None,
        attached_storage_paths: list[str] | None = None,
    ):
        condition_groups = [
            ClassificationConditionGroupData(
                group_name=cg.group_name,
                expression=cg.expression,
                prompt_id=cg.prompt.prompt_key if cg.prompt else None,
                manipulation=cg.manipulation,
                continue_flag=cg.continue_flag,
                next_node=resolver(cg.next_node_id) if cg.next_node_id else None,
                dock_visible=cg.dock_visible,
                order=cg.order,
                field_expressions=cg.field_expressions or {},
                field_manipulations=cg.field_manipulations or {},
            )
            for cg in node.condition_groups.all()
        ]

        prompts_dict = {}
        default_llm_config = node.default_llm_config

        for pc in node.prompt_configs.all():
            if pc.kind == SYSTEM_ONE_PROMPT_KIND:
                prompts_dict[pc.prompt_key] = PromptConfigData(
                    kind=SYSTEM_ONE_PROMPT_KIND,
                    prompt_text="",
                    llm_id=None,
                    llm_data=None,
                    result_variable=pc.result_variable or "prompt_result",
                    variable_mappings=pc.variable_mappings or {},
                    questions=pc.questions or {},
                    input_map=pc.input_map or {},
                    system_one_config=(
                        self.convert_system_one_config_to_pydantic(pc.system_one_config)
                        if pc.system_one_config
                        else None
                    ),
                )
                continue
            llm_config_obj = pc.llm_config or default_llm_config
            llm_data = None
            llm_id = None
            if llm_config_obj:
                llm_id = llm_config_obj.id
                llm_data = self.convert_llm_config_to_pydantic(llm_config_obj)
            prompts_dict[pc.prompt_key] = PromptConfigData(
                prompt_text=pc.prompt_text,
                llm_id=llm_id,
                output_schema=pc.output_schema or {},
                result_variable=pc.result_variable or "prompt_result",
                variable_mappings=pc.variable_mappings or {},
                llm_data=llm_data,
            )

        pre_python_code_data = None
        if node.pre_python_code is not None:
            pre_python_code_data = self._convert_code_slot(
                python_code=node.pre_python_code,
                graph_id=graph_id,
                session_id=session_id,
                extra_storage_paths=None,
                org_id=org_id,
                storage_grant=storage_grant_of(node, prefix="pre_"),
                attached_storage_paths=attached_storage_paths,
            )

        post_python_code_data = None
        if node.post_python_code is not None:
            post_python_code_data = self._convert_code_slot(
                python_code=node.post_python_code,
                graph_id=graph_id,
                session_id=session_id,
                extra_storage_paths=None,
                org_id=org_id,
                storage_grant=storage_grant_of(node, prefix="post_"),
                attached_storage_paths=attached_storage_paths,
            )

        return ClassificationDecisionTableNodeData(
            node_name=resolver(node.id),
            pre_python_code=pre_python_code_data,
            pre_input_map=node.pre_input_map or {},
            pre_output_variable_path=node.pre_output_variable_path,
            post_python_code=post_python_code_data,
            post_input_map=node.post_input_map or {},
            post_output_variable_path=node.post_output_variable_path,
            condition_groups=condition_groups,
            prompts=prompts_dict,
            default_next_node=resolver(node.default_next_node_id),
            next_error_node=resolver(node.next_error_node_id),
        )

    def convert_decision_table_node_to_pydantic(
        self,
        decision_table_node: DecisionTableNode,
        *,
        resolver: NodeNameResolver,
    ) -> DecisionTableNodeData:
        condition_group_list = [
            self.convert_condition_group_to_pydantic(condition_group, resolver=resolver)
            for condition_group in decision_table_node.condition_groups.all()
        ]
        return DecisionTableNodeData(
            node_name=resolver(decision_table_node.id),
            conditional_group_list=condition_group_list,
            default_next_node=resolver(decision_table_node.default_next_node_id),
            next_error_node=resolver(decision_table_node.next_error_node_id),
        )

    def convert_end_node_to_pydantic(
        self, end_node: EndNode, resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER
    ) -> EndNodeData:
        return EndNodeData(
            node_name=resolver(end_node.id),
            output_map=end_node.output_map,
        )

    @staticmethod
    def _convert_trigger_auth(
        trigger: WebhookTrigger,
    ) -> WebhookTriggerAuthData | None:
        auth: WebhookTriggerAuth | None = getattr(trigger, "auth", None)
        if not auth or auth.header_name is None:
            return None
        secret = secret_resolver.resolve_sealed(
            secret_id=auth.secret_id,
            org_id=trigger.org_id,
            context="WebhookTriggerAuth.secret",
        )
        return WebhookTriggerAuthData(
            kind=auth.kind,
            header_name=auth.header_name,
            secret=secret,
        )

    def convert_webhook_trigger_node_to_pydantic(
        self,
        webhook_trigger_node: WebhookTriggerNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
        graph_id: int | None = None,
        session_id: int | None = None,
        extra_storage_paths: list[str] | None = None,
        org_id: int | None = None,
        attached_storage_paths: list[str] | None = None,
    ) -> WebhookTriggerNodeData:
        """Convert a webhook trigger node into the data a run sends to the sandbox.

        Args:
            session_id: The running session; its `sessions/<id>/` folder becomes
                writable when the node uses storage.
            extra_storage_paths: Further writable folders for a run without a
                session, such as a test-mode run's own folder.
            org_id: `Graph.org_id` of `graph_id` when the caller already loaded
                the graph row; read from the graph when omitted.
            attached_storage_paths: `attached_storage_paths(graph_id)` when the caller
                already read it; read from the graph when omitted.
        """
        python_code_data = self._convert_code_slot(
            python_code=webhook_trigger_node.python_code,
            graph_id=graph_id,
            session_id=session_id,
            extra_storage_paths=extra_storage_paths,
            org_id=org_id,
            storage_grant=storage_grant_of(webhook_trigger_node),
            attached_storage_paths=attached_storage_paths,
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

    def convert_schedule_trigger_node_to_pydantic(
        self,
        schedule_trigger_node: ScheduleTriggerNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> ScheduleTriggerNodeData:
        return ScheduleTriggerNodeData(
            node_name=resolver(schedule_trigger_node.id),
            run_mode=schedule_trigger_node.run_mode,
            start_date_time=(
                schedule_trigger_node.start_date_time.isoformat()
                if schedule_trigger_node.start_date_time
                else None
            ),
            every=schedule_trigger_node.every,
            unit=schedule_trigger_node.unit,
            weekdays=schedule_trigger_node.weekdays or [],
            end_type=schedule_trigger_node.end_type,
            end_date_time=(
                schedule_trigger_node.end_date_time.isoformat()
                if schedule_trigger_node.end_date_time
                else None
            ),
            max_runs=schedule_trigger_node.max_runs,
        )

    def convert_edge_to_pytdantic(self, edge: Edge, *, resolver: NodeNameResolver) -> EdgeData:
        return EdgeData(
            start_key=resolver(edge.start_node_id),
            end_key=resolver(edge.end_node_id),
        )

    def convert_file_extractor_node_to_pydantic(
        self,
        file_extractor_node: FileExtractorNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
        graph_id: int | None = None,
        session_id: int | None = None,
        org_id: int | None = None,
    ) -> FileExtractorNodeData:
        org_id = self._org_id_for_graph(graph_id, org_id)
        storage_allowed_paths = None
        storage_org_prefix = None
        if graph_id is not None:
            storage_allowed_paths = self._resolve_allowed_paths_for_graph(graph_id)
            if session_id is not None:
                storage_allowed_paths.append(f"sessions/{session_id}/")
            storage_org_prefix = self.storage_prefix_for_org(org_id)

        return FileExtractorNodeData(
            node_name=resolver(file_extractor_node.id),
            input_map=file_extractor_node.input_map,
            output_variable_path=file_extractor_node.output_variable_path,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            org_id=org_id,
        )

    def convert_key_value_node_to_pydantic(
        self,
        key_value_node: KeyValueNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
    ) -> KeyValueNodeData:
        return KeyValueNodeData(
            node_name=resolver(key_value_node.id),
            key_value_table_id=key_value_node.key_value_table_id,
            mode=key_value_node.mode,
            entries=key_value_node.entries,
            input_map=key_value_node.input_map,
            output_variable_path=key_value_node.output_variable_path,
        )

    def convert_audio_transcription_node_to_pydantic(
        self,
        audio_transcription_node: AudioTranscriptionNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
        graph_id: int | None = None,
        session_id: int | None = None,
        org_id: int | None = None,
    ) -> AudioTranscriptionNodeData:
        org_id = self._org_id_for_graph(graph_id, org_id)
        storage_allowed_paths = None
        storage_org_prefix = None
        if graph_id is not None:
            storage_allowed_paths = self._resolve_allowed_paths_for_graph(graph_id)
            if session_id is not None:
                storage_allowed_paths.append(f"sessions/{session_id}/")
            storage_org_prefix = self.storage_prefix_for_org(org_id)

        return AudioTranscriptionNodeData(
            node_name=resolver(audio_transcription_node.id),
            input_map=audio_transcription_node.input_map,
            output_variable_path=audio_transcription_node.output_variable_path,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            org_id=org_id,
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
        auth_token = (
            secret_resolver.resolve_sealed(
                secret_id=ngrok_webhook_config.auth_token_secret_id,
                org_id=ngrok_webhook_config.trigger.org_id,
                context="NgrokWebhookConfig.auth_token",
            )
            or ""
        )
        auth = self._convert_trigger_auth(ngrok_webhook_config.trigger)

        return NgrokConfigData(
            name=ngrok_webhook_config.trigger.path,
            org_id=ngrok_webhook_config.trigger.org_id,
            auth_token=auth_token,
            domain=ngrok_webhook_config.domain,
            region=ngrok_webhook_config.region,
            auth=auth,
        )

    def convert_localhost_webhook_config_to_pydantic(
        self, localhost_webhook_config: LocalhostWebhookConfig
    ) -> LocalhostConfigData:
        auth = self._convert_trigger_auth(localhost_webhook_config.trigger)

        return LocalhostConfigData(
            name=localhost_webhook_config.trigger.path,
            org_id=localhost_webhook_config.trigger.org_id,
            domain=localhost_webhook_config.domain,
            auth=auth,
        )


def _main_secret_argument(provider_name: str) -> str:
    provider = CatalogRepository.default().provider(provider_name)
    return provider.main_secret_argument if provider else "api_key"
