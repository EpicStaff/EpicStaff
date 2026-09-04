from django.core.exceptions import ValidationError

from src.shared.models import (
    LocalhostConfigData,
    ArgsSchema,
    AudioTranscriptionNodeData,
    BaseToolData,
    ClassificationConditionGroupData,
    ClassificationDecisionTableNodeData,
    ConditionalEdgeData,
    ConditionData,
    ConditionGroupData,
    DecisionTableNodeData,
    EdgeData,
    EmbedderConfigData,
    EmbedderData,
    EndNodeData,
    FileExtractorNodeData,
    RagSearchConfig,
    GraphRagSearchConfig,
    KnowledgeNodeData,
    NaiveRagSearchConfig,
    LLMConfigData,
    LLMData,
    McpToolData,
    NgrokConfigData,
    PythonCodeData,
    PythonCodeToolData,
    PythonNodeData,
    PromptConfigData,
    RealtimeAgentChatData,
    ScheduleTriggerNodeData,
    SubGraphNodeData,
    TelegramTriggerNodeData,
    TelegramTriggerNodeFieldData,
    WebhookNodeAuthData,
    WebhookTriggerNodeData,
    variables_to_args_schema,
)

from tables.models import PythonCode, PythonCodeTool
from tables.models.graph_models import (
    AudioTranscriptionNode,
    Condition,
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    ConditionalEdge,
    ConditionGroup,
    DecisionTableNode,
    Edge,
    EndNode,
    FileExtractorNode,
    Graph,
    GraphStorageFile,
    KnowledgeNode,
    PythonNode,
    ScheduleTriggerNode,
    SubGraphNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.llm_models import LLMConfig
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeToolConfig
from tables.models.realtime_models import (
    RealtimeAgentChat,
    OpenAIRealtimeConfig,
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
)
from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    WebhookTrigger,
)
from tables.services.realtime_surface_service import RealtimeSurfaceService
from tables.services.secrets import assert_tool_secrets_declared, secret_resolver
from utils.graph_utils import (
    SINGLE_LOOKUP_RESOLVER,
    NodeNameResolver,
)
from utils.singleton_meta import SingletonMeta
from tables.services.rag_assignment_service import SearchConfigService
from tables.services.rag_registry import resolve_rag_in_collection

from tables.models.embedding_models import EmbeddingConfig


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
        rag_search_config = self.build_rag_search_config(
            rag_type_id, all_search_configs
        )
        embedder_api_key_secret_id = self._node_rag_embedder_secret_id(knowledge_node)
        return KnowledgeNodeData(
            node_name=resolver(knowledge_node.id),
            collection_id=collection_id,
            rag_type_id=rag_type_id,
            query=knowledge_node.query,
            rag_search_config=rag_search_config,
            input_map=knowledge_node.input_map,
            output_variable_path=knowledge_node.output_variable_path,
            embedder_api_key_secret_id=embedder_api_key_secret_id,
        )

    @staticmethod
    def _node_rag_embedder_secret_id(knowledge_node: KnowledgeNode) -> int | None:
        """Secret id of the node's RAG embedder, resolved by the same (collection,
        rag_id, rag_type) coordinates the knowledge service searches by."""
        if not (knowledge_node.rag_type and knowledge_node.rag_id):
            return None
        rag = resolve_rag_in_collection(
            knowledge_node.rag_type,
            knowledge_node.rag_id,
            knowledge_node.source_collection,
        )
        embedder = rag.embedder
        return embedder.api_key_secret_id if embedder else None

    def _resolve_allowed_paths_for_graph(self, graph_id: int) -> list[str]:
        return list(
            GraphStorageFile.objects.filter(graph_id=graph_id)
            .select_related("storage_file")
            .values_list("storage_file__path", flat=True)
        )

    def _resolve_org_prefix_for_graph(self, graph_id: int) -> str | None:
        org_id = (
            Graph.objects.filter(id=graph_id).values_list("org_id", flat=True).first()
        )
        if org_id is not None:
            return f"org_{org_id}"
        return None

    def _resolve_authoritative_org_id_for_graph(self, graph_id: int) -> int | None:
        """Authoritative RBAC org for a graph, read directly from `Graph.org_id`.

        Distinct from `_resolve_org_prefix_for_graph`, which reads the optional
        `GraphOrganization` join table (a separate storage-prefix concept) and
        can be None even when `Graph.org_id` is set. This resolver is the only
        source of truth for the `X-Organization-Id` header injected into
        sandbox callback tools -- never derive it from agent/tool config input.
        """
        return (
            Graph.objects.filter(pk=graph_id).values_list("org_id", flat=True).first()
        )

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

        rt_agent_chat_data = RealtimeAgentChatData(
            role=ad.name,
            goal=ad.description or "assist the user",
            backstory=ad.instructions or "You are a helpful voice assistant",
            org_id=ad.organization_id,
            user_id=user_id,
            knowledge_collection_id=surface_resolution.knowledge_collection_id,
            rag_type_id=surface_resolution.rag_type_id,
            rag_search_config=surface_resolution.rag_search_config,
            rag_embedder_api_key_secret_id=surface_resolution.rag_embedder_api_key_secret_id,
            llm=self.convert_llm_config_to_pydantic(ad.llm_config),
            memory=False,
            tools=surface_resolution.tools,
            rt_model_name=rt_model_name,
            rt_api_key_secret_id=rt_api_key_secret_id,
            rt_base_url=rt_base_url,
            transcript_model_name=transcript_model_name,
            transcript_api_key_secret_id=transcript_api_key_secret_id,
            temperature=ad.default_temperature,
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

        return rt_agent_chat_data

    def convert_python_code_to_pydantic(
        self,
        python_code: PythonCode,
        use_storage: bool = False,
        storage_allowed_paths: list[str] | None = None,
        storage_org_prefix: str | None = None,
        session_id: int | None = None,
        org_id: int | None = None,
    ):
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
            use_storage=use_storage,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            # The declaration is the allow-list: everything selected is injected,
            # whether the code reads it or not. That is what makes a computed name
            # -- get_secret(f"KEY_{env}") -- work, since no static parse could see
            # it. The parser is now only a validator (declaration_validator.py).
            # Names only: resolution happens in redis_service, on the copy that
            # goes to Redis -- never on the object that becomes graph_schema.
            secret_names=list(python_code.secrets.values_list("name", flat=True)),
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
        )
        # A PythonCodeTool is org-owned, not graph-owned, so the session-start graph
        # walk cannot reach it. Gate it here, where the tool is already in hand and
        # its name is available for the error.
        assert_tool_secrets_declared(
            tool_name=python_code_tool.name,
            code=python_code_tool.python_code.code,
            declared=set(python_code_data.secret_names),
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

        assert isinstance(
            python_configuration, dict
        ), "Error reading python tool configuration. How did you even pass validation?"

        storage_allowed_paths = None
        storage_org_prefix = None
        if python_code_tool.use_storage:
            if storage_allowed_paths_override is not None:
                storage_allowed_paths = storage_allowed_paths_override
            elif graph_id is not None:
                storage_allowed_paths = self._resolve_allowed_paths_for_graph(graph_id)
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
        )
        # A configured tool reaches the session through this method only, so gating
        # convert_python_code_tool_to_pydantic alone would leave it ungated.
        assert_tool_secrets_declared(
            tool_name=python_code_tool.name,
            code=python_code.code,
            declared=set(python_code_data.secret_names),
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
            timeout=mcp_tool.timeout,
            auth_secret_id=mcp_tool.auth_secret_id,
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
                seed=config.seed,
                base_url=config.model.base_url,
                api_version=config.model.api_version,
                api_key_secret_id=config.api_key_secret_id,
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
                api_key_secret_id=embedding_config.api_key_secret_id,
            ),
        )

    def convert_python_node_to_pydantic(
        self,
        python_node: PythonNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
        graph_id: int | None = None,
        session_id: int | None = None,
    ) -> PythonNodeData:
        storage_allowed_paths = None
        storage_org_prefix = None
        if python_node.use_storage and graph_id is not None:
            storage_allowed_paths = self._resolve_allowed_paths_for_graph(graph_id)
            if session_id is not None:
                storage_allowed_paths.append(f"sessions/{session_id}/")
            storage_org_prefix = self._resolve_org_prefix_for_graph(graph_id)

        org_id = None
        if graph_id is not None:
            org_id = self._resolve_authoritative_org_id_for_graph(graph_id)

        python_code_data = self.convert_python_code_to_pydantic(
            python_code=python_node.python_code,
            use_storage=python_node.use_storage,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            org_id=org_id,
        )
        return PythonNodeData(
            node_name=resolver(python_node.id),
            python_code=python_code_data,
            input_map=python_node.input_map,
            output_variable_path=python_node.output_variable_path,
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

    def convert_classification_decision_table_node_to_pydantic(
        self,
        node: ClassificationDecisionTableNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
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
            pre_python_code_data = self.convert_python_code_to_pydantic(
                node.pre_python_code
            )

        post_python_code_data = None
        if node.post_python_code is not None:
            post_python_code_data = self.convert_python_code_to_pydantic(
                node.post_python_code
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

    def convert_end_node_to_pydantic(
        self, end_node: EndNode, resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER
    ) -> EndNodeData:
        return EndNodeData(
            node_name=resolver(end_node.id),
            output_map=end_node.output_map,
        )

    def _get_node_auths_for_trigger(
        self, trigger: WebhookTrigger
    ) -> tuple[list[WebhookNodeAuthData], bool]:
        """Collect enabled WebhookNodeAuths from nodes attached to this
        trigger, and report whether at least one attached node has NO
        enabled auth configured.

        The second element (`has_unauthenticated_node`) drives
        `BaseTunnelConfigData.has_unauthenticated_node`: when a path mixes an
        authenticated node (e.g. Telegram, mandatory auth) with an auth-free
        node, `webhook_routes.handle_webhook` must let an unauthenticated
        request through -- scoped only to the auth-free node(s) via
        `UNAUTHENTICATED_FALLBACK_PRINCIPAL` -- instead of 401ing the whole
        path just because `auths` is non-empty.
        """
        nodes = [
            *trigger.telegram_trigger_nodes.all(),
            *trigger.webhook_trigger_nodes.all(),
        ]
        auth_data_list: list[WebhookNodeAuthData] = []
        has_unauthenticated_node = False
        for node in nodes:
            auth_data = self._convert_node_auth(node)
            if auth_data is None:
                has_unauthenticated_node = True
            else:
                auth_data_list.append(auth_data)
        return auth_data_list, has_unauthenticated_node

    @staticmethod
    def _convert_node_auth(
        node: TelegramTriggerNode | WebhookTriggerNode,
    ) -> WebhookNodeAuthData | None:
        """Convert `node.webhook_node_auth` (a reverse OneToOne) to
        `WebhookNodeAuthData`, or `None` if there's no enabled auth row.

        `getattr(node, "webhook_node_auth", None)` is deliberate, not a
        simplification-for-its-own-sake: accessing a reverse OneToOne
        descriptor with no related row raises `RelatedObjectDoesNotExist`
        (a subclass of `AttributeError`), and `getattr(..., None)` -- like
        `hasattr` -- swallows that specific `AttributeError` and returns the
        default. Using `getattr` instead of `hasattr` + a second attribute
        access avoids triggering that descriptor lookup twice.
        """
        auth = getattr(node, "webhook_node_auth", None)
        if not auth or not auth.enabled:
            return None
        return WebhookNodeAuthData(
            enabled=auth.enabled,
            scheme=auth.scheme,
            header_name=auth.header_name,
            timestamp_header_name=auth.timestamp_header_name,
            tolerance_seconds=auth.tolerance_seconds,
            secret_hash=auth.secret_hash,
            signing_secret=auth.signing_secret,
            principal=f"{node._meta.label_lower}:{node.pk}",
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
        graph_id: int | None = None,
        session_id: int | None = None,
    ) -> FileExtractorNodeData:
        storage_allowed_paths = None
        storage_org_prefix = None
        if graph_id is not None:
            storage_allowed_paths = self._resolve_allowed_paths_for_graph(graph_id)
            if session_id is not None:
                storage_allowed_paths.append(f"sessions/{session_id}/")
            storage_org_prefix = self._resolve_org_prefix_for_graph(graph_id)

        org_id = None
        if graph_id is not None:
            org_id = self._resolve_authoritative_org_id_for_graph(graph_id)

        return FileExtractorNodeData(
            node_name=resolver(file_extractor_node.id),
            input_map=file_extractor_node.input_map,
            output_variable_path=file_extractor_node.output_variable_path,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            org_id=org_id,
        )

    def convert_audio_transcription_node_to_pydantic(
        self,
        audio_transcription_node: AudioTranscriptionNode,
        resolver: NodeNameResolver = SINGLE_LOOKUP_RESOLVER,
        graph_id: int | None = None,
        session_id: int | None = None,
    ) -> AudioTranscriptionNodeData:
        storage_allowed_paths = None
        storage_org_prefix = None
        if graph_id is not None:
            storage_allowed_paths = self._resolve_allowed_paths_for_graph(graph_id)
            if session_id is not None:
                storage_allowed_paths.append(f"sessions/{session_id}/")
            storage_org_prefix = self._resolve_org_prefix_for_graph(graph_id)

        org_id = None
        if graph_id is not None:
            org_id = self._resolve_authoritative_org_id_for_graph(graph_id)

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
            secret_resolver.resolve(
                secret_id=ngrok_webhook_config.auth_token_secret_id,
                org_id=ngrok_webhook_config.trigger.org_id,
                context="NgrokWebhookConfig.auth_token",
            )
            or ""
        )
        auths, has_unauthenticated_node = self._get_node_auths_for_trigger(
            ngrok_webhook_config.trigger
        )

        return NgrokConfigData(
            name=ngrok_webhook_config.trigger.path,
            org_id=ngrok_webhook_config.trigger.org_id,
            auth_token=auth_token,
            domain=ngrok_webhook_config.domain,
            region=ngrok_webhook_config.region,
            auths=auths,
            has_unauthenticated_node=has_unauthenticated_node,
        )

    def convert_localhost_webhook_config_to_pydantic(
        self, localhost_webhook_config: LocalhostWebhookConfig
    ) -> LocalhostConfigData:
        auths, has_unauthenticated_node = self._get_node_auths_for_trigger(
            localhost_webhook_config.trigger
        )

        return LocalhostConfigData(
            name=localhost_webhook_config.trigger.path,
            org_id=localhost_webhook_config.trigger.org_id,
            domain=localhost_webhook_config.domain,
            auths=auths,
            has_unauthenticated_node=has_unauthenticated_node,
        )
